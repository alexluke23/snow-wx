"""NWS winter-hazard products for the obs map's hazards layer (dev13 item 2).

The map draws the official NWS watches/warnings/advisories polygons live from NOAA's map service (WWA
watch_warn_adv, mapservices.weather.noaa.gov; public domain, credit NOAA/NWS). This source only builds the LIST of
winter products from the service's CURRENT product names and official colors (nothing hard-coded from memory), so the
browser can filter the live query and draw a legend: data/hazards.json. Rules (config `hazards`): include patterns,
exclude patterns, and only watch / warning / advisory levels. Failing is harmless: the map falls back to our own
alerts index and says so.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from .common import utcnow, write_json

log = logging.getLogger("snow-wx.hazards")

LEVEL_RE = re.compile(r"\b(watch|warning|advisory)$", re.I)


def level_of(name: str) -> str | None:
    m = LEVEL_RE.search(name.strip())
    return m.group(1).lower() if m else None


def hex_color(rgba) -> str:
    r, g, b = (int(x) for x in rgba[:3])
    return f"#{r:02x}{g:02x}{b:02x}"


def winter_products(renderer: dict, include: list[str], exclude: list[str]) -> list[dict]:
    """[{name, level, color}] for the winter products among the renderer's classes (pure; tested)."""
    inc = [re.compile(p, re.I) for p in include]
    exc = [re.compile(p, re.I) for p in exclude]
    out, seen = [], set()
    groups = renderer.get("uniqueValueGroups") or [{"classes": renderer.get("uniqueValueInfos") or []}]
    for g in groups:
        for c in g.get("classes", []):
            name = (c.get("label") or "").strip()
            if not name or name in seen or level_of(name) is None:
                continue
            if any(p.search(name) for p in inc) and not any(p.search(name) for p in exc):
                seen.add(name)
                color = (c.get("symbol") or {}).get("color") or [128, 128, 128, 255]
                out.append({"name": name, "level": level_of(name), "color": hex_color(color)})
    order = {"warning": 0, "watch": 1, "advisory": 2}
    return sorted(out, key=lambda p: (order[p["level"]], p["name"]))


def run(cfg: dict, session, outdir: Path) -> dict:
    hc = cfg["hazards"]
    base = f"{hc['service'].rstrip('/')}/{hc['layer']}"
    r = session.get(base, params={"f": "json"}, timeout=session.request_timeout)
    r.raise_for_status()
    layer = r.json()
    renderer = (layer.get("drawingInfo") or {}).get("renderer") or {}
    products = winter_products(renderer, hc.get("include", []), hc.get("exclude", []))
    if not products:
        raise RuntimeError("no winter products found in the NWS hazards service")
    write_json(outdir / "hazards.json", {
        "generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "service": hc["service"], "layer": hc["layer"],
        "field": "prod_type", "source": "NOAA/NWS watches, warnings and advisories (mapservices.weather.noaa.gov)",
        "products": products})
    log.info("hazards: %d winter products", len(products))
    return {"count": len(products), "unit": "winter products"}
