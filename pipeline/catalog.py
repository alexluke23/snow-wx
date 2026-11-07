"""Ski-area catalog (PLAN.md §5.1): OpenSkiMap areas + lifts -> data/ski_areas.json.

Run on demand (`python -m pipeline catalog`), not hourly. Base/summit come from
lift terminals (lowest bottom / highest top of the area's operating lifts),
elevations from USGS 3DEP, cross-checked against OpenSkiMap's own elevations.
Joins: region, time zone, avalanche zone, nearest SNOTEL/ASOS, NWS grid, NBM grid.

External lookups (3DEP, api.weather.gov) are cached in data_cache/catalog/ so a
re-run only asks for points it has not seen.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import requests
import yaml

from .common import REPO_ROOT, utcnow, write_json

log = logging.getLogger("snow-wx.catalog")

CATALOG_CONFIG = REPO_ROOT / "config" / "ski_areas.yml"
CACHE = REPO_ROOT / "data_cache" / "catalog"
OUT = REPO_ROOT / "data" / "ski_areas.json"
M_TO_FT = 3.28084


def load_catalog_config(path=None) -> dict:
    with open(path or CATALOG_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------- pure helpers

def area_state(props: dict, states: list[str]) -> str | None:
    for pl in props.get("places") or []:
        code = (pl.get("iso3166_2") or "")
        if code.startswith("US-") and code[3:] in states:
            return code[3:]
    return None


def lift_vertical_ft(props: dict) -> float:
    lifts = (props.get("statistics") or {}).get("lifts") or {}
    lo, hi = lifts.get("minElevation"), lifts.get("maxElevation")
    return (hi - lo) * M_TO_FT if lo is not None and hi is not None else 0.0


def run_length_km(props: dict) -> float:
    runs = ((props.get("statistics") or {}).get("runs") or {}).get("byActivity") or {}
    by = (runs.get("downhill") or {}).get("byDifficulty") or {}
    return sum((v or {}).get("lengthInKm") or 0.0 for v in by.values())


def _matches(props: dict, names: list[str]) -> bool:
    keys = {str(props.get("name") or "").lower(), str(props.get("id") or "").lower()}
    return any(str(n).lower() in keys for n in names or [])


def select_areas(features: list[dict], ccfg: dict) -> list[dict]:
    """Western, operating, downhill areas with lifts and enough vertical; config
    include/exclude applied; same-name duplicates collapsed to the bigger one."""
    states = ccfg["states"]
    picked: dict[tuple, dict] = {}
    for f in features:
        p = f.get("properties") or {}
        st = area_state(p, states)
        if not st or not p.get("name"):
            continue
        forced = _matches(p, ccfg.get("include"))
        if _matches(p, ccfg.get("exclude")):
            continue
        if not forced:
            if p.get("status") != "operating" or "downhill" not in (p.get("activities") or []):
                continue
            if lift_vertical_ft(p) < ccfg.get("min_vertical_ft", 0):
                continue
        key = (p["name"].strip().lower(), st)
        rec = {"props": p, "state": st, "geometry": f.get("geometry")}
        old = picked.get(key)
        if old is None or lift_vertical_ft(p) > lift_vertical_ft(old["props"]):
            picked[key] = rec
    return list(picked.values())


def lift_terminals(lift_features: list[dict], area_ids: set[str]) -> dict[str, list[dict]]:
    """area id -> [{name, type, bottom: (lon, lat, z_m|None), top: (...)}] for operating lifts."""
    out: dict[str, list[dict]] = {}
    for f in lift_features:
        p = f.get("properties") or {}
        if p.get("status") not in (None, "operating"):
            continue
        g = f.get("geometry") or {}
        coords = g.get("coordinates") or []
        if g.get("type") == "MultiLineString":
            coords = [c for part in coords for c in part]
        if g.get("type") not in ("LineString", "MultiLineString") or len(coords) < 2:
            continue
        a, b = coords[0], coords[-1]
        za, zb = (a[2] if len(a) > 2 else None), (b[2] if len(b) > 2 else None)
        if za is not None and zb is not None and za > zb:
            a, b, za, zb = b, a, zb, za
        term = {"name": p.get("name"), "type": p.get("liftType"),
                "bottom": (a[0], a[1], za), "top": (b[0], b[1], zb)}
        for sa in p.get("skiAreas") or []:
            sid = (sa.get("properties") or {}).get("id")
            if sid in area_ids:
                out.setdefault(sid, []).append(term)
    return out


def base_summit(terms: list[dict], runs_min_m: float | None, drop_m: float):
    """Lowest bottom terminal (ignoring transport lifts that start far below the
    lowest run) and highest top terminal. Returns (base, summit, n_lifts) with
    points as (lon, lat, z_m) or None when there are no terminals with z."""
    with_z = [t for t in terms if t["bottom"][2] is not None and t["top"][2] is not None]
    if not with_z:
        return None, None, len(terms)
    ski = with_z
    if runs_min_m is not None:
        ski = [t for t in with_z if t["bottom"][2] >= runs_min_m - drop_m] or with_z
    base = min((t["bottom"] for t in ski), key=lambda p: p[2])
    summit = max((t["top"] for t in with_z), key=lambda p: p[2])
    return base, summit, len(terms)


def slugify(name: str, state: str, taken: set[str]) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "area"
    slug = s if s not in taken else f"{s}-{state.lower()}"
    n = 2
    while slug in taken:
        slug, n = f"{s}-{state.lower()}-{n}", n + 1
    taken.add(slug)
    return slug


def region_for(lon: float, lat: float, state: str, ccfg: dict) -> str:
    for r in ccfg.get("regions") or []:
        w, e, s, n = r["box"]
        if w <= lon <= e and s <= lat <= n:
            return r["name"]
    return (ccfg.get("state_names") or {}).get(state, state)


def haversine_km(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def nearest(stations: list[dict], lat: float, lon: float, count: int, max_km: float) -> list[dict]:
    """stations: [{id, name, lat, lon, elev_ft}] -> nearest `count` within max_km."""
    scored = [(haversine_km(lat, lon, s["lat"], s["lon"]), s) for s in stations]
    scored = sorted((d, s) for d, s in scored if d <= max_km) if scored else []
    return [{**{k: s[k] for k in ("id", "name", "elev_ft") if k in s}, "dist_km": round(d, 1)}
            for d, s in scored[:count]]


def zone_for(lon: float, lat: float, zones: list[tuple]) -> dict | None:
    """zones: [(shapely geometry, info dict)] -> info of the zone containing the point."""
    from shapely.geometry import Point
    pt = Point(lon, lat)
    for geom, info in zones:
        if geom.contains(pt):
            return info
    return None


def verify(dem_ft: float | None, osm_ft: float | None, tol_ft: float) -> tuple[str, str]:
    """('ok'|'dem-only'|'mismatch'|'no-dem', note)."""
    if dem_ft is None:
        return "no-dem", "3DEP returned no value"
    if osm_ft is None:
        return "dem-only", "no OpenSkiMap elevation to compare"
    diff = dem_ft - osm_ft
    if abs(diff) > tol_ft:
        return "mismatch", f"3DEP {dem_ft:.0f} ft vs OpenSkiMap {osm_ft:.0f} ft ({diff:+.0f})"
    return "ok", ""


# NBM / NDFD 2.5-km CONUS Lambert conformal grid -------------------------------

def nbm_proj(g: dict):
    from pyproj import Proj
    return Proj(proj="lcc", lat_1=g["latin1"], lat_2=g["latin2"], lat_0=g["lad"],
                lon_0=g["lov"], R=g["radius"])


def lcc_ij(lat: float, lon: float, g: dict) -> tuple[int, int]:
    """Nearest (i, j) on the grid; i along x (Nx), j along y (Ny), j=0 at the
    first (southern) row when the grid scans +j (NBM does)."""
    p = nbm_proj(g)
    x0, y0 = p(g["lon1"], g["lat1"])
    x, y = p(lon, lat)
    i = int(round((x - x0) / g["dx"]))
    j = int(round((y - y0) / g["dy"]))
    if not (0 <= i < g["nx"] and 0 <= j < g["ny"]):
        raise ValueError(f"({lat}, {lon}) is outside the NBM grid")
    return i, j


def cell_envelope(i: int, j: int, g: dict) -> tuple[float, float, float, float]:
    """lon/lat envelope (xmin, ymin, xmax, ymax) of grid cell (i, j)."""
    p = nbm_proj(g)
    x0, y0 = p(g["lon1"], g["lat1"])
    xs = [x0 + (i + di) * g["dx"] for di in (-0.5, 0.5)]
    ys = [y0 + (j + dj) * g["dy"] for dj in (-0.5, 0.5)]
    lons, lats = zip(*[p(x, y, inverse=True) for x in xs for y in ys])
    return min(lons), min(lats), max(lons), max(lats)


# ---------------------------------------------------------------- fetch helpers

class JsonCache:
    """Tiny persistent dict for slow lookups (3DEP, NWS)."""

    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data), encoding="utf-8")


def _key(lat, lon) -> str:
    return f"{lat:.5f},{lon:.5f}"


def download_openskimap(session, ccfg: dict, refresh: bool = False) -> tuple[list, list]:
    out = []
    for kind in ("ski_areas", "lifts"):
        path = REPO_ROOT / "data_cache" / "openskimap" / f"{kind}.geojson"
        if refresh or not path.exists():
            log.info("downloading OpenSkiMap %s", kind)
            r = session.get(ccfg["source"][kind], timeout=600)
            r.raise_for_status()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
        with open(path, encoding="utf-8") as f:
            out.append(json.load(f)["features"])
    return out[0], out[1]


def _get_json(session, url, *, attempts=4, **kw):
    for i in range(attempts):
        try:
            r = session.get(url, timeout=90, **kw)
            if r.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            if i == attempts - 1:
                raise
            log.debug("retry %s: %s", url[:80], e)
            time.sleep(3 * (i + 1))


def dem_elevations(session, ccfg, points: list[tuple[float, float]], cache: JsonCache,
                   batch: int = 8, workers: int = 6) -> dict[str, float | None]:
    """(lat, lon) -> 3DEP elevation (ft); batched getSamples requests.

    3DEP answers at roughly one point per second whatever the batch size, so
    batches stay small (no timeouts) and run in parallel; the cache is saved as
    batches finish so an interrupted run resumes."""
    todo = sorted({_key(la, lo) for la, lo in points} - set(cache.data))

    def one(keys):
        pts = [[float(k.split(",")[1]), float(k.split(",")[0])] for k in keys]
        geom = json.dumps({"points": pts, "spatialReference": {"wkid": 4326}})
        js = _get_json(session, ccfg["services"]["dem_samples"],
                       params={"geometry": geom, "geometryType": "esriGeometryMultipoint",
                               "returnFirstValueOnly": "true", "f": "json"})
        res = {}
        for s in js.get("samples") or []:
            k = keys[s["locationId"]]
            try:
                v = float(s["value"])
                res[k] = None if v < -1000 else round(v * M_TO_FT, 1)
            except (TypeError, ValueError):
                res[k] = None
        return res

    chunks = [todo[i:i + batch] for i in range(0, len(todo), batch)]
    log.info("3DEP samples: %d new points in %d requests", len(todo), len(chunks))
    with ThreadPoolExecutor(workers) as ex:
        for n, res in enumerate(ex.map(one, chunks), 1):
            cache.data.update(res)
            if n % 10 == 0:
                cache.save()
                log.info("3DEP samples: %d/%d requests", n, len(chunks))
    cache.save()
    return {_key(la, lo): cache.data.get(_key(la, lo)) for la, lo in points}


def dem_cell_mean(session, ccfg, envs: dict[str, tuple], cache: JsonCache, workers: int = 4) -> dict:
    """key -> mean 3DEP elevation (ft) over a lon/lat envelope."""
    todo = [k for k in envs if k not in cache.data]

    def one(k):
        xmin, ymin, xmax, ymax = envs[k]
        geom = json.dumps({"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax,
                           "spatialReference": {"wkid": 4326}})
        js = _get_json(session, ccfg["services"]["dem_stats"],
                       params={"geometry": geom, "geometryType": "esriGeometryEnvelope",
                               "pixelSize": json.dumps({"x": 90, "y": 90,
                                                        "spatialReference": {"wkid": 3857}}),
                               "f": "json"})
        st = (js.get("statistics") or [{}])[0]
        return k, (round(st["mean"] * M_TO_FT, 1) if "mean" in st else None)

    log.info("3DEP cell means: %d new cells", len(todo))
    with ThreadPoolExecutor(workers) as ex:
        for n, (k, v) in enumerate(ex.map(one, todo), 1):
            cache.data[k] = v
            if n % 25 == 0:
                cache.save()
                log.info("3DEP cell means: %d/%d", n, len(todo))
    cache.save()
    return {k: cache.data.get(k) for k in envs}


def nws_points(session, ccfg, points: list[tuple[float, float]], cache: JsonCache,
               workers: int = 4) -> dict[str, dict | None]:
    todo = sorted({_key(la, lo) for la, lo in points} - set(cache.data))

    def one(k):
        la, lo = map(float, k.split(","))
        try:
            js = _get_json(session, ccfg["services"]["nws_points"].format(lat=la, lon=lo),
                           headers={"Accept": "application/geo+json"})
        except requests.RequestException as e:
            log.warning("NWS points %s failed: %s", k, e)
            return k, None
        p = js.get("properties") or {}
        return k, {"wfo": p.get("gridId"), "x": p.get("gridX"), "y": p.get("gridY"),
                   "tz": p.get("timeZone"),
                   "zone": (p.get("forecastZone") or "").rsplit("/", 1)[-1] or None}

    log.info("NWS points: %d new lookups", len(todo))
    with ThreadPoolExecutor(workers) as ex:
        for k, v in ex.map(one, todo):
            if v is not None:
                cache.data[k] = v
    cache.save()
    return {_key(la, lo): cache.data.get(_key(la, lo)) for la, lo in points}


def nbm_grid(session, ccfg, cache_path: Path = CACHE / "nbm_grid.json") -> dict:
    """Grid definition from one byte-ranged NBM message (cached)."""
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    import eccodes  # pipeline/__init__ has already put the ecCodes DLL on PATH
    now = utcnow()
    for back in range(3, 30):
        t = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=back)
        url = ccfg["services"]["nbm_grid_idx"].format(date=t.strftime("%Y%m%d"), hh=t.strftime("%H"))
        r = session.get(url, timeout=60)
        if r.ok:
            break
    else:
        raise RuntimeError("no recent NBM cycle found")
    lines = r.text.splitlines()
    k = next(i for i, ln in enumerate(lines) if ":TMP:2 m above ground:" in ln)
    start, end = int(lines[k].split(":")[1]), int(lines[k + 1].split(":")[1]) - 1
    msg = session.get(url[:-4], headers={"Range": f"bytes={start}-{end}"}, timeout=120).content
    h = eccodes.codes_new_from_message(msg)
    try:
        get = lambda key: eccodes.codes_get(h, key)  # noqa: E731
        g = {"nx": get("Nx"), "ny": get("Ny"), "lad": get("LaDInDegrees"), "lov": get("LoVInDegrees"),
             "latin1": get("Latin1InDegrees"), "latin2": get("Latin2InDegrees"),
             "lat1": get("latitudeOfFirstGridPointInDegrees"),
             "lon1": get("longitudeOfFirstGridPointInDegrees"),
             "dx": get("DxInMetres"), "dy": get("DyInMetres"),
             "radius": get("radius") if get("shapeOfTheEarth") in (0, 1) else 6371229.0,
             "j_positive": get("jScansPositively"), "source": url[:-4]}
        if g["lov"] > 180:
            g["lov"] -= 360
        if g["lon1"] > 180:
            g["lon1"] -= 360
    finally:
        eccodes.codes_release(h)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(g, indent=1), encoding="utf-8")
    return g


def load_stations(obs_dir: Path) -> tuple[list[dict], list[dict]]:
    def read(name):
        path = obs_dir / f"{name}.geojson"
        if not path.exists():
            raise FileNotFoundError(f"{path} missing: run `python -m pipeline build` (or obs) first")
        return json.loads(path.read_text(encoding="utf-8"))["features"]
    snotel = [{"id": f["properties"]["triplet"], "name": f["properties"]["name"],
               "lat": f["geometry"]["coordinates"][1], "lon": f["geometry"]["coordinates"][0],
               "elev_ft": f["properties"].get("elev_ft")} for f in read("snotel")]
    asos = [{"id": f["properties"]["id"], "name": f["properties"]["name"],
             "lat": f["geometry"]["coordinates"][1], "lon": f["geometry"]["coordinates"][0],
             "elev_m": f["properties"].get("elev_m")} for f in read("asos")]
    return snotel, asos


def load_zones(session, url: str, states: list[str]) -> list[tuple]:
    from shapely.geometry import shape
    js = _get_json(session, url)
    zones = []
    for f in js.get("features") or []:
        p = f.get("properties") or {}
        if p.get("state") not in states or not f.get("geometry"):
            continue
        zones.append((shape(f["geometry"]), {"zone_id": f.get("id"), "zone": p.get("name"),
                                             "center_id": p.get("center_id")}))
    return zones


# ---------------------------------------------------------------- build

def _pt(lon, lat, elev_ft):
    return {"lat": round(lat, 5), "lon": round(lon, 5), "elev_ft": None if elev_ft is None else round(elev_ft)}


def build_catalog(session, cfg: dict, ccfg: dict, obs_dir: Path, refresh: bool = False):
    from .avalanche import MAP_LAYER
    areas_fc, lifts_fc = download_openskimap(session, ccfg, refresh)
    areas = select_areas(areas_fc, ccfg)
    terms = lift_terminals(lifts_fc, {a["props"]["id"] for a in areas})
    del lifts_fc
    log.info("selected %d areas, %d with lift terminals", len(areas), len(terms))

    drop = ccfg.get("transport_drop_m", 60)
    rows = []
    for a in areas:
        p = a["props"]
        runs = (p.get("statistics") or {}).get("runs") or {}
        ov = (ccfg.get("overrides") or {}).get(p["name"], {})
        skip = {str(x).lower() for x in ov.get("exclude_lifts") or []}
        mine = [t for t in terms.get(p["id"], []) if str(t["name"] or "").lower() not in skip]
        base, summit, n = base_summit(mine, runs.get("minElevation"), drop)
        if "base" in ov:
            base = (ov["base"]["lon"], ov["base"]["lat"], None)
        if "summit" in ov:
            summit = (ov["summit"]["lon"], ov["summit"]["lat"], None)
        rows.append({"a": a, "p": p, "ov": ov, "base": base, "summit": summit, "lifts": n,
                     "runs_km": run_length_km(p)})
    missing = [r["p"]["name"] for r in rows if r["base"] is None]
    rows = [r for r in rows if r["base"] is not None]

    CACHE.mkdir(parents=True, exist_ok=True)
    dem_cache = JsonCache(CACHE / "dem_points.json")
    pts = [(r[k][1], r[k][0]) for r in rows for k in ("base", "summit")]
    dem = dem_elevations(session, ccfg, pts, dem_cache)
    snotel, asos = load_stations(obs_dir)
    for s in snotel:
        s["elev_ft"] = None if s["elev_ft"] in (None, "None") else round(float(s["elev_ft"]))
    # ASOS elevations are missing from the obs feed: DEM only the stations we use.
    acfg = ccfg["nearest"]["asos"]
    used = {n["id"] for r in rows for n in nearest(asos, r["base"][1], r["base"][0], **acfg)}
    asos = [s for s in asos if s["id"] in used]
    need = [(s["lat"], s["lon"]) for s in asos if s.get("elev_m") in (None, "None")]
    dem_asos = dem_elevations(session, ccfg, need, dem_cache) if need else {}
    for s in asos:
        s["elev_ft"] = (dem_asos.get(_key(s["lat"], s["lon"])) if s.get("elev_m") in (None, "None")
                        else round(float(s["elev_m"]) * M_TO_FT))
        if s["elev_ft"] is not None:
            s["elev_ft"] = round(s["elev_ft"])

    nws = nws_points(session, ccfg, pts, JsonCache(CACHE / "nws_points.json"))
    grid = nbm_grid(session, ccfg)
    envs, ij = {}, {}
    for r in rows:
        for k in ("base", "summit"):
            lon, lat = r[k][0], r[k][1]
            i, j = lcc_ij(lat, lon, grid)
            ij[(r["p"]["id"], k)] = (i, j)
            envs[f"{i},{j}"] = cell_envelope(i, j, grid)
    cell_elev = dem_cell_mean(session, ccfg, envs, JsonCache(CACHE / "dem_cells.json"))
    zones = load_zones(session, MAP_LAYER, ccfg["states"])

    tol = ccfg.get("verify_tolerance_ft", 150)
    major_ids = {r["p"]["id"] for r in sorted(rows, key=lambda r: -r["runs_km"])[: ccfg.get("major_count", 60)]}
    taken: set[str] = set()
    out, report = [], []
    for r in sorted(rows, key=lambda r: (r["a"]["state"], r["ov"].get("name", r["p"]["name"]))):
        p, st = r["p"], r["a"]["state"]
        name = r["ov"].get("name", p["name"])
        pts_out, checks = {}, {}
        for k in ("base", "summit"):
            lon, lat, z = r[k]
            dem_ft = dem.get(_key(lat, lon))
            osm_ft = None if z is None else z * M_TO_FT
            status, note = verify(dem_ft, osm_ft, tol)
            checks[k] = {"status": status, "dem_ft": dem_ft, "osm_ft": None if osm_ft is None else round(osm_ft),
                         "note": note}
            pts_out[k] = _pt(lon, lat, dem_ft if dem_ft is not None else osm_ft)
        vert = (pts_out["summit"]["elev_ft"] or 0) - (pts_out["base"]["elev_ft"] or 0)
        status = "ok"
        if any(c["status"] in ("mismatch", "no-dem") for c in checks.values()) or vert <= 0:
            status = "review"
        elif any(c["status"] == "dem-only" for c in checks.values()):
            status = "dem-only"
        sb, ss = nws.get(_key(r["base"][1], r["base"][0])), nws.get(_key(r["summit"][1], r["summit"][0]))
        mid_lat = (r["base"][1] + r["summit"][1]) / 2
        mid_lon = (r["base"][0] + r["summit"][0]) / 2
        tz = (ss or sb or {}).get("tz") or ccfg["state_tz"][st]
        zone = zone_for(r["summit"][0], r["summit"][1], zones) or zone_for(r["base"][0], r["base"][1], zones)
        near_s = nearest(snotel, mid_lat, mid_lon, **ccfg["nearest"]["snotel"])
        near_a = nearest(asos, r["base"][1], r["base"][0], **ccfg["nearest"]["asos"])
        for s in near_s + near_a:
            if s.get("elev_ft") is not None and pts_out["base"]["elev_ft"] is not None:
                s["dz_base_ft"] = round(s["elev_ft"] - pts_out["base"]["elev_ft"])
        nbm = {}
        for k in ("base", "summit"):
            i, j = ij[(p["id"], k)]
            nbm[k] = {"i": i, "j": j, "elev_ft": None if cell_elev.get(f"{i},{j}") is None
                      else round(cell_elev[f"{i},{j}"])}
        rec = {
            "id": slugify(name, st, taken),
            "name": name,
            "state": st,
            "region": r["ov"].get("region") or region_for(r["summit"][0], r["summit"][1], st, ccfg),
            "tz": tz,
            "url": r["ov"].get("url") or ((p.get("websites") or [None])[0]),
            "major": p["id"] in major_ids,
            "base": pts_out["base"],
            "summit": pts_out["summit"],
            "vertical_ft": vert,
            "lifts": r["lifts"],
            "runs_km": round(r["runs_km"], 1),
            "avalanche": zone,
            "nearest": {"snotel": near_s, "asos": near_a},
            "nws": {k: (None if v is None else {"wfo": v["wfo"], "x": v["x"], "y": v["y"], "zone": v.get("zone")})
                    for k, v in (("base", sb), ("summit", ss))},
            "nbm_grid": nbm,
            "verify": status,
            "osm_id": p["id"],
        }
        out.append(rec)
        report.append({"id": rec["id"], "name": name, "state": st, "region": rec["region"],
                       "major": rec["major"], "lifts": r["lifts"], "verify": status,
                       "base_ft": pts_out["base"]["elev_ft"], "base_osm_ft": checks["base"]["osm_ft"],
                       "summit_ft": pts_out["summit"]["elev_ft"], "summit_osm_ft": checks["summit"]["osm_ft"],
                       "vertical_ft": vert,
                       "notes": "; ".join(f"{k}: {c['note']}" for k, c in checks.items() if c["note"])})
    return out, report, missing, grid


def run(cfg: dict, session, out: Path = OUT, obs_dir: Path | None = None, refresh: bool = False,
        ccfg: dict | None = None) -> int:
    ccfg = ccfg or load_catalog_config()
    areas, report, missing, grid = build_catalog(session, cfg, ccfg, obs_dir or REPO_ROOT / "build" / "data", refresh)
    doc = {"generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
           "attribution": ccfg["source"]["attribution"] + "; elevations USGS 3DEP",
           "license": "ODbL-1.0 (derived from OpenStreetMap / OpenSkiMap)",
           "count": len(areas),
           # NBM/NDFD 2.5-km grid used for nbm_grid i/j (points pipeline reads it from here)
           "nbm_grid": {k: v for k, v in grid.items() if k != "source"},
           "areas": areas}
    write_json(out, doc, ndigits=6)   # coordinates + grid definition need the precision
    rpt = out.with_name("ski_areas_verify.csv")
    with open(rpt, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(report[0]))
        w.writeheader()
        w.writerows(report)
    n_ok = sum(a["verify"] == "ok" for a in areas)
    log.info("wrote %s: %d areas (%d major), verify ok %d, dem-only %d, review %d; no lifts with z: %s",
             out, len(areas), sum(a["major"] for a in areas), n_ok,
             sum(a["verify"] == "dem-only" for a in areas), sum(a["verify"] == "review" for a in areas),
             ", ".join(missing) or "none")
    return 0
