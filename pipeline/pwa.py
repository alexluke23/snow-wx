"""Offline-first PWA build step (W4, docs/specs/pwa.md). BUILD ONLY: everything is behind config `pwa.enabled` (default false) and must
NOT be enabled before the W1 domain move (installed users get stranded if the origin changes).

`python -m pipeline pwa --out build` (after the site and data are assembled) writes, only when enabled:
  manifest.json   name, icons (192/512 + maskable + apple-touch 180), display standalone, start_url = My mountains, scope = base path
  sw.js           from pipeline/pwa_sw.js: versioned shell precache, SWR for the small data files and each favorite's points/ndfd files
  icons/*.png     generated with Pillow (a simple snowflake)
  and injects the manifest link, theme colour and the page config + js/pwa.js into every top-level page.
With `pwa.kill: true` (and enabled false) it writes ONLY a worker that unregisters itself and deletes every snowwx-* cache, so a bad
release can be rolled back for installed users. Base path / origin come from config site.base_path / site.origin; nothing is hard-coded.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

log = logging.getLogger("snow-wx.pwa")
HERE = Path(__file__).resolve().parent
THEME = "#12202e"
KILL_SW = """/* Snow-Wx PWA kill switch (config pwa.kill): unregister and delete every snowwx-* cache. */
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil((async () => {
  for (const k of await caches.keys()) if (k.startsWith("snowwx-")) await caches.delete(k);
  await self.registration.unregister();
  for (const c of await self.clients.matchAll({ type: "window" })) c.navigate(c.url);
})()));
"""


def base_path(cfg: dict) -> str:
    bp = (cfg.get("site") or {}).get("base_path")
    return "/" + str(bp).strip("/") if bp and str(bp).strip("/") else ""


def shell_files(out: Path) -> list[str]:
    """Our own pages, CSS and JS (relative to the site root); no data, models, tiles or big vendor bundles (MapLibre)."""
    files = sorted(p.name for p in out.glob("*.html")) + [f"css/{p.name}" for p in sorted((out / "css").glob("*.css"))]
    files += [str(p.relative_to(out)).replace("\\", "/") for p in sorted((out / "js").rglob("*.js"))]
    files += [str(p.relative_to(out)).replace("\\", "/") for p in sorted((out / "vendor" / "leaflet-1.9.4").rglob("*")) if p.is_file()]
    return files


def version_of(out: Path, files: list[str], salt: str = "") -> str:
    h = hashlib.sha1(salt.encode())
    for f in files:
        h.update(f.encode())
        h.update((out / f).read_bytes())
    return h.hexdigest()[:10]


def render_sw(version: str, bp: str, files: list[str]) -> str:
    s = (HERE / "pwa_sw.js").read_text(encoding="utf-8")
    return s.replace("__VERSION__", version).replace("__BASE__", bp).replace("__SHELL__", json.dumps(files))


def manifest(cfg: dict) -> dict:
    bp = base_path(cfg)
    return {"name": "Snow-Wx: snow forecasts for the western US", "short_name": "Snow-Wx", "description": "Open snow, snowpack and avalanche data.",
            "start_url": f"{bp}/mine.html?source=pwa", "scope": f"{bp}/", "display": "standalone", "background_color": "#f5f7fa", "theme_color": THEME,
            "icons": [{"src": f"{bp}/icons/icon-192.png", "sizes": "192x192", "type": "image/png"},
                      {"src": f"{bp}/icons/icon-512.png", "sizes": "512x512", "type": "image/png"},
                      {"src": f"{bp}/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]}


def make_icons(out: Path) -> None:
    from PIL import Image, ImageDraw
    import math

    def draw(size: int, pad: float) -> Image.Image:
        im = Image.new("RGBA", (size, size), THEME)
        d = ImageDraw.Draw(im)
        c, r = size / 2, size * (0.5 - pad)
        for k in range(6):                                           # a six-armed snowflake with small side branches
            a = math.radians(60 * k + 90)
            x, y = c + r * math.cos(a), c - r * math.sin(a)
            d.line([(c, c), (x, y)], fill="#ffffff", width=max(2, size // 40))
            for t in (0.55, 0.8):
                bx, by = c + r * t * math.cos(a), c - r * t * math.sin(a)
                for s in (-1, 1):
                    b = a + s * math.radians(40)
                    d.line([(bx, by), (bx + r * 0.22 * math.cos(b), by - r * 0.22 * math.sin(b))], fill="#ffffff", width=max(2, size // 50))
        return im
    (out / "icons").mkdir(parents=True, exist_ok=True)
    draw(192, 0.12).save(out / "icons" / "icon-192.png")
    draw(512, 0.12).save(out / "icons" / "icon-512.png")
    draw(512, 0.28).save(out / "icons" / "icon-maskable-512.png")      # maskable: content inside the 80 % safe zone
    draw(180, 0.12).save(out / "icons" / "apple-touch-icon.png")


def inject(html: str, cfg: dict, version: str) -> str:
    if "snowwx-pwa" in html:
        return html
    bp = base_path(cfg)
    conf = json.dumps({"version": version, "base": bp, "sw": f"{bp}/sw.js", "scope": f"{bp}/", "start": f"{bp}/mine.html"})
    head = (f'<link rel="manifest" href="{bp}/manifest.json"><meta name="theme-color" content="{THEME}">'
            f'<link rel="apple-touch-icon" href="{bp}/icons/apple-touch-icon.png"><meta name="mobile-web-app-capable" content="yes">'
            f'<meta name="apple-mobile-web-app-capable" content="yes"><meta name="snowwx-pwa" content="{version}">'
            f'<script>window.SNOWWX_PWA={conf};</script><script src="js/pwa.js" defer></script>')
    return re.sub(r"</head>", head + "\n</head>", html, count=1)


def run(cfg: dict, out: Path, *, force: bool = False) -> int:
    pc = cfg.get("pwa") or {}
    out = Path(out)
    if pc.get("kill"):                                               # rollback for installed users: wins over enabled
        (out / "sw.js").write_text(KILL_SW, encoding="utf-8")
        log.info("pwa: KILL SWITCH worker written (unregisters itself, clears snowwx-* caches)")
        return 0
    if not force and not pc.get("enabled"):
        log.info("pwa: disabled (config pwa.enabled=false); nothing written")
        return 0
    files = shell_files(out)
    version = version_of(out, files, str(pc.get("version") or ""))
    (out / "sw.js").write_text(render_sw(version, base_path(cfg), files), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps(manifest(cfg), indent=1), encoding="utf-8")
    make_icons(out)
    for p in out.glob("*.html"):
        s = p.read_text(encoding="utf-8")
        p.write_text(inject(s, cfg, version), encoding="utf-8")
    log.info("pwa: version %s, %d shell files, manifest + icons + sw.js written", version, len(files))
    return 0
