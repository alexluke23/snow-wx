"""dev20: the browser suite's frozen inputs (tools/browser_fixtures.py) never depend on live data."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import browser_fixtures as BF  # noqa: E402


def test_freeze_makes_the_snapshot_active_now_and_keeps_the_inspected_areas_alert_free(tmp_path):
    now = datetime(2027, 3, 1, 12, tzinfo=timezone.utc)
    info = BF.freeze(tmp_path, now)
    ix = json.loads((tmp_path / "data" / "alerts" / "index.json").read_text(encoding="utf-8"))
    assert info["alerts"] == len(ix["alerts"]) > 0 and ix["generated_at"] == "2027-03-01T12:00:00Z"
    ends = [datetime.fromisoformat(a["ends"]) for a in ix["alerts"].values() if a.get("ends")]
    assert ends and max(ends) == datetime(2027, 3, 2, 0, tzinfo=timezone.utc) and all(e > now for e in ends)
    assert not (set(ix["areas"]) & BF.KEEP_OUT) and not (set(ix.get("points", {})) & BF.KEEP_OUT)
    for name in ("details.json", "hazard_text.json"):
        assert (tmp_path / "data" / "alerts" / name).exists()


def test_freeze_is_deterministic_for_the_same_now(tmp_path):
    now = datetime(2027, 3, 1, 12, tzinfo=timezone.utc)
    BF.freeze(tmp_path / "a", now)
    BF.freeze(tmp_path / "b", now)
    for name in ("index.json", "details.json", "hazard_text.json"):
        assert (tmp_path / "a" / "data" / "alerts" / name).read_bytes() == (tmp_path / "b" / "data" / "alerts" / name).read_bytes()


def test_third_party_hosts_are_answered_from_fixtures_and_unknown_hosts_are_refused():
    code, ctype, body = BF.respond("https://basemap.nationalmap.gov/arcgis/rest/services/USGSShadedReliefOnly/MapServer/tile/6/24/12")
    assert code == 200 and ctype == "image/png" and body[:8] == b"\x89PNG\r\n\x1a\n"
    tj = json.loads(BF.respond("https://tiles.openfreemap.org/planet")[2])
    assert tj["tiles"][0].startswith("https://tiles.openfreemap.org/") and BF.respond("https://tiles.openfreemap.org/planet/fixture/6/1/2.pbf")[2] == b""
    hz = json.loads(BF.respond("https://mapservices.weather.noaa.gov/eventdriven/rest/services/WWA/watch_warn_adv/MapServer/1/query?where=1")[2])
    assert hz["features"] and all("prod_type" in f["properties"] for f in hz["features"])
    assert BF.respond("https://api.weather.gov/alerts/active") is None and BF.respond("https://cdn.example.com/x.js") is None
