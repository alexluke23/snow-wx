"""W7 wind-exposure flag, Phase A (pipeline/wind_exposure.py; spec docs/specs/wind-exposure.md). The five spec cases, plus wording/flag rules.
The flag is built but OFF (config wind_exposure.enabled = false); these tests never turn it on for the site."""

from datetime import datetime, timedelta
from pathlib import Path

import yaml

from pipeline import wind_exposure as W

T0 = datetime(2026, 11, 18, 0, 0)
TIMES = [(T0 + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%MZ") for h in range(72)]


def precip(snow_by_6h: dict[int, float]):
    """6-hour windows ending at hour 6, 12, ... with the given snow (in)"""
    ends = list(range(6, 73, 6))
    return {"end": [(T0 + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%MZ") for h in ends], "hours": [6] * len(ends),
            "snow_in": [snow_by_6h.get(h, 0.0) for h in ends]}


def wind(base=8, gust=14, spans=(), direction=225):
    """hourly series: spans = [(from_h, to_h, sustained, gust)]"""
    w, g = [base] * 72, [gust] * 72
    for a, b, ws, gs in spans:
        for h in range(a, b):
            w[h], g[h] = ws, gs
    return w, g, [direction] * 72


# ---- the five cases
def test_1_strong_southwest_wind_during_snowfall_flags_with_leeward_northeast():
    w, g, d = wind(spans=[(6, 14, 32, 48)], direction=225)
    f = W.assess(TIMES, w, g, d, precip({12: 4.0, 18: 3.0}))
    assert f and f["flag"] and f["wind_from"] == "SW" and f["leeward"] == "NE" and f["peak_wind_mph"] == 32 and f["peak_gust_mph"] == 48
    assert "leeward (NE-facing)" in f["text"] and f["title"] == "Wind-affected snow likely" and f["disclaimer"] == "Wind transport potential — not an avalanche rating."


def test_2_strong_wind_with_no_snow_gives_no_flag():
    w, g, d = wind(spans=[(6, 20, 40, 60)])
    assert W.assess(TIMES, w, g, d, precip({})) is None
    assert W.assess(TIMES, w, g, d, precip({12: 0.1})) is None            # a trace is not an episode


def test_3_gusts_alone_trigger_when_sustained_wind_is_moderate():
    w, g, d = wind(spans=[(8, 14, 18, 38)], direction=315)             # sustained 18 < 25, gusts 38 >= 35
    f = W.assess(TIMES, w, g, d, precip({12: 2.0}))
    assert f and f["peak_wind_mph"] == 18 and f["peak_gust_mph"] == 38 and f["wind_from"] == "NW" and f["leeward"] == "SE"


def test_4_snowfall_in_light_wind_gives_no_flag():
    w, g, d = wind(base=9, gust=20)
    assert W.assess(TIMES, w, g, d, precip({12: 6.0, 18: 5.0})) is None


def test_5_wind_that_arrives_after_the_snow_stops_still_counts_within_12_hours_but_not_later():
    snow = precip({12: 3.0})                                              # the snow ends at 12 UTC
    w, g, d = wind(spans=[(16, 20, 30, 40)])
    assert W.assess(TIMES, w, g, d, snow)["start"] == "2026-11-18T16:00Z"
    w, g, d = wind(spans=[(30, 36, 30, 40)])                              # 18 h after the snow: not "during or just after"
    assert W.assess(TIMES, w, g, d, snow) is None


# ---- edges: data gaps, direction, horizon, thresholds
def test_missing_wind_data_gives_no_flag_and_no_crash():
    assert W.assess(TIMES, [None] * 72, [None] * 72, [None] * 72, precip({12: 4.0})) is None
    assert W.assess([], [], [], [], {}) is None and W.assess(TIMES, [], [], [], precip({12: 4.0})) is None


def test_missing_direction_keeps_the_flag_without_a_direction_sentence():
    w, g, _ = wind(spans=[(6, 14, 32, 48)])
    f = W.assess(TIMES, w, g, [None] * 72, precip({12: 4.0}))
    assert f and f["wind_from"] is None and f["leeward"] is None and "direction not available" in f["text"]


def test_opposing_wind_directions_give_no_dominant_direction():
    w, g, _ = wind(spans=[(6, 14, 32, 48)])
    d = [90 if h % 2 else 270 for h in range(72)]
    f = W.assess(TIMES, w, g, d, precip({12: 4.0}))
    assert f and f["wind_from"] is None


def test_one_windy_hour_is_not_enough_and_the_horizon_is_72_hours():
    w, g, d = wind(spans=[(10, 11, 40, 60)])
    assert W.assess(TIMES, w, g, d, precip({12: 4.0})) is None            # min_windy_hours = 2
    w, g, d = wind(spans=[(66, 72, 40, 60)])
    late = {"end": [(T0 + timedelta(hours=78)).strftime("%Y-%m-%dT%H:%MZ")], "hours": [6], "snow_in": [4.0]}   # episode starts at 72 h
    assert W.assess(TIMES, w, g, d, late) is None


def test_thresholds_come_from_config_and_the_flag_is_off_by_default():
    assert W.DEFAULTS["enabled"] is False
    cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "settings.yml").read_text(encoding="utf-8"))
    assert cfg["wind_exposure"]["enabled"] is False                         # NEVER enabled in the repo: the owner decides after the reviewer sign-off
    assert W.configure(cfg)["sustained_mph"] == 25 and W.configure({"wind_exposure": {"sustained_mph": 30, "bogus": 1}})["sustained_mph"] == 30
    doc = {"id": "x", "times": TIMES, "points": {"summit": {"series": {"wind_mph": [40] * 72, "gust_mph": [60] * 72, "wdir": [270] * 72},
                                                           "precip": precip({12: 4.0})}}, "area": {"avalanche": {"center_id": "UAC"}}}
    assert W.for_point_doc(doc, cfg) is None                                # disabled: nothing is produced, nothing reaches the site
    on = W.for_point_doc(doc, {"wind_exposure": {"enabled": True}})
    assert on and on["avalanche_center_id"] == "UAC" and on["wind_from"] == "W"


def test_wording_is_never_an_avalanche_rating_or_a_risk_number():
    w, g, d = wind(spans=[(6, 14, 32, 48)], direction=250)
    f = W.assess(TIMES, w, g, d, precip({12: 4.0}))
    blob = " ".join(str(v) for k, v in f.items() if k in ("title", "text", "caveat")).lower()
    assert not [x for x in W.FORBIDDEN if x in blob], blob
    assert "not an avalanche rating" in f["disclaimer"].lower() and "avalanche centre" in f["caveat"].lower()
    assert not [k for k in f if "risk" in k or "score" in k or "index" in k or "danger" in k]        # no numeric risk field exists
    # the only numbers are the forecast wind itself (and the snowfall that triggered the flag)
    assert set(k for k, v in f.items() if isinstance(v, (int, float)) and not isinstance(v, bool)) == {"snow_in", "peak_wind_mph", "peak_gust_mph"}


def test_the_site_never_renders_the_flag_unless_a_point_file_carries_it():
    """the page code is inert without the field, and the build never writes it while the config flag is false"""
    root = Path(__file__).resolve().parents[1]
    js = (root / "web" / "js" / "area.js").read_text(encoding="utf-8")
    assert "wind_exposure" in js and "windExposure(" in js and "d.wind_exposure" in js
    run = (root / "pipeline" / "nbm" / "run.py").read_text(encoding="utf-8")
    assert "wind_exposure" in run and "for_point_doc" in run
