"""Sno-Parks & winter recreation points (PLAN.md §5.6, M4.5): data/rec_points.json.

    python -m pipeline catalog --rec      (on demand; slow lookups cached in data_cache/catalog)

Sources (owner-approved S7, docs/sources_recreation.md):
- USFS EDW Recreation Sites (public domain): SNOWPARK, SNOWPLAY AREA, SKI AREA NORDIC, and
  TRAILHEADs whose name says Sno-Park / ski / nordic / snowmobile / snowshoe / sled.
- OpenStreetMap (ODbL) gap fill: features named Sno-Park / Snow Park / Park N' Ski, parking
  with snowmobile=yes|designated, trailheads with ski=*; dropped when an EDW site is within
  0.4 km (or 1.5 km with a matching name). Ski-resort terrain parks are excluded.
State Sno-Park lists are never copied (hand checks only).

Each record has the ski-area shape so the forecast, NDFD, Powder Finder and archive code
work unchanged: "base" = the trailhead, "summit" = "high terrain" = the highest 3DEP point
within 5 km (labelled as such on the site). Elevations: USGS 3DEP; NBM cell elevation = full
3DEP cell average (owner decision).
"""

from __future__ import annotations

import io
import json
import logging
import math
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from .catalog import (CACHE, JsonCache, M_TO_FT, _get_json, _key, cell_envelope, dem_cell_mean, dem_elevations,
                      haversine_km, lcc_ij, load_stations, load_zones, nbm_grid, nearest, nws_points, region_for,
                      slugify, state_tz, zone_for)
from .common import REPO_ROOT, utcnow, write_json

log = logging.getLogger("snow-wx.rec")
OUT = REPO_ROOT / "data" / "rec_points.json"
EDW = "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_RecInfraRecreationSites_02/MapServer/0/query"
OVERPASS = "https://overpass-api.de/api/interpreter"
EDW_TYPES = ("SNOWPARK", "SNOWPLAY AREA", "SKI AREA NORDIC", "TRAILHEAD")
WINTER_WORDS = re.compile(r"sno-?\s?park|snow\s?park|park\s?n'?\s?ski|nordic|x-?country|cross[- ]country|ski|snowmobile|snowshoe|sled|tubing|snowplay|snow play", re.I)
NOT_REC = re.compile(r"terrain park|skate|dog park|water ?park|rv park|mobile home|trailer park|industrial|business park", re.I)
STATE_PROGRAMS = {"WA": "Washington Sno-Park permit (State Parks Winter Recreation)",
                  "OR": "Oregon Sno-Park permit (ODOT)",
                  "CA": "California SNO-PARK permit (State Parks OHMVR)",
                  "ID": "Idaho Park N' Ski permit (IDPR), where it is a Park N' Ski area"}
SUBTYPE_LABEL = {"snopark": "Sno-Park", "snowplay": "Snow play area", "nordic": "Nordic area", "trailhead": "Winter trailhead"}
HIGH_RADIUS_KM = 5.0


# ---------------------------------------------------------------- pure helpers

def title(name: str) -> str:
    """'DUTCHMAN FLAT' -> 'Dutchman Flat' (EDW names are upper case); keeps mixed-case names."""
    if name and name.isupper():
        small = {"and", "of", "the", "at", "on", "to", "in"}
        words = name.lower().split()
        name = " ".join(w if (i and w in small) else (w[:1].upper() + w[1:]) for i, w in enumerate(words))
        name = re.sub(r"\bSno-park\b", "Sno-Park", name)
    return name


def edw_site(a: dict) -> dict | None:
    """EDW attributes -> site, or None if it is not a winter recreation site."""
    t = (a.get("site_type") or "").upper()
    name = a.get("public_site_name") or a.get("site_name") or ""
    if t not in EDW_TYPES or not a.get("latitude") or not a.get("longitude"):
        return None
    if t == "TRAILHEAD" and not WINTER_WORDS.search(name):
        return None
    sub = {"SNOWPARK": "snopark", "SNOWPLAY AREA": "snowplay", "SKI AREA NORDIC": "nordic"}.get(t, "trailhead")
    acts = [x.strip().lower() for x in re.split(r"[|,]", a.get("activity_type_list") or "") if x.strip() and x.strip() != "No Data"]
    return {"name": title(name.strip()), "lat": float(a["latitude"]), "lon": float(a["longitude"]), "subtype": sub,
            "source": "usfs-edw", "source_id": str(a.get("site_cn") or a.get("site_id") or ""),
            "agency": "USDA Forest Service", "link": a.get("usda_portal_url") or None,
            "fee": a.get("fee_charged") == "Y", "passes": (a.get("passes") or "").strip() or None,
            "source_activities": acts}


def osm_site(e: dict) -> dict | None:
    t = e.get("tags") or {}
    lat = e.get("lat") or (e.get("center") or {}).get("lat")
    lon = e.get("lon") or (e.get("center") or {}).get("lon")
    name = t.get("name") or ""
    if lat is None or not name or NOT_REC.search(name) or t.get("piste:type") == "downhill":
        return None
    named = re.search(r"sno-?\s?park|snow\s?park|park\s?n'?\s?ski", name, re.I)
    if not (named or t.get("snowmobile") in ("yes", "designated") or t.get("ski") in ("yes", "designated", "nordic")):
        return None
    sub = "snopark" if named else ("nordic" if t.get("ski") else "trailhead")
    acts = []
    if t.get("snowmobile") in ("yes", "designated"):
        acts.append("snowmobiling")
    if t.get("piste:type") == "nordic" or t.get("ski"):
        acts.append("cross-country skiing")
    return {"name": name.strip(), "lat": float(lat), "lon": float(lon), "subtype": sub, "source": "osm",
            "source_id": f"{e.get('type', 'node')}/{e.get('id')}", "agency": t.get("operator") or None,
            "link": t.get("website") or None, "fee": t.get("fee") == "yes", "passes": None, "source_activities": acts}


def _tokens(name: str) -> set[str]:
    stop = {"sno", "park", "snopark", "snow", "the", "trailhead", "area", "sno-park", "parking", "lot", "nordic"}
    return {w for w in re.findall(r"[a-z]+", name.lower()) if w not in stop and len(w) > 2}


def dedupe(edw: list[dict], osm: list[dict], near_km: float = 0.4, name_km: float = 1.5) -> list[dict]:
    """EDW sites plus the OSM sites that no EDW site already covers; also merges EDW duplicates."""
    out: list[dict] = []
    for s in edw:
        if any(haversine_km(s["lat"], s["lon"], o["lat"], o["lon"]) < 0.15 for o in out):
            continue
        out.append(s)
    for s in osm:
        dup = False
        for o in out:
            d = haversine_km(s["lat"], s["lon"], o["lat"], o["lon"])
            if d < near_km or (d < name_km and _tokens(s["name"]) & _tokens(o["name"])):
                dup = True
                if o["source"] == "usfs-edw" and not o.get("link") and s.get("link"):
                    o["link"] = s["link"]
                break
        if not dup:
            out.append(s)
    return out


def activities(site: dict) -> tuple[list[str], bool]:
    """(activities, inferred?) from the source list, else from type and name."""
    acts = set()
    for a in site.get("source_activities") or []:
        if "snowmobil" in a or "snowcraft" in a or "ice & snow" in a:
            acts.add("snowmobiling")
        if "cross-country" in a or "nordic" in a:
            acts.add("cross-country skiing")
        if "snowshoe" in a:
            acts.add("snowshoeing")
        if "snow play" in a or "sled" in a or "tubing" in a:
            acts.add("sledding / snow play")
    if acts:
        return sorted(acts), False
    n = site["name"].lower()
    if site["subtype"] == "nordic" or re.search(r"nordic|x-?country|cross[- ]country|ski", n):
        acts.add("cross-country skiing")
    if site["subtype"] == "snowplay" or re.search(r"sled|tubing|snow ?play", n):
        acts.add("sledding / snow play")
    if "snowmobile" in n:
        acts.add("snowmobiling")
    if "snowshoe" in n:
        acts.add("snowshoeing")
    if not acts and site["subtype"] in ("snopark", "trailhead"):
        acts.update({"cross-country skiing", "snowshoeing"})     # typical Sno-Park use; marked inferred
    return sorted(acts), True


def permit_for(state: str | None, site: dict) -> str | None:
    if site.get("passes"):
        return site["passes"][:200]
    prog = STATE_PROGRAMS.get(state or "")
    if prog and site["subtype"] in ("snopark", "nordic", "trailhead"):
        return f"Likely: {prog}; check with the land manager"
    return "Fee site; check with the land manager" if site.get("fee") else None


def high_point(elev_m: np.ndarray, center: tuple[float, float], bbox: tuple[float, float, float, float],
               radius_km: float = HIGH_RADIUS_KM) -> tuple[float, float, float] | None:
    """Highest cell of a north-up raster over bbox (w, s, e, n) within radius of center -> (lat, lon, ft)."""
    a = np.asarray(elev_m, dtype="float64")
    ny, nx = a.shape
    w, s, e, n = bbox
    lats = n - (np.arange(ny) + 0.5) * (n - s) / ny
    lons = w + (np.arange(nx) + 0.5) * (e - w) / nx
    la, lo = np.meshgrid(lats, lons, indexing="ij")
    d = np.hypot((la - center[0]) * 111.0, (lo - center[1]) * 111.0 * math.cos(math.radians(center[0])))
    a = np.where((d <= radius_km) & np.isfinite(a) & (a > -1000), a, np.nan)
    if not np.isfinite(a).any():
        return None
    k = int(np.nanargmax(a))
    r, c = divmod(k, nx)
    return float(lats[r]), float(lons[c]), float(a[r, c] * M_TO_FT)


# ---------------------------------------------------------------- fetch

def fetch_edw(session, bbox) -> list[dict]:
    """Winter site types, plus trailheads whose name says winter (server-side filter: EDW has
    thousands of summer trailheads), paged in 1,000-record pages."""
    w, s, e, n = bbox
    words = ["SNO", "SNOW", "NORDIC", "SKI", "X-COUNTRY", "CROSS COUNTRY", "SNOWMOBILE", "SNOWSHOE", "SLED", "TUBING"]
    th = " OR ".join(f"UPPER(site_name) LIKE '%{x}%'" for x in words)
    where = f"site_type IN ('SNOWPARK','SNOWPLAY AREA','SKI AREA NORDIC') OR (site_type = 'TRAILHEAD' AND ({th}))"
    out, offset = [], 0
    while True:
        js = _get_json(session, EDW, params={
            "where": where, "geometry": json.dumps({"xmin": w, "ymin": s, "xmax": e, "ymax": n, "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryEnvelope", "inSR": 4326, "spatialRel": "esriSpatialRelIntersects",
            "outFields": "site_cn,site_id,site_name,public_site_name,site_type,activity_type_list,fee_charged,passes,usda_portal_url,latitude,longitude",
            "returnGeometry": "false", "f": "json", "resultOffset": offset, "resultRecordCount": 1000, "orderByFields": "objectid"})
        feats = js.get("features") or []
        out += [x for x in (edw_site(f["attributes"]) for f in feats) if x]
        if not js.get("exceededTransferLimit") or not feats:
            break
        offset += len(feats)
    return out


def fetch_osm(session, bbox) -> list[dict]:
    w, s, e, n = bbox
    b = f"({s},{w},{n},{e})"
    q = f"""[out:json][timeout:120];
( nwr["name"~"[Ss]no-?[ -]?[Pp]ark|[Ss]now[ -]?[Pp]ark|Park ?N'? ?Ski"]{b};
  nwr["amenity"="parking"]["snowmobile"~"^(yes|designated)$"]{b};
  nwr["highway"="trailhead"]["ski"~"^(yes|designated|nordic)$"]{b}; );
out tags center 2000;"""
    import time
    last = None
    for attempt, url in enumerate([OVERPASS, OVERPASS, "https://overpass.kumi.systems/api/interpreter", OVERPASS]):
        try:
            r = session.post(url, data={"data": q}, timeout=180)
            r.raise_for_status()
            return [x for x in (osm_site(e) for e in r.json().get("elements") or []) if x]
        except Exception as e:  # noqa: BLE001 - Overpass is often busy (429/502/504): retry, then a mirror
            last = e
            log.info("Overpass attempt %d failed: %s", attempt + 1, e)
            time.sleep(10 * (attempt + 1))
    raise RuntimeError(f"Overpass unavailable: {last}")


def high_terrain(session, ccfg, sites: list[dict], cache: JsonCache, workers: int = 6) -> dict:
    """key -> [lat, lon, ft] of the highest 3DEP point within 5 km (one 81 x 81 raster each)."""
    from PIL import Image
    url = ccfg["services"]["dem_samples"].rsplit("/", 1)[0] + "/exportImage"
    todo = [s for s in sites if _key(s["lat"], s["lon"]) not in cache.data]

    def one(s):
        lat, lon = s["lat"], s["lon"]
        dlat = HIGH_RADIUS_KM / 111.0
        dlon = HIGH_RADIUS_KM / (111.0 * math.cos(math.radians(lat)))
        bbox = (lon - dlon, lat - dlat, lon + dlon, lat + dlat)
        try:
            r = session.get(url, params={"bbox": ",".join(f"{v:.6f}" for v in bbox), "bboxSR": 4326, "imageSR": 4326,
                                         "size": "81,81", "format": "tiff", "pixelType": "F32",
                                         "interpolation": "RSP_BilinearInterpolation", "f": "image"}, timeout=120)
            r.raise_for_status()
            hp = high_point(np.array(Image.open(io.BytesIO(r.content)), dtype="float64"), (lat, lon), bbox)
        except Exception as e:  # noqa: BLE001 - one site failing must not stop the rest
            log.warning("high terrain %s: %s", s["name"], e)
            return None
        return _key(lat, lon), (None if hp is None else [round(hp[0], 5), round(hp[1], 5), round(hp[2])])

    log.info("high terrain: %d new rasters", len(todo))
    with ThreadPoolExecutor(workers) as ex:
        for n, res in enumerate(ex.map(one, todo), 1):
            if res:
                cache.data[res[0]] = res[1]
            if n % 25 == 0:
                cache.save()
                log.info("high terrain: %d/%d", n, len(todo))
    cache.save()
    return {_key(s["lat"], s["lon"]): cache.data.get(_key(s["lat"], s["lon"])) for s in sites}


# ---------------------------------------------------------------- build

def build_rec_points(session, cfg: dict, ccfg: dict, obs_dir: Path, out: Path = OUT, workers: int = 6) -> int:
    from .avalanche import MAP_LAYER
    bbox = cfg["region"]["bbox"]
    edw = fetch_edw(session, bbox)
    try:
        osm = fetch_osm(session, bbox)
    except Exception as e:  # noqa: BLE001 - EDW alone is still a catalog
        log.warning("OSM gap fill failed: %s", e)
        osm = []
    sites = dedupe(edw, osm)
    log.info("sites: %d EDW + %d OSM -> %d after de-duplication", len(edw), len(osm), len(sites))

    CACHE.mkdir(parents=True, exist_ok=True)
    nws = nws_points(session, ccfg, [(s["lat"], s["lon"]) for s in sites], JsonCache(CACHE / "nws_points.json"))
    # keep only points inside the 11 western states (state from the NWS forecast zone, e.g. WAZ522)
    states = set(ccfg["states"])
    keep = []
    for s in sites:
        z = (nws.get(_key(s["lat"], s["lon"])) or {}).get("zone") or ""
        s["state"] = z[:2] if len(z) >= 2 else None
        if s["state"] in states:
            keep.append(s)
    sites = keep
    dem = dem_elevations(session, ccfg, [(s["lat"], s["lon"]) for s in sites], JsonCache(CACHE / "dem_points.json"))
    high = high_terrain(session, ccfg, sites, JsonCache(CACHE / "rec_high.json"), workers=workers)
    hp_nws = nws_points(session, ccfg, [(h[0], h[1]) for h in high.values() if h], JsonCache(CACHE / "nws_points.json"))
    grid = nbm_grid(session, ccfg)
    envs, ij = {}, {}
    for s in sites:
        h = high.get(_key(s["lat"], s["lon"]))
        s["_hp"] = (h[0], h[1], h[2]) if h else (s["lat"], s["lon"], dem.get(_key(s["lat"], s["lon"])))
        for k, (la, lo) in (("base", (s["lat"], s["lon"])), ("summit", s["_hp"][:2])):
            i, j = lcc_ij(la, lo, grid)
            ij[(id(s), k)] = (i, j)
            envs[f"{i},{j}"] = cell_envelope(i, j, grid)
    # full 3DEP cell average (owner decision; slow once, cached in data_cache/catalog/dem_cells.json)
    cell_elev = dem_cell_mean(session, ccfg, envs, JsonCache(CACHE / "dem_cells.json"), workers=workers)
    zones = load_zones(session, MAP_LAYER, ccfg["states"])
    snotel, asos = load_stations(obs_dir)
    for st in snotel:
        st["elev_ft"] = None if st["elev_ft"] in (None, "None") else round(float(st["elev_ft"]))

    taken: set[str] = set()
    recs = []
    for s in sorted(sites, key=lambda x: (x["state"], x["name"])):
        st = s["state"]
        base_ft = dem.get(_key(s["lat"], s["lon"]))
        hla, hlo, hft = s["_hp"]
        nb, nh = nws.get(_key(s["lat"], s["lon"])), hp_nws.get(_key(hla, hlo)) or nws.get(_key(s["lat"], s["lon"]))
        acts, inferred = activities(s)
        near_s = nearest(snotel, s["lat"], s["lon"], **ccfg["nearest"]["snotel"])
        near_a = nearest(asos, s["lat"], s["lon"], **ccfg["nearest"]["asos"])
        nbm = {}
        for k in ("base", "summit"):
            i, j = ij[(id(s), k)]
            e = cell_elev.get(f"{i},{j}")
            nbm[k] = {"i": i, "j": j, "elev_ft": None if e is None else round(e)}
        rid = "sp-" + slugify(s["name"], st, taken)
        recs.append({
            "id": rid, "kind": "snopark", "subtype": s["subtype"], "type_label": SUBTYPE_LABEL[s["subtype"]],
            "name": s["name"], "state": st, "region": region_for(s["lon"], s["lat"], st, ccfg),
            "tz": (nb or {}).get("tz") or state_tz(st, s["lat"], ccfg),
            "url": s.get("link"), "major": False,
            "base": {"lat": round(s["lat"], 5), "lon": round(s["lon"], 5), "elev_ft": None if base_ft is None else round(base_ft)},
            "summit": {"lat": round(hla, 5), "lon": round(hlo, 5), "elev_ft": None if hft is None else round(hft)},
            "vertical_ft": None if base_ft is None or hft is None else round(hft - base_ft),
            "agency": s.get("agency"), "permit": permit_for(st, s), "activities": acts, "activities_inferred": inferred,
            "avalanche": zone_for(s["lon"], s["lat"], zones) or zone_for(hlo, hla, zones),
            "nearest": {"snotel": near_s, "asos": near_a},
            "nws": {k: (None if v is None else {"wfo": v["wfo"], "x": v["x"], "y": v["y"], "zone": v.get("zone"),
                                                "county": v.get("county")}) for k, v in (("base", nb), ("summit", nh))},
            "nbm_grid": nbm, "source": s["source"], "source_id": s["source_id"],
        })
    write_json(out, {"generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "source": "USDA Forest Service EDW Recreation Sites (public domain); OpenStreetMap contributors (ODbL); "
                               "elevations USGS 3DEP",
                     "license": "Database: ODbL 1.0 (contains OpenStreetMap data); USFS records public domain",
                     "count": len(recs), "by_source": {k: sum(r["source"] == k for r in recs) for k in ("usfs-edw", "osm")},
                     "areas": recs}, ndigits=6)
    log.info("wrote %s: %d winter recreation points", out, len(recs))
    return 0
