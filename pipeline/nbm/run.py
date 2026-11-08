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
from .inventory import Sel, find, forecast_hours, parse_idx, selections

log = logging.getLogger("snow-wx.nbm")

BUCKET = "https://noaa-nbm-grib2-pds.s3.amazonaws.com"
CACHE = REPO_ROOT / "data_cache" / "nbm"
CATALOG = REPO_ROOT / "data" / "ski_areas.json"
SOURCE = "NOAA/NWS National Blend of Models (NBM) via NOAA Open Data Dissemination (AWS)"
SELECTION_VERSION = 2          # bump when inventory.selections changes (invalidates the sample cache)

K_TO_F = lambda k: (k - 273.15) * 1.8 + 32.0  # noqa: E731
MS_TO_MPH = 2.236936
MM_TO_IN = 1 / 25.4
M_TO_IN = 39.37008
M_TO_FT = 3.28084


def url(cycle: datetime, product: str, fhour: int) -> str:
    return (f"{BUCKET}/blend.{cycle:%Y%m%d}/{cycle:%H}/{product}/"
            f"blend.t{cycle:%H}z.{product}.f{fhour:03d}.co.grib2")


def convert(key: str, v: np.ndarray) -> np.ndarray:
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


def latest_cycle(session, now: datetime, max_hour: int, lookback_h: int = 30) -> datetime | None:
    """Newest 00/06/12/18Z cycle whose core and qmd files reach max_hour."""
    t = now.replace(minute=0, second=0, microsecond=0)
    t -= timedelta(hours=t.hour % 6)
    for _ in range(lookback_h // 6 + 1):
        ok = all(session.head(url(t, p, max_hour) + ".idx", timeout=30).status_code == 200
                 for p in ("core", "qmd"))
        if ok:
            return t
        t -= timedelta(hours=6)
    return None


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
               cache_dir: Path) -> dict[str, np.ndarray]:
    path = cache_dir / f"f{fhour:03d}.npz"
    if path.exists():
        with np.load(path) as z:
            return {k: z[k] for k in z.files}
    sels = selections(fhour, cycle.hour)
    out: dict[str, np.ndarray] = {}
    for product in ("core", "qmd"):
        mine = [(s, req) for s, req in sels if s.file == product]
        if not mine:
            continue
        r = _get(session, url(cycle, product, fhour) + ".idx")
        if r is None:
            raise FileNotFoundError(f"{product} f{fhour:03d} idx missing")
        inv = parse_idx(r.text)
        chosen = {}
        for s, req in mine:
            m = find(inv, s, fhour)
            if m is None:
                if req:
                    raise KeyError(f"{product} f{fhour:03d}: no {s.var} {s.level} {s.hours}h {s.kind} {s.value}")
                continue
            if m.length is None:
                raise ValueError("last message in file; length unknown")
            chosen[m] = s.key
        for start, end, members in merge_ranges(list(chosen)):
            blob = _get(session, url(cycle, product, fhour), {"Range": f"bytes={start}-{end}"}).content
            for m in members:
                part = blob[m.offset - start: m.offset - start + m.length]
                out[chosen[m]] = convert(chosen[m], decode_at(part, ij, grid))
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(path, **out)
    return out


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

    # 6-h windows: the unit that periods and totals are summed from
    W: dict[int, dict | None] = {}
    for e in [h for h in hours if h % 6 == 0]:
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
        ws = [W.get(h) for h in range(s + 6, e + 1, 6)]
        return None if not ws or any(w is None for w in ws) else ws

    def qpct(key, e):
        lo, hi = v(e, f"{key}_p10"), v(e, f"{key}_p90")
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
        elif h % 6 == 0 and W.get(h):
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
        qp = qpct("qpf12" if e - s == 12 else "qpf6", e)
        ext_rng, slr = extended_range(qp, ws)
        nbm_rng = P.rank_sum([w["rng"] for w in ws])
        extended = nbm_rng is None
        rng = P.with_mean(ext_rng if extended else nbm_rng, snow)
        steps = steps_in(s, e)
        idx = [hours.index(h) for h in steps]
        temps = [series["t_f"][k] for k in idx if series["t_f"][k] is not None]
        gusts = [series["gust_mph"][k] for k in idx if series["gust_mph"][k] is not None]
        sls = [series["snowlvl_ft"][k] for k in idx if series["snowlvl_ft"][k] is not None]
        snowy_gusts = [series["gust_mph"][k] for k, h in zip(idx, steps)
                       if series["gust_mph"][k] is not None and raw_snow_at(h) > 0]
        pops = [x for x in (v(h, "pop6") for h in range(s + 6, e + 1, 6)) if x is not None]
        out_periods.append({
            **P.period_label(init, s, e, tz),
            "snow_in": _r(snow, 1),
            "snow_lo": _r(rng[0], 1) if rng else None, "snow_hi": _r(rng[1], 1) if rng else None,
            "extended": extended,
            # 0-48 h only: the extended-outlook range too, to compare the two methods
            "snow_ext_lo": _r(ext_rng[0], 1) if (ext_rng and not extended) else None,
            "snow_ext_hi": _r(ext_rng[1], 1) if (ext_rng and not extended) else None,
            "qpf_in": _r(q, 2),
            "qpf_lo": _r(min(qp[0], q), 2) if qp else None, "qpf_hi": _r(max(qp[1], q), 2) if qp else None,
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
    sblocks = [("qpf_2_3d", 48, 72), ("qpf_3_5d", 72, 120), ("qpf_5_7d", 120, 168), ("qpf_7_10d", 168, 240)]
    for name, end in (("24h", 24), ("72h", 72), ("7d", 168), ("10d", 240)):
        ws = windows(0, end)
        if end not in hset or ws is None:
            continue
        q = sum(w["qpf"] for w in ws)
        snow = 0.0 if q < P.WET_IN else sum(w["snow"] for w in ws)
        parts = [P.rank_sum([w["rng"] for w in (windows(0, min(end, 48)) or [{"rng": None}])])]
        for key, s, e in sblocks:
            if e <= end:
                parts.append(extended_range(qpct(key, e), windows(s, e))[0])
        srng = P.with_mean(P.rank_sum(parts), snow)
        qrng = P.with_mean(P.rank_sum([qpct(k, e) for k, e in qblocks[name]]), q)
        totals[name] = {"snow_in": _r(snow, 1),
                        "snow_lo": _r(srng[0], 1) if srng else None, "snow_hi": _r(srng[1], 1) if srng else None,
                        "qpf_in": _r(q, 2),
                        "qpf_lo": _r(qrng[0], 2) if qrng else None, "qpf_hi": _r(qrng[1], 2) if qrng else None,
                        "p_snow": _r(P.weighted_mean([w["ps"] for w in ws], [w["qpf"] for w in ws]), 2),
                        "extended": end > 48}
    return {"series": series, "precip": precip, "periods": out_periods, "totals": P.monotone_totals(totals)}


def build_outputs(cat: dict, data: dict[int, dict], hours: list[int], init: datetime,
                  col: dict[tuple, int], generated: str) -> tuple[dict, list]:
    files, summary = {}, []
    times = [(init + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%MZ") for h in hours]
    for a in cat["areas"]:
        tz = ZoneInfo(a.get("tz") or "America/Denver")
        doc = {"id": a["id"], "name": a["name"], "tz": a.get("tz"),
               "source": SOURCE, "cycle": init.strftime("%Y%m%d%H"),
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
            # [most likely (mean), 10th, 90th] snow in inches per window
            "summit": brief(tot["summit"]), "base": brief(tot["base"]), "checks": doc["checks"],
            "p_snow_base_72h": tot["base"].get("72h", {}).get("p_snow"),
            "snowlvl_min_72h_ft": min([p["snowlvl_min_ft"] for p in per[:6] if p["snowlvl_min_ft"] is not None],
                                      default=None),
            "gust_max_72h_mph": max([p["gust_max_mph"] for p in per[:6] if p["gust_max_mph"] is not None],
                                    default=None),
        })
    return files, summary


def station_outputs(stations: list[dict], data, hours, init, col, generated) -> dict:
    """Single-elevation forecasts at SNOTEL sites (area.html#snotel-...)."""
    times = [(init + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%MZ") for h in hours]
    out = {}
    for st in stations:
        g = st["nbm_grid"]
        fc = point_forecast(data, hours, init, col[(g["i"], g["j"])], st["elev_ft"], g.get("elev_ft"),
                            ZoneInfo(st.get("tz") or "America/Denver"))
        out[st["id"]] = {"id": st["id"], "name": st["name"], "tz": st.get("tz"), "source": SOURCE,
                         "cycle": init.strftime("%Y%m%d%H"), "issued": init.strftime("%Y-%m-%dT%H:%MZ"),
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
    hours = [h for h in forecast_hours(max_hour)]
    # samples are columns in cell order: key the cache on the cell list and the selections
    import hashlib
    key = hashlib.md5(repr((cells, SELECTION_VERSION)).encode()).hexdigest()[:10]
    cache_dir = CACHE / f"{cid}_{key}"
    log.info("NBM %s: %d forecast hours, %d grid cells for %d areas + %d SNOTEL sites", cid, len(hours), len(cells),
             len(cat["areas"]), len(stations))
    t0 = time.time()
    data: dict[int, dict] = {}
    with ThreadPoolExecutor(workers) as ex:
        futs = {h: ex.submit(fetch_hour, session, cycle, h, ij, grid, cache_dir) for h in hours}
        for h, fut in futs.items():
            data[h] = fut.result()
    log.info("NBM fetch+decode %.0f s", time.time() - t0)

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
    write_json(out / "summary.json", {"cycle": cid, "issued": cycle.strftime("%Y-%m-%dT%H:%MZ"),
                                      "generated_at": generated, "source": SOURCE, "areas": summary})
    log.info("NBM %s: wrote %d area files (max %.0f KB, total %.1f MB) + summary.json",
             cid, len(files), max(sizes) / 1024, sum(sizes) / 1e6)
    flagged = {k: d["checks"] for k, d in files.items() if d.get("checks")}
    if flagged:
        log.warning("plausibility flags (%d areas): %s", len(flagged),
                    "; ".join(f"{k}: {', '.join(v)}" for k, v in list(flagged.items())[:10]))
    emit(new="true", cycle=tag)
    return 0
