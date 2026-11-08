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


# idx excerpts in the layouts seen in docs/nbm_inventory.md (7 Nov 2026)
SYN_F072 = """\
1:0:d=2026110718:TMP:2 m above ground:72 hour fcst:
2:100:d=2026110718:WIND:10 m above ground:72 hour fcst:
3:200:d=2026110718:WDIR:10 m above ground:72 hour fcst:
4:300:d=2026110718:GUST:10 m above ground:72 hour fcst:
5:400:d=2026110718:TCDC:surface:72 hour fcst:
6:500:d=2026110718:SNOWLVL:0 m above mean sea level:72 hour fcst:
7:600:d=2026110718:SNOWLR:surface:72 hour fcst:
8:700:d=2026110718:APCP:surface:66-72 hour acc fcst:
9:800:d=2026110718:ASNOW:surface:66-72 hour acc fcst:
10:900:d=2026110718:END:surface:72 hour fcst:
"""
QMD_18Z_F072 = """\
1:0:d=2026110718:APCP:surface:66-72 hour acc fcst:10% level
2:100:d=2026110718:APCP:surface:60-72 hour acc fcst:10% level
3:200:d=2026110718:APCP:surface:2-3 day acc fcst:10% level
4:300:d=2026110718:APCP:surface:2-3 day acc fcst:90% level
5:400:d=2026110718:END:surface:72 hour fcst:
"""
ODD_F077 = """\
1:0:d=2026110801:ASNOW:surface:53-77 hour acc@(fcst,dt=24 hour),missing=0:10% level
2:100:d=2026110801:ASNOW:surface:5-77 hour acc@(fcst,dt=72 hour),missing=0:90% level
3:200:d=2026110801:ASNOW:surface:71-77 hour acc@(fcst,dt=6 hour),missing=0:50% level
4:300:d=2026110801:ASNOW:surface:29-53 hour acc fcst:prob >0.0254:prob fcst 255/255
5:400:d=2026110801:ASNOW:surface:23-47 hour acc@(fcst,dt=24 hour),missing=0:10% level
6:500:d=2026110801:ASNOW:surface:71-77 hour acc fcst:
7:600:d=2026110801:END:surface:77 hour fcst:
"""


def test_select_is_inventory_driven():
    syn = {k for k in inv.select(inv.parse_idx(SYN_F072), 72, 18, "core").values()}
    assert {"t2m", "wind", "wdir", "gust", "sky", "snowlvl", "slr", "qpf6", "snow6"} <= syn
    # 18Z qmd f072 carries only the 2-3 day block (no 0-3 day): selected, nothing required
    q = inv.select(inv.parse_idx(QMD_18Z_F072), 72, 18, "qmd")
    assert set(q.values()) == {"qpf_2_3d_p10", "qpf_2_3d_p90"}
    # 01Z full suite: 24/72/6-h snowfall percentiles; windows ending earlier (repeated in
    # later files, sometimes with other values) are ignored
    odd = set(inv.select(inv.parse_idx(ODD_F077), 77, 1, "core").values())
    assert odd == {"snow24_p10", "snow72_p90", "snow6_p50", "snow6"}


def test_required_keys_and_sample_hours():
    assert {"qpf1", "snow1"} <= inv.required_keys(5, 1) and "qpf6" not in inv.required_keys(5, 1)
    assert {"qpf6", "snow6"} <= inv.required_keys(11, 1) and "qpf6" not in inv.required_keys(10, 1)
    assert "qpf1" not in inv.required_keys(72, 0) and "qpf6" in inv.required_keys(72, 0)
    syn = inv.sample_hours(list(range(1, 49)) + list(range(51, 193, 3)) + list(range(198, 265, 6)), 0)
    assert syn == inv.forecast_hours(264)                       # synoptic layout unchanged
    odd = inv.sample_hours(list(range(1, 265)), 1)
    assert odd[:3] == [1, 2, 3] and 38 in odd and 39 not in odd and 77 in odd and 78 not in odd
    assert all((1 + h) % 6 == 0 for h in odd if h > 72) and odd[-1] == 263


class FakeResp:
    def __init__(self, status=200, text="", content=b""):
        self.status_code, self.text, self.content, self.ok = status, text, content, status == 200

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    """core idx with one basic field missing; no qmd idx at all."""
    def __init__(self, idx_text):
        self.idx_text = idx_text

    def get(self, u, headers=None, timeout=None):
        if u.endswith(".idx"):
            return FakeResp(200, self.idx_text) if "/core/" in u else FakeResp(404)
        return FakeResp(200, content=b"x" * 2000)

    def head(self, u, timeout=None):
        return FakeResp(200)


def test_fetch_hour_fail_soft_missing_message_and_product(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from pipeline.nbm import run as R
    monkeypatch.setattr(R, "decode_at", lambda part, ij, grid: np.array([1.0]))
    idx = SYN_F072.replace("4:300:d=2026110718:GUST:10 m above ground:72 hour fcst:\n", "")   # gust missing
    out, missing = R.fetch_hour(FakeSession(idx), datetime(2026, 11, 7, 18, tzinfo=timezone.utc), 72,
                                (np.array([0]), np.array([0])), {"nx": 1}, tmp_path)
    assert "t2m" in out and "gust" not in out and missing == ["gust"]
    out2, missing2 = R.fetch_hour(None, datetime(2026, 11, 7, 18, tzinfo=timezone.utc), 72, None, {}, tmp_path)
    assert missing2 == ["gust"] and set(out2) == set(out)        # read back from the cache
    q = R.data_quality({72: ["gust"], 66: []}, 18)
    assert q["missing"] == 1 and q["required"] == 18 and q["by_field"] == {"gust": 1}


def test_latest_cycle_prefers_full_suite_and_falls_back():
    from datetime import datetime, timezone
    from pipeline.nbm.run import latest_cycle
    now = datetime(2026, 11, 8, 4, 30, tzinfo=timezone.utc)
    # newest full-suite cycle (01Z) incomplete -> previous full-suite cycle (19Z)
    done = {datetime(2026, 11, 7, 19, tzinfo=timezone.utc), datetime(2026, 11, 8, 0, tzinfo=timezone.utc)}
    c = latest_cycle(None, now, 264, complete=lambda s, t, h: t in done)
    assert c == datetime(2026, 11, 7, 19, tzinfo=timezone.utc)
    # no full-suite cycle complete in the lookback -> newest complete synoptic cycle
    c = latest_cycle(None, now, 264, complete=lambda s, t, h: t.hour == 0)
    assert c == datetime(2026, 11, 8, 0, tzinfo=timezone.utc)
    assert latest_cycle(None, now, 264, complete=lambda s, t, h: False) is None


def test_odd_cycle_totals_use_nbm_snowfall_percentiles():
    from datetime import timezone
    init = datetime(2026, 11, 8, 1, tzinfo=timezone.utc)
    hours = inv.sample_hours(list(range(1, 81)), 1, 80)
    data = {}
    for h in hours:
        d = {"t2m": np.full(1, 30.0), "wind": np.full(1, 10.0), "gust": np.full(1, 20.0), "wdir": np.full(1, 270.0),
             "sky": np.full(1, 80.0), "snowlvl": np.full(1, 5000.0), "slr": np.full(1, 12.0)}
        if h <= 36:
            d.update(qpf1=np.full(1, 0.02), snow1=np.full(1, 0.2))
        if (1 + h) % 6 == 0 and h >= 11:
            d.update(qpf6=np.full(1, 0.1), snow6=np.full(1, 1.0), snow6_p10=np.full(1, 0.2), snow6_p90=np.full(1, 2.0))
        if h == 29:
            d.update(snow24_p10=np.full(1, 2.0), snow24_p90=np.full(1, 6.0))
        if h == 77:
            d.update(snow72_p10=np.full(1, 5.0), snow72_p90=np.full(1, 20.0))
        data[h] = d
    fc = point_forecast(data, hours, init, 0, elev_ft=9000, grid_ft=9000, tz=ZoneInfo("America/Denver"))
    t24, t72 = fc["totals"]["24h"], fc["totals"]["72h"]
    assert t24["from"] == "2026-11-08T06:00Z" and t24["snow_in"] == 4.0          # 4 x 6-h means
    assert (t24["snow_lo"], t24["snow_hi"]) == (2.0, 6.0) and t24["range"] == "NBM 10-90"   # real 24-h window
    assert (t72["snow_lo"], t72["snow_hi"]) == (5.0, 20.0) and t72["extended"] is False     # real 72-h window
    assert fc["periods"][0]["start"] == "2026-11-08T12:00Z" and not fc["periods"][0]["extended"]


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
    assert P.precip_type(0.3, 0.9) == "snow" and P.precip_type(0.3, 0.5) == "mixed"
    assert P.precip_type(0.3, 0.1) == "mostly rain" and P.precip_type(0.005, 0.9) is None


def test_slr_ranges_quality():
    assert P.clamp_slr(118.0) == 25.0 and P.clamp_slr(0.2) == 4.0 and P.clamp_slr(None) == 10.0
    assert P.rank_sum([(0.0, 2.0), (1.0, 3.0)]) == (1.0, 5.0) and P.rank_sum([(0, 1), None]) is None
    assert P.weighted_mean([1.0, 3.0], [0.0, 1.0]) == 3.0 and P.weighted_mean([2.0, 4.0], [0, 0]) == 3.0
    assert P.powder_quality(16, 20, 4) == "Blower"
    assert P.powder_quality(12, 35, 4) == "Medium, wind-affected"
    assert P.powder_quality(8, None, 4) == "Dense" and P.powder_quality(20, 10, 0.1) is None
    assert P.window_sum({6: 1.0, 12: 2.0}, 0, 12, 6) == 3.0
    assert P.window_sum({6: 1.0}, 0, 12, 6) is None
    base = {"10d": {"snow_in": 9.0, "snow_hi": 38.0}}
    assert len(P.plausibility(base, {"10d": {"snow_in": 3.0, "snow_hi": 23.0}})) == 2
    assert P.plausibility({"10d": {"snow_in": 3.5, "snow_hi": 24.0}}, {"10d": {"snow_in": 3.0, "snow_hi": 23.0}}) == []


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


def _fake_hour(h, n=2, snowlvl=6000.0):
    d = {"t2m": np.full(n, 30.0), "wind": np.full(n, 10.0), "gust": np.full(n, 20.0),
         "wdir": np.full(n, 270.0), "sky": np.full(n, 80.0), "snowlvl": np.full(n, snowlvl),
         "slr": np.full(n, 15.0)}
    if h <= 36:
        d.update(qpf1=np.full(n, 0.05), snow1=np.full(n, 0.5), pop1=np.full(n, 0.5))
    if h % 6 == 0:
        d.update(qpf6=np.full(n, 0.2), snow6=np.full(n, 3.0), pop6=np.full(n, 0.6))
        if h <= 48:
            d.update(snow6_p10=np.full(n, 1.0), snow6_p50=np.full(n, 3.0), snow6_p90=np.full(n, 5.0))
        if h % 12 == 0:
            d.update(qpf12_p10=np.full(n, 0.1), qpf12_p25=np.full(n, 0.2), qpf12_p50=np.full(n, 0.4),
                     qpf12_p75=np.full(n, 0.6), qpf12_p90=np.full(n, 0.8))
    if h == 24:
        d.update(qpf_0_1d_p10=np.full(n, 0.2), qpf_0_1d_p50=np.full(n, 0.8), qpf_0_1d_p90=np.full(n, 1.6))
    if h == 72:
        d.update(qpf_0_3d_p10=np.full(n, 0.5), qpf_0_3d_p25=np.full(n, 1.0), qpf_0_3d_p50=np.full(n, 2.0),
                 qpf_0_3d_p75=np.full(n, 3.0), qpf_0_3d_p90=np.full(n, 4.0),
                 qpf_2_3d_p10=np.full(n, 0.1), qpf_2_3d_p50=np.full(n, 0.6), qpf_2_3d_p90=np.full(n, 1.2))
    return d


def test_point_forecast_periods_and_totals():
    init = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    hours = list(range(1, 37)) + list(range(42, 73, 6))
    data = {h: _fake_hour(h) for h in hours}
    fc = point_forecast(data, hours, init, 0, elev_ft=9000, grid_ft=8000, tz=ZoneInfo("America/Denver"))
    # 1000 ft above the grid cell: 30 F - 3.57 F
    assert fc["series"]["t_f"][0] == pytest.approx(26.4, abs=0.05)
    assert fc["series"]["p_snow"][0] == 1.0                                  # snow level 6000 < 9000 ft
    per = fc["periods"][0]
    # bars = deterministic means: two 6-h windows x 3.0 in; range = NBM snow pct added rank by rank
    assert (per["snow_in"], per["snow_lo"], per["snow_hi"], per["extended"]) == (6.0, 2.0, 10.0, False)
    assert per["type"] == "snow" and per["local"] == "5 AM–5 PM MST" and per["powder"] == "Blower"
    # 0-48 h comparison (calibration report): likely range = QPF 25/75 (0.2/0.6) x SLR 15 x P 1
    assert (per["snow_ext_lo"], per["snow_ext_hi"]) == (3.0, 9.0) and per["range"] == "NBM 10-90"
    late = fc["periods"][4]                                                  # 60-72 h: extended outlook
    assert late["extended"] and late["snow_in"] == 6.0 and (late["snow_lo"], late["snow_hi"]) == (3.0, 9.0)
    assert late["range"] == "likely 25-75"
    tot = fc["totals"]
    assert tot["24h"]["snow_in"] == 12.0 and (tot["24h"]["snow_lo"], tot["24h"]["snow_hi"]) == (4.0, 20.0)
    # 72 h: likely range from the 0-3 day QPF block 25/75 (1.0/3.0) x 15; the mean (36 in)
    # is outside it and stays there: no clamping (owner decision S3)
    assert tot["72h"]["snow_in"] == 36.0 and (tot["72h"]["snow_lo"], tot["72h"]["snow_hi"]) == (15.0, 45.0)
    assert sum(p["snow_in"] for p in fc["periods"]) == tot["72h"]["snow_in"]   # bars add up to the total
    assert fc["precip"]["hours"][0] == 1 and fc["precip"]["snow_in"][0] == 0.5


def test_point_snow_scaled_by_snow_level_and_dry_rule():
    init = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    hours = list(range(1, 25))
    data = {h: _fake_hour(h, snowlvl=9000.0) for h in hours}               # snow level = point elevation
    fc = point_forecast(data, hours, init, 0, elev_ft=9000, grid_ft=9000, tz=ZoneInfo("America/Denver"))
    assert fc["periods"][0]["snow_in"] == 3.0 and fc["periods"][0]["type"] == "mixed"   # x P(snow) 0.5
    for h in hours:                                                          # QPF < 0.01 in: no snow
        if h % 6 == 0:
            data[h]["qpf6"] = np.full(2, 0.004)
    fc = point_forecast(data, hours, init, 0, elev_ft=9000, grid_ft=9000, tz=ZoneInfo("America/Denver"))
    assert fc["totals"]["24h"]["snow_in"] == 0.0 and fc["periods"][0]["type"] is None


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




def test_calibration_report_counts_means_outside_ranges():
    from pipeline.nbm.run import calibration_report
    def per(m, lo, hi, end, rng="NBM 10-90", elo=None, ehi=None):
        return {"snow_in": m, "snow_lo": lo, "snow_hi": hi, "end": end, "range": rng,
                "snow_ext_lo": elo, "snow_ext_hi": ehi}
    files = {"a": {"points": {"summit": {"periods": [
        per(2.0, 1.0, 4.0, "2026-11-08T12:00Z", elo=0.5, ehi=1.5),          # 0-48 h: in NBM, above likely
        per(5.0, 1.0, 4.0, "2026-11-09T00:00Z"),                            # 0-48 h: above NBM
        per(3.0, 1.0, 2.0, "2026-11-12T00:00Z", rng="likely 25-75"),        # beyond: above likely
        per(1.5, 1.0, 2.0, "2026-11-12T12:00Z"),                            # beyond: inside NBM
        per(0.0, 0.0, 0.1, "2026-11-13T00:00Z")]}}}}                        # dry: skipped
    r = calibration_report(files, "2026110800")
    assert r["first_48h"]["nbm_10_90"]["periods"] == 2 and r["first_48h"]["nbm_10_90"]["mean_inside"] == 0.5
    assert r["first_48h"]["likely_25_75"]["mean_above"] == 1.0
    assert r["beyond_48h"]["likely_25_75"]["mean_above"] == 1.0 and r["beyond_48h"]["nbm_10_90"]["mean_inside"] == 1.0
