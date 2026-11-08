"""NWS official forecast (NDFD) at every ski area and SNOTEL site (PLAN.md §5.3, M3.5).

Fetch once, sample all: whole-element GRIB2 files from the NODD bucket
(s3://noaa-ndfd-pds/opnl/AR.conus/VP.001-003 and VP.004-007, no .idx, so whole files),
decoded in memory and sampled at every point's NDFD 2.5-km cell.

Inventory (checked 7 Nov 2026): temp (hourly then 3-h, to day 7), maxt/mint, pop12,
sky, wspd/wgust (to day 7); snow, qpf (6-h windows) and snowlevel (to 72 h only).
NDFD's 2145x1377 Lambert grid uses alternativeRowScanning like NBM core.

Output: data/ndfd/<id>.json in the same shape as the NBM point files (series, 6-h
precip windows, 12-h periods, totals) so the area page can toggle NBM <-> NWS.
NWS values are shown raw for their 2.5-km grid cell (owner decision S3): no lapse
adjustment and no snow-level scaling; NDFD snow already contains the forecasters'
rain/snow decisions. The rain/snow label comes from NDFD's own snow:liquid ratio.
The cell elevation shown with it is the overlapping NBM cell's 3DEP mean (NDFD files
carry no terrain), hence "≈".
"""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from . import points as P
from .catalog import lcc_ij
from .common import REPO_ROOT, utcnow, write_json
from .nbm.run import flat_index

log = logging.getLogger("snow-wx.ndfd")

BUCKET = "https://noaa-ndfd-pds.s3.amazonaws.com/opnl/AR.conus"
ELEMENTS = {"VP.001-003": ("temp", "maxt", "mint", "pop12", "sky", "wspd", "wgust", "snow", "qpf", "snowlevel"),
            "VP.004-007": ("temp", "maxt", "mint", "pop12", "sky", "wspd", "wgust")}
SOURCE = "NOAA/NWS National Digital Forecast Database (NDFD) via NOAA Open Data Dissemination (AWS)"
MS_TO_MPH, M_TO_IN, MM_TO_IN, M_TO_FT = 2.236936, 39.37008, 1 / 25.4, 3.28084
CACHE = REPO_ROOT / "data_cache" / "ndfd"


def parse_step(step: str) -> int:
    """'330m' -> 330 minutes, '6' -> 360 (hours when no unit)."""
    m = re.fullmatch(r"(\d+)([mh]?)", step)
    return int(m.group(1)) * (1 if m.group(2) == "m" else 60)


def window_minutes(step_range: str) -> int:
    """'330m-690m' -> 360; '0-6' -> 360; '30m' (instantaneous) -> 0."""
    if "-" not in step_range:
        return 0
    a, b = step_range.split("-")
    return parse_step(b) - parse_step(a)


def convert(el: str, v: np.ndarray) -> np.ndarray:
    if el in ("temp", "maxt", "mint"):
        return (v - 273.15) * 1.8 + 32
    if el in ("wspd", "wgust"):
        return v * MS_TO_MPH
    if el == "snow":
        return v * M_TO_IN
    if el == "qpf":
        return v * MM_TO_IN
    if el == "snowlevel":
        return v * M_TO_FT
    return v                         # pop12, sky: %


def latest_key(session) -> tuple[str | None, datetime | None]:
    """Last-Modified of the day-1-3 temperature file, as YYYYMMDDHH (the run key)."""
    r = session.head(f"{BUCKET}/VP.001-003/ds.temp.bin", timeout=60)
    if not r.ok:
        return None, None
    t = parsedate_to_datetime(r.headers["Last-Modified"]).astimezone(timezone.utc)
    return t.strftime("%Y%m%d%H"), t


def grid_from_message(h) -> dict:
    import eccodes
    g = lambda k: eccodes.codes_get(h, k)  # noqa: E731
    radius = 6371200.0
    try:
        if g("shapeOfTheEarth") == 1:
            radius = g("scaledValueOfRadiusOfSphericalEarth") / 10 ** g("scaleFactorOfRadiusOfSphericalEarth")
    except Exception:  # noqa: BLE001
        pass
    lov, lon1 = g("LoVInDegrees"), g("longitudeOfFirstGridPointInDegrees")
    return {"nx": g("Nx"), "ny": g("Ny"), "lad": g("LaDInDegrees"), "lov": lov - 360 if lov > 180 else lov,
            "latin1": g("Latin1InDegrees"), "latin2": g("Latin2InDegrees"), "lat1": g("latitudeOfFirstGridPointInDegrees"),
            "lon1": lon1 - 360 if lon1 > 180 else lon1, "dx": g("DxInMetres"), "dy": g("DyInMetres"), "radius": radius}


def read_element(blob: bytes, el: str, points_ll: list[tuple[float, float]], grid_box: dict) -> list[dict]:
    """[{end, minutes, values}] for every message of one element file."""
    import eccodes
    out, off = [], 0
    ii = jj = None
    while off < len(blob):
        start = blob.find(b"GRIB", off)
        if start < 0:
            break
        length = int.from_bytes(blob[start + 8:start + 16], "big")       # GRIB2 total length
        h = eccodes.codes_new_from_message(blob[start:start + length])
        off = start + length
        try:
            if grid_box.get("grid") is None:
                grid_box["grid"] = grid_from_message(h)
            if ii is None:
                ij = [lcc_ij(la, lo, grid_box["grid"]) for la, lo in points_ll]
                ii, jj = np.array([a for a, _ in ij]), np.array([b for _, b in ij])
            alt = bool(eccodes.codes_get(h, "alternativeRowScanning"))
            eccodes.codes_set(h, "missingValue", 9.999e20)
            vals = eccodes.codes_get_values(h)
            end = datetime.strptime(f"{eccodes.codes_get(h, 'validityDate')}{eccodes.codes_get(h, 'validityTime'):04d}",
                                    "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
            ref = datetime.strptime(f"{eccodes.codes_get(h, 'dataDate')}{eccodes.codes_get(h, 'dataTime'):04d}",
                                    "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
            mins = window_minutes(eccodes.codes_get(h, "stepRange"))
        finally:
            eccodes.codes_release(h)
        v = vals[flat_index(ii, jj, grid_box["grid"]["nx"], alt)].astype("float64")
        v[v > 9e20] = np.nan
        out.append({"end": end, "minutes": mins, "ref": ref, "values": convert(el, v)})
    return out


def fetch_all(session, points_ll, cache_dir: Path) -> tuple[dict, dict]:
    """{element: [messages]} merged over both day ranges (days 1-3 win on overlap)."""
    grid_box: dict = {}

    def one(vp, el):
        path = cache_dir / f"{vp}.{el}.bin"
        if path.exists():
            blob = path.read_bytes()
        else:
            for k in range(4):
                try:
                    r = session.get(f"{BUCKET}/{vp}/ds.{el}.bin", timeout=300)
                    r.raise_for_status()
                    blob = r.content
                    break
                except Exception:  # noqa: BLE001
                    if k == 3:
                        raise
                    time.sleep(5 * (k + 1))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
        return vp, el, blob

    jobs = [(vp, el) for vp, els in ELEMENTS.items() for el in els]
    with ThreadPoolExecutor(4) as ex:
        blobs = list(ex.map(lambda a: one(*a), jobs))
    data: dict[str, list] = {}
    for vp, el, blob in blobs:          # decode serially (ecCodes is not thread-safe)
        msgs = read_element(blob, el, points_ll, grid_box)
        seen = {m["end"] for m in data.get(el, [])}
        data.setdefault(el, []).extend(m for m in msgs if m["end"] not in seen)
    for el in data:
        data[el].sort(key=lambda m: m["end"])
    return data, grid_box.get("grid") or {}


# ---------------------------------------------------------------- assemble (pure)

def _r(v, nd=1):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return round(float(v), nd)


def ndfd_type(qpf_in, snow_in):
    """Rain/snow label from NDFD itself: snow:liquid >= 5 snow, > 0 mixed, else mostly rain."""
    if qpf_in is None or qpf_in < 0.01:
        return None
    if not snow_in:
        return "mostly rain"
    return "snow" if snow_in / qpf_in >= 5 else "mixed"


def point_doc(data: dict, k: int, elev_ft: float | None, tz) -> tuple[list[str], dict]:
    """NBM-shaped forecast for column k: (times, {series, precip, periods, totals})."""
    temps = data.get("temp", [])
    times = [m["end"] for m in temps]
    by_end = {el: {m["end"]: m for m in msgs} for el, msgs in data.items()}

    def at(el, t):
        m = by_end.get(el, {}).get(t)
        return None if m is None else float(m["values"][k])

    def latest_at_or_before(el, t):
        """Instantaneous elements with coarser steps: nearest earlier value within 3 h."""
        for dh in range(0, 4):
            v = at(el, t - timedelta(hours=dh))
            if v is not None and not np.isnan(v):
                return v
        return None

    series = {key: [] for key in ("t_f", "wind_mph", "gust_mph", "wdir", "sky", "snowlvl_ft",
                                  "snowlvl_p10", "snowlvl_p90", "p_snow", "slr", "pop")}
    for t in times:
        sl = latest_at_or_before("snowlevel", t)
        ps = None                       # raw NDFD: no P(snow at elevation)
        pop = next((float(m["values"][k]) / 100 for m in data.get("pop12", [])
                    if m["end"] - timedelta(minutes=m["minutes"]) < t <= m["end"]), None)
        series["t_f"].append(_r(at("temp", t)))
        series["wind_mph"].append(_r(latest_at_or_before("wspd", t), 0))
        series["gust_mph"].append(_r(latest_at_or_before("wgust", t), 0))
        series["wdir"].append(None)
        series["sky"].append(_r(latest_at_or_before("sky", t), 0))
        series["snowlvl_ft"].append(_r(sl, -2))
        series["snowlvl_p10"].append(None)
        series["snowlvl_p90"].append(None)
        series["p_snow"].append(_r(ps, 2))
        series["slr"].append(None)
        series["pop"].append(_r(pop, 2))

    # 6-h snow / QPF windows exactly as NDFD gives them (raw)
    W = {}
    for m in data.get("qpf", []):
        t, n = m["end"], m["minutes"] // 60
        q = float(m["values"][k])
        s = at("snow", t)
        if np.isnan(q):
            continue
        snow = 0.0 if (s is None or np.isnan(s)) else s
        W[t] = {"qpf": q, "snow": snow, "hours": n}
    precip = {"end": [t.strftime("%Y-%m-%dT%H:%MZ") for t in W], "hours": [w["hours"] for w in W.values()],
              "qpf_in": [_r(w["qpf"], 2) for w in W.values()], "snow_in": [_r(w["snow"], 1) for w in W.values()],
              "pop": [None] * len(W)}

    out_periods = []
    if times:
        first = times[0]
        start = first.replace(minute=0) - timedelta(hours=first.hour % 12) if first.hour % 12 else first.replace(minute=0)
        init = start
        hours = [int((t - init).total_seconds() // 3600) for t in times]
        for s, e in P.periods(init, hours):
            ws = [w for t, w in W.items() if init + timedelta(hours=s) < t <= init + timedelta(hours=e)]
            if not ws or sum(w["hours"] for w in ws) < (e - s):
                continue
            q = sum(w["qpf"] for w in ws)
            snow = sum(w["snow"] for w in ws)
            t0, t1 = init + timedelta(hours=s), init + timedelta(hours=e)
            temps_p = [series["t_f"][i] for i, t in enumerate(times) if t0 < t <= t1 and series["t_f"][i] is not None]
            gusts = [series["gust_mph"][i] for i, t in enumerate(times) if t0 < t <= t1 and series["gust_mph"][i] is not None]
            sls = [series["snowlvl_ft"][i] for i, t in enumerate(times) if t0 < t <= t1 and series["snowlvl_ft"][i] is not None]
            pops = [float(m["values"][k]) / 100 for m in data.get("pop12", []) if t0 < m["end"] <= t1 + timedelta(hours=6)]
            out_periods.append({**P.period_label(init, s, e, tz), "snow_in": _r(snow, 1), "snow_lo": None, "snow_hi": None,
                                "extended": False, "qpf_in": _r(q, 2), "qpf_lo": None, "qpf_hi": None,
                                "p_snow": None, "type": ndfd_type(q, snow), "range": None,
                                "pop": _r(max(pops), 2) if pops else None, "slr": None, "powder": None,
                                "t_max_f": _r(max(temps_p)) if temps_p else None, "t_min_f": _r(min(temps_p)) if temps_p else None,
                                "gust_max_mph": _r(max(gusts), 0) if gusts else None,
                                "snowlvl_min_ft": _r(min(sls), -2) if sls else None})
    totals = {}
    if W:
        t0 = min(t - timedelta(hours=w["hours"]) for t, w in W.items())
        for name, h in (("24h", 24), ("72h", 72)):
            ws = [w for t, w in W.items() if t <= t0 + timedelta(hours=h)]
            if sum(w["hours"] for w in ws) < h:
                continue
            q = sum(w["qpf"] for w in ws)
            snow = sum(w["snow"] for w in ws)
            totals[name] = {"snow_in": _r(snow, 1), "snow_lo": None, "snow_hi": None, "qpf_in": _r(q, 2),
                            "qpf_lo": None, "qpf_hi": None, "p_snow": None, "extended": False, "range": None}
    return [t.strftime("%Y-%m-%dT%H:%MZ") for t in times], {"series": series, "precip": precip,
                                                            "periods": out_periods, "totals": totals}


def forecast_points(repo: Path = REPO_ROOT) -> list[dict]:
    """[{id, tz, points: {key: {lat, lon, elev_ft}}}] for ski areas and SNOTEL sites."""
    out = []
    cat = json.loads((repo / "data" / "ski_areas.json").read_text(encoding="utf-8"))
    for a in cat["areas"]:
        out.append({"id": a["id"], "tz": a.get("tz"), "points": {k: {"lat": a[k]["lat"], "lon": a[k]["lon"],
                                                                     "elev_ft": a[k]["elev_ft"],
                                                                     "grid_elev_ft": a["nbm_grid"][k].get("elev_ft")}
                                                                 for k in ("summit", "base")}})
    sp = repo / "data" / "snotel_points.json"
    if sp.exists():
        for s in json.loads(sp.read_text(encoding="utf-8"))["points"]:
            out.append({"id": s["id"], "tz": s.get("tz"), "points": {"point": {"lat": s["lat"], "lon": s["lon"],
                                                                               "elev_ft": s["elev_ft"],
                                                                               "grid_elev_ft": s["nbm_grid"].get("elev_ft")}}})
    return out


def run(cfg: dict, session, out: Path, *, published: str | None = None, github_output: str | None = None) -> int:
    def emit(**kv):
        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                for k2, v in kv.items():
                    f.write(f"{k2}={v}\n")

    key, modified = latest_key(session)
    if key is None:
        log.warning("NDFD not reachable")
        emit(new="false")
        return 0
    from .version import stamp
    tag = stamp(key, "ndfd")
    if published == tag:
        log.info("NDFD %s already published; nothing new", tag)
        emit(new="false", cycle=tag)
        return 0
    pts = forecast_points()
    flat = [(pid, k, p["lat"], p["lon"]) for f in pts for k, p in [(kk, f["points"][kk]) for kk in f["points"]]
            for pid in [f["id"]]]
    t0 = time.time()
    data, grid = fetch_all(session, [(la, lo) for _, _, la, lo in flat], CACHE / key)
    issued = min(m["ref"] for msgs in data.values() for m in msgs)
    log.info("NDFD %s: %d elements, %d points, fetch+decode %.0f s", key, len(data), len(flat), time.time() - t0)
    col = {(pid, k): n for n, (pid, k, _, _) in enumerate(flat)}
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.json"):
        old.unlink()
    generated = utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    sizes = []
    for f in pts:
        tz = ZoneInfo(f.get("tz") or "America/Denver")
        doc = {"id": f["id"], "source": SOURCE, "issued": issued.strftime("%Y-%m-%dT%H:%MZ"),
               "generated_at": generated, "points": {}}
        for k, p in f["points"].items():
            times, fc = point_doc(data, col[(f["id"], k)], p["elev_ft"], tz)
            doc["times"] = times
            doc["points"][k] = {"elev_ft": p["elev_ft"], "grid_elev_ft": p.get("grid_elev_ft"), "raw": True, **fc}
        path = out / f"{f['id']}.json"
        write_json(path, doc)
        sizes.append(path.stat().st_size)
    write_json(out / "index.json", {"key": key, "issued": issued.strftime("%Y-%m-%dT%H:%MZ"),
                                    "generated_at": generated, "source": SOURCE, "count": len(pts)})
    log.info("NDFD %s: wrote %d files (max %.0f KB, total %.1f MB)", key, len(sizes), max(sizes) / 1024, sum(sizes) / 1e6)
    emit(new="true", cycle=tag)
    return 0
