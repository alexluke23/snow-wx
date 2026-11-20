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


# ---------------------------------------------------------------- dev19: the popup text comes only from our files; the pipeline fills what the 11 states miss
def test_alert_id_from_the_map_services_url():
    from pipeline.alerts import alert_id_from_url
    assert alert_id_from_url("https://api.weather.gov/alerts/urn:oid:2.49.0.1.840.0.abc.001") == "urn:oid:2.49.0.1.840.0.abc.001"
    assert alert_id_from_url("https://api.weather.gov/alerts/urn%3Aoid%3A2.49.0.1.840.0.abc.001?x=1") == "urn:oid:2.49.0.1.840.0.abc.001"
    assert alert_id_from_url("https://example.com/x") == "" and alert_id_from_url(None) == ""


class _Resp:
    def __init__(self, js, status=200):
        self._js, self.status_code = js, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._js


class _Sess:
    """the hazard layer query + single-alert fetches; `texts` = {alert id: feature properties}"""

    def __init__(self, layer, alerts, layer_status=200):
        self.layer, self.alerts, self.layer_status, self.calls = layer, alerts, layer_status, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(url)
        if "/MapServer/" in url:
            return _Resp({"features": self.layer}, self.layer_status)
        aid = url.split("/alerts/")[1].replace("%3A", ":")
        if aid in self.alerts:
            return _Resp({"type": "Feature", "properties": {"id": aid, **self.alerts[aid]}})
        return _Resp({}, 404)


HC = {"service": "https://mapservices.example/rest/MapServer", "layer": 1, "include": ["winter storm", "wind advisory"], "exclude": ["marine"]}


def _poly(aid, prod="Winter Storm Warning", wfo="KUNR"):
    return {"attributes": {"prod_type": prod, "url": f"https://api.weather.gov/alerts/{aid}", "wfo": wfo}}


def test_polygons_without_text_are_filled_server_side_and_counted():
    from pipeline.alerts import alert_key, complete_hazard_texts
    have = {alert_key("urn:A"): {"e": "Winter Storm Warning"}}
    s = _Sess([_poly("urn:A"), _poly("urn:B"), _poly("urn:B"), _poly("urn:C", "Wind Advisory", "KABR"), _poly("urn:D"), _poly("urn:M", "Small Craft Advisory")],
              {"urn:B": {"event": "Winter Storm Warning", "headline": "h", "description": "Heavy snow", "senderName": "NWS Rapid City"},
               "urn:C": {"event": "Wind Advisory", "description": "Gusts"}})
    extra, cov = complete_hazard_texts(s, HC, have, [-125, 31, -102, 49.5])
    assert set(extra) == {alert_key("urn:B"), alert_key("urn:C")} and extra[alert_key("urn:B")]["d"] == "Heavy snow" and extra[alert_key("urn:B")]["o"] == "NWS Rapid City"
    assert cov["polygons"] == 4 and cov["resolved"] == 1 and cov["filled"] == 2 and cov["unresolved"] == 1 and cov["unresolved_wfos"] == ["KUNR"]      # urn:D is not fetchable (404); the marine product is not a hazard


def test_the_fill_is_capped_and_a_broken_layer_is_unknown_not_an_error():
    from pipeline.alerts import complete_hazard_texts
    layer = [_poly(f"urn:{i}") for i in range(10)]
    s = _Sess(layer, {f"urn:{i}": {"event": "Winter Storm Warning", "description": "x"} for i in range(10)})
    extra, cov = complete_hazard_texts(s, HC, {}, [-125, 31, -102, 49.5], cap=3)
    assert len(extra) == 3 and cov["filled"] == 3 and cov["unresolved"] == 7 and len([c for c in s.calls if "/alerts/" in c]) == 3
    extra, cov = complete_hazard_texts(_Sess([], {}, layer_status=500), HC, {}, [-125, 31, -102, 49.5])
    assert extra == {} and cov["unknown"] is True


def test_run_writes_the_coverage_next_to_the_texts(tmp_path, monkeypatch):
    import json

    from pipeline import alerts
    from pipeline.alerts import alert_key
    from pipeline.common import load_config
    cfg = load_config()
    cfg["region"]["states"] = ["CO"]
    cfg["hazards"] = {**cfg["hazards"], "service": HC["service"]}
    feat = {"type": "Feature", "geometry": None, "properties": {"id": "urn:A", "event": "Winter Storm Warning", "status": "Actual", "headline": "h", "description": "d", "geocode": {"UGC": ["COZ001"]}}}

    class S(_Sess):
        def get(self, url, params=None, headers=None, timeout=None):
            if url == alerts.URL:
                return _Resp({"features": [feat]})
            return super().get(url, params=params, headers=headers, timeout=timeout)
    monkeypatch.setattr(alerts, "load_sites", lambda: ([], []))
    s = S([_poly("urn:A"), _poly("urn:Z")], {"urn:Z": {"event": "Winter Storm Warning", "description": "Dakota text"}})
    alerts.run(cfg, s, tmp_path)
    doc = json.loads((tmp_path / "alerts" / "hazard_text.json").read_text(encoding="utf-8"))
    assert set(doc["alerts"]) == {alert_key("urn:A"), alert_key("urn:Z")} and doc["coverage"]["polygons"] == 2 and doc["coverage"]["filled"] == 1 and doc["coverage"]["unresolved"] == 0
