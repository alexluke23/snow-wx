"""Avalanche danger by forecast zone from the avalanche.org public API.

Docs: https://github.com/NationalAvalancheCenter/Avalanche.org-Public-API-Docs
The docs ask that danger displays be published and expired correctly and not
change the intent or accuracy of the forecast, so expired ratings are greyed
out and every zone links to its center's full forecast.

Output
  avalanche.geojson   zone polygons with danger level, color, links, validity
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .common import feature_collection, utcnow, write_json

log = logging.getLogger("snow-wx.avalanche")

MAP_LAYER = "https://api.avalanche.org/v2/public/products/map-layer"

# North American Avalanche Danger Scale
DANGER = {
    1: ("Low", "#50B848"),
    2: ("Moderate", "#FFF200"),
    3: ("Considerable", "#F7941E"),
    4: ("High", "#ED1C24"),
    5: ("Extreme", "#231F20"),
}
NO_RATING = ("No rating", "#CCCCCC")

KEEP = ("name", "center", "center_id", "center_link", "state", "timezone",
        "travel_advice", "link", "start_date", "end_date")


def round_coords(obj, ndigits: int):
    if isinstance(obj, (list, tuple)):
        if obj and isinstance(obj[0], (int, float)):
            return [round(float(v), ndigits) for v in obj]
        return [round_coords(o, ndigits) for o in obj]
    return obj


def parse_time(value):
    """Parse an ISO time. Naive times are treated as UTC.

    The API's times carry no zone. If they are really local (UTC-7/-8 in the
    West), reading them as UTC makes a rating expire a few hours *early*,
    never late -- the safe direction for a hazard display.
    """
    if not value:
        return None
    t = pd.to_datetime(value, errors="coerce")
    if pd.isna(t):
        return None
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def process(fc: dict, states: list[str], precision: int, now) -> dict:
    out = []
    for feat in fc.get("features", []):
        p = feat.get("properties") or {}
        if p.get("state") not in states:
            continue
        geom = feat.get("geometry")
        if not geom:
            continue
        props = {"zone_id": feat.get("id"), **{k: p.get(k) for k in KEEP}}
        try:
            level = int(p.get("danger_level"))
        except (TypeError, ValueError):
            level = -1
        end = parse_time(p.get("end_date"))
        expired = level in DANGER and end is not None and end < now
        if level in DANGER and not expired:
            label, color = DANGER[level]
        else:
            label, color = NO_RATING
            level = 0
        props.update({
            "danger_level": level,
            "danger": label,
            "color": color,
            "expired": expired,
            "warning": bool((p.get("warning") or {}).get("product")),
        })
        out.append({
            "type": "Feature",
            "geometry": {"type": geom["type"],
                         "coordinates": round_coords(geom.get("coordinates"), precision)},
            "properties": props,
        })
    return feature_collection(out)


def ratings_index(fc: dict) -> dict:
    keep = ("name", "center", "danger", "danger_level", "color", "expired", "link", "end_date")
    return {str(f["properties"].get("zone_id")): {k: f["properties"].get(k) for k in keep}
            for f in fc.get("features", []) if f["properties"].get("zone_id") is not None}


def run(cfg: dict, session, outdir: Path) -> dict:
    r = session.get(MAP_LAYER, timeout=session.request_timeout)
    r.raise_for_status()
    now = pd.Timestamp(utcnow())
    fc = process(r.json(), cfg["region"]["states"],
                 cfg["avalanche"].get("coord_precision", 4), now)
    write_json(outdir / "avalanche.geojson", fc)
    # Small zone_id -> rating index for pages that need one zone (area pages):
    # avoids downloading every polygon.
    write_json(outdir / "avalanche_ratings.json", ratings_index(fc))
    n = len(fc["features"])
    rated = sum(1 for f in fc["features"] if f["properties"]["danger_level"] > 0)
    log.info("Avalanche: wrote %d zones (%d with current ratings)", n, rated)
    if n == 0:
        raise RuntimeError("no avalanche zones in region")
    return {"count": n, "rated": rated}
