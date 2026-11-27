"""Point-forecast processing shared by NBM (and later NDFD / models): pure functions.

Methods (owner decisions, PLAN.md §3, session 2; documented for about.html):
- Amounts (bars, "Expected", totals) are NBM deterministic (mean) values, summed
  over 6-h windows, so day/night bars add up to the totals. Snow is zeroed when the
  window's expected QPF is < 0.01".
- Point snow = NBM snowfall × P(snow level below the point), the probability taken
  from NBM's snow-level percentiles (10/50/90, linear tails) to 48 h and from a
  ±800 ft ramp on the deterministic snow level after that.
- Ranges (what each product uses TODAY; the site's default wording is the 25–75 "likely" band, owner Nov 17):
  * Snowfall-by-day bars (12Z–12Z) and the 24/48/72 h totals: ONE native NBM window's percentiles (24/48/72 h, or 6 h for a short
    first day), scaled by P(snow at the point): `snow_p25/p50/p75` per day; `snow_q1/q3` (25–75, the "likely" range shown) and
    `snow_lo/hi` (10–90, kept for the archive, Finder fields and W3) per total, with `native` true only for a single window.
  * 12-h day/night periods (stored in the points file, used by the calibration report, not drawn): 6-h native windows added RANK BY RANK
    — `snow_lo/hi` = 10–90 and `snow_q1/q3` = 25–75 to ~48 h. This is a documented, conservative approximation (slightly wide);
    M9 should check it against observed SNOTEL snowfall. Beyond that ("extended outlook", `range` "derived 25-75"): NBM QPF
    25–75 × SNOWLR (clamped 4–25) × P(snow).
  * 7/10-day totals: only the expected amount is shown; any range fields stored for them are composites and never displayed.
  * Percentiles are never summed across days or into 7/10-day totals. Ranges are not forced to contain the deterministic mean:
    NBM calibrates the two separately.
- Temperature: NBM value at the 2.5-km cell moved to the point with 6.5 °C/km
  (height change capped at 4000 ft).
- Periods: 12 h, 00Z–12Z (night) and 12Z–00Z (day), labelled in local time.
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
    """Label for a period/step: None (dry), "snow", "mixed" or "mostly rain"."""
    if qpf_in is None or p_snow is None or qpf_in < wet:
        return None
    return "snow" if p_snow >= 0.7 else "mixed" if p_snow >= 0.3 else "mostly rain"


SLR_MIN, SLR_MAX, SLR_DEFAULT = 4.0, 25.0, 10.0
WET_IN = 0.01


def clamp_slr(slr):
    """NBM SNOWLR (or a fallback) limited to a physically plausible 4–25:1."""
    if slr is None or (isinstance(slr, float) and math.isnan(slr)) or slr <= 0:
        return SLR_DEFAULT
    return min(SLR_MAX, max(SLR_MIN, slr))


def rank_sum(ranges):
    """Add (lo, hi) ranges rank by rank; None if any part is missing."""
    lo = hi = 0.0
    for r in ranges:
        if r is None or r[0] is None or r[1] is None:
            return None
        lo, hi = lo + r[0], hi + r[1]
    return lo, hi


def weighted_mean(values, weights):
    pairs = [(v, w) for v, w in zip(values, weights) if v is not None]
    if not pairs:
        return None
    tw = sum(max(w or 0.0, 0.0) for _, w in pairs)
    if tw <= 0:
        return sum(v for v, _ in pairs) / len(pairs)
    return sum(v * max(w or 0.0, 0.0) for v, w in pairs) / tw


def plausibility(base_totals: dict, summit_totals: dict, key="10d", ratio=1.25, slack_in=1.0) -> list[str]:
    """Flags for review: base snow above summit snow (mean or 90th pct) by more than
    `ratio` x summit + slack. Different 2.5-km cells can legitimately differ a little."""
    out = []
    b, s = base_totals.get(key), summit_totals.get(key)
    if not b or not s:
        return out
    for f in ("snow_in", "snow_hi"):
        if b.get(f) is not None and s.get(f) is not None and b[f] > s[f] * ratio + slack_in:
            out.append(f"base {f} {b[f]:.1f} > summit {s[f]:.1f} ({key})")
    return out


# ONE powder-quality definition (owner Nov 17): config/settings.yml `powder_quality`; web/js/colors.js POWDER_Q mirrors it
# (a test keeps them equal). Dense < dense_below, Medium dense_below..blower_at, Blower >= blower_at (snow-to-liquid ratio).
POWDER_Q = {"dense_below": 10.0, "blower_at": 15.0, "wind_gust_mph": 30.0, "min_snow_in": 0.5}
POWDER_LABEL = {"dense": "Dense", "medium": "Medium", "blower": "Blower"}


def configure_powder_quality(cfg: dict | None) -> None:
    """Thresholds from config/settings.yml `powder_quality`."""
    POWDER_Q.update({k: float(v) for k, v in ((cfg or {}).get("powder_quality") or {}).items()})


def powder_class(slr) -> str | None:
    """'dense' | 'medium' | 'blower' from the snow ratio, by the shared thresholds."""
    if slr is None:
        return None
    return "dense" if slr < POWDER_Q["dense_below"] else "medium" if slr < POWDER_Q["blower_at"] else "blower"


def snow_type(slr, gust_mph_during_snow=None, snow_in=None) -> dict | None:
    """Powder quality of a period (documented heuristic, never an accuracy claim): {type, label, wind}, with
    "wind-affected" when summit gusts during snowfall reach the threshold. None when little snow falls."""
    if slr is None or not snow_in or snow_in < POWDER_Q["min_snow_in"]:
        return None
    k = powder_class(slr)
    return {"type": k, "label": POWDER_LABEL[k],
            "wind": bool(gust_mph_during_snow is not None and gust_mph_during_snow >= POWDER_Q["wind_gust_mph"])}


def powder_quality(slr, gust_mph_during_snow=None, snow_in=None):
    """Powder quality as text ("Blower", "Medium, wind-affected"); None when there is no snow."""
    t = snow_type(slr, gust_mph_during_snow, snow_in)
    return None if t is None else t["label"] + (", wind-affected" if t["wind"] else "")


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


def day_spans(init: datetime, hours: list[int]) -> list[tuple[int, int]]:
    """(start_h, end_h) days ending at 12Z (~4-5 AM in the West), the unit of the "Snowfall by day"
    chart (owner S11). The first day runs from the run start to the first 12Z and may be partial."""
    if not hours:
        return []
    last = max(hours)
    first_end = (12 - init.hour) % 24 or 24
    out, s, e = [], 0, first_end
    while e <= last:
        out.append((s, e))
        s, e = e, e + 24
    return out


def native_window(start_h: int, end_h: int, have) -> str | None:
    """Which NBM snowfall-percentile window exactly covers (start_h, end_h]: "snow24" or "snow6",
    or None. `have(key, end_h)` says whether that window's percentiles exist. NBM percentiles are
    never added together (owner S11), so a span with no single native window has no range."""
    L = end_h - start_h
    key = {24: "snow24", 6: "snow6"}.get(L)
    return key if key and have(key, end_h) else None


def day_label(init: datetime, start_h: int, end_h: int, tz) -> dict:
    t0, t1 = init + timedelta(hours=start_h), init + timedelta(hours=end_h)
    l0, l1 = t0.astimezone(tz), t1.astimezone(tz)
    return {"start": t0.strftime("%Y-%m-%dT%H:%MZ"), "end": t1.strftime("%Y-%m-%dT%H:%MZ"),
            "label": f"{l0:%a} {l0.day}", "local": f"{l0:%a} {_hour(l0)} – {l1:%a} {_hour(l1)} {l1:%Z}"}


def _hour(t: datetime) -> str:
    return t.strftime("%I %p").lstrip("0")


def period_label(init: datetime, start_h: int, end_h: int, tz) -> dict:
    t0, t1 = init + timedelta(hours=start_h), init + timedelta(hours=end_h)
    l0, l1 = t0.astimezone(tz), t1.astimezone(tz)
    day = t0.hour == 12 or (t0.hour == 18 and end_h - start_h == 6)
    return {"start": t0.strftime("%Y-%m-%dT%H:%MZ"), "end": t1.strftime("%Y-%m-%dT%H:%MZ"),
            "label": f"{l0:%a} {'day' if day else 'night'}", "is_day": day,
            "local": f"{_hour(l0)}–{_hour(l1)} {l1:%Z}"}


def window_sum(series: dict[int, float | None], start_h: int, end_h: int, step: int) -> float | None:
    """Sum of step-length accumulations ending in (start_h, end_h]."""
    total, n = 0.0, 0
    for h in range(start_h + step, end_h + 1, step):
        v = series.get(h)
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return None
        total, n = total + v, n + 1
    return total if n else None


WET_POP = 0.2          # "precipitation likely" = chance of precip >= 20 % (area page + Powder Finder)


def window_wet(periods: list[dict], start: str, end: str, pop_min: float = WET_POP) -> tuple[int | None, float | None]:
    """(highest chance of precip in %, lowest snow level while precip is likely, ft) over the
    12-h periods overlapping [start, end] (ISO strings). The snow level only counts periods
    whose chance of precip is >= pop_min, so a dry window gives None (Powder Finder "–")."""
    inside = [p for p in periods if p.get("end", "") > start and p.get("start", "") < end]
    pops = [p["pop"] for p in inside if p.get("pop") is not None]
    wet = [p["snowlvl_min_ft"] for p in inside
           if p.get("snowlvl_min_ft") is not None and p.get("pop") is not None and p["pop"] >= pop_min]
    return (round(100 * max(pops)) if pops else None), (min(wet) if wet else None)


def window_snow_type(periods: list[dict], start: str, end: str) -> str | None:
    """Main snow type over a window: the type of the periods with the most snow (owner S10)."""
    acc: dict[str, float] = {}
    for p in periods:
        t = p.get("snow_type")
        if t and p.get("end", "") > start and p.get("start", "") < end:
            acc[t["type"]] = acc.get(t["type"], 0.0) + (p.get("snow_in") or 0.0)
    return max(acc, key=acc.get) if acc else None
