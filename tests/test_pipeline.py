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
