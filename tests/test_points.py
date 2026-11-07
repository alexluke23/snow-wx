"""NBM inventory parsing and point-forecast math (offline)."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from pipeline import points as P
from pipeline.nbm import inventory as inv
from pipeline.nbm.run import merge_ranges, point_forecast

IDX = """\
1:0:d=2026110612:TMP:2 m above ground:24 hour fcst:
2:100:d=2026110612:ASNOW:surface:23-24 hour acc@(fcst,dt=1 hour),missing=0:10% level
3:250:d=2026110612:ASNOW:surface:23-24 hour acc fcst:
4:300:d=2026110612:APCP:surface:18-24 hour acc fcst:prob >0.254:prob fcst 255/255
5:400:d=2026110612:PTYPE:surface:24 hour fcst:prob >=5 <7:prob fcst 1/1
6:450:d=2026110612:TMIN:2 m above ground:12-24 hour min fcst:ens std dev
7:500:d=2026110612:APCP:surface:0-1 day acc fcst:50% level
8:600:d=2026110612:SNOWLVL:0 m above mean sea level:24 hour fcst:
"""


def test_parse_idx_kinds_windows_lengths():
    msgs = inv.parse_idx(IDX)
    assert [m.kind for m in msgs] == ["det", "pct", "det", "prob", "prob", "std", "pct", "det"]
    assert (msgs[1].start, msgs[1].end, msgs[1].value, msgs[1].length) == (23, 24, 10, 150)
    assert msgs[3].value == ">0.254" and msgs[4].value == ">=5 <7" and msgs[5].stat == "min"
    assert (msgs[6].start, msgs[6].end) == (0, 24)                     # day window in hours
    assert msgs[0].start is None and msgs[-1].length is None
    S = inv.Sel
    assert inv.find(msgs, S("x", "core", "ASNOW", "surface", 1), 24) is msgs[2]
    assert inv.find(msgs, S("x", "core", "ASNOW", "surface", 1, "pct", 10), 24) is msgs[1]
    assert inv.find(msgs, S("x", "core", "APCP", "surface", None, "pct", 50, span=(0, 24)), 24) is msgs[6]
    assert inv.find(msgs, S("x", "core", "ASNOW", "surface", 6), 24) is None


def test_selections_and_hours():
    hours = inv.forecast_hours(264)
    assert hours[:3] == [1, 2, 3] and 36 in hours and 37 not in hours and 39 in hours
    assert 72 in hours and 75 not in hours and hours[-1] == 264 and len(hours) == 36 + 12 + 32
    keys = lambda h, c=12: {s.key for s, _ in inv.selections(h, c)}  # noqa: E731
    assert {"qpf1", "snow1", "t2m"} <= keys(5) and "qpf6" not in keys(5)
    assert {"qpf6", "snow6", "qpf12_p50", "qpf_0_1d_p50"} <= keys(24)       # 12Z+24 = 12Z
    assert "qpf12_p50" not in keys(18) and "qpf12_p50" in keys(18, 6)        # 06Z+18 = 00Z
    assert {"qpf_0_3d_p10", "qpf_0_3d_p90"} <= keys(72) and "qpf1" not in keys(72)


def test_merge_ranges():
    msgs = inv.parse_idx(IDX)[:7]
    merged = merge_ranges([msgs[1], msgs[2], msgs[6]])
    assert [(a, b, len(m)) for a, b, m in merged] == [(100, 299, 2), (500, 599, 1)]


def test_lapse_adjust_and_cap():
    assert P.lapse_adjust_f(30.0, 8000, 8000) == 30.0
    # summit 3281 ft (1 km) above the grid cell: 6.5 C = 11.7 F colder
    assert P.lapse_adjust_f(30.0, 8000, 8000 + 3280.84) == pytest.approx(30 - 11.7, abs=0.01)
    assert P.lapse_adjust_f(30.0, 8000, 2000) == pytest.approx(30 + 6.5 * 1.8 * 4000 * 0.3048 / 1000)
    assert P.lapse_adjust_f(None, 8000, 9000) is None


def test_p_snow_from_snow_level():
    f = P.p_snow_level_below
    assert f(9000, 6000, 7000, 8000) == 1.0
    assert f(5000, 6000, 7000, 8000) == 0.0
    assert f(7000, 6000, 7000, 8000) == pytest.approx(0.5)
    assert f(7500, 6000, 7000, 8000) == pytest.approx(0.7)
    assert f(6000, 6000, 7000, 8000) == pytest.approx(0.1)
    assert f(7400, None, 7000, None) == pytest.approx(0.75)               # deterministic ramp
    assert f(9000, None, None, None) is None
    assert P.precip_type(0.3, 0.9) == "snow" and P.precip_type(0.3, 0.5) == "mix"
    assert P.precip_type(0.3, 0.1) == "rain" and P.precip_type(0.0, 0.9) is None


def test_ratio_quality_sums():
    assert P.snow_ratio(6.0, 0.5, 20, 1.0) == 12.0
    assert P.snow_ratio(0.0, 0.0, 15, 0.4) == pytest.approx(6.0)        # fallback SLR x P(snow)
    assert P.snow_ratio(0.0, 0.0, 0.3, 0.5) == pytest.approx(5.0)       # SLR ~0 when dry -> 10:1
    assert P.powder_quality(16, 20, 4) == "Blower"
    assert P.powder_quality(12, 35, 4) == "Medium, wind-affected"
    assert P.powder_quality(8, None, 4) == "Dense" and P.powder_quality(20, 10, 0.1) is None
    assert P.comonotonic_sum([{10: 1, 50: 2, 90: 4}, {10: 0, 50: 1, 90: 3}]) == {10: 1, 50: 3, 90: 7}
    assert P.comonotonic_sum([{10: 1, 50: None}]) == {10: None, 50: None}
    assert P.window_sum({6: 1.0, 12: 2.0}, 0, 12, 6) == 3.0
    assert P.window_sum({6: 1.0}, 0, 12, 6) is None


def test_periods_align_to_00z_12z():
    tz = ZoneInfo("America/Denver")
    init = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    per = P.periods(init, list(range(1, 49)))
    assert per[:3] == [(0, 12), (12, 24), (24, 36)] and per[-1] == (36, 48)
    lab = P.period_label(init, 0, 12, tz)
    assert lab["label"] == "Sat day" and lab["is_day"] and lab["start"] == "2026-11-07T12:00Z"
    assert P.period_label(init, 12, 24, tz)["label"] == "Sat night"
    init6 = datetime(2026, 11, 7, 6, tzinfo=timezone.utc)
    assert P.periods(init6, list(range(1, 31)))[:2] == [(0, 6), (6, 18)]       # partial first night


def _fake_hour(h, n=2, snow1=0.0, qpf1=0.0):
    d = {"t2m": np.full(n, 30.0), "wind": np.full(n, 10.0), "gust": np.full(n, 20.0),
         "wdir": np.full(n, 270.0), "sky": np.full(n, 80.0), "snowlvl": np.full(n, 6000.0),
         "slr": np.full(n, 15.0)}
    if h <= 36:
        d.update(qpf1=np.full(n, qpf1), snow1=np.full(n, snow1), pop1=np.full(n, 0.5))
    if h % 6 == 0:
        d.update(qpf6=np.full(n, 0.2), snow6=np.full(n, 3.0), pop6=np.full(n, 0.6))
        if h % 12 == 0:
            d.update(qpf12_p10=np.full(n, 0.1), qpf12_p50=np.full(n, 0.4), qpf12_p90=np.full(n, 0.8))
    if h == 24:
        d.update(qpf_0_1d_p10=np.full(n, 0.2), qpf_0_1d_p50=np.full(n, 0.8), qpf_0_1d_p90=np.full(n, 1.6))
    return d


def test_point_forecast_periods_and_totals():
    init = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    hours = list(range(1, 25))
    data = {h: _fake_hour(h, snow1=0.5, qpf1=0.03) for h in hours}
    fc = point_forecast(data, hours, init, 0, elev_ft=9000, grid_ft=8000, tz=ZoneInfo("America/Denver"))
    # 1000 ft above the grid cell: 30 F - 3.57 F
    assert fc["series"]["t_f"][0] == pytest.approx(26.4, abs=0.05)
    assert fc["series"]["p_snow"][0] == 1.0                                  # snow level 6000 < 9000 ft
    per = fc["periods"][0]
    # det snow 6 in / det QPF 0.4 in = 15:1, applied to QPF percentiles 0.1/0.4/0.8
    assert per["snow_in"] == {"10": 1.5, "50": 6.0, "90": 12.0} and per["type"] == "snow"
    assert per["powder"] == "Blower" and per["t_max_f"] == pytest.approx(26.4, abs=0.05)
    assert fc["totals"]["24h"]["snow_in"]["50"] == pytest.approx(12.0)      # 0.8 in x 15
    assert len(fc["precip"]["end"]) == 24 and fc["precip"]["hours"][0] == 1


def test_ndfd_interval_overlap():
    from pipeline.nbm.sanity import overlap_sum, parse_interval
    a, b = parse_interval("2026-11-07T18:00:00+00:00/PT6H")
    assert (b - a).total_seconds() == 6 * 3600
    assert parse_interval("2026-11-07T00:00:00+00:00/P1DT6H")[1].day == 8
    vals = [{"validTime": "2026-11-07T06:00:00+00:00/PT12H", "value": 12.0},
            {"validTime": "2026-11-07T18:00:00+00:00/PT6H", "value": 6.0},
            {"validTime": "2026-11-08T00:00:00+00:00/PT12H", "value": 10.0}]
    t0 = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    from datetime import timedelta
    # half of the first interval (6), all of the second (6), half of the third (5)
    assert overlap_sum(vals, t0, t0 + timedelta(hours=18)) == pytest.approx(17.0)
    assert overlap_sum(vals, t0, t0 + timedelta(hours=48)) is None           # < 90% covered


def test_flat_index_alternative_row_scanning():
    from pipeline.nbm.run import flat_index
    ii, jj = np.array([0, 3, 3]), np.array([0, 0, 1])
    assert flat_index(ii, jj, 10, False).tolist() == [0, 3, 13]
    assert flat_index(ii, jj, 10, True).tolist() == [0, 3, 16]      # odd row stored reversed: 10 + (9 - 3)


def test_monotone_totals():
    t = {"24h": {"qpf_in": {"90": 1.0}, "snow_in": {"50": 5.0, "90": 9.0}},
         "72h": {"qpf_in": {"90": 0.8}, "snow_in": {"50": 6.0, "90": 8.0}},
         "7d": {"qpf_in": {"90": 2.0}, "snow_in": {"50": None, "90": 7.0}}}
    P.monotone_totals(t)
    assert t["72h"]["qpf_in"]["90"] == 1.0 and t["72h"]["snow_in"] == {"50": 6.0, "90": 9.0}
    assert t["7d"]["snow_in"] == {"50": None, "90": 9.0}
