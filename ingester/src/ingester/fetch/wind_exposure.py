"""Wind-exposure flag, Phase A (W7, docs/specs/wind-exposure.md §5.9). BUILT BEHIND A FLAG: config `wind_exposure.enabled` is false and is
not to be turned on before an avalanche-literate reviewer has signed the checklist in the spec.

An INFORMATIONAL flag only. It says that strong wind is forecast during or just after snowfall at the summit point, gives the wind direction
and the leeward side, and links to the avalanche centre. It is NOT an avalanche rating, produces no number that could be read as a slab or
avalanche risk, and never redistributes snowfall. Model winds do not resolve terrain: the text says so.

Pure functions (offline tests: tests/test_wind_exposure.py). Input is the summit point of the NBM point file: hourly `wind_mph`, `gust_mph`,
`wdir` (degrees the wind blows FROM) and the precipitation windows (`end`, `hours`, `snow_in`). Nothing here touches percentiles.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

DEFAULTS = {
    "enabled": False,
    "sustained_mph": 25,      # ridge-top wind at/above this ...
    "gust_mph": 35,           # ... or gusts at/above this count as "windy" [thresholds to tune; spec 5.9]
    "min_window_snow_in": 0.2,  # a precipitation window with at least this much snow counts as "snowing"
    "min_episode_snow_in": 0.5,  # an episode (consecutive snowy windows) needs at least this much in total
    "after_h": 12,            # wind in the hours after the snow ends still counts (snow is loose and transportable)
    "min_windy_hours": 2,     # at least this many windy hours inside the episode
    "horizon_h": 72,          # only the first 72 h (the part of the forecast people plan around)
}

TITLE = "Wind-affected snow likely"
DISCLAIMER = "Wind transport potential — not an avalanche rating."
CAVEAT = ("Model winds do not resolve terrain: local wind loading can differ a lot over short distances. "
          "Read the avalanche centre's forecast before you go.")
COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
# text the flag may use; tests/test_wind_exposure.py forbids anything that reads like a rating or a risk score
FORBIDDEN = ("danger", "slab", "risk", "unstable", "considerable", "high hazard", "safe", "avalanche rating:")


def configure(cfg: dict | None) -> dict:
    """The effective settings (defaults overridden by config `wind_exposure`)."""
    out = dict(DEFAULTS)
    out.update({k: v for k, v in ((cfg or {}).get("wind_exposure") or {}).items() if k in DEFAULTS})
    return out


def compass(deg: float) -> str:
    """16-point compass name for a direction in degrees."""
    return COMPASS[int(((deg % 360) + 11.25) // 22.5) % 16]


def mean_direction(degs: list[float]) -> float | None:
    """Vector mean of directions (degrees); None when empty or when the winds cancel out (no dominant direction)."""
    if not degs:
        return None
    x = sum(math.sin(math.radians(d)) for d in degs) / len(degs)
    y = sum(math.cos(math.radians(d)) for d in degs) / len(degs)
    if math.hypot(x, y) < 0.3:
        return None
    return math.degrees(math.atan2(x, y)) % 360


def _t(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%MZ")


def episodes(precip: dict, cfg: dict, t0: datetime) -> list[tuple[datetime, datetime, float]]:
    """Snow episodes [(start, end, snow_in)] from consecutive precipitation windows that each carry at least `min_window_snow_in`.
    A window ends at `end` and is `hours` long; windows are native NBM periods used as they are (nothing is summed across percentiles:
    these are the expected-amount series)."""
    out: list[list] = []
    for end, hours, snow in zip(precip.get("end") or [], precip.get("hours") or [], precip.get("snow_in") or []):
        if snow is None or snow < cfg["min_window_snow_in"]:
            continue
        e = _t(end)
        s = e - timedelta(hours=hours)
        if (s - t0).total_seconds() / 3600 >= cfg["horizon_h"]:
            break
        if out and s <= out[-1][1] + timedelta(hours=1):
            out[-1][1] = e
            out[-1][2] += snow
        else:
            out.append([s, e, snow])
    return [(s, e, round(x, 1)) for s, e, x in out if x >= cfg["min_episode_snow_in"]]


def assess(times: list[str], wind: list, gust: list, wdir: list, precip: dict, cfg: dict | None = None) -> dict | None:
    """The flag for one summit point, or None (no flag). The FIRST qualifying episode in the next 72 h is described.

    Qualifies: an episode of snowfall with at least `min_windy_hours` hours, from its start until `after_h` hours after its end, where the
    sustained wind is >= `sustained_mph` or the gust is >= `gust_mph`. Missing wind values count as not windy; with no wind data at all there
    is no flag (and no crash). A missing direction keeps the flag but drops the direction sentence."""
    c = {**DEFAULTS, **(cfg or {})}
    if not times or not precip:
        return None
    tt = [_t(x) for x in times]
    for s, e, snow in episodes(precip, c, tt[0]):
        stop = e + timedelta(hours=c["after_h"])
        idx = [i for i, t in enumerate(tt) if s <= t <= stop]
        windy = [i for i in idx if ((wind[i] if i < len(wind) else None) or 0) >= c["sustained_mph"] or ((gust[i] if i < len(gust) else None) or 0) >= c["gust_mph"]]
        if len(windy) < c["min_windy_hours"]:
            continue
        pw = max((wind[i] for i in windy if i < len(wind) and wind[i] is not None), default=None)
        pg = max((gust[i] for i in windy if i < len(gust) and gust[i] is not None), default=None)
        d = mean_direction([wdir[i] for i in windy if i < len(wdir) and wdir[i] is not None])
        out = {"flag": True, "title": TITLE, "disclaimer": DISCLAIMER, "caveat": CAVEAT,
               "start": tt[windy[0]].strftime("%Y-%m-%dT%H:%MZ"), "end": tt[windy[-1]].strftime("%Y-%m-%dT%H:%MZ"),
               "snow_in": snow, "peak_wind_mph": None if pw is None else round(pw), "peak_gust_mph": None if pg is None else round(pg),
               "wind_from": None if d is None else compass(d), "leeward": None if d is None else compass((d + 180) % 360)}
        out["text"] = text(out)
        return out
    return None


def text(f: dict) -> str:
    """One plain sentence pair (no numbers beyond the forecast wind itself; no rating language)."""
    peak = f.get("peak_gust_mph") or f.get("peak_wind_mph")
    wind = f"Strong wind is forecast during or just after snowfall (peak around {peak} mph)." if peak else "Strong wind is forecast during or just after snowfall."
    if f.get("wind_from"):
        return (f"{wind} Wind from the {f['wind_from']}: wind-loading is possible on leeward ({f['leeward']}-facing) slopes, "
                "and the snow may be scoured on windward ridges.")
    return f"{wind} Wind-loading is possible on leeward slopes and the snow may be scoured on windward ridges (wind direction not available)."


def for_point_doc(doc: dict, cfg: dict) -> dict | None:
    """Wrapper used by the points run: None when disabled (the default), else assess() on the summit point of a point document."""
    c = configure(cfg)
    if not c["enabled"]:
        return None
    p = (doc.get("points") or {}).get("summit") or (doc.get("points") or {}).get("point")
    if not p:
        return None
    s = p.get("series") or {}
    res = assess(doc.get("times") or [], s.get("wind_mph") or [], s.get("gust_mph") or [], s.get("wdir") or [], p.get("precip") or {}, c)
    if res is not None:
        av = (doc.get("area") or {}).get("avalanche") or {}
        res["avalanche_center_id"] = av.get("center_id")           # the page links to the centre's own forecast
    return res
