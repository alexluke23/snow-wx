"""NBM point pipeline: newest synoptic cycle -> data/points/<area>.json + summary.json.

Fetch once, sample all: for each forecast hour the needed GRIB messages are
byte-range downloaded from the NODD bucket (merged into few requests), decoded
in memory with ecCodes, and sampled at every ski-area base/summit grid cell.
Per-hour samples are cached (data_cache/nbm/<cycle>/fNNN.npz) so reruns are fast.
"""

from __future__ import annotations

import json
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from .. import points as P
from ..common import REPO_ROOT, utcnow, write_json
from .inventory import FULL_SUITE_CYCLES, parse_idx, required_keys, sample_hours, select

log = logging.getLogger("snow-wx.nbm")

BUCKET = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"
CACHE = REPO_ROOT / "data_cache" / "nbm"
CATALOG = REPO_ROOT / "data" / "ski_areas.json"
SOURCE = "NOAA/NWS National Blend of Models (NBM) via NOAA Open Data Dissemination (AWS)"
SELECTION_VERSION = 5          # bump when inventory.selections changes (invalidates the sample cache)

K_TO_F = lambda k: (k - 273.15) * 1.8 + 32.0  # noqa: E731
MS_TO_MPH = 2.236936
MM_TO_IN = 1 / 25.4
M_TO_IN = 39.37008
M_TO_FT = 3.28084


def url(cycle: datetime, product: str, fhour: int) -> str:
    return (f"{BUCKET}/blend.{cycle:%Y%m%d}/{cycle:%H}/{product}/"
            f"blend.t{cycle:%H}z.{product}.f{fhour:03d}.co.grib2")


def convert(key: str, v: np.ndarray) -> np.ndarray:
    if "_gt" in key:                    # exceedance probabilities: percent, keep as is
        return v
    if key in ("t2m", "tmax12", "tmin12"):
        return K_TO_F(v)
    if key in ("wind", "gust"):
        return v * MS_TO_MPH
    if key.startswith("snowlvl"):
        return v * M_TO_FT
    if key.startswith("qpf"):
        return v * MM_TO_IN
    if key.startswith("snow"):
        return v * M_TO_IN
    if key.startswith(("p_", "pop")):
        return v / 100.0
    return v


# ---------------------------------------------------------------- fetch

def _get(session, u, headers=None, attempts=4):
    for i in range(attempts):
        try:
            r = session.get(u, headers=headers or {}, timeout=120)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r
        except Exception as e:  # noqa: BLE001
            if i == attempts - 1:
                raise
            log.debug("retry %s: %s", u[-40:], e)
            time.sleep(3 * (i + 1))


MAX_MISSING_SHARE = 0.20     # fail the run when more required messages than this are missing


def cycle_complete(session, t: datetime, max_hour: int) -> bool:
    """A cycle is usable once its last core file (f<max_hour>) is published."""
    try:
        return session.head(url(t, "core", max_hour) + ".idx", timeout=30).status_code == 200
    except Exception:  # noqa: BLE001
        return False


def latest_cycle(session, now: datetime, max_hour: int, lookback_h: int = 36,
                 complete=cycle_complete, full_suite_max_age_h: int = 12) -> datetime | None:
    """Owner fallback order (S4): newest complete full-suite cycle (01/07/13/19Z: NBM
    snowfall percentiles and exceedances to ~day 11, docs/nbm_inventory.md) -> the
    previous full-suite cycle if it is at most 12 h old -> only then the newest complete
    00/06/12/18Z cycle within the lookback."""
    t = now.replace(minute=0, second=0, microsecond=0)
    for k in range(full_suite_max_age_h + 1):
        c = t - timedelta(hours=k)
        if c.hour in FULL_SUITE_CYCLES and complete(session, c, max_hour):
            return c
    for k in range(lookback_h + 1):
        c = t - timedelta(hours=k)
        if c.hour % 6 == 0 and complete(session, c, max_hour):
            return c
    return None


def companion_cycle(cycle: datetime) -> datetime | None:
    """The 00/06/12/18Z cycle an hour before a full-suite cycle (preferred QPF source)."""
    return cycle - timedelta(hours=1) if cycle.hour in FULL_SUITE_CYCLES else None


def liquid_source(session, cycle: datetime, max_back_h: int = 13) -> datetime | None:
    """QPF percentiles (qmd) for a full-suite cycle. qmd is published ~7.5 h after its
    cycle (measured 6-7 Nov 2026), so the companion an hour before the full-suite cycle is
    usually not out yet when the full suite completes (~1.7 h): use the newest
    00/06/12/18Z cycle at most 13 h older whose qmd is complete (f276)."""
    if cycle.hour not in FULL_SUITE_CYCLES:
        return None
    for k in range(1, max_back_h + 1):
        c = cycle - timedelta(hours=k)
        if c.hour % 6 == 0:
            try:
                if session.head(url(c, "qmd", 276) + ".idx", timeout=30).status_code == 200:
                    return c
            except Exception:  # noqa: BLE001
                pass
    return None


def list_hours(session, cycle: datetime) -> list[int]:
    """Forecast hours published for the cycle's core product (S3 listing)."""
    import re
    hours, token = set(), None
    while True:
        params = {"list-type": 2, "prefix": f"blend.{cycle:%Y%m%d}/{cycle:%H}/core/"}
        if token:
            params["continuation-token"] = token
        t = session.get(f"{BUCKET}/", params=params, timeout=60).text
        hours |= {int(x) for x in re.findall(r"core\.f(\d{3})\.co\.grib2\.idx</Key>", t)}
        m = re.search(r"<NextContinuationToken>([^<]+)", t)
        if not m:
            return sorted(hours)
        token = m.group(1)


def merge_ranges(msgs, gap: int = 0):
    """[(offset, length)] sorted -> merged (start, end_inclusive, [members])."""
    out = []
    for m in sorted(msgs, key=lambda m: m.offset):
        end = m.offset + m.length - 1
        if out and m.offset <= out[-1][1] + 1 + gap:
            out[-1][1] = max(out[-1][1], end)
            out[-1][2].append(m)
        else:
            out.append([m.offset, end, [m]])
    return out


def flat_index(ii: np.ndarray, jj: np.ndarray, nx: int, alternate_rows: bool) -> np.ndarray:
    """Position of grid point (i, j) in the decoded value array. With
    alternativeRowScanning (NBM core files) every odd row is stored east-to-west,
    and ecCodes returns values in storage order."""
    ii = np.where(alternate_rows & (jj % 2 == 1), nx - 1 - ii, ii)
    return jj * nx + ii


# ecCodes is not thread-safe while it loads key definitions ("fatal flex scanner
# internal error"); downloads run in threads, decoding is serialized.
_ECCODES_LOCK = threading.Lock()


def decode_at(blob: bytes, ij: tuple[np.ndarray, np.ndarray], grid: dict) -> np.ndarray:
    with _ECCODES_LOCK:
        return _decode_at(blob, ij, grid)


def _decode_at(blob: bytes, ij: tuple[np.ndarray, np.ndarray], grid: dict) -> np.ndarray:
    import eccodes
    h = eccodes.codes_new_from_message(blob)
    try:
        nx, ny = eccodes.codes_get(h, "Nx"), eccodes.codes_get(h, "Ny")
        if (nx, ny) != (grid["nx"], grid["ny"]):
            raise ValueError(f"grid {nx}x{ny} != catalog grid {grid['nx']}x{grid['ny']}")
        if eccodes.codes_get(h, "iScansNegatively") or not eccodes.codes_get(h, "jScansPositively"):
            raise ValueError("unexpected scanning mode")
        alt = bool(eccodes.codes_get(h, "alternativeRowScanning"))
        eccodes.codes_set(h, "missingValue", 9.999e20)
        vals = eccodes.codes_get_values(h)
    finally:
        eccodes.codes_release(h)
    out = vals[flat_index(ij[0], ij[1], nx, alt)].astype("float64")
    out[out > 9e20] = np.nan
    return out


def fetch_hour(session, cycle: datetime, fhour: int, ij: tuple, grid: dict,
               cache_dir: Path, comp: datetime | None = None) -> tuple[dict[str, np.ndarray], list[str]]:
    """({key: values at the cells}, [missing required keys]) for one forecast hour.

    Fail-soft: a missing idx/product or message is missing data for this hour, never
    an exception; the caller counts and judges the share."""
    path = cache_dir / f"f{fhour:03d}.npz"
    if path.exists():
        with np.load(path) as z:
            out = {k: z[k] for k in z.files if k != "__missing__"}
            return out, [str(x) for x in z["__missing__"]] if "__missing__" in z.files else []
    out: dict[str, np.ndarray] = {}
    sources = [(cycle, "core", fhour), (cycle, "qmd", fhour)]
    if comp is not None and (cycle.hour + fhour) % 12 == 0:
        # liquid ranges: a 00/06/12/18Z cycle's qmd 12-h QPF percentiles at the same
        # valid time (its forecast hour is larger by the cycle difference)
        sources.append((comp, "qmd", fhour + int((cycle - comp).total_seconds() // 3600)))
    for src, product, fh in sources:
        if product == "qmd" and src.hour % 6:
            continue                                  # qmd exists only for 00/06/12/18Z
        r = _get(session, url(src, product, fh) + ".idx")
        if r is None:
            log.debug("%s %s f%03d: no idx", src, product, fh)
            continue
        chosen = {m: k for m, k in select(parse_idx(r.text), fh, src.hour, product).items() if m.length}
        if src is not cycle:
            chosen = {m: k for m, k in chosen.items() if k.startswith("qpf12_")}
        for start, end, members in merge_ranges(list(chosen)):
            try:
                blob = _get(session, url(src, product, fh), {"Range": f"bytes={start}-{end}"}).content
            except Exception as e:  # noqa: BLE001
                log.warning("%s f%03d: byte range failed (%s)", product, fhour, e)
                continue
            for m in members:
                part = blob[m.offset - start: m.offset - start + m.length]
                try:
                    out[chosen[m]] = convert(chosen[m], decode_at(part, ij, grid))
                except Exception as e:  # noqa: BLE001
                    log.warning("f%03d %s: decode failed (%s)", fhour, chosen[m], e)
    missing = sorted(required_keys(fhour, cycle.hour) - set(out))
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, __missing__=np.array(missing, dtype="U16"), **out)
    return out, missing


# ---------------------------------------------------------------- assemble

def _r(v, nd=1):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(float(v), nd)


def _val(data, h, key, i):
    arr = data.get(h, {}).get(key)
    if arr is None:
        return None
    v = float(arr[i])
    return None if math.isnan(v) else v


def exceedance(data: dict, hours: list[int], init: datetime, i: int) -> dict:
    """NBM's own snowfall exceedance probabilities (%) for 24/48/72-h windows ending at
    valid 12Z (about 4-5 AM local in the West), at every threshold NBM provides."""
    out = {}
    for L in (24, 48, 72):
        ends = [h for h in hours if (init.hour + h) % 24 == 12 and any(k.startswith(f"snow{L}_gt") for k in data.get(h, {}))]
        if not ends:
            continue
        thr = sorted({k[len(f"snow{L}_gt"):] for h in ends for k in data[h] if k.startswith(f"snow{L}_gt")}, key=float)
        rows = []
        for h in ends:
            row = []
            for t in thr:
                a = data[h].get(f"snow{L}_gt{t}")
                x = None if a is None else float(a[i])
                row.append(None if x is None or math.isnan(x) else int(round(x)))
            rows.append(row)
        out[f"{L}h"] = {"start": [(init + timedelta(hours=h - L)).strftime("%Y-%m-%dT%H:%MZ") for h in ends],
                        "end": [(init + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%MZ") for h in ends],
                        "thr": [float(t) for t in thr], "p": rows}
    return out


def point_forecast(data: dict[int, dict], hours: list[int], init: datetime, i: int,
                   elev_ft: float, grid_ft: float | None, tz) -> dict:
    """Series, 6-h windows, 12-h periods and totals for one point (column i).

    Amounts are NBM deterministic means scaled by P(snow at the point); 10-90 %
    ranges use NBM snowfall percentiles to 48 h and QPF percentiles x SLR x P(snow)
    after that ("extended"). See pipeline/points.py for the method notes.
    """
    def v(h, k):
        return _val(data, h, k, i)

    hset = set(hours)
    series = {k: [] for k in ("t_f", "wind_mph", "gust_mph", "wdir", "sky", "snowlvl_ft",
                              "snowlvl_p10", "snowlvl_p90", "p_snow", "slr", "pop")}
    ps: dict[int, float | None] = {}
    for h in hours:
        series["t_f"].append(_r(P.lapse_adjust_f(v(h, "t2m"), grid_ft, elev_ft)))
        series["wind_mph"].append(_r(v(h, "wind"), 0))
        series["gust_mph"].append(_r(v(h, "gust"), 0))
        series["wdir"].append(_r(v(h, "wdir"), 0))
        series["sky"].append(_r(v(h, "sky"), 0))
        sl50, det = v(h, "snowlvl_p50"), v(h, "snowlvl")
        p10, p90 = v(h, "snowlvl_p10"), v(h, "snowlvl_p90")
        mid = sl50 if sl50 is not None else det
        series["snowlvl_ft"].append(_r(mid, -2))
        series["snowlvl_p10"].append(_r(p10, -2))
        series["snowlvl_p90"].append(_r(p90, -2))
        ps[h] = P.p_snow_level_below(elev_ft, p10, mid, p90)
        series["p_snow"].append(_r(ps[h], 2))
        series["slr"].append(_r(v(h, "slr"), 1))
        series["pop"].append(_r(v(h + (-h % 6), "pop6"), 2))

    def steps_in(s, e):
        return [h for h in hours if s < h <= e]

    def raw_snow_at(h):
        """Deterministic snow falling at step h (1-h amount to f036, else its 6-h window)."""
        x = v(h, "snow1") if h <= 36 else v(h + (-h % 6), "snow6")
        return x or 0.0

    def slr_in(s, e):
        """Mean NBM SNOWLR over snowy steps. NBM SNOWLR shrinks toward 0 where snow is
        unlikely (it is not conditional on snow), so without deterministic snow use the
        window's highest SNOWLR; clamp_slr later bounds it to 4-25. A fixed default
        here made a dry cell (10:1) outrank a marginal one (Ski Apache base vs summit)."""
        steps = steps_in(s, e)
        vals = [v(h, "slr") for h in steps if raw_snow_at(h) > 0]
        vals = [x for x in vals if x is not None and x > 0]
        if vals:
            return sum(vals) / len(vals)
        anyv = [x for x in (v(h, "slr") for h in steps) if x is not None and x > 0]
        return max(anyv) if anyv else None

    # 6-h windows (ending at valid 00/06/12/18Z, whatever the cycle hour): the unit that
    # periods and totals are summed from
    W: dict[int, dict | None] = {}
    for e in [h for h in hours if v(h, "qpf6") is not None or v(h, "snow6") is not None]:
        q, raw = v(e, "qpf6"), v(e, "snow6")
        if q is None or raw is None:
            W[e] = None
            continue
        pw = [ps[h] for h in steps_in(e - 6, e) if ps.get(h) is not None]
        pw = sum(pw) / len(pw) if pw else 1.0
        lo, hi = v(e, "snow6_p10"), v(e, "snow6_p90")
        W[e] = {"qpf": q, "raw": raw, "ps": pw, "snow": 0.0 if q < P.WET_IN else raw * pw,
                "rng": None if lo is None or hi is None else (lo * pw, hi * pw),
                "slr": slr_in(e - 6, e)}

    def windows(s, e):
        ws = [W.get(h) for h in range(e, s, -6)][::-1]
        return None if not ws or any(w is None for w in ws) else ws

    def qpct(key, e, lo_p=10, hi_p=90):
        lo, hi = v(e, f"{key}_p{lo_p}"), v(e, f"{key}_p{hi_p}")
        return None if lo is None or hi is None else (lo, hi)

    def extended_range(qp, ws):
        """QPF percentiles x SLR x P(snow) for the windows ws."""
        if not ws:
            return None, None
        slr = P.clamp_slr(P.weighted_mean([w["slr"] for w in ws], [w["raw"] for w in ws]))
        p = P.weighted_mean([w["ps"] for w in ws], [w["qpf"] for w in ws])
        if qp is None or p is None:
            return None, slr
        return (qp[0] * slr * p, qp[1] * slr * p), slr

    # hourly chart: 1-h windows to f036, then 6-h windows
    precip = {"end": [], "hours": [], "qpf_in": [], "snow_in": [], "pop": []}
    for h in hours:
        if h <= 36:
            w6 = W.get(h + (-h % 6))
            q, raw, n, pop = v(h, "qpf1"), v(h, "snow1"), 1, v(h, "pop1")
            dry = bool(w6) and w6["qpf"] < P.WET_IN
            snow = None if raw is None else (0.0 if dry else raw * (ps.get(h) or 0.0))
        elif W.get(h):
            q, snow, pop, n = W[h]["qpf"], W[h]["snow"], v(h, "pop6"), 6
        else:
            continue
        precip["end"].append((init + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%MZ"))
        precip["hours"].append(n)
        precip["qpf_in"].append(_r(q, 2))
        precip["snow_in"].append(_r(snow, 1))
        precip["pop"].append(_r(pop, 2))

    out_periods = []
    for s, e in P.periods(init, hours):
        ws = windows(s, e)
        if e not in hset or ws is None:
            continue
        q = sum(w["qpf"] for w in ws)
        snow = 0.0 if q < P.WET_IN else sum(w["snow"] for w in ws)
        pmean = P.weighted_mean([w["ps"] for w in ws], [w["qpf"] for w in ws])
        key = "qpf12" if e - s == 12 else "qpf6"
        # Ranges are NOT forced to contain the deterministic mean (owner S3): NBM's
        # deterministic and probabilistic fields are calibrated separately.
        ext_rng, slr = extended_range(qpct(key, e, 25, 75), ws)       # "likely range"
        nbm_rng = P.rank_sum([w["rng"] for w in ws])                   # NBM snowfall 10-90
        extended = nbm_rng is None
        rng = ext_rng if extended else nbm_rng
        qp = qpct(key, e, 25, 75) if extended else qpct(key, e)
        steps = steps_in(s, e)
        idx = [hours.index(h) for h in steps]
        temps = [series["t_f"][k] for k in idx if series["t_f"][k] is not None]
        gusts = [series["gust_mph"][k] for k in idx if series["gust_mph"][k] is not None]
        sls = [series["snowlvl_ft"][k] for k in idx if series["snowlvl_ft"][k] is not None]
        snowy_gusts = [series["gust_mph"][k] for k, h in zip(idx, steps)
                       if series["gust_mph"][k] is not None and raw_snow_at(h) > 0]
        pops = [x for x in (v(h, "pop6") for h in range(e, s, -6)) if x is not None]
        out_periods.append({
            **P.period_label(init, s, e, tz),
            "snow_in": _r(snow, 1),
            "snow_lo": _r(rng[0], 1) if rng else None, "snow_hi": _r(rng[1], 1) if rng else None,
            "extended": extended, "range": "derived 25-75" if extended else "NBM 10-90",
            # 0-48 h only: the extended-outlook (likely) range too, for the calibration report
            "snow_ext_lo": _r(ext_rng[0], 1) if (ext_rng and not extended) else None,
            "snow_ext_hi": _r(ext_rng[1], 1) if (ext_rng and not extended) else None,
            "qpf_in": _r(q, 2),
            "qpf_lo": _r(qp[0], 2) if qp else None, "qpf_hi": _r(qp[1], 2) if qp else None,
            "p_snow": _r(pmean, 2), "type": P.precip_type(q, pmean),
            "pop": _r(max(pops), 2) if pops else None,
            "slr": _r(slr, 1),
            "powder": P.powder_quality(slr, max(snowy_gusts, default=None), snow),
            "t_max_f": _r(max(temps)) if temps else None, "t_min_f": _r(min(temps)) if temps else None,
            "gust_max_mph": _r(max(gusts), 0) if gusts else None,
            "snowlvl_min_ft": _r(min(sls), -2) if sls else None,
        })

    totals = {}
    qblocks = {"24h": [("qpf_0_1d", 24)], "72h": [("qpf_0_3d", 72)],
               "7d": [("qpf_0_3d", 72), ("qpf_3_5d", 120), ("qpf_5_7d", 168)],
               "10d": [("qpf_0_3d", 72), ("qpf_3_5d", 120), ("qpf_5_7d", 168), ("qpf_7_10d", 240)]}
    # Totals start at the first valid 00/06/12/18Z (f000 for synoptic cycles, f005 for 01/07Z ...)
    t0 = (min(W) - 6) if W else 0

    def nbm_cover(s, e):
        """Rank-sum of NBM snowfall-percentile windows (72/48/24/6 h) that exactly tile
        (s, e]; None if they can't. Scaled by P(snow at the point). Tiles greedily with the
        longest window first, so a longer total extends the shorter one's windows (the 7-day
        range starts with the same 72-h window as the 72-h total); fewest-pieces search
        only if the greedy tiling dead-ends."""
        have = lambda L, end2: end2 <= e and v(end2, f"snow{L}_p10" if L > 6 else "snow6_p10") is not None  # noqa: E731
        pos, greedy = s, []
        while pos < e:
            L = next((L for L in (72, 48, 24, 6) if have(L, pos + L)), None)
            if L is None:
                greedy = None
                break
            greedy.append((L, pos + L))
            pos += L
        best = {s: []}
        for pos in range(s, e, 6):
            if pos not in best:
                continue
            for L in (72, 48, 24, 6):
                end2 = pos + L
                if end2 > e or v(end2, f"snow{L}_p10" if L > 6 else "snow6_p10") is None:
                    continue
                cand = best[pos] + [(L, end2)]
                if end2 not in best or len(cand) < len(best[end2]):
                    best[end2] = cand
        tiles = greedy if greedy is not None else best.get(e)
        if tiles is None:
            return None
        parts = []
        for L, end2 in tiles:
            ws = windows(end2 - L, end2) or []
            pw = P.weighted_mean([w["ps"] for w in ws], [w["qpf"] for w in ws]) if ws else 1.0
            key = "snow6" if L == 6 else f"snow{L}"
            lo, hi = v(end2, f"{key}_p10"), v(end2, f"{key}_p90")
            parts.append(None if lo is None or hi is None else (lo * (pw or 0), hi * (pw or 0)))
        return P.rank_sum(parts)

    for name, L in (("24h", 24), ("72h", 72), ("7d", 168), ("10d", 240)):
        end = t0 + L
        ws = windows(t0, end)
        if end not in hset or ws is None:
            continue
        q = sum(w["qpf"] for w in ws)
        snow = 0.0 if q < P.WET_IN else sum(w["snow"] for w in ws)
        cover = nbm_cover(t0, end)
        if cover is not None:  # NBM's own snowfall percentiles (all horizons on 01/07/13/19Z cycles)
            srng = cover
            qrng = P.rank_sum([qpct(k, e) for k, e in qblocks[name]]) if t0 == 0 and L <= 48 else None
        elif L <= 48:
            srng, qrng = None, P.rank_sum([qpct(k, e) for k, e in qblocks[name]])
        elif t0 != 0:          # day blocks are cycle-relative (f000): only for synoptic cycles
            srng = qrng = None
        else:                  # "likely range": QPF 25-75 x SLR x P(snow), blocks added rank by rank
            srng = P.rank_sum([extended_range(qpct(k, e, 25, 75), windows(e - {72: 72, 120: 48, 168: 48, 240: 72}[e], e))[0]
                               for k, e in qblocks[name]])
            qrng = P.rank_sum([qpct(k, e, 25, 75) for k, e in qblocks[name]])
        totals[name] = {"snow_in": _r(snow, 1),
                        "snow_lo": _r(srng[0], 1) if srng else None, "snow_hi": _r(srng[1], 1) if srng else None,
                        "qpf_in": _r(q, 2),
                        "qpf_lo": _r(qrng[0], 2) if qrng else None, "qpf_hi": _r(qrng[1], 2) if qrng else None,
                        "p_snow": _r(P.weighted_mean([w["ps"] for w in ws], [w["qpf"] for w in ws]), 2),
                        "extended": cover is None and L > 48,
                        "range": "NBM 10-90" if cover is not None else ("derived 25-75" if srng else None),
                        "from": (init + timedelta(hours=t0)).strftime("%Y-%m-%dT%H:%MZ")}
    return {"series": series, "precip": precip, "periods": out_periods, "totals": totals,
            "exceed": exceedance(data, hours, init, i)}


def build_outputs(cat: dict, data: dict[int, dict], hours: list[int], init: datetime,
                  col: dict[tuple, int], generated: str) -> tuple[dict, list]:
    files, summary = {}, []
    times = [(init + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%MZ") for h in hours]
    for a in cat["areas"]:
        tz = ZoneInfo(a.get("tz") or "America/Denver")
        doc = {"id": a["id"], "name": a["name"], "tz": a.get("tz"),
               "source": SOURCE, "cycle": init.strftime("%Y%m%d%H"), "liquid_cycle": liquid_cycle(init, data),
               "issued": init.strftime("%Y-%m-%dT%H:%MZ"), "generated_at": generated,
               "times": times, "fhours": hours, "points": {},
               # the catalog record, so the area page needs one request instead of the whole catalog
               "area": {k: v for k, v in a.items() if k not in ("nbm_grid", "osm_id", "verify")}}
        for k in ("summit", "base"):
            g = a["nbm_grid"][k]
            i = col[(g["i"], g["j"])]
            fc = point_forecast(data, hours, init, i, a[k]["elev_ft"], g.get("elev_ft"), tz)
            doc["points"][k] = {"elev_ft": a[k]["elev_ft"], "grid_elev_ft": g.get("elev_ft"),
                                "grid": [g["i"], g["j"]], **fc}
        tot = {k: doc["points"][k]["totals"] for k in ("summit", "base")}
        doc["checks"] = P.plausibility(tot["base"], tot["summit"])
        files[a["id"]] = doc
        per = doc["points"]["summit"]["periods"]
        brief = lambda t: {n: [x["snow_in"], x["snow_lo"], x["snow_hi"]] for n, x in t.items()}  # noqa: E731
        summary.append({
            "id": a["id"], "name": a["name"], "state": a["state"], "region": a["region"],
            "major": a.get("major", False), "lat": a["summit"]["lat"], "lon": a["summit"]["lon"],
            "elev": {"summit": a["summit"]["elev_ft"], "base": a["base"]["elev_ft"]},
            # [most likely (mean), 10th, 90th] snow in inches per window
            "summit": brief(tot["summit"]), "base": brief(tot["base"]), "checks": doc["checks"],
            "p_snow_base_72h": tot["base"].get("72h", {}).get("p_snow"),
            "snowlvl_min_72h_ft": min([p["snowlvl_min_ft"] for p in per[:6] if p["snowlvl_min_ft"] is not None],
                                      default=None),
            "gust_max_72h_mph": max([p["gust_max_mph"] for p in per[:6] if p["gust_max_mph"] is not None],
                                    default=None),
        })
    return files, summary


def calibration_report(files: dict, cid: str, min_in: float = 0.5) -> dict:
    """How the deterministic snow sits against the ranges (kept to recheck after storms).

    Over every point and 12-h period with a wet range (upper end >= min_in), split by
    lead (period end <= 48 h or later) and by range type: share of NBM means inside
    NBM's own 10-90 snowfall range, inside the derived "likely" 25-75 range, and the
    mean bounds. NBM's deterministic and probabilistic fields are calibrated
    separately, so a mean outside its range is legitimate; this tracks how often.
    """
    from datetime import datetime as _dt
    init = _dt.strptime(cid, "%Y%m%d%H")

    def bucket():
        return {"periods": 0, "inside": 0, "below": 0, "above": 0, "lo": 0.0, "hi": 0.0, "mean": 0.0}
    acc = {(lead, kind): bucket() for lead in ("first_48h", "beyond_48h") for kind in ("nbm_10_90", "derived_25_75")}
    for doc in files.values():
        for pt in doc["points"].values():
            for per in pt["periods"]:
                lead = (_dt.strptime(per["end"], "%Y-%m-%dT%H:%MZ") - init).total_seconds() / 3600
                lead = "first_48h" if lead <= 48 else "beyond_48h"
                ranges = [("nbm_10_90" if per.get("range") == "NBM 10-90" else "derived_25_75", per["snow_lo"], per["snow_hi"])]
                if per.get("snow_ext_lo") is not None:          # derived range kept for comparison
                    ranges.append(("derived_25_75", per["snow_ext_lo"], per["snow_ext_hi"]))
                m = per["snow_in"]
                for kind, lo, hi in ranges:
                    if m is None or lo is None or hi is None or hi < min_in:
                        continue
                    b = acc[(lead, kind)]
                    b["periods"] += 1
                    b["inside"] += lo <= m <= hi
                    b["below"] += m < lo
                    b["above"] += m > hi
                    b["lo"] += lo; b["hi"] += hi; b["mean"] += m
    out = {"cycle": cid, "min_in": min_in}
    for (lead, kind), b in acc.items():
        n = b["periods"]
        out.setdefault(lead, {})[kind] = {"periods": n} if not n else {
            "periods": n, "mean_inside": round(b["inside"] / n, 3), "mean_below": round(b["below"] / n, 3),
            "mean_above": round(b["above"] / n, 3), "avg_range_in": [round(b["lo"] / n, 2), round(b["hi"] / n, 2)],
            "avg_mean_in": round(b["mean"] / n, 2)}
    return out


def data_quality(missing: dict[int, list[str]], cycle_hour: int) -> dict:
    """Counts of required messages and of missing ones (shown in meta.json status)."""
    required = sum(len(required_keys(h, cycle_hour)) for h in missing)
    n = sum(len(v) for v in missing.values())
    by_field: dict[str, int] = {}
    for v in missing.values():
        for k in v:
            by_field[k] = by_field.get(k, 0) + 1
    return {"hours": len(missing), "required": required, "missing": n,
            "share": round(n / required, 4) if required else 1.0, "by_field": by_field}


LIQUID_FROM: dict[str, str | None] = {}     # cycle id -> QPF-percentile cycle id (set per run)


def liquid_cycle(init: datetime, data: dict) -> str | None:
    """Which cycle the QPF (liquid) percentiles come from, if any."""
    if not any(k.startswith("qpf12_p") for d in data.values() for k in d):
        return None
    return LIQUID_FROM.get(init.strftime("%Y%m%d%H")) or init.strftime("%Y%m%d%H")


def exceed_summary(files: dict, cat: dict) -> dict:
    """Powder Finder "Chance of" mode: per area and elevation, P(>=x) per window
    (lazy-loaded file; the windows/thresholds are shared by every area)."""
    areas, windows = {}, None
    for a in cat["areas"]:
        doc = files.get(a["id"])
        if not doc:
            continue
        ex = {k: doc["points"][k]["exceed"] for k in ("summit", "base")}
        if windows is None:
            windows = {L: {kk: vv for kk, vv in w.items() if kk != "p"} for L, w in ex["summit"].items()}
        areas[a["id"]] = {k: {L: w["p"] for L, w in e.items()} for k, e in ex.items()}
    return {"windows": windows or {}, "areas": areas}


def station_outputs(stations: list[dict], data, hours, init, col, generated) -> dict:
    """Single-elevation forecasts at SNOTEL sites (area.html#snotel-...)."""
    times = [(init + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%MZ") for h in hours]
    out = {}
    for st in stations:
        g = st["nbm_grid"]
        fc = point_forecast(data, hours, init, col[(g["i"], g["j"])], st["elev_ft"], g.get("elev_ft"),
                            ZoneInfo(st.get("tz") or "America/Denver"))
        out[st["id"]] = {"id": st["id"], "name": st["name"], "tz": st.get("tz"), "source": SOURCE,
                         "cycle": init.strftime("%Y%m%d%H"), "liquid_cycle": liquid_cycle(init, data), "issued": init.strftime("%Y-%m-%dT%H:%MZ"),
                         "generated_at": generated, "times": times, "fhours": hours, "station": st,
                         "points": {"point": {"elev_ft": st["elev_ft"], "grid_elev_ft": g.get("elev_ft"),
                                              "grid": [g["i"], g["j"]], **fc}}}
    return out


def run_points(cfg: dict, session, out: Path, *, cycle: datetime | None = None,
               published: str | None = None, max_hour: int = 264, workers: int = 6,
               github_output: str | None = None, catalog: Path = CATALOG, now=None) -> int:
    cat = json.loads(Path(catalog).read_text(encoding="utf-8"))
    grid = cat["nbm_grid"]          # grid definition stored with the catalog
    sp = Path(catalog).with_name("snotel_points.json")
    stations = json.loads(sp.read_text(encoding="utf-8"))["points"] if sp.exists() else []

    def emit(**kv):
        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                for k, v in kv.items():
                    f.write(f"{k}={v}\n")

    cycle = cycle or latest_cycle(session, now or utcnow(), max_hour)
    if cycle is None:
        log.warning("no complete NBM cycle found")
        emit(new="false")
        return 0
    cycle = cycle.replace(tzinfo=timezone.utc) if cycle.tzinfo is None else cycle
    cid = cycle.strftime("%Y%m%d%H")
    from ..version import stamp
    tag = stamp(cid, "points")
    if published == tag:
        log.info("NBM %s already published; nothing new", tag)
        emit(new="false", cycle=tag)
        return 0

    cells = sorted({(a["nbm_grid"][k]["i"], a["nbm_grid"][k]["j"]) for a in cat["areas"] for k in ("base", "summit")}
                   | {(s["nbm_grid"]["i"], s["nbm_grid"]["j"]) for s in stations})
    col = {c: n for n, c in enumerate(cells)}
    ij = (np.array([c[0] for c in cells]), np.array([c[1] for c in cells]))
    hours = sample_hours(list_hours(session, cycle), cycle.hour, max_hour)
    if not hours:
        log.error("NBM %s: no forecast hours listed", cid)
        emit(new="false")
        return 1
    # samples are columns in cell order: key the cache on the cell list and the selections
    import hashlib
    comp = liquid_source(session, cycle)
    LIQUID_FROM[cid] = comp.strftime("%Y%m%d%H") if comp else None
    log.info("NBM %s: liquid (QPF) percentiles from %s", cid, comp.strftime("%Y%m%d%H") if comp else "-")
    key = hashlib.md5(repr((cells, SELECTION_VERSION, comp)).encode()).hexdigest()[:10]
    cache_dir = CACHE / f"{cid}_{key}"
    log.info("NBM %s: %d forecast hours, %d grid cells for %d areas + %d SNOTEL sites", cid, len(hours), len(cells),
             len(cat["areas"]), len(stations))
    t0 = time.time()
    data: dict[int, dict] = {}
    missing: dict[int, list[str]] = {}
    with ThreadPoolExecutor(workers) as ex:
        futs = {h: ex.submit(fetch_hour, session, cycle, h, ij, grid, cache_dir, comp) for h in hours}
        for h, fut in futs.items():
            data[h], missing[h] = fut.result()
    log.info("NBM fetch+decode %.0f s", time.time() - t0)
    quality = data_quality(missing, cycle.hour)
    if quality["missing"]:
        log.warning("NBM %s: %d of %d required messages missing (%.1f%%): %s", cid, quality["missing"],
                    quality["required"], 100 * quality["share"], quality["by_field"])
    if quality["share"] > MAX_MISSING_SHARE or not any("t2m" in d for d in data.values()):
        log.error("NBM %s: too much data missing (%.0f%%); not publishing", cid, 100 * quality["share"])
        emit(new="false")
        return 1

    generated = utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    files, summary = build_outputs(cat, data, hours, cycle, col, generated)
    files.update(station_outputs(stations, data, hours, cycle, col, generated))
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    sizes = []
    for aid, doc in files.items():
        p = out / f"{aid}.json"
        write_json(p, doc)
        sizes.append(p.stat().st_size)
    write_json(out / "exceed_summary.json", {"cycle": cid, "issued": cycle.strftime("%Y-%m-%dT%H:%MZ"),
                                             "source": SOURCE, **exceed_summary(files, cat)})
    cal = calibration_report(files, cid)
    write_json(out / "calibration.json", cal)
    log.info("calibration: %s", json.dumps({k: v for k, v in cal.items() if k in ("first_48h", "beyond_48h")}))
    write_json(out / "summary.json", {"cycle": cid, "quality": quality, "issued": cycle.strftime("%Y-%m-%dT%H:%MZ"),
                                      "generated_at": generated, "source": SOURCE, "areas": summary})
    log.info("NBM %s: wrote %d area files (max %.0f KB, total %.1f MB) + summary.json",
             cid, len(files), max(sizes) / 1024, sum(sizes) / 1e6)
    flagged = {k: d["checks"] for k, d in files.items() if d.get("checks")}
    if flagged:
        log.warning("plausibility flags (%d areas): %s", len(flagged),
                    "; ".join(f"{k}: {', '.join(v)}" for k, v in list(flagged.items())[:10]))
    emit(new="true", cycle=tag)
    return 0
