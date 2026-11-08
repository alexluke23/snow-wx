"""NWS alert matching (offline, recorded-style sample)."""

from pipeline import alerts as A

ZONE_ALERT = {"type": "Feature", "geometry": None, "properties": {
    "id": "urn:oid:1", "status": "Actual", "event": "Winter Storm Warning", "severity": "Severe",
    "headline": "Winter Storm Warning until Sun 5 PM", "senderName": "NWS Salt Lake City UT",
    "areaDesc": "Wasatch Mountains", "geocode": {"UGC": ["UTZ111", "UTZ110"]}, "ends": "2026-11-09T17:00:00-07:00",
    "description": "Heavy snow expected. Total snow accumulations 12 to 24 inches.", "instruction": "Avoid travel."}}
POLY_ALERT = {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[-112, 40], [-111, 40], [-111, 41], [-112, 41], [-112, 40]]]},
              "properties": {"id": "urn:oid:2", "status": "Actual", "event": "High Wind Warning", "severity": "Severe",
                             "geocode": {"UGC": ["UTZ999"]}, "expires": "2026-11-08T12:00:00-07:00"}}
TEST_ALERT = {"type": "Feature", "geometry": None, "properties": {
    "id": "urn:oid:3", "status": "Test", "event": "Winter Weather Advisory", "geocode": {"UGC": ["UTZ111"]}}}


def test_short_names_and_levels():
    assert A.short_name("Winter Storm Warning") == "Winter Storm Warn."
    assert A.short_name("Winter Weather Advisory") == "Winter Weather Adv."
    assert A.summarize(ZONE_ALERT)["level"] == "warning" and A.summarize(TEST_ALERT)["level"] == "advisory"


def test_match_by_zone_county_and_polygon():
    areas = [{"id": "alta", "codes": {"UTZ111", "UTC035"}, "lonlat": [(-111.64, 40.59)]},
             {"id": "far", "codes": {"COZ034"}, "lonlat": [(-106.1, 39.5)]}]
    points = [{"id": "snotel-1", "codes": {"UTZ999"}, "lonlat": [(-111.7, 40.6)]},
              {"id": "snotel-2", "codes": {"UTZ001"}, "lonlat": [(-111.5, 40.5)]}]   # inside the polygon only
    index, details = A.build([ZONE_ALERT, POLY_ALERT, TEST_ALERT], areas, points)
    assert [r["event"] for r in index["areas"]["alta"]] == ["Winter Storm Warning", "High Wind Warning"]
    assert "far" not in index["areas"]
    assert [r["event"] for r in index["points"]["snotel-2"]] == ["High Wind Warning"]
    assert index["count"] == 2                                   # status "Test" ignored
    k = index["areas"]["alta"][0]["id"]
    assert "12 to 24 inches" in details[k]["description"] and index["alerts"][k]["ends"].startswith("2026-11-09")


def test_relevant_alerts_first_others_kept():
    flood = {"type": "Feature", "geometry": None, "properties": {
        "id": "urn:oid:9", "status": "Actual", "event": "Flood Warning", "geocode": {"UGC": ["UTZ111"]}}}
    wind = {"type": "Feature", "geometry": None, "properties": {
        "id": "urn:oid:8", "status": "Actual", "event": "Wind Advisory", "geocode": {"UGC": ["UTZ111"]}}}
    areas = [{"id": "alta", "codes": {"UTZ111"}, "lonlat": [(-111.64, 40.59)]}]
    index, _ = A.build([flood, wind, ZONE_ALERT], areas, [])
    refs = index["areas"]["alta"]
    # winter/wind first (warnings before advisories), the flood warning is kept but last
    assert [r["event"] for r in refs] == ["Winter Storm Warning", "Wind Advisory", "Flood Warning"]
    assert [r["relevant"] for r in refs] == [True, True, False]
