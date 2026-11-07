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


def _pct(d: dict, key: str, h: int, i: int) -> dict:
    return {p: _val(d, h, f"{key}_p{p}", i) for p in P_LEVELS}


P_LEVELS = (10, 50, 90)


def _val(data, h, key, i):
    arr = data.get(h, {}).get(key)
    if arr is None:
        return None
    v = float(arr[i])
    return None if math.isnan(v) else v


def point_forecast(data: dict[int, dict], hours: list[int], init: datetime, i: int,
                   elev_ft: float, grid_ft: float | None, tz) -> dict:
    """Series, 12-h periods and totals for one point (column i of every array)."""
    series = {k: [] for k in ("t_f", "wind_mph", "gust_mph", "wdir", "sky", "snowlvl_ft",
                              "snowlvl_p10", "snowlvl_p90", "p_snow", "slr")}
    psnow_by_h = {}
    for h in hours:
        t = _val(data, h, "t2m", i)
        series["t_f"].append(_r(P.lapse_adjust_f(t, grid_ft, elev_ft)))
        series["wind_mph"].append(_r(_val(data, h, "wind", i), 0))
        series["gust_mph"].append(_r(_val(data, h, "gust", i), 0))
        series["wdir"].append(_r(_val(data, h, "wdir", i), 0))
        series["sky"].append(_r(_val(data, h, "sky", i) , 0))
        sl50 = _val(data, h, "snowlvl_p50", i)
        det = _val(data, h, "snowlvl", i)
        p10, p90 = _val(data, h, "snowlvl_p10", i), _val(data, h, "snowlvl_p90", i)
        series["snowlvl_ft"].append(_r(sl50 if sl50 is not None else det, -2))
        series["snowlvl_p10"].append(_r(p10, -2))
        series["snowlvl_p90"].append(_r(p90, -2))
        ps = P.p_snow_level_below(elev_ft, p10, sl50 if sl50 is not None else det, p90)
        psnow_by_h[h] = ps
        series["p_snow"].append(_r(ps, 2))
        series["slr"].append(_r(_val(data, h, "slr", i), 1))

    # precipitation windows: 1 h to f036, then 6 h
    precip = {"end": [], "hours": [], "qpf_in": [], "snow_in": [], "pop": []}
    for h in hours:
        if h <= 36:
            q, s, pop, n = _val(data, h, "qpf1", i), _val(data, h, "snow1", i), _val(data, h, "pop1", i), 1
        elif h % 6 == 0:
            q, s, pop, n = _val(data, h, "qpf6", i), _val(data, h, "snow6", i), _val(data, h, "pop6", i), 6
        else:
            continue
        precip["end"].append((init + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%MZ"))
        precip["hours"].append(n)
        precip["qpf_in"].append(_r(q, 2))
        precip["snow_in"].append(_r(s, 1))
        precip["pop"].append(_r(pop, 2))

    qpf6 = {h: _val(data, h, "qpf6", i) for h in hours if h % 6 == 0}
    snow6 = {h: _val(data, h, "snow6", i) for h in hours if h % 6 == 0}
    hset = set(hours)

    def snowing(h):
        """Snow falling at step h: the 1-h amount to f036, else the 6-h window holding h."""
        v = _val(data, h, "snow1", i) if h <= 36 else snow6.get(h + (-h % 6))
        return (v or 0.0) > (0.02 if h <= 36 else 0.1)

    def window_stats(s, e):
        steps = [h for h in hours if s < h <= e]
        ps = [psnow_by_h[h] for h in steps if psnow_by_h.get(h) is not None]
        # NBM SNOWLR is ~0 where no snow falls: average it over snowy steps only
        slr = [_val(data, h, "slr", i) for h in steps if snowing(h)]
        slr = [v for v in slr if v is not None and v > 0]
        return (sum(ps) / len(ps) if ps else None), (sum(slr) / len(slr) if slr else None), steps

    def scaled(qpf_pct, s, e):
        qd, sd = P.window_sum(qpf6, s, e, 6), P.window_sum(snow6, s, e, 6)
        ps, slr, _ = window_stats(s, e)
        ratio = P.snow_ratio(sd, qd, slr, ps)
        snow = {p: (None if v is None else v * ratio) for p, v in qpf_pct.items()}
        return snow, qd, sd, ps, slr

    out_periods = []
    for s, e in P.periods(init, hours):
        if e not in hset:
            continue
        key = "qpf12" if e - s == 12 else "qpf6"
        qpct = _pct(data, key, e, i)
        snow, qd, sd, ps, slr = scaled(qpct, s, e)
        _, _, steps = window_stats(s, e)
        temps = [series["t_f"][hours.index(h)] for h in steps]
        temps = [t for t in temps if t is not None]
        gusts_snow = [series["gust_mph"][hours.index(h)] for h in steps if snowing(h)]
        gusts = [g for g in (series["gust_mph"][hours.index(h)] for h in steps) if g is not None]
        sls = [series["snowlvl_ft"][hours.index(h)] for h in steps if series["snowlvl_ft"][hours.index(h)] is not None]
        nbm_snow_pct = {p: P.window_sum({h: _val(data, h, f"snow6_p{p}", i) for h in qpf6}, s, e, 6)
                        for p in P_LEVELS}
        out_periods.append({
            **P.period_label(init, s, e, tz),
            "qpf_in": {str(p): _r(v, 2) for p, v in qpct.items()},
            "snow_in": {str(p): _r(v, 1) for p, v in snow.items()},
            "snow_det_in": _r(sd, 1), "qpf_det_in": _r(qd, 2),
            "nbm_snow_pct_in": ({str(p): _r(v, 1) for p, v in nbm_snow_pct.items()}
                                if all(v is not None for v in nbm_snow_pct.values()) else None),
            "p_snow": _r(ps, 2),
            "type": P.precip_type(qpct.get(50), ps),
            "slr": _r(slr, 1),
            "powder": P.powder_quality(slr, max([g for g in gusts_snow if g is not None], default=None),
                                       snow.get(50)),
            "t_max_f": _r(max(temps)) if temps else None, "t_min_f": _r(min(temps)) if temps else None,
            "gust_max_mph": _r(max(gusts), 0) if gusts else None,
            "snowlvl_min_ft": _r(min(sls), -2) if sls else None,
        })

    totals = {}
    blocks = {"24h": [("qpf_0_1d", 0, 24)], "72h": [("qpf_0_3d", 0, 72)],
              "7d": [("qpf_0_3d", 0, 72), ("qpf_3_5d", 72, 120), ("qpf_5_7d", 120, 168)],
              "10d": [("qpf_0_3d", 0, 72), ("qpf_3_5d", 72, 120), ("qpf_5_7d", 120, 168),
                      ("qpf_7_10d", 168, 240)]}
    for name, parts in blocks.items():
        if any(e not in hset for _, _, e in parts):
            continue
        qparts, sparts = [], []
        for key, s, e in parts:
            q = _pct(data, key, e, i)
            sn, *_ = scaled(q, s, e)
            qparts.append(q)
            sparts.append(sn)
        q, sn = P.comonotonic_sum(qparts), P.comonotonic_sum(sparts)
        e = parts[-1][2]
        ps, _, _ = window_stats(0, e)
        totals[name] = {"qpf_in": {str(p): _r(v, 2) for p, v in q.items()},
                        "snow_in": {str(p): _r(v, 1) for p, v in sn.items()},
                        "snow_det_in": _r(P.window_sum(snow6, 0, e, 6), 1),
                        "p_snow": _r(ps, 2), "approx": len(parts) > 1}
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
               "times": times, "fhours": hours, "points": {}}
        for k in ("summit", "base"):
            g = a["nbm_grid"][k]
            i = col[(g["i"], g["j"])]
            fc = point_forecast(data, hours, init, i, a[k]["elev_ft"], g.get("elev_ft"), tz)
            doc["points"][k] = {"elev_ft": a[k]["elev_ft"], "grid_elev_ft": g.get("elev_ft"),
                                "grid": [g["i"], g["j"]], **fc}
        files[a["id"]] = doc
        tot = {k: doc["points"][k]["totals"] for k in ("summit", "base")}
        per = doc["points"]["summit"]["periods"]
        summary.append({
            "id": a["id"], "name": a["name"], "state": a["state"], "region": a["region"],
            "major": a.get("major", False), "lat": a["summit"]["lat"], "lon": a["summit"]["lon"],
            "summit": {n: t["snow_in"] for n, t in tot["summit"].items()},
            "base": {n: t["snow_in"] for n, t in tot["base"].items()},
            "p_snow_base_72h": tot["base"].get("72h", {}).get("p_snow"),
            "snowlvl_min_72h_ft": min([p["snowlvl_min_ft"] for p in per[:6] if p["snowlvl_min_ft"] is not None],
                                      default=None),
            "gust_max_72h_mph": max([p["gust_max_mph"] for p in per[:6] if p["gust_max_mph"] is not None],
                                    default=None),
        })
    return files, summary


def run_points(cfg: dict, session, out: Path, *, cycle: datetime | None = None,
               published: str | None = None, max_hour: int = 264, workers: int = 6,
               github_output: str | None = None, catalog: Path = CATALOG, now=None) -> int:
    cat = json.loads(Path(catalog).read_text(encoding="utf-8"))
    grid = cat["nbm_grid"]          # grid definition stored with the catalog

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
    if published == cid:
        log.info("NBM %s already published; nothing new", cid)
        emit(new="false", cycle=cid)
        return 0

    cells = sorted({(a["nbm_grid"][k]["i"], a["nbm_grid"][k]["j"]) for a in cat["areas"] for k in ("base", "summit")})
    col = {c: n for n, c in enumerate(cells)}
    ij = (np.array([c[0] for c in cells]), np.array([c[1] for c in cells]))
    hours = [h for h in forecast_hours(max_hour)]
    cache_dir = CACHE / cid
    log.info("NBM %s: %d forecast hours, %d grid cells for %d areas", cid, len(hours), len(cells), len(cat["areas"]))
    t0 = time.time()
    data: dict[int, dict] = {}
    with ThreadPoolExecutor(workers) as ex:
        futs = {h: ex.submit(fetch_hour, session, cycle, h, ij, grid, cache_dir) for h in hours}
        for h, fut in futs.items():
            data[h] = fut.result()
    log.info("NBM fetch+decode %.0f s", time.time() - t0)

    generated = utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    files, summary = build_outputs(cat, data, hours, cycle, col, generated)
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
    emit(new="true", cycle=cid)
    return 0
