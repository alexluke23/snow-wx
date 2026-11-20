"""GitHub Pages redirect stub for the W1 cutover (dev18 stretch 1; docs/specs/hosting-seo.md "Redirect / canonical stub").

After the custom domain is live, the old https://<user>.github.io/snow-wx/ keeps answering, but only as a stub: every old page is a tiny HTML file with a meta refresh, a canonical link
to the NEW address and a plain link, and the old `area.html#<id>` links are mapped to the new indexable path (`/ski/<state>/<id>/`) by a small FILE script (no inline scripts, no data).
Sno-Parks and SNOTEL sites have no prerendered path page: their `#id` goes to the new interactive page `area.html#<id>`.

    python -m pipeline stub --origin https://snowwx.example --out stub        # writes the folder; deploy it to GitHub Pages in place of the old site

The stub is generated from the same catalog as `pipeline/pages.py`, so a new area can never be missing from the map (tests/test_stub.py checks every ski area).
"""

from __future__ import annotations

import html
import json
import logging
from pathlib import Path

from .pages import page_path

log = logging.getLogger("snow-wx.stub")
# every page the old site served (web/*.html): old file -> new file (same name, same folder on the new origin)
OLD_PAGES = ["index.html", "area.html", "finder.html", "mine.html", "models.html", "about.html", "status.html", "sources.html", "disclaimer.html", "privacy.html", "terms.html"]


def new_url(origin: str, base_path: str, rel: str = "") -> str:
    return f"{origin.rstrip('/')}{('/' + base_path.strip('/')) if base_path.strip('/') else ''}/{rel}"


def stub_page(target: str, title: str = "Snow-Wx has moved", script: str = "", refresh: bool = True) -> str:
    t = html.escape(target, quote=True)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <meta name="robots" content="noindex">
  <link rel="canonical" href="{t}">
  {('<meta http-equiv="refresh" content="0; url=' + t + '">') if refresh else ''}{script}
</head>
<body>
  <p>Snow-Wx has moved to <a href="{t}">{t}</a>.</p>
</body>
</html>
"""


def id_map(areas: list[dict], origin: str, base_path: str, other_ids: list[str] | None = None) -> dict[str, str]:
    """{old #id: new URL}: prerendered ski-area path pages, and the interactive page for every other id (Sno-Parks, SNOTEL sites)"""
    m = {a["id"]: new_url(origin, base_path, page_path(a)) for a in areas}
    for i in other_ids or []:
        m.setdefault(i, new_url(origin, base_path, "area.html") + f"#{i}")
    return m


def redirect_js(mapping: dict[str, str], fallback: str) -> str:
    return ("/* old area.html#id -> the new address; unknown ids go to the new interactive page with the same hash */(function(){var m=" + json.dumps(mapping, separators=(",", ":"))
            + ";var f=" + json.dumps(fallback) + ";var id=decodeURIComponent(location.hash.replace(/^#/,''));location.replace(m[id]||(id?f+'#'+encodeURIComponent(id):f));})();\n")


def build(cfg: dict, out: Path, origin: str, areas: list[dict], other_ids: list[str] | None = None, base_path: str | None = None) -> dict:
    out = Path(out)
    (out / "js").mkdir(parents=True, exist_ok=True)
    bp = base_path if base_path is not None else ""            # the NEW site's base path (a custom domain serves from the root)
    mapping = id_map(areas, origin, bp, other_ids)
    (out / "js" / "stub-redirect.js").write_text(redirect_js(mapping, new_url(origin, bp, "area.html")), encoding="utf-8")
    for name in OLD_PAGES:
        target = new_url(origin, bp, "" if name == "index.html" else name)
        script = '\n  <script src="js/stub-redirect.js"></script>' if name == "area.html" else ""
        # area.html redirects by script only: a meta refresh would drop the #id before the script could read it
        (out / name).write_text(stub_page(target, script=script, refresh=name != "area.html"), encoding="utf-8")
    (out / "404.html").write_text(stub_page(new_url(origin, bp, ""), "Snow-Wx has moved"), encoding="utf-8")
    log.info("stub: %d pages, %d #id redirects -> %s", len(OLD_PAGES) + 1, len(mapping), origin)
    return {"pages": len(OLD_PAGES) + 1, "ids": len(mapping)}
