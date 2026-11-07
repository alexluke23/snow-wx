"""Point-forecast processing shared by NBM (and later NDFD / models): pure functions.

Methods (documented for about.html):
- Temperature: NBM value at the 2.5-km cell, moved from the cell's mean terrain
  height to the point with a fixed lapse rate (6.5 °C/km), height change capped.
- P(snow at a point) = P(snow level below the point). Within ~48 h NBM gives
  snow-level percentiles (10/50/90); the CDF is interpolated between them with
  linear tails. Later, only the deterministic snow level exists, so a ±800 ft ramp
  stands in for its uncertainty.
- Periods are 12 h, 00Z–12Z ("night") and 12Z–00Z ("day"), because NBM beyond
  48 h is 6-hourly and its QPF percentiles come in windows ending at 00/06/12/18Z.
  In the West that is about 5 AM–5 PM local (MST) / 4 AM–4 PM (PST).
- Snowfall range = QPF percentiles × the period's snow-to-liquid factor
  (NBM deterministic snow ÷ deterministic QPF), because NBM has no snowfall
  percentiles past ~48 h. One method for the whole 11 days.
- 7- and 10-day ranges add NBM's 3/2/2/3-day block percentiles rank by rank
  (slightly wider than the true range); 24 h and 72 h use NBM's own windows.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

LAPSE_C_PER_KM = 6.5
MAX_ADJUST_FT = 4000.0
DET_SNOWLVL_HALF_RAMP_FT = 800.0


def lapse_adjust_f(t_f, grid_ft, point_ft, lapse_c_per_km=LAPSE_C_PER_KM, max_dz_ft=MAX_ADJUST_FT):
    """Temperature (°F) moved from grid elevation to point elevation."""
    if t_f is None or grid_ft is None or point_ft is None:
        return t_f
    dz_ft = max(-max_dz_ft, min(max_dz_ft, grid_ft - point_ft))
    return t_f + lapse_c_per_km * 1.8 * dz_ft * 0.3048 / 1000.0


def p_snow_level_below(elev_ft, p10=None, p50=None, p90=None):
    """P(snow level < elev) in [0, 1] from 10/50/90 percentiles, or from p50 alone
    (deterministic) with a symmetric ±DET_SNOWLVL_HALF_RAMP_FT ramp."""
    if elev_ft is None or p50 is None or any(isinstance(v, float) and math.isnan(v) for v in (p50,)):
        return None
    if p10 is None or p90 is None or math.isnan(p10) or math.isnan(p90):
        lo, hi = p50 - DET_SNOWLVL_HALF_RAMP_FT, p50 + DET_SNOWLVL_HALF_RAMP_FT
        knots = [(lo, 0.0), (p50, 0.5), (hi, 1.0)]
    else:
        p10, p90 = min(p10, p50), max(p90, p50)
        knots = [(p10 - max(p50 - p10, 1.0), 0.0), (p10, 0.1), (p50, 0.5), (p90, 0.9),
                 (p90 + max(p90 - p50, 1.0), 1.0)]
    if elev_ft <= knots[0][0]:
        return 0.0
    if elev_ft >= knots[-1][0]:
        return 1.0
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if x0 <= elev_ft <= x1:
            return y0 if x1 == x0 else y0 + (y1 - y0) * (elev_ft - x0) / (x1 - x0)
    return None


def precip_type(qpf_in, p_snow, wet=0.01):
    """Label for a period/step: None (dry), snow, mix or rain."""
    if qpf_in is None or p_snow is None or qpf_in < wet:
        return None
    return "snow" if p_snow >= 0.7 else "mix" if p_snow >= 0.3 else "rain"


def powder_quality(slr, gust_mph_during_snow=None, snow_in=None):
    """Simple documented heuristic (PLAN.md §5.2). None when there is no snow."""
    if not snow_in or snow_in < 0.5 or slr is None:
        return None
    q = "Blower" if slr >= 15 else "Medium" if slr >= 10 else "Dense"
    if gust_mph_during_snow is not None and gust_mph_during_snow > 30:
        q += ", wind-affected"
    return q


def snow_ratio(snow_det_in, qpf_det_in, slr_mean=None, p_snow=None, min_qpf=0.01, default_slr=10.0):
    """Snow per inch of liquid for a window: NBM det snow ÷ det QPF. When the
    deterministic QPF is ~0 (only the wet percentiles have precip), use the mean
    SLR of snowy steps (else 10:1) × P(snow at the point)."""
    if qpf_det_in is not None and qpf_det_in >= min_qpf and snow_det_in is not None:
        return max(0.0, snow_det_in / qpf_det_in)
    if p_snow is not None:
        return max(0.0, (slr_mean if slr_mean and slr_mean >= 5 else default_slr) * p_snow)
    return 0.0


def comonotonic_sum(blocks: list[dict]) -> dict:
    """Add percentile dicts rank by rank ({10: a, 50: b, 90: c} + ...)."""
    out = {}
    for b in blocks:
        for k, v in b.items():
            if v is None:
                return {k: None for k in b}
            out[k] = out.get(k, 0.0) + v
    return out


def periods(init: datetime, hours: list[int], length_h: int = 12) -> list[tuple[int, int]]:
    """(start_h, end_h) forecast-hour windows aligned to 00Z/12Z covering the run;
    the first may be shorter (6 h) when the cycle is 06Z or 18Z."""
    if not hours:
        return []
    last = max(hours)
    first_end = length_h - (init.hour % length_h) if init.hour % length_h else length_h
    out, s, e = [], 0, first_end
    while e <= last:
        out.append((s, e))
        s, e = e, e + length_h
    return out


def period_label(init: datetime, start_h: int, end_h: int, tz) -> dict:
    t0, t1 = init + timedelta(hours=start_h), init + timedelta(hours=end_h)
    l0 = t0.astimezone(tz)
    day = t0.hour == 12 or (t0.hour == 18 and end_h - start_h == 6)
    return {"start": t0.strftime("%Y-%m-%dT%H:%MZ"), "end": t1.strftime("%Y-%m-%dT%H:%MZ"),
            "label": f"{l0:%a} {'day' if day else 'night'}", "is_day": day}


def window_sum(series: dict[int, float | None], start_h: int, end_h: int, step: int) -> float | None:
    """Sum of step-length accumulations ending in (start_h, end_h]."""
    total, n = 0.0, 0
    for h in range(start_h + step, end_h + 1, step):
        v = series.get(h)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        total, n = total + v, n + 1
    return total if n else None


def monotone_totals(totals: dict, order=("24h", "72h", "7d", "10d"), fields=("qpf_in", "snow_in")) -> dict:
    """Longer windows can't hold less than shorter ones: each window's percentile is
    raised to at least the previous window's (separate NBM blocks and snow ratios
    can otherwise disagree slightly)."""
    prev = None
    for name in order:
        cur = totals.get(name)
        if cur is None:
            continue
        if prev is not None:
            for f in fields:
                for k, v in cur[f].items():
                    pv = prev[f].get(k)
                    if v is not None and pv is not None and v < pv:
                        cur[f][k] = pv
        prev = cur
    return totals
