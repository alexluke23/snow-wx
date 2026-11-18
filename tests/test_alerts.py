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


# ---- dev17 Part 0a: compact text of every alert of the hazard layer's event types (also those touching no ski area / SNOTEL site)
HZ_INC = ["winter storm", "winter weather", "wind advisory", "high wind"]
HZ_EXC = ["marine", "gale"]


def _feat(i, event, status="Actual", **kw):
    p = {"id": f"urn:oid:hz{i}", "status": status, "event": event, "headline": f"{event} until Sun", "senderName": "NWS Test",
         "areaDesc": "Somewhere; Elsewhere", "geocode": {"UGC": ["XXZ001"]}, "effective": "2026-11-18T01:00:00-07:00",
         "ends": "2026-11-19T05:00:00-07:00", "description": "Heavy snow.\nTotals 12 in.", "instruction": "Slow down."}
    p.update(kw)
    return {"type": "Feature", "geometry": None, "properties": p}


def test_hazard_texts_cover_layer_event_types_even_when_no_site_matches():
    feats = [_feat(1, "Winter Storm Warning"), _feat(2, "Wind Advisory"), _feat(3, "Flood Warning"), _feat(4, "Gale Warning"),
             _feat(5, "Winter Weather Advisory", status="Test"), _feat(6, "Special Weather Statement"), _feat(7, "High Wind Watch")]
    out = A.hazard_texts(feats, HZ_INC, HZ_EXC)
    assert sorted(v["e"] for v in out.values()) == ["High Wind Watch", "Wind Advisory", "Winter Storm Warning"]   # flood/gale/test/statement left out
    k = A.alert_key("urn:oid:hz1")
    assert out[k] == {"e": "Winter Storm Warning", "h": "Winter Storm Warning until Sun", "o": "NWS Test", "f": "2026-11-18T01:00:00-07:00",
                      "x": "2026-11-19T05:00:00-07:00", "a": "Somewhere; Elsewhere", "d": "Heavy snow.\nTotals 12 in.", "i": "Slow down."}
    index, _ = A.build(feats, [{"id": "x", "codes": {"UTZ1"}, "lonlat": [(0, 0)]}], [])
    assert index["count"] == 0                                    # none touch a site, yet the popup text exists


def test_hazard_texts_are_compact_and_truncate_long_text():
    big = "x" * 20000
    out = A.hazard_texts([_feat(1, "Winter Storm Warning", description=big, instruction=big, areaDesc=big, headline=None)], HZ_INC, HZ_EXC)
    v = next(iter(out.values()))
    assert len(v["d"]) == 4000 and len(v["i"]) == 2000 and len(v["a"]) == 500 and "h" not in v      # empty fields are left out
    assert A.is_hazard_event("Wind Advisory", HZ_INC, HZ_EXC) and not A.is_hazard_event("Winter Storm Warning Test", HZ_INC, HZ_EXC)


def test_run_writes_hazard_text_next_to_the_index(tmp_path, monkeypatch):
    feats = [_feat(1, "Winter Storm Warning"), _feat(2, "Flood Warning")]

    class R:
        def raise_for_status(self): pass
        def json(self): return {"features": feats}

    class S:
        def get(self, *a, **k): return R()
    monkeypatch.setattr(A, "load_sites", lambda: ([], []))
    res = A.run({"region": {"states": ["UT"]}, "hazards": {"enabled": True, "include": HZ_INC, "exclude": HZ_EXC}}, S(), tmp_path)
    import json
    ht = json.loads((tmp_path / "alerts" / "hazard_text.json").read_text(encoding="utf-8"))
    assert list(ht["alerts"]) == [A.alert_key("urn:oid:hz1")] and res["count"] == 0
