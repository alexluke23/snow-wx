"""W1 cutover rehearsal (dev18 stretch 1): build the site for a PLACEHOLDER domain and verify that nothing hard-codes the current github.io origin, and that sitemap, canonical,
Open Graph, JSON-LD, manifest, service worker, 404 and the #id redirects all follow `site.origin` / `site.base_path`. Offline: no network, no workflow touched.

    python tools/w1_rehearsal.py [--origin https://snowwx.example] [--base ""] [--keep DIR]

Writes the same files a real build writes (web/ copy, pages, pwa, 404 base) into a temp folder, then asserts. Exit 0 = every check passed. tests/test_w1_rehearsal.py runs it.
The result of a run is the evidence for docs/w1_cutover_checklist.md.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
import pipeline  # noqa: E402,F401
from pipeline import linkcheck, pages, pwa, stub  # noqa: E402
from pipeline.__main__ import fill_404_base  # noqa: E402
from pipeline.common import load_config  # noqa: E402

OLD_HOSTS = ("github.io", "alexluke23")
TEXT = {".html", ".js", ".json", ".xml", ".txt", ".css", ".webmanifest"}


def build(out: Path, origin: str, base: str) -> dict:
    """a build for the placeholder domain, without the network: web/ + catalog + the W2/W4 outputs forced on + 404 base"""
    cfg = load_config()
    cfg["site"] = {**cfg["site"], "origin": origin, "base_path": base}
    shutil.copytree(REPO / "web", out, dirs_exist_ok=True)
    (out / "data").mkdir(exist_ok=True)
    for n in ("ski_areas.json", "rec_points.json"):
        shutil.copy2(REPO / "data" / n, out / "data" / n)
    assert pages.run(cfg, out, force=True) == 0
    assert pwa.run(cfg, out, force=True) == 0
    fill_404_base(out, cfg)
    return cfg


REPO_LINK = re.compile(r"https://github\.com/alexluke23/snow-wx[^\s\"'<>)]*")       # links to the CODE repository stay valid after the cutover: not an origin


def scan_text(out: Path):
    for p in sorted(out.rglob("*")):
        if p.is_file() and p.suffix.lower() in TEXT and "vendor" not in p.parts:
            t = REPO_LINK.sub("", p.read_text(encoding="utf-8", errors="ignore"))
            if p.suffix == ".js":
                t = re.sub(r"/\*.*?\*/", "", t, flags=re.S)
                t = re.sub(r"(?m)(^|\s)//.*$", "", t)                                     # comments may name the old values; code may not
            yield p, t


def run(origin: str, base: str, keep: Path | None = None) -> list[tuple[str, bool, str]]:
    tmp = Path(tempfile.mkdtemp()) if keep is None else Path(keep)
    out = tmp / "site"
    cfg = build(out, origin, base)
    res: list[tuple[str, bool, str]] = []

    def check(name, ok, detail=""):
        res.append((name, bool(ok), detail))

    prefix = origin.rstrip("/") + base
    # 1. nothing hard-codes the current host
    hits = [f"{p.relative_to(out).as_posix()}: {h}" for p, t in scan_text(out) for h in OLD_HOSTS if h in t]
    check("no github.io / account name anywhere in the built site", not hits, "; ".join(hits[:5]))
    if base == "":
        bp_hits = [p.relative_to(out).as_posix() for p, t in scan_text(out) if re.search(r"""["'(=]/snow-wx[/"']""", t)]
        check("no hard-coded /snow-wx base path (the placeholder serves from the root)", not bp_hits, "; ".join(bp_hits[:5]))
    # 2. sitemap, robots, canonical, og, json-ld
    sm = (out / "sitemap.xml").read_text(encoding="utf-8")
    locs = re.findall(r"<loc>([^<]+)</loc>", sm)
    check("sitemap URLs all on the new origin + base", locs and all(u.startswith(prefix + "/") or u == prefix + "/" for u in locs), f"{len(locs)} URLs")
    check("robots.txt points at the new sitemap", f"Sitemap: {prefix}/sitemap.xml" in (out / "robots.txt").read_text(encoding="utf-8"))
    areas = json.loads((out / "data" / "ski_areas.json").read_text(encoding="utf-8"))["areas"]
    bad = []
    for a in areas:
        h = (out / pages.page_path(a) / "index.html").read_text(encoding="utf-8")
        for pat in (r'<link rel="canonical" href="([^"]+)"', r'<meta property="og:url" content="([^"]+)"', r'"url": "([^"]+)"'):
            for m in re.findall(pat, h):
                if not m.startswith(prefix):
                    bad.append(f"{a['id']}: {m}")
    check("canonical, og:url and JSON-LD url on every area page follow the config", not bad, "; ".join(bad[:3]))
    # 3. PWA files
    man = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    check("manifest start_url / scope / icons follow base_path", man["start_url"].startswith(base + "/") and man["scope"] == base + "/" and all(i["src"].startswith(base + "/") for i in man["icons"]))
    sw = (out / "sw.js").read_text(encoding="utf-8")
    check("service worker BASE follows base_path", f'const BASE = "{base}"' in sw)
    pc = (out / "js" / "pwa-config.js").read_text(encoding="utf-8")
    check("pwa-config.js follows base_path", f'"base": "{base}"' in pc and f'"scope": "{base}/"' in pc)
    # 4. old #id links -> new paths
    rj = (out / "js" / "id-redirect.js").read_text(encoding="utf-8")
    m = json.loads(re.search(r"var m=(\{.*?\});", rj).group(1))
    check("every ski area has an #id redirect to its new path", set(m) == {a["id"] for a in areas} and all(v.startswith(base + "/ski/") for v in m.values()), f"{len(m)} areas")
    # 5. no inline scripts (CSP) in any page
    inline = [p.relative_to(out).as_posix() for p, t in scan_text(out) if p.suffix == ".html" and re.search(r"<script(?![^>]*\bsrc=)(?![^>]*application/ld\+json)[^>]*>", t)]
    check("no inline <script> in any page (strict CSP possible)", not inline, "; ".join(inline[:5]))
    # 6. internal links and SEO files
    lc = linkcheck.check_internal(out, base_path=base)
    check("no broken internal link in the built site", not lc["broken"], f"{lc['pages']} pages, {lc['links']} links; {lc['broken'][:2]}")
    sf = linkcheck.check_seo_files(out, prefix)
    check("robots / sitemap / canonical sanity", not sf, "; ".join(sf[:3]))
    nf = (out / "404.html").read_text(encoding="utf-8")
    check("404 page base follows base_path", f'<base href="{base}/">' in nf and "__BASE_HREF__" not in nf)
    # 7. the redirect stub from the OLD address (generated for this origin)
    st = tmp / "stub"
    info = stub.build(cfg, st, origin, areas, [a["id"] for a in json.loads((out / "data" / "rec_points.json").read_text(encoding="utf-8")).get("areas", [])], base)
    missing_old = [n for n in stub.OLD_PAGES if not (st / n).exists()]
    live_pages = sorted(p.name for p in (REPO / "web").glob("*.html") if p.name != "404.html")
    uncovered = [n for n in live_pages if n not in stub.OLD_PAGES]
    check("the redirect stub covers every page the live site serves", not missing_old and not uncovered, f"missing {missing_old}; not in stub.OLD_PAGES: {uncovered}")
    sj = (st / "js" / "stub-redirect.js").read_text(encoding="utf-8")
    sm_ids = json.loads(re.search(r"var m=(\{.*?\});", sj).group(1))
    check("the stub maps every ski area #id to its new path", {a["id"] for a in areas} <= set(sm_ids) and all(v.startswith(prefix + "/") for v in sm_ids.values()), f"{info['ids']} ids")
    stub_hits = [p.name for p, t in scan_text(st) if any(h in t for h in OLD_HOSTS)]
    check("the stub itself contains no old host and no inline script", not stub_hits and not any("<script>" in t for _, t in scan_text(st)), "; ".join(stub_hits))
    if keep is None:
        shutil.rmtree(tmp, ignore_errors=True)
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--origin", default="https://snowwx.example")
    ap.add_argument("--base", default="")
    ap.add_argument("--keep", default=None)
    a = ap.parse_args(argv)
    res = run(a.origin, a.base.rstrip("/"), Path(a.keep) if a.keep else None)
    for name, ok, detail in res:
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))
    return 0 if all(ok for _, ok, _ in res) else 1


if __name__ == "__main__":
    sys.exit(main())
