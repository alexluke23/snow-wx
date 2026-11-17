"""Data-health monitor (per-source limits, issue plan, never fails) and the previous-copy restore (SITE_ORIGIN)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from pipeline import monitor, restore, snotel
from pipeline.__main__ import run_obs
from pipeline.common import load_config, utcnow

from .fakes import FakeResponse, FakeSession
from .test_snotel_outage import Down, good_copy

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def iso(hours_ago):
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture()
def mcfg():
    return load_config()["monitoring"]


def meta_with(**sources):
    return {"sources": sources}


def test_limits_come_from_each_sources_real_cadence(mcfg):
    """Hourly sources: 3 failures or 6 h. Points (6-hourly job): 14 h, not 6 h: a normal 9 h gap must not alarm."""
    assert mcfg["sources"]["snotel"] == {"max_failures": 3, "max_age_hours": 6}
    assert mcfg["sources"]["points"] == {"max_age_hours": 14}
    meta = meta_with(
        points={"ok": True, "at": iso(9)},                                           # 9 h: fine for a 6-hourly product
        snotel={"ok": False, "consecutive_failures": 2, "last_success_at": iso(2), "at": iso(0)},   # below both limits
        asos={"ok": True, "at": iso(0.2), "consecutive_failures": 0, "last_success_at": iso(0.2)},
    )
    res = monitor.evaluate(meta, NOW, mcfg)
    assert res["points"]["problem"] is None and res["snotel"]["problem"] is None and res["asos"]["problem"] is None


def test_failures_age_and_missing_products_raise_problems(mcfg):
    meta = meta_with(
        snotel={"ok": False, "consecutive_failures": 3, "last_success_at": iso(3), "at": iso(0)},
        alerts={"ok": False, "consecutive_failures": 1, "last_success_at": iso(7), "at": iso(0)},     # age > 6 h
        points={"ok": True, "at": iso(15)},                                                           # > 14 h
        models={"ok": False, "error": "no model runs yet"},                                           # product never arrived
        nohrsc={"ok": True, "at": iso(20)},                                                           # 20 h < 30 h: fine
    )
    res = monitor.evaluate(meta, NOW, mcfg)
    assert "3 runs in a row" in res["snotel"]["problem"]
    assert "7 h ago" in res["alerts"]["problem"] and "15 h ago" in res["points"]["problem"]
    assert "missing" in res["models"]["problem"] and res["nohrsc"]["problem"] is None
    assert res["afd"]["problem"] is None and res["afd"]["detail"]["note"]            # absent from meta: no false alarm


def test_one_issue_per_source_created_updated_closed(mcfg):
    bad = meta_with(snotel={"ok": False, "consecutive_failures": 4, "last_success_at": iso(5), "at": iso(0)})
    acts = monitor.plan(monitor.evaluate(bad, NOW, {"sources": {"snotel": mcfg["sources"]["snotel"]}}), [], "https://run/1")
    assert [a[0] for a in acts] == ["create"] and acts[0][2] == "Data health: snotel"
    body = acts[0][3]
    open_issue = {"number": 7, "title": "Data health: snotel", "body": body}
    # same problem, only the run link changes: no update (no e-mail spam)
    again = monitor.plan(monitor.evaluate(bad, NOW, {"sources": {"snotel": mcfg["sources"]["snotel"]}}), [open_issue], "https://run/2")
    assert again == []
    worse = meta_with(snotel={"ok": False, "consecutive_failures": 5, "last_success_at": iso(5), "at": iso(0)})
    assert [a[0] for a in monitor.plan(monitor.evaluate(worse, NOW, {"sources": {"snotel": mcfg["sources"]["snotel"]}}), [open_issue])] == ["update"]
    good = meta_with(snotel={"ok": True, "consecutive_failures": 0, "last_success_at": iso(0.1), "at": iso(0.1)})
    closed = monitor.plan(monitor.evaluate(good, NOW, {"sources": {"snotel": mcfg["sources"]["snotel"]}}), [open_issue])
    assert closed[0][:2] == ("close", 7)


def test_apply_assigns_the_owner_labels_and_survives_gh_errors(mcfg):
    calls = []

    def gh(args, input_text=None):
        calls.append(args)
        if args[:2] == ["label", "create"]:
            raise RuntimeError("already exists")
        if args[:2] == ["issue", "edit"]:
            raise RuntimeError("boom")
        return ""

    out = monitor.apply([("create", "snotel", "Data health: snotel", "body"), ("update", 3, "b"), ("close", 4, "ok")], mcfg, gh)
    create = next(c for c in calls if c[:2] == ["issue", "create"])
    assert "--assignee" in create and create[create.index("--assignee") + 1] == "alexluke23"
    assert "--label" in create and create[create.index("--label") + 1] == "data-health"
    assert any(o.startswith("FAILED update") for o in out) and any(o.startswith("closed #4") for o in out)  # the rest still ran


def test_monitor_never_raises_or_fails_the_job(monkeypatch, tmp_path):
    monkeypatch.setattr(monitor, "fetch_meta", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network")))
    assert monitor.main(["--origin", "https://example.invalid"]) == 0
    assert monitor.main(["--config", str(tmp_path / "missing.yml")]) == 0
    assert monitor.check({}, None, NOW, []) == ["live meta.json unreachable: nothing to evaluate"]


# ---------------------------------------------------------------- previous copy restore (Option A)

class Site:
    """The live site: path -> JSON payload (served by origin/data/...)."""

    request_timeout = 5

    def __init__(self, files, origin="https://live.example/snow-wx"):
        self.files, self.origin, self.calls = files, origin, []

    def get(self, url, params=None, timeout=None):
        self.calls.append(url)
        key = url[len(self.origin) + len("/data/"):]
        return FakeResponse(self.files[key]) if key in self.files else FakeResponse({}, 404)


def live_files(cfg, tmp_path, hours_old):
    src = tmp_path / "live"
    good_copy(cfg, src, hours_old=hours_old)
    files = {"snotel.geojson": json.loads((src / "snotel.geojson").read_text(encoding="utf-8")),
             "meta.json": {"sources": {"snotel": {"ok": False, "consecutive_failures": 2, "last_success_at": iso(30)}}}}
    for p in (src / "snotel").glob("*.json"):
        files[f"snotel/{p.name}"] = json.loads(p.read_text(encoding="utf-8"))
    return files


def test_restore_uses_configurable_origin_and_only_young_stations(tmp_path):
    cfg = load_config()
    cfg["region"]["states"] = ["CO", "UT"]
    files = live_files(cfg, tmp_path, hours_old=10)
    out = tmp_path / "ci"
    info = restore.restore_previous(cfg, Site(files), out, origin="https://live.example/snow-wx")
    assert info["stations"] == 3 and info["meta"] is True
    assert (out / "snotel" / "663_CO_SNTL.json").exists() and (out / "meta.json").exists()
    assert restore.site_origin({"site": {"origin": "https://a/b/"}}) == "https://a/b"
    import os
    os.environ["SITE_ORIGIN"] = "https://new-domain.example"
    try:
        assert restore.site_origin(cfg) == "https://new-domain.example"                  # W1 cutover = one env var / config line
    finally:
        del os.environ["SITE_ORIGIN"]
    # too old on the live site: nothing restored (never show old values as current)
    old = live_files(cfg, tmp_path / "x", hours_old=60)
    out2 = tmp_path / "ci2"
    info = restore.restore_previous(cfg, Site(old), out2, origin="https://live.example/snow-wx")
    assert info["stations"] == 0 and not (out2 / "snotel.geojson").exists()
    # unreachable site: no exception, no files
    info = restore.restore_previous(cfg, Site({}), tmp_path / "ci3", origin="https://live.example/snow-wx")
    assert info["stations"] == 0 and "skipped" in info


def test_restored_copy_survives_an_outage_on_a_fresh_runner(tmp_path, monkeypatch):
    """Fresh runner: restore the live copy, AWDB down -> stale (not unavailable), history continues from live meta."""
    cfg = load_config()
    cfg["region"]["states"] = ["CO", "UT"]
    cfg["snotel"]["chunk_size"] = 1
    files = live_files(cfg, tmp_path, hours_old=8)
    out = tmp_path / "ci"
    restore.restore_previous(cfg, Site(files), out, origin="https://live.example/snow-wx")
    import pipeline.__main__ as m
    monkeypatch.setattr(m, "make_session", lambda c: Down())
    assert run_obs(cfg, out, ["snotel"]) == 1
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))["sources"]["snotel"]
    assert meta["stale"] is True and 7 < meta["age_h"] < 10
    assert meta["consecutive_failures"] == 3 and meta["last_success_at"] == iso(30)        # history continues from live meta


# ---------------------------------------------------------------- never re-stamp stale data as fresh

def test_stale_timestamps_never_change_across_many_failed_runs(tmp_path, monkeypatch):
    cfg = load_config()
    cfg["region"]["states"] = ["CO", "UT"]
    cfg["snotel"]["chunk_size"] = 1
    cfg["snotel"]["max_age_hours"] = 48
    prev = good_copy(cfg, tmp_path, hours_old=2)
    obs0 = {f["properties"]["triplet"]: f["properties"]["obs_time"] for f in prev["features"]}
    files0 = {p.name: p.read_bytes() for p in (tmp_path / "snotel").glob("*.json")}
    import pipeline.__main__ as m
    monkeypatch.setattr(m, "make_session", lambda c: Down())
    clock = [utcnow()]
    monkeypatch.setattr(snotel, "utcnow", lambda: clock[0])
    ages, through = [], set()
    for i in range(5):                                           # five consecutive hourly failures
        clock[0] += timedelta(hours=1)
        run_obs(cfg, tmp_path, ["snotel"])
        gj = json.loads((tmp_path / "snotel.geojson").read_text(encoding="utf-8"))
        assert {f["properties"]["triplet"]: f["properties"]["obs_time"] for f in gj["features"]} == obs0   # original times
        assert all(f["properties"]["stale"] for f in gj["features"]) and gj["stale"] is True
        ages.append(gj["features"][0]["properties"]["age_h"])
        through.add(gj["observed_through"])
        meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["sources"]["snotel"]
        assert meta["ok"] is False and meta["stale"] is True and meta["consecutive_failures"] == i + 1
    assert ages == sorted(ages) and ages[-1] - ages[0] == pytest.approx(4.0, abs=0.2)        # age grows by an hour per run
    assert len(through) == 1                                                                 # observed_through never moves
    assert {p.name: p.read_bytes() for p in (tmp_path / "snotel").glob("*.json")} == files0  # station files untouched


def test_24h_and_72h_changes_are_hidden_once_older_than_their_window():
    now = utcnow()
    props = {"triplet": "1:UT:SNTL", "state": "UT", "obs_time": (now - timedelta(hours=26) - timedelta(hours=7)).strftime("%Y-%m-%d %H:%M"),
             "depth_in": 40.0, "depth_24h": 6.0, "swe_24h": 0.5, "precip_24h": 0.4, "tmax_24h": 30.0, "tmin_24h": 10.0,
             "depth_72h": 12.0, "swe_72h": 1.1, "temp_f": 20.0}
    f = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-111.0, 40.0]}, "properties": props}
    old = snotel._stale(f, now)["properties"]
    assert old["depth_24h"] is None and old["swe_24h"] is None and old["tmax_24h"] is None   # 26 h > 24 h window
    assert old["depth_72h"] == 12.0 and old["depth_in"] == 40.0 and old["obs_time"] == props["obs_time"]   # 72 h window still open
    young = dict(props, obs_time=(now - timedelta(hours=5) - timedelta(hours=7)).strftime("%Y-%m-%d %H:%M"))
    assert snotel._stale({**f, "properties": young}, now)["properties"]["depth_24h"] == 6.0
