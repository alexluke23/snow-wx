"""Frozen inputs for tools/browser_check.py (dev20): the browser suite must not depend on live alerts or on any live third-party host.

    python tools/browser_fixtures.py record [--build build]     # ONE-TIME (re)recording into tests/fixtures/browser/ (network: the NWS hazards layer once)

What is frozen
  * data/alerts/{index,details,hazard_text}.json: a small recorded snapshot (<= 6 alerts, never on the areas the checks inspect). `freeze(site)` copies it into a
    worker's site copy and shifts every time field so the alerts are ACTIVE now (ends = now + 12 h): same content every run, never "expired".
  * third-party hosts (answered inside the browser by `respond(url)`; nothing leaves the machine):
      basemap.nationalmap.gov tiles  -> one generated 256 px PNG (light relief-like grey)
      tiles.openfreemap.org          -> a TileJSON whose tiles are empty vector tiles (MapLibre draws nothing and reaches "idle")
      mapservices.weather.noaa.gov   -> a recorded hazard-layer answer (a few winter polygons, coordinates rounded)
      anything else                  -> refused (and listed in the check's log), so a new live dependency shows up at once.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "browser"
KEEP_OUT = {"alta-ski-area", "brighton-resort", "mt-bachelor", "jackson-hole-mountain-resort", "snowbird", "sp-wing-mountain", "snotel-1000-OR-SNTL"}   # areas the checks inspect
TIME_KEYS = {"effective", "onset", "ends", "expires", "f", "x", "sent"}


def tile_png() -> bytes:
    p = FIX / "tile.png"
    return p.read_bytes()


def _shift(obj, delta: timedelta):
    """every ISO time under TIME_KEYS moved by `delta` (keeps the UTC offset as written)"""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in TIME_KEYS and isinstance(v, str):
                try:
                    out[k] = (datetime.fromisoformat(v.replace("Z", "+00:00")) + delta).isoformat(timespec="seconds")
                    continue
                except ValueError:
                    pass
            out[k] = _shift(v, delta)
        return out
    if isinstance(obj, list):
        return [_shift(v, delta) for v in obj]
    return obj


def freeze(site: Path, now: datetime | None = None) -> dict:
    """copy the frozen alert snapshot into `site`/data/alerts, made active relative to `now`. Returns what was written."""
    now = now or datetime.now(timezone.utc)
    meta = json.loads((FIX / "alerts" / "frozen.json").read_text(encoding="utf-8"))
    ref_end = datetime.fromisoformat(meta["latest_end"].replace("Z", "+00:00"))
    delta = (now + timedelta(hours=12)) - ref_end
    out = site / "data" / "alerts"
    out.mkdir(parents=True, exist_ok=True)
    for name in ("index.json", "details.json", "hazard_text.json"):
        d = _shift(json.loads((FIX / "alerts" / name).read_text(encoding="utf-8")), delta)
        if isinstance(d, dict) and "generated_at" in d:
            d["generated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        (out / name).write_text(json.dumps(d), encoding="utf-8")
    return {"alerts": meta["count"], "shift_h": round(delta.total_seconds() / 3600, 1)}


# ------------------------------------------------------------------ network answers (used by browser_check.Browser)
TILEJSON = {"tilejson": "3.0.0", "tiles": ["https://tiles.openfreemap.org/planet/fixture/{z}/{x}/{y}.pbf"], "minzoom": 0, "maxzoom": 14,
            "bounds": [-180, -85, 180, 85], "vector_layers": [{"id": n, "fields": {}} for n in ("park", "transportation", "boundary", "mountain_peak", "place")]}


def respond(url: str):
    """(status, content_type, body bytes) for a third-party URL, or None = refuse it"""
    host = re.sub(r"^https?://([^/]+).*$", r"\1", url)
    path = url.split("?")[0]
    if host == "basemap.nationalmap.gov" and "/tile/" in path:
        return 200, "image/png", tile_png()
    if host == "tiles.openfreemap.org":
        if path.rstrip("/").endswith("/planet"):
            return 200, "application/json", json.dumps(TILEJSON).encode()
        if path.endswith(".pbf"):
            return 200, "application/x-protobuf", b""                     # an empty vector tile / glyph range
    if host == "mapservices.weather.noaa.gov" and path.endswith("/query"):
        return 200, "application/geo+json", (FIX / "hazards_query.json").read_bytes()
    return None


# ------------------------------------------------------------------ recording (one-time; needs the network for the hazard layer)
def record(build: Path) -> None:
    import requests
    from PIL import Image, ImageDraw
    sys.path.insert(0, str(REPO))
    FIX.mkdir(parents=True, exist_ok=True)
    # 1. tile
    im = Image.new("RGB", (256, 256), (236, 236, 233))
    dr = ImageDraw.Draw(im)
    for i in range(0, 256, 32):
        dr.line([(0, i), (256, i + 40)], fill=(222, 222, 218), width=6)
    buf = io.BytesIO()
    im.quantize(8).save(buf, "PNG", optimize=True)
    (FIX / "tile.png").write_bytes(buf.getvalue())
    # 2. alerts snapshot: <= 6 alerts, none on the inspected areas
    src = build / "data" / "alerts"
    ix = json.loads((src / "index.json").read_text(encoding="utf-8"))
    det = json.loads((src / "details.json").read_text(encoding="utf-8"))
    ht = json.loads((src / "hazard_text.json").read_text(encoding="utf-8"))
    areas = {k: v for k, v in ix.get("areas", {}).items() if k not in KEEP_OUT}
    ids = []
    for v in areas.values():
        for a in v:
            if a["id"] not in ids:
                ids.append(a["id"])
    ids = ids[:6]
    keep = set(ids)
    ix2 = {**ix, "alerts": {k: v for k, v in ix["alerts"].items() if k in keep},
           "areas": {k: [a for a in v if a["id"] in keep] for k, v in areas.items() if any(a["id"] in keep for a in v)},
           "points": {k: [a for a in v if a["id"] in keep] for k, v in ix.get("points", {}).items() if k not in KEEP_OUT and any(a["id"] in keep for a in v)}}
    ix2["count"] = len(ix2["alerts"])
    (FIX / "alerts").mkdir(exist_ok=True)
    (FIX / "alerts" / "index.json").write_text(json.dumps(ix2, indent=0), encoding="utf-8")
    (FIX / "alerts" / "details.json").write_text(json.dumps({k: v for k, v in det.items() if k in keep}, indent=0), encoding="utf-8")
    (FIX / "alerts" / "hazard_text.json").write_text(json.dumps({**ht, "alerts": dict(list(ht["alerts"].items())[:6])}, indent=0), encoding="utf-8")
    ends = [v.get("ends") for v in ix2["alerts"].values() if v.get("ends")]
    latest = max(datetime.fromisoformat(e) for e in ends) if ends else datetime.now(timezone.utc)
    (FIX / "alerts" / "frozen.json").write_text(json.dumps({"recorded": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "count": len(ix2["alerts"]),
                                                            "latest_end": latest.isoformat(), "kept_out": sorted(KEEP_OUT)}, indent=1), encoding="utf-8")
    # 3. hazard layer: the live answer for the West, <= 8 winter polygons, coordinates at 3 decimals
    hz = json.loads((build / "data" / "hazards.json").read_text(encoding="utf-8"))
    names = [p["name"] for p in hz["products"]]
    where = "prod_type IN (" + ",".join("'" + n.replace("'", "''") + "'" for n in names) + ")"
    q = {"where": where, "geometry": "-125,31,-102,49.5", "geometryType": "esriGeometryEnvelope", "inSR": "4326", "outSR": "4326", "spatialRel": "esriSpatialRelIntersects",
         "outFields": "prod_type,expiration,url,wfo", "geometryPrecision": "3", "maxAllowableOffset": "0.05", "f": "geojson"}
    r = requests.get(f"{hz['service']}/{hz['layer']}/query", params=q, timeout=60, headers={"User-Agent": "snow-wx test fixture recorder (+https://github.com/alexluke23/snow-wx)"})
    r.raise_for_status()
    gj = r.json()
    gj["features"] = gj.get("features", [])[:8]
    (FIX / "hazards_query.json").write_text(json.dumps(gj, separators=(",", ":")), encoding="utf-8")
    print(f"recorded: tile {len((FIX / 'tile.png').read_bytes())} B, {len(ids)} alerts, {len(gj['features'])} hazard polygons")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["record"])
    ap.add_argument("--build", default=str(REPO / "build"))
    a = ap.parse_args()
    record(Path(a.build))
