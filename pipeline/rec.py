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
REVIEW_CSV = REPO_ROOT / "data" / "rec_points_review.csv"
EDW = "https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_RecInfraRecreationSites_02/MapServer/0/query"
OVERPASS = "https://overpass-api.de/api/interpreter"
EDW_TYPES = ("SNOWPARK", "SNOWPLAY AREA", "SKI AREA NORDIC", "TRAILHEAD")
WINTER_WORDS = re.compile(r"sno-?\s?park|snow\s?park|park\s?n'?\s?ski|nordic|x-?country|cross[- ]country|ski|snowmobile|snowshoe|sled|tubing|snowplay|snow play", re.I)
NOT_REC = re.compile(r"terrain park|skate|dog park|water ?park|rv park|mobile home|trailer park|industrial|business park", re.I)
# Official programs to point to when the source states no permit (owner S8: link, never guess)
STATE_PROGRAMS = {"WA": ("Washington State Parks Sno-Park program", "https://parks.wa.gov/find-sno-parks"),
                  "OR": ("Oregon Sno-Park program (ODOT)", "https://www.oregon.gov/odot/maintenance/pages/sno-park-program.aspx"),
                  "CA": ("California SNO-PARK program (State Parks OHMVR)", "https://ohv.parks.ca.gov/?page_id=30701"),
                  "ID": ("Idaho Park N' Ski program (IDPR)", "https://parksandrecreation.idaho.gov/park-activity/cross-country-xc-skiing/")}
USFS_HOME = ("the managing national forest (USDA Forest Service)", "https://www.fs.usda.gov/")
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


def activities(site: dict) -> list[str]:
    """Activities only as the source states them (owner S8: no inferred list; motorized vs
    non-motorized mistakes matter). Empty when the source has none."""
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
    return sorted(acts)


def permit_for(site: dict) -> str | None:
    """Permit text only when the source states it (no guessing)."""
    return site["passes"][:200] if site.get("passes") else None


def permit_check(state: str | None, site: dict) -> dict:
    """Where to check parking permits when none is stated: the official state program,
    else the site's managing-agency page, else the Forest Service."""
    if state in STATE_PROGRAMS:
        name, url = STATE_PROGRAMS[state]
    elif site.get("link"):
        name, url = "the managing agency", site["link"]
    else:
        name, url = USFS_HOME
    return {"name": name, "url": url}


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
        acts = activities(s)
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
            "agency": s.get("agency"), "permit": permit_for(s), "permit_check": permit_check(st, s), "activities": acts,
            "avalanche": zone_for(s["lon"], s["lat"], zones) or zone_for(hlo, hla, zones),
            "nearest": {"snotel": near_s, "asos": near_a},
            "nws": {k: (None if v is None else {"wfo": v["wfo"], "x": v["x"], "y": v["y"], "zone": v.get("zone"),
                                                "county": v.get("county")}) for k, v in (("base", nb), ("summit", nh))},
            "nbm_grid": nbm, "source": s["source"], "source_id": s["source_id"],
        })
    recs, applied = apply_decisions(recs, read_decisions(REVIEW_CSV))       # owner decisions (keep / drop / merge); none = no change
    if applied["drop"] or applied["merge"]:
        log.info("owner review decisions applied: %d dropped, %d merged, %d kept", len(applied["drop"]), len(applied["merge"]), len(applied["keep"]))
    for w in applied["warnings"]:
        log.warning("owner review: %s", w)
    write_json(out, {"generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "source": "USDA Forest Service EDW Recreation Sites (public domain); OpenStreetMap contributors (ODbL); "
                               "elevations USGS 3DEP",
                     "license": "Database: ODbL 1.0 (contains OpenStreetMap data); USFS records public domain",
                     "count": len(recs), "by_source": {k: sum(r["source"] == k for r in recs) for k in ("usfs-edw", "osm")},
                     "areas": recs}, ndigits=6)
    log.info("wrote %s: %d winter recreation points", out, len(recs))
    return 0


# ---------------------------------------------------------------- owner review (dev16)

REVIEW_COLS = ("id", "name", "state", "source", "subtype", "reasons", "near_ski_area", "near_ski_km", "elev_ft", "cell_elev_ft", "lat", "lon")
DECISION_COLS = ("decision", "merge_into", "note")          # owner-filled (dev17): keep | drop | merge (+ merge_into = the id to keep)
DECISIONS = ("keep", "drop", "merge")


def read_decisions(path: Path = REVIEW_CSV) -> dict[str, dict]:
    """{id: {decision, merge_into, note}} from the owner's review CSV. Rows with an empty or unknown decision are ignored, so a CSV with no
    decisions (the default) changes nothing. Values are case-insensitive and stripped."""
    import csv
    path = Path(path)
    if not path.exists():
        return {}
    out = {}
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            d = (row.get("decision") or "").strip().lower()
            if d in DECISIONS and row.get("id"):
                out[row["id"].strip()] = {"decision": d, "merge_into": (row.get("merge_into") or "").strip(), "note": (row.get("note") or "").strip()}
    return out


def apply_decisions(recs: list[dict], decisions: dict[str, dict]) -> tuple[list[dict], dict]:
    """Pure. keep = no change; drop = remove the point; merge = remove it and list its id in the target's `merged_ids` (target = `merge_into`, which
    must exist, not be dropped / merged itself and not be the point itself; otherwise the point is kept and a warning is returned).
    Returns (recs, {keep: [ids], drop: [ids], merge: [(id, target)], warnings: [..]}). With no decisions the SAME list content is returned."""
    rep = {"keep": [], "drop": [], "merge": [], "warnings": []}
    if not decisions:
        return recs, rep
    ids = {r["id"] for r in recs}
    drops = {i for i, d in decisions.items() if i in ids and d["decision"] == "drop"}
    merges = {i: d["merge_into"] for i, d in decisions.items() if i in ids and d["decision"] == "merge"}
    # a merge is valid when its target exists, is not itself, and is KEPT (not dropped, and not itself merged away). Resolved by recursion over the
    # chain so the result never depends on CSV row order: A -> B -> C: B merges into C, A -> B is invalid (B is gone) and A stays; if B's own merge is
    # invalid, B stays and A -> B is valid. A cycle (A -> B -> A) makes both merges invalid.
    memo: dict[str, bool] = {}

    def is_gone(i: str, seen: tuple = ()) -> bool:
        if i in drops:
            return True
        if i not in merges or i in seen:
            return False
        if i not in memo:
            t = merges[i]
            memo[i] = bool(t) and t != i and t in ids and not is_gone(t, seen + (i,))
        return memo[i]

    valid = {i: t for i, t in merges.items() if is_gone(i)}
    gone = drops | set(valid)
    merged: dict[str, list[str]] = {}
    for i, d in decisions.items():
        if i not in ids:
            rep["warnings"].append(f"decision for unknown id {i} ignored")
        elif d["decision"] == "keep":
            rep["keep"].append(i)
        elif d["decision"] == "drop":
            rep["drop"].append(i)
        elif i in valid:
            rep["merge"].append((i, valid[i]))
            merged.setdefault(valid[i], []).append(i)
        else:
            rep["warnings"].append(f"merge of {i} needs a valid merge_into (got {d['merge_into']!r}); kept")
    out = []
    for r in recs:
        if r["id"] in gone:
            continue
        out.append({**r, "merged_ids": sorted(merged[r["id"]])} if r["id"] in merged else r)
    return out, rep
GENERIC_NAME = re.compile(r"^(trail\s?head|th|site|parking|lot|unit)\b[\s#\d.-]*$", re.I)


def review_flags(rec: dict, ski_areas: list[dict], others: list[dict] | None = None) -> dict:
    """Why a Sno-Park point deserves an owner look (dev16 M4.5). Pure. Returns {reasons: [...], near_ski_area, near_ski_km}.
    Reasons: near_ski_area (< 1 km from a ski area's base or summit: a resort Nordic/trailhead that may duplicate it), osm_only (gap-fill
    source, no USFS record), generic_name, elevation_mismatch (trailhead vs its 2.5 km NBM cell > 2,500 ft: forecast may not represent it),
    no_nws_grid (no NWS point: no NDFD or alerts), duplicate_nearby (another recreation point within 0.4 km or the same name within 5 km)."""
    reasons = []
    b = rec.get("base") or {}
    best, best_km = None, None
    for a in ski_areas:
        for k in ("base", "summit"):
            p = a.get(k) or {}
            if p.get("lat") is None or b.get("lat") is None:
                continue
            d = haversine_km(b["lat"], b["lon"], p["lat"], p["lon"])
            if best_km is None or d < best_km:
                best, best_km = a["name"], d
    if best_km is not None and best_km < 1.0:
        reasons.append("near_ski_area")
    if rec.get("source") == "osm":
        reasons.append("osm_only")
    if GENERIC_NAME.match(rec.get("name") or ""):
        reasons.append("generic_name")
    cell = ((rec.get("nbm_grid") or {}).get("base") or {}).get("elev_ft")
    if cell is not None and b.get("elev_ft") is not None and abs(cell - b["elev_ft"]) > 2500:
        reasons.append("elevation_mismatch")
    if not ((rec.get("nws") or {}).get("base") or {}).get("wfo"):
        reasons.append("no_nws_grid")
    nm = _tokens(rec.get("name") or "")
    for o in (others or []) if b.get("lat") is not None else []:
        if o is rec or o.get("id") == rec.get("id") or (o.get("base") or {}).get("lat") is None:
            continue
        d = haversine_km(b["lat"], b["lon"], o["base"]["lat"], o["base"]["lon"])
        if d < 0.4 or (d < 5.0 and nm and nm == _tokens(o.get("name") or "")):
            reasons.append("duplicate_nearby")
            break
    return {"reasons": reasons, "near_ski_area": best if best_km is not None and best_km < 1.0 else None,
            "near_ski_km": round(best_km, 2) if best_km is not None and best_km < 1.0 else None}


def review_rows(rec_doc: dict, ski_doc: dict, decisions: dict[str, dict] | None = None) -> list[dict]:
    areas = rec_doc["areas"]
    rows = []
    for r in areas:
        f = review_flags(r, ski_doc["areas"], areas)
        if f["reasons"]:
            rows.append({"id": r["id"], "name": r["name"], "state": r["state"], "source": r.get("source"), "subtype": r.get("subtype"),
                         "reasons": ";".join(f["reasons"]), "near_ski_area": f["near_ski_area"], "near_ski_km": f["near_ski_km"],
                         "elev_ft": r["base"]["elev_ft"], "cell_elev_ft": ((r.get("nbm_grid") or {}).get("base") or {}).get("elev_ft"),
                         "lat": r["base"]["lat"], "lon": r["base"]["lon"]})
    decisions = decisions or {}
    for row in rows:                                                # keep what the owner already decided when the CSV is regenerated
        d = decisions.get(row["id"], {})
        row.update(decision=d.get("decision", ""), merge_into=d.get("merge_into", ""), note=d.get("note", ""))
    return rows


def write_review(rec_path: Path = OUT, ski_path: Path | None = None, out: Path | None = None) -> list[dict]:
    """data/rec_points_review.csv for the owner (committed next to the catalog, like ski_areas_verify.csv)."""
    import csv
    ski = json.loads((ski_path or REPO_ROOT / "data" / "ski_areas.json").read_text(encoding="utf-8"))
    out = out or Path(rec_path).with_name("rec_points_review.csv")
    old = read_decisions(out)
    rows = review_rows(json.loads(Path(rec_path).read_text(encoding="utf-8")), ski, old)
    # rows the owner dropped / merged are no longer in rec_points.json: carry them (and their decision) forward so a regenerated CSV never
    # forgets a decision; they are removed again on every catalog build
    seen = {r["id"] for r in rows}
    if Path(out).exists():
        with open(out, encoding="utf-8", newline="") as f:
            for r in csv.DictReader(f):
                if r.get("id") not in seen and (r.get("decision") or "").strip().lower() in ("drop", "merge"):
                    rows.append({k: r.get(k, "") for k in REVIEW_COLS + DECISION_COLS})
    with open(out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_COLS + DECISION_COLS)
        w.writeheader()
        w.writerows(rows)
    return rows
