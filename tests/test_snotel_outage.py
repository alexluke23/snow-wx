"""SNOTEL outage handling (fix-snotel): fail fast, keep the last good copy only while it is young, flag it stale,
recover by itself. Offline: fakes only."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from pipeline import snotel
from pipeline.__main__ import run_obs, with_history
from pipeline.common import load_config, utcnow

from .fakes import FakeResponse, FakeSession


@pytest.fixture()
def cfg():
    c = load_config()
    c["region"]["states"] = ["CO", "UT"]
    c["snotel"]["chunk_size"] = 1                     # several chunks even with three fake stations
    return c


class Down(FakeSession):
    """The whole AWDB host answers 502 (what the live outage looks like)."""

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        return FakeResponse({}, 502)


def good_copy(cfg, out, hours_old=0.0):
    """A healthy run into `out`, then age its observations by `hours_old` (the previous good copy)."""
    snotel.run(cfg, FakeSession(), out)
    if hours_old:
        p = out / "snotel.geojson"
        gj = json.loads(p.read_text(encoding="utf-8"))
        for f in gj["features"]:
            t = snotel.feature_obs_utc(f) - timedelta(hours=hours_old)
            off = snotel.utc_offset(None, f["properties"]["state"], f["geometry"]["coordinates"][0])
            f["properties"]["obs_time"] = (t + timedelta(hours=off)).strftime("%Y-%m-%d %H:%M")
        p.write_text(json.dumps(gj), encoding="utf-8")
    return json.loads((out / "snotel.geojson").read_text(encoding="utf-8"))


def test_down_fails_fast_with_one_probe(cfg, tmp_path):
    s = Down()
    with pytest.raises(snotel.SnotelUnavailable) as e:
        snotel.run(cfg, s, tmp_path)
    assert len(s.calls) == 1                           # the probe only: no 12 state requests, no chunks
    assert e.value.status["unavailable"] is True and not (tmp_path / "snotel.geojson").exists()


def test_empty_station_list_is_unavailable(cfg, tmp_path):
    class Empty(FakeSession):
        def get(self, url, params=None, timeout=None):
            self.calls.append((url, params))
            if url.endswith("/stations") and params["stationTriplets"].startswith("*"):
                return FakeResponse([])
            return super().get(url, params, timeout)

    with pytest.raises(snotel.SnotelUnavailable, match="no SNOTEL stations"):
        snotel.run(cfg, Empty(), tmp_path)


def test_slow_service_hits_the_time_limit(cfg, tmp_path, monkeypatch):
    """Each request 'takes' 300 s on a fake clock; with max_seconds 400 the run stops after the first chunk
    instead of grinding through every state and chunk."""
    now = [0.0]
    monkeypatch.setattr(snotel, "_clock", lambda: now[0])
    cfg["snotel"]["max_seconds"] = 400

    class Slow(FakeSession):
        def get(self, url, params=None, timeout=None):
            now[0] += 100.0
            return super().get(url, params, timeout)

    s = Slow()
    info = None
    try:
        info = snotel.run(cfg, s, tmp_path)           # probe 100 s, states 200-300 s, then the limit
    except snotel.SnotelUnavailable as exc:
        assert exc.status["unavailable"]
    assert len(s.calls) <= 6 and (info is None or info["count"] < 3)


def test_partial_failure_keeps_fresh_stations_and_carries_the_rest(cfg, tmp_path):
    prev = good_copy(cfg, tmp_path, hours_old=5)
    assert len(prev["features"]) == 3

    class FailSecondChunk(FakeSession):
        def get(self, url, params=None, timeout=None):
            if url.endswith("/data") and "335:CO:SNTL" in params["stationTriplets"]:
                return FakeResponse({}, 503)
            return super().get(url, params, timeout)

    info = snotel.run(cfg, FailSecondChunk(), tmp_path)
    gj = json.loads((tmp_path / "snotel.geojson").read_text(encoding="utf-8"))
    by = {f["properties"]["triplet"]: f["properties"] for f in gj["features"]}
    assert len(by) == 3 and info["carried_stale"] == 1
    assert "stale" not in by["663:CO:SNTL"] and by["335:CO:SNTL"]["stale"] is True
    assert 4.5 < by["335:CO:SNTL"]["age_h"] < 8.5      # the ORIGINAL timestamp survives (5 h old)
    assert gj["stale"] is False


def test_outage_keeps_young_copy_stale_with_original_timestamps(cfg, tmp_path):
    prev = good_copy(cfg, tmp_path, hours_old=13)
    obs_before = {f["properties"]["triplet"]: f["properties"]["obs_time"] for f in prev["features"]}
    with pytest.raises(snotel.SnotelUnavailable) as e:
        snotel.run(cfg, Down(), tmp_path)
    st = e.value.status
    assert st["stale"] is True and 12.5 < st["age_h"] < 16.5 and st["count"] == 3 and "unavailable" not in st
    gj = json.loads((tmp_path / "snotel.geojson").read_text(encoding="utf-8"))
    assert gj["stale"] is True and gj["observed_through"]
    for f in gj["features"]:
        p = f["properties"]
        assert p["stale"] and p["obs_time"] == obs_before[p["triplet"]] and 12.5 < p["age_h"] < 16.5
    assert (tmp_path / "snotel" / "663_CO_SNTL.json").exists()   # station files stay for the chart


def test_outage_beyond_max_age_removes_data_and_says_unavailable(cfg, tmp_path):
    good_copy(cfg, tmp_path, hours_old=60)              # max_age_hours is 48
    with pytest.raises(snotel.SnotelUnavailable) as e:
        snotel.run(cfg, Down(), tmp_path)
    st = e.value.status
    assert st["unavailable"] is True and st["last_observed"] and st["dropped_too_old"] == 3
    assert not (tmp_path / "snotel.geojson").exists()
    assert not list((tmp_path / "snotel").glob("*.json"))        # old values can never show as current


def test_outage_with_no_previous_copy_is_unavailable(cfg, tmp_path):
    with pytest.raises(snotel.SnotelUnavailable) as e:
        snotel.run(cfg, Down(), tmp_path)
    assert e.value.status == {"unavailable": True, "last_observed": None, "dropped_too_old": 0}


def test_recovery_needs_no_manual_step(cfg, tmp_path):
    """down (stale) -> up: the first good run replaces everything, clears stale and resets the history."""
    good_copy(cfg, tmp_path, hours_old=20)
    cfg["snotel"]["enabled"] = True
    only = ["snotel"]
    import pipeline.__main__ as m
    m.SOURCES  # noqa: B018
    sess = {"s": Down()}
    orig = m.make_session
    m.make_session = lambda c: sess["s"]
    try:
        assert run_obs(cfg, tmp_path, only) == 1                                     # down: nothing ok
        meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["sources"]["snotel"]
        assert meta["ok"] is False and meta["stale"] and meta["consecutive_failures"] == 1 and meta["outage_since"]
        assert run_obs(cfg, tmp_path, only) == 1
        meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["sources"]["snotel"]
        assert meta["consecutive_failures"] == 2 and meta["outage_since"]
        sess["s"] = FakeSession()                                                    # service is back
        assert run_obs(cfg, tmp_path, only) == 0
    finally:
        m.make_session = orig
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["sources"]["snotel"]
    assert meta["ok"] is True and meta["consecutive_failures"] == 0 and meta["last_success_at"] == meta["at"]
    assert "stale" not in meta and "outage_since" not in meta and "unavailable" not in meta
    gj = json.loads((tmp_path / "snotel.geojson").read_text(encoding="utf-8"))
    assert gj["stale"] is False and not any(f["properties"].get("stale") for f in gj["features"])


def test_with_history_counts_and_keeps_last_success():
    ok = with_history({"ok": True, "at": "2026-11-16T11:17:00Z"}, None)
    assert ok["last_success_at"] == "2026-11-16T11:17:00Z" and ok["consecutive_failures"] == 0
    f1 = with_history({"ok": False, "at": "2026-11-16T12:17:00Z"}, ok)
    f2 = with_history({"ok": False, "at": "2026-11-16T13:17:00Z"}, f1)
    assert (f2["consecutive_failures"], f2["last_success_at"], f2["outage_since"]) == (2, "2026-11-16T11:17:00Z", "2026-11-16T12:17:00Z")


def test_simulate_failure_input_exercises_the_stale_path(cfg, tmp_path, monkeypatch):
    good_copy(cfg, tmp_path, hours_old=3)
    monkeypatch.setenv("SIMULATE_FAILURE", "snotel")
    with pytest.raises(snotel.SnotelUnavailable) as e:
        snotel.run(cfg, FakeSession(), tmp_path)           # the (healthy) fake service is never called
    assert e.value.status["stale"] is True and "simulated" in str(e.value)
    monkeypatch.setenv("SIMULATE_FAILURE", "asos")
    import pipeline.__main__ as m
    monkeypatch.setattr(m, "make_session", lambda c: FakeSession())
    assert m.run_obs(cfg, tmp_path, ["snotel", "asos"]) == 0                      # snotel fine, asos simulated down
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["sources"]
    assert meta["snotel"]["ok"] is True and meta["asos"]["ok"] is False and "simulated" in meta["asos"]["error"]


def test_storm_total_windows_48h_and_7d_and_their_hiding_when_stale():
    import pandas as pd
    t0 = pd.Timestamp("2026-11-10 00:00")
    times = [t0 + pd.Timedelta(hours=h) for h in range(0, 170)]
    depth = [10.0 + h * 0.1 for h in range(170)]           # +0.1 in per hour
    fmt = lambda t: t.strftime("%Y-%m-%d %H:%M")           # noqa: E731
    series = {"SNWD": [(fmt(t), v) for t, v in zip(times, depth)], "WTEQ": [(fmt(t), 2.0 + h * 0.01) for h, t in enumerate(times)]}
    s = snotel.summarize(series)
    assert s["depth_48h"] == pytest.approx(4.8, abs=0.3) and s["depth_72h"] == pytest.approx(7.2, abs=0.3)
    assert s["depth_7d"] == pytest.approx(16.8, abs=0.4) and s["swe_7d"] == pytest.approx(1.68, abs=0.05)
    f = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-111.0, 40.0]}, "properties": {
        "triplet": "1:UT:SNTL", "state": "UT", "obs_time": (utcnow() - timedelta(hours=60) - timedelta(hours=7)).strftime("%Y-%m-%d %H:%M"),
        **{k: 5.0 for k in ("depth_24h", "swe_24h", "depth_48h", "swe_48h", "depth_72h", "swe_72h", "depth_7d", "swe_7d")}}}
    p = snotel._stale(f, utcnow())["properties"]
    assert p["depth_48h"] is None and p["swe_48h"] is None            # 60 h old: the 24 h and 48 h windows are closed
    assert p["depth_72h"] == 5.0 and p["depth_7d"] == 5.0 and p["swe_7d"] == 5.0
