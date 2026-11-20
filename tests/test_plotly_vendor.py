"""Plotly is self-hosted (dev19 Part 2): the vendored build is the pinned 2.35.2 basic bundle (hash + licence files), every loader points at our own origin, and nothing in the site
or the service worker references the CDN any more."""
import hashlib
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
V = REPO / "web" / "vendor" / "plotly-2.35.2"


def test_vendored_build_is_the_pinned_version_with_its_licences():
    js = (V / "plotly-basic.min.js").read_bytes()
    assert js.startswith(b"/**\n* plotly.js (basic - minified) v2.35.2") or b"plotly.js (basic - minified) v2.35.2" in js[:200].replace(b"\r\n", b"\n")
    readme = (V / "README.txt").read_text(encoding="utf-8")
    sha = re.search(r"SHA-256: ([0-9a-f]{64})", readme).group(1)
    assert hashlib.sha256(js.replace(b"\r\n", b"\n")).hexdigest() == sha                    # line endings do not matter (autocrlf on Windows)
    assert "MIT License" in (V / "LICENSE").read_text(encoding="utf-8") and "polybooljs" in (V / "plotly-basic.min.js.LICENSE.txt").read_text(encoding="utf-8")
    assert 1_000_000 < len(js) < 1_200_000


def test_loaders_use_the_own_origin_and_no_cdn_reference_is_left():
    assert 'sc.src = "vendor/plotly-2.35.2/plotly-basic.min.js"' in (REPO / "web" / "js" / "app.js").read_text(encoding="utf-8")
    assert 'PLOTLY_URL = "vendor/plotly-2.35.2/plotly-basic.min.js"' in (REPO / "web" / "js" / "area.js").read_text(encoding="utf-8")
    sw = (REPO / "pipeline" / "pwa_sw.js").read_text(encoding="utf-8")
    assert 'const PLOTLY = self.location.origin + BASE + "/vendor/plotly-2.35.2/plotly-basic.min.js"' in sw
    offenders = []
    for p in list((REPO / "web").glob("*.html")) + list((REPO / "web" / "js").rglob("*.js")) + [REPO / "pipeline" / "pwa_sw.js"]:
        if "cdn.plot.ly" in p.read_text(encoding="utf-8"):
            offenders.append(p.name)
    assert not offenders, f"still referencing the Plotly CDN: {offenders}"
    assert 'rel="preconnect" href="https://cdn.plot.ly"' not in (REPO / "web" / "area.html").read_text(encoding="utf-8")
