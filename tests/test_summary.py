"""Daily Snow summaries (W3): every rule, conflicts/priority, and the native-windows-only rule. Fixtures only."""

from __future__ import annotations

import copy

from pipeline import summary as S

RULES = S.load_rules()


def period(end, snow=0.0, slr=None, gust=10, wind=False, p_snow=1.0, qpf=0.0, lvl=None):
    return {"start": "x", "end": end, "snow_in": snow, "slr": slr, "gust_max_mph": gust, "p_snow": p_snow, "qpf_in": qpf,
            "snowlvl_min_ft": lvl, "snow_type": ({"type": "dry", "label": "Dry/light", "wind": wind} if snow >= 0.5 else None)}


def exceed(window, p50, p_ge, end="2026-11-18T12:00Z"):
    thr = sorted(p_ge)
    return {window: {"start": ["2026-11-17T12:00Z"], "end": [end], "thr": thr, "p": [[p_ge[t] for t in thr]],
                     "pct": {"10": [1.0], "50": [p50], "90": [p50 * 2]}}}


def doc(p50_24=0.0, p12=0, slr=15, gust=15, p50_72=0.0, native=True, lo=None, hi=None, wind=False, base_rain=False, expected_72=None):
    per = [period("2026-11-18T00:00Z", snow=p50_24 / 2, slr=slr if p50_24 else None, gust=gust, wind=wind),
           period("2026-11-18T12:00Z", snow=p50_24 / 2, slr=slr if p50_24 else None, gust=gust, wind=wind)]
    ex = {**exceed("24h", p50_24, {4.0: 50, 8.0: 30, 12.0: p12}), **exceed("72h", p50_72, {4.0: 80, 12.0: 50}, end="2026-11-20T12:00Z")}
    summit = {"periods": per, "exceed": ex,
              "totals": {"24h": {"snow_in": p50_24, "native": True},
                         "72h": {"snow_in": expected_72 if expected_72 is not None else p50_72, "native": native,
                                 "snow_lo": lo, "snow_hi": hi, "snow_q1": None if lo is None else lo + 3, "snow_q3": None if hi is None else hi - 4}}}
    out = {"points": {"summit": summit}}
    if base_rain:
        out["points"]["base"] = {"periods": [period("2026-11-18T00:00Z", snow=0.2, p_snow=0.2, qpf=0.4, lvl=5200)], "exceed": {}, "totals": {}}
    return out


def test_deep_powder_day_fires_with_native_p50_p12_slr_and_calm_wind():
    out = S.summarize(doc(p50_24=10, p12=40, slr=16, gust=12, p50_72=12, lo=6, hi=20), rules=RULES)
    assert out["tag"] == "Deep powder day" and "rule" not in out["sentence"] and out["confidence"] == "high"
    assert "10 in" in out["sentence"] and "40% chance" in out["sentence"] and "heuristic" in out["sentence"]
    assert out["rule_ids"][0] == "deep_powder" and out["native"] is True


def test_deep_powder_needs_every_condition():
    for kw in ({"p50_24": 6}, {"p12": 20}, {"slr": 12}, {"gust": 30}):
        base = dict(p50_24=10, p12=40, slr=16, gust=12, p50_72=12, lo=6, hi=20)
        base.update(kw)
        assert "deep_powder" not in S.summarize(doc(**base), rules=RULES)["rule_ids"], kw


def test_storm_cycle_uses_native_72h_range_and_never_a_composite():
    out = S.summarize(doc(p50_24=5, p12=5, slr=10, p50_72=20, lo=14, hi=30), rules=RULES)
    assert out["tag"] == "Storm cycle" and "likely 17–26 in" in out["sentence"] and "10–90" not in out["sentence"] and "NBM" not in out["sentence"]
    composite = S.summarize(doc(p50_24=5, p12=5, slr=10, p50_72=20, native=False, lo=14, hi=30, expected_72=19), rules=RULES)
    assert "storm_cycle" not in composite["rule_ids"] and composite["confidence"] == "medium" and composite["native"] is False
    assert "17–26" not in composite["sentence"] and not any("17–26" in b for b in composite["bullets"])


def test_rain_at_the_base_outranks_powder_and_wind_is_a_bullet():
    out = S.summarize(doc(p50_24=10, p12=40, slr=16, gust=12, p50_72=12, lo=6, hi=20, base_rain=True, wind=True), rules=RULES)
    assert out["tag"] == "Rain at the base" and "5,200 ft" in out["sentence"]
    assert out["rule_ids"][:3] == ["rain_base", "deep_powder", "wind"]               # priority order; the rest become bullets
    assert any("Deep, light snow" in b for b in out["bullets"])


def test_alert_wins_and_irrelevant_alerts_are_ignored():
    d = doc(p50_24=10, p12=40, slr=16, p50_72=12, lo=6, hi=20)
    out = S.summarize(d, alerts=[{"event": "Winter Storm Warning", "relevant": True}], rules=RULES)
    assert out["tag"] == "Alert active" and "Winter Storm Warning" in out["sentence"] and out["rule_ids"][1] == "deep_powder"
    quiet = S.summarize(d, alerts=[{"event": "Coastal Flood Advisory", "relevant": False}], rules=RULES)
    assert quiet["tag"] == "Deep powder day"


def test_wind_affected_snow_and_dry_stretch_and_baseline():
    tiny = S.summarize(doc(p50_24=1, slr=12, gust=40, wind=True, p50_72=1.5, lo=0, hi=3), rules=RULES)
    assert "wind" not in tiny["rule_ids"]                                   # not worth a wind headline for a dusting
    wind = S.summarize(doc(p50_24=4, slr=12, gust=40, wind=True, p50_72=6, lo=2, hi=9), rules=RULES)
    assert wind["tag"] == "Wind-affected" and "heuristic" in wind["sentence"]
    dry = S.summarize(doc(p50_72=0.2, lo=0, hi=1), rules=RULES)
    assert dry["tag"] == "Dry stretch" and "Little new snow" in dry["sentence"] and dry["confidence"] == "high"
    base = S.summarize(doc(p50_24=3, p12=1, slr=9, p50_72=4, lo=2, hi=7), rules=RULES)
    assert base["tag"] == "Snow expected" and "about 4 in" in base["sentence"]


def test_dry_stretch_outranks_wind_affected():
    # native 72 h median under 1 in but an expected total over the 3 in wind bar: Dry stretch is the headline, wind a bullet
    out = S.summarize(doc(p50_24=1.2, slr=12, gust=40, wind=True, p50_72=0.8, lo=0, hi=2, expected_72=3.5), rules=RULES)
    assert out["tag"] == "Dry stretch" and {"dry", "wind"} <= set(out["rule_ids"]) and out["rule_ids"].index("dry") < out["rule_ids"].index("wind")
    assert any("Wind-affected" in b for b in out["bullets"])


def test_no_native_windows_means_skipped_rules_and_lower_confidence():
    d = doc(p50_24=10, p12=40, slr=16, p50_72=20, lo=6, hi=20)
    d2 = copy.deepcopy(d)
    d2["points"]["summit"]["exceed"] = {}                          # fallback cycle without exceedance windows
    d2["points"]["summit"]["totals"]["72h"]["native"] = False
    out = S.summarize(d2, rules=RULES)
    assert out["confidence"] == "low" and out["native"] is False
    assert not {"deep_powder", "storm_cycle"} & set(out["rule_ids"])
    assert out["tag"] in ("Snow expected", "Little snow") and "average of possible outcomes" in out["sentence"]
    assert S.summarize({"points": {}}, rules=RULES)["tag"] == "No forecast"


def test_station_point_and_rules_file_are_consistent():
    assert set(RULES["priority"]) >= {"alert", "rain_base", "deep_powder", "storm_cycle", "wind", "dry", "baseline"}
    d = doc(p50_24=10, p12=40, slr=16, p50_72=12, lo=6, hi=20)
    station = {"points": {"point": d["points"]["summit"]}}
    assert S.summarize(station, rules=RULES)["tag"] == "Deep powder day"
