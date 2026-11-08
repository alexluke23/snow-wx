import json

import pandas as pd
import pytest

from pipeline import asos, avalanche, snotel
from pipeline.__main__ import run_obs
from pipeline.common import load_config, utcnow
from tests.fakes import FakeSession, hourly_values


@pytest.fixture
def cfg():
    c = load_config()
    c["region"]["states"] = ["CO", "UT", "ID"]
    return c


# ---------- SNOTEL ----------

def test_snotel_summary_detects_storm_and_drops_spike():
    series = {code: [(v["date"], v["value"], None) for v in hourly_values(code)]
              for code in ("WTEQ", "SNWD", "PREC", "TOBS")}
    s = snotel.summarize(series)
    assert s["depth_in"] == pytest.approx(42, abs=0.2)
    assert s["depth_24h"] == pytest.approx(12, abs=1.0)
    assert s["swe_24h"] == pytest.approx(1.2, abs=0.1)
    assert s["precip_24h"] == pytest.approx(1.3, abs=0.1)
    ts = snotel.timeseries(series, ["SNWD"])
    assert 999 not in ts["SNWD"]


def test_smoothed_depth_damps_noise_and_keeps_gaps():
    times = [f"2026-11-06 {h:02d}:00" for h in range(8)]
    depth = [30, 31, 44, 30, 31, None, 31, 30]          # in-range spike at 02:00, gap at 05:00
    series = {"SNWD": [(t, v, None) for t, v in zip(times, depth)]}
    ts = snotel.timeseries(series, ["SNWD"])
    assert len(ts["SNWD_med3"]) == len(ts["SNWD"]) == len(ts["times"]) == 8
    assert ts["SNWD"][2] == 44                          # raw kept
    assert ts["SNWD_med3"][2] == 31                     # median of 31, 44, 30
    assert ts["SNWD_med3"][5] is None                   # gap not bridged
    assert ts["SNWD_med3"][0] == pytest.approx(30.5)    # edge: median of 30, 31


def test_timeseries_handles_missing_elements():
    # Live failure 2026-11-07: a station with no TOBS data gave the frame a
    # non-datetime index and the time-based rolling window raised.
    series = {"SNWD": [(v["date"], v["value"], None) for v in hourly_values("SNWD", 30)],
              "WTEQ": [], "TOBS": []}
    ts = snotel.timeseries(series, ["WTEQ", "SNWD", "PREC", "TOBS"])
    assert len(ts["SNWD_med3"]) == len(ts["times"]) == 31
    assert all(v is None for v in ts["TOBS"])
    only_empty = snotel.timeseries({"SNWD": []}, ["SNWD"])
    assert only_empty["times"] == [] and only_empty["SNWD_med3"] == []


def test_change_over_needs_history():
    idx = pd.date_range("2026-11-01", periods=10, freq="h")
    s = pd.Series(range(10), index=idx, dtype=float)
    assert snotel.change_over(s, 24) is None
    assert snotel.change_over(s, 5) == 5


def test_snotel_run_writes_files(cfg, tmp_path):
    info = snotel.run(cfg, FakeSession(), tmp_path)
    assert info["count"] == 3
    fc = json.loads((tmp_path / "snotel.geojson").read_text())
    props = fc["features"][0]["properties"]
    assert props["pct_median"] == pytest.approx(125, abs=0.1)
    assert props["median_swe_in"] == pytest.approx(6.4)
    assert (tmp_path / props["file"]).exists()


def test_pct_median_suppressed_when_median_tiny():
    # Wood Creek, early season: 0.7" SWE vs a 0.175" median would read 400%.
    daily = {"WTEQ": [("2026-11-04", 0.6, 0.15), ("2026-11-05", 0.7, 0.175)]}
    assert snotel.pct_of_median(daily) == pytest.approx(400)
    assert snotel.pct_of_median(daily, min_median=1.0) is None
    assert snotel.median_swe(daily) == (0.7, 0.175)
    ok = {"WTEQ": [("2026-11-05", 8.0, 6.4)]}
    assert snotel.pct_of_median(ok, min_median=1.0) == pytest.approx(125)
    assert snotel.pct_of_median({"WTEQ": [("2026-11-05", 0.0, 0.0)]}, 1.0) is None


# ---------- ASOS ----------

def test_asos_run_flags_stale(cfg, tmp_path):
    asos.run(cfg, FakeSession(), tmp_path)
    fc = json.loads((tmp_path / "asos.geojson").read_text())
    by_id = {f["properties"]["id"]: f["properties"] for f in fc["features"]}
    assert by_id["DEN"]["stale"] is False and by_id["DEN"]["wind_kt"] == 17
    assert by_id["EGE"]["stale"] is True
    assert fc["features"][0]["geometry"]["coordinates"][0] < -100


# ---------- Avalanche ----------

def test_avalanche_filters_states_and_expires(cfg, tmp_path):
    avalanche.run(cfg, FakeSession(), tmp_path)
    fc = json.loads((tmp_path / "avalanche.geojson").read_text())
    by_name = {f["properties"]["name"]: f["properties"] for f in fc["features"]}
    assert "Turnagain Pass" not in by_name            # AK filtered out
    assert by_name["Front Range"]["danger"] == "Considerable"
    assert by_name["Salt Lake"]["expired"] is True    # end_date in the past
    assert by_name["Salt Lake"]["danger_level"] == 0
    assert by_name["Galena Summit"]["danger"] == "No rating"


def test_parse_time_naive_is_utc():
    t = avalanche.parse_time("2026-11-06T12:00:00")
    assert str(t.tz) == "UTC"


# ---------- whole command ----------

def test_one_source_failing_does_not_stop_others(cfg, tmp_path, monkeypatch):
    fake = FakeSession(fail=["avalanche.org"])
    monkeypatch.setattr("pipeline.__main__.make_session", lambda c: fake)
    assert run_obs(cfg, tmp_path) == 0
    meta = json.loads((tmp_path / "meta.json").read_text())
    assert meta["sources"]["avalanche"]["ok"] is False
    assert meta["sources"]["snotel"]["ok"] is True
    assert meta["sources"]["asos"]["ok"] is True


def test_meta_merges_partial_runs_and_products(cfg, tmp_path):
    import json as _json
    from pipeline.__main__ import product_status, write_meta
    write_meta(cfg, tmp_path, {"snotel": {"ok": True, "count": 5}, "asos": {"ok": True, "count": 3}})
    write_meta(cfg, tmp_path, {"avalanche": {"ok": True, "count": 2}})          # e.g. obs --only avalanche
    assert set(_json.loads((tmp_path / "meta.json").read_text())["sources"]) == {"snotel", "asos", "avalanche"}
    site = tmp_path / "site"
    (site / "data" / "points").mkdir(parents=True)
    (site / "data" / "points" / "summary.json").write_text(_json.dumps(
        {"cycle": "2026110712", "generated_at": "2026-11-07T15:00:00Z", "areas": [{}, {}]}))
    st = product_status(site)
    assert st["points"] == {"ok": True, "count": 2, "unit": "ski areas", "detail": "NBM 12Z run",
                            "at": "2026-11-07T15:00:00Z"}
    assert st["models"]["ok"] is False


def test_search_index_lists_areas_and_snotel_with_page_ids(tmp_path):
    import json
    from pipeline.search import build_index
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "ski_areas.json").write_text(json.dumps({"areas": [
        {"id": "alta-ski-area", "name": "Alta Ski Area", "region": "Wasatch", "state": "UT"}]}))
    (tmp_path / "data" / "snotel_points.json").write_text(json.dumps({"points": [
        {"id": "snotel-766-UT-SNTL", "triplet": "766:UT:SNTL", "name": "Snowbird", "state": "UT", "elev_ft": 9177}]}))
    items = build_index(tmp_path)["items"]
    assert items[0] == {"k": "area", "id": "alta-ski-area", "n": "Alta Ski Area", "s": "Ski area · Wasatch, UT"}
    assert items[1]["id"] == "snotel-766-UT-SNTL" and items[1]["x"] == ["766", "766:UT:SNTL"]
    assert items[1]["s"] == "SNOTEL 766 · UT · 9,177 ft"
