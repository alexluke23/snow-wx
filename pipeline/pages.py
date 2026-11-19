"""Prerendered, indexable area pages (W2, docs/specs/hosting-seo.md 5.10). BEHIND A FLAG: config `pages.enabled` (default false), so a
partial state can never change the live site.

For every ski area in data/ski_areas.json: <out>/ski/<state>/<id>/index.html (title, meta description = the Daily Snow summary
sentence, h1, summary text, canonical from site.origin + site.base_path, Open Graph/Twitter tags, JSON-LD WebPage + Place),
plus sitemap.xml, robots.txt and, when enabled, a redirect snippet injected into <out>/area.html so old `area.html#id` links go to
the path. The interactive page (area.html#id) keeps working. Pure builders are tested offline (tests/test_pages.py).
Run as `python -m pipeline pages --out build` AFTER the points tar has been unpacked into build/data (workflow wiring is a later step).
Sno-Parks and OG images are not built yet (spec: top 20 only if time remains).
"""

from __future__ import annotations

import html
import json
import logging
import re
from pathlib import Path

log = logging.getLogger("snow-wx.pages")
GENERIC = "Snow forecast, snow level, avalanche danger and observations for {name} ({state}). Open data from NOAA/NWS."


def page_path(a: dict) -> str:
    return f"ski/{a['state'].lower()}/{a['id']}/"


def _bp(cfg: dict) -> str:
    bp = (cfg.get("site") or {}).get("base_path")
    return "/" + str(bp).strip("/") if bp and str(bp).strip("/") else ""


def base_url(cfg: dict) -> str:
    return str((cfg.get("site") or {}).get("origin") or "").rstrip("/") + _bp(cfg)


def description(a: dict, doc: dict | None) -> str:
    sm = (doc or {}).get("summary") or {}
    txt = sm.get("sentence") or GENERIC.format(name=a["name"], state=a["state"])
    return re.sub(r"\s+", " ", txt).strip()[:300]


def render_page(a: dict, doc: dict | None, cfg: dict) -> str:
    e = html.escape
    bp = _bp(cfg)
    canon = f"{base_url(cfg)}/{page_path(a)}"
    desc = description(a, doc)
    title = f"{a['name']} snow forecast ({a['state']}) · Snow-Wx"
    sm = (doc or {}).get("summary") or {}
    t72 = ((doc or {}).get("points") or {}).get("summit", {}).get("totals", {}).get("72h") or {}
    head = f"<p><b>{e(sm.get('tag', ''))}</b> {e(sm['sentence'])}</p>" if sm.get("sentence") else f"<p>{e(desc)}</p>"
    bullets = "<ul>" + "".join(f"<li>{e(b)}</li>" for b in sm.get("bullets") or []) + "</ul>" if sm.get("bullets") else ""
    exp = (f"<p>Expected snowfall at the summit over the next 72 hours: about {t72['snow_in']:.0f} in.</p>"
           if t72.get("snow_in") is not None else "")
    ld = {"@context": "https://schema.org", "@type": "WebPage", "name": title, "description": desc, "url": canon,
          "about": {"@type": "Place", "name": a["name"],
                    "geo": {"@type": "GeoCoordinates", "latitude": a["summit"]["lat"], "longitude": a["summit"]["lon"],
                            "elevation": round(a["summit"]["elev_ft"] * 0.3048)},
                    "address": {"@type": "PostalAddress", "addressRegion": a["state"], "addressCountry": "US"}}}
    ld_json = json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(canon)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="Snow-Wx">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:url" content="{e(canon)}">
<meta name="twitter:card" content="summary"><meta name="twitter:title" content="{e(title)}"><meta name="twitter:description" content="{e(desc)}">
<link rel="icon" href="data:,">
<link rel="stylesheet" href="{bp}/css/style.css">
<script type="application/ld+json">{ld_json}</script>
</head>
<body class="about-page doc-page">
<main class="about">
<h1>{e(a['name'])} snow forecast</h1>
<p class="lead">{e(a.get('region', ''))}, {e(a['state'])} · base {a['base']['elev_ft']:,.0f} ft · summit {a['summit']['elev_ft']:,.0f} ft</p>
{head}
{bullets}
{exp}
<p><a href="{bp}/area.html#{e(a['id'])}">Open the full interactive forecast: charts, snow level, chances, observations and avalanche danger →</a></p>
<p class="hint">Forecasts: NOAA/NWS National Blend of Models. Not a substitute for the NWS forecast or your local avalanche center.</p>
</main>
</body>
</html>
"""


def sitemap(cfg: dict, areas: list[dict]) -> str:
    base = base_url(cfg)
    urls = [f"{base}/", f"{base}/finder.html", f"{base}/about.html", f"{base}/status.html"] + [f"{base}/{page_path(a)}" for a in areas]
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "".join(f"<url><loc>{html.escape(u)}</loc></url>\n" for u in urls) + "</urlset>\n")


def robots(cfg: dict) -> str:
    return f"User-agent: *\nAllow: /\nSitemap: {base_url(cfg)}/sitemap.xml\n"


def redirect_js(areas: list[dict], base_path: str = "") -> str:
    """js/id-redirect.js: old `area.html#id` links go to the indexable path. A FILE (not an inline <script>) so the draft Content-Security-Policy needs no 'unsafe-inline'."""
    m = {a["id"]: f"{base_path}/{page_path(a)}" for a in areas}
    return ("/* pages.enabled: old #id links go to the indexable path */(function(){var m=" + json.dumps(m, separators=(",", ":"))
            + ";var id=decodeURIComponent(location.hash.replace(/^#/,''));if(m[id])location.replace(m[id]);})();\n")


def run(cfg: dict, outdir: Path, catalog: Path | None = None, *, force: bool = False) -> int:
    """Write the pages into `outdir` (the site folder, data/ already merged). No-op unless pages.enabled (or force)."""
    if not force and not (cfg.get("pages") or {}).get("enabled"):
        log.info("pages: disabled (config pages.enabled=false); nothing written")
        return 0
    if not (cfg.get("site") or {}).get("origin"):
        log.error("pages: site.origin is required for canonical URLs")
        return 1
    out = Path(outdir)
    areas = json.loads((catalog or out / "data" / "ski_areas.json").read_text(encoding="utf-8"))["areas"]
    for a in areas:
        try:
            doc = json.loads((out / "data" / "points" / f"{a['id']}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = None
        p = out / page_path(a) / "index.html"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(render_page(a, doc, cfg), encoding="utf-8")
    (out / "sitemap.xml").write_text(sitemap(cfg, areas), encoding="utf-8")
    (out / "robots.txt").write_text(robots(cfg), encoding="utf-8")
    ar = out / "area.html"
    if ar.exists():
        s = ar.read_text(encoding="utf-8")
        (out / "js").mkdir(parents=True, exist_ok=True)
        (out / "js" / "id-redirect.js").write_text(redirect_js(areas, _bp(cfg)), encoding="utf-8")
        if "js/id-redirect.js" not in s:
            ar.write_text(s.replace("<head>", '<head>\n  <script src="js/id-redirect.js"></script>', 1), encoding="utf-8")
    log.info("pages: wrote %d area pages, sitemap.xml, robots.txt", len(areas))
    return 0
