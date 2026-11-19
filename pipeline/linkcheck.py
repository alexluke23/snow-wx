"""Whole-site link check (dev18 Part 2d) over the GENERATED site folder (build/): every internal link and asset must exist (and `#fragment` ids must exist in static
pages), every outbound link is checked politely (HEAD, a streamed GET only when HEAD is refused, one request per URL, a pause per host), and robots / canonical /
sitemap / title / description sanity is reported. Pure parsing + checks are tested offline with fakes (tests/test_linkcheck.py).

    python -m pipeline linkcheck --build build                 # internal links + SEO sanity only (offline)
    python -m pipeline linkcheck --build build --outbound      # + every distinct https link found in the pages
    python -m pipeline linkcheck --build build --outbound --data   # + links in data files (resort sites, avalanche centers, permit pages, webcams)

Exit code 0 = no broken internal link and no dead outbound link; 1 otherwise (SEO findings are reported, not fatal, unless --strict).
"""

from __future__ import annotations

import json
import logging
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urldefrag, urlparse

from .webcams import check_url, host_of

log = logging.getLogger("snow-wx.linkcheck")
SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "sms:", "blob:")
# hosts that rate-limit politely-spaced requests: longer pause between requests (seconds). A 429/403 is "could not verify" (ok: None), never "dead".
HOST_PAUSE = {"fs.usda.gov": 4.0}
UNVERIFIABLE = (403, 429)
IGNORED_REL = ("preconnect", "dns-prefetch", "preload", "modulepreload")                 # not pages: connection hints
# pages whose #fragment is built by JavaScript (hash routing): the fragment is not an element id there
DYNAMIC_HASH_PAGES = {"area.html", "index.html", "finder.html", "models.html", "mine.html", "status.html"}


class Page(HTMLParser):
    """links, assets, ids, title, meta description, canonical and robots meta of one HTML document"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []      # (kind, url) kind: a | link | script | img | form
        self.ids: set[str] = set()
        self.title, self.description, self.canonical, self.robots = "", "", "", ""
        self.base = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if a.get("name") and tag == "a":
            self.ids.add(a["name"])
        if tag == "title":
            self._in_title = True
        elif tag == "base" and a.get("href"):
            self.base = a["href"]
        elif tag == "a" and a.get("href"):
            self.links.append(("a", a["href"]))
        elif tag == "link" and a.get("href"):
            rel = (a.get("rel") or "").lower()
            if "canonical" in rel:
                self.canonical = a["href"]
            elif any(x in rel for x in IGNORED_REL):
                pass
            elif "icon" not in rel or not a["href"].startswith("data:"):
                self.links.append(("link", a["href"]))
        elif tag in ("script", "img", "source", "iframe") and a.get("src"):
            self.links.append((tag if tag != "source" else "img", a["src"]))
        elif tag == "meta":
            n = (a.get("name") or "").lower()
            if n == "description":
                self.description = a.get("content") or ""
            elif n == "robots":
                self.robots = (a.get("content") or "").lower()

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def parse(html: str) -> Page:
    p = Page()
    p.feed(html)
    return p


def html_files(build: Path) -> list[Path]:
    return sorted(p for p in Path(build).rglob("*.html") if "vendor" not in p.parts and "node_modules" not in p.parts)


def resolve_internal(build: Path, page: Path, url: str, base: str = "") -> tuple[Path | None, str]:
    """-> (target file under build, fragment) for a relative / root-relative link; (None, "") for external or non-file links"""
    if not url or url.startswith(SKIP_SCHEMES) or re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I) or url.startswith("//"):
        return None, ""
    clean, frag = urldefrag(url)
    clean = unquote(clean.split("?")[0])
    if clean == "":
        return page, frag
    if clean.startswith("/"):
        target = Path(build) / clean.lstrip("/")
    else:
        base_dir = page.parent
        if base:                                               # <base href="/snow-wx/">: relative links start at the base (a root-relative base maps to the build root)
            b = urlparse(base).path
            base_dir = Path(build) / b.lstrip("/") if b.startswith("/") else base_dir / b
        target = base_dir / clean
    if target.is_dir() or clean.endswith("/"):
        target = target / "index.html"
    return target, frag


def check_internal(build: Path, base_path: str = "") -> dict:
    """{'pages': n, 'links': n, 'broken': [(page, url, why)], 'seo': [...]}. `base_path` ("/snow-wx") is stripped from root-relative links first."""
    build = Path(build)
    broken, seo, nlinks = [], [], 0
    docs = {p: parse(p.read_text(encoding="utf-8", errors="ignore")) for p in html_files(build)}
    for page, doc in docs.items():
        rel = page.relative_to(build).as_posix()
        for kind, url in doc.links:
            nlinks += 1
            u = url
            if base_path and u.startswith(base_path + "/"):
                u = u[len(base_path):]
            base = doc.base.replace("__BASE_HREF__", "/")
            if base_path and (base == base_path + "/" or base.startswith(base_path + "/")):
                base = base[len(base_path):] or "/"                                      # the site's own folder maps to the build root
            target, frag = resolve_internal(build, page, u, base)
            if target is None:
                continue
            if not target.exists():
                broken.append((rel, url, "missing file"))
                continue
            if frag and kind == "a" and target.suffix == ".html":
                if target.name in DYNAMIC_HASH_PAGES:
                    continue
                tdoc = docs.get(target) or parse(target.read_text(encoding="utf-8", errors="ignore"))
                if frag not in tdoc.ids:
                    broken.append((rel, url, f"no element id '{frag}' in {target.name}"))
        if not doc.title.strip():
            seo.append((rel, "no <title>"))
        if not doc.description.strip():
            seo.append((rel, "no meta description"))
        if "noindex" in doc.robots and doc.canonical:
            seo.append((rel, "noindex page with a canonical tag"))
    return {"pages": len(docs), "links": nlinks, "broken": broken, "seo": seo}


def check_seo_files(build: Path, origin: str) -> list[str]:
    """robots.txt / sitemap.xml / canonical sanity when those files exist (they are built by `pipeline pages`, flag-gated): returns findings"""
    build, out = Path(build), []
    origin = origin.rstrip("/")
    robots, sitemap = build / "robots.txt", build / "sitemap.xml"
    if robots.exists():
        txt = robots.read_text(encoding="utf-8", errors="ignore")
        m = re.findall(r"(?im)^sitemap:\s*(\S+)", txt)
        if not m:
            out.append("robots.txt has no Sitemap: line")
        for u in m:
            if not u.startswith(origin):
                out.append(f"robots.txt Sitemap {u} is not on the site origin {origin}")
        if re.search(r"(?im)^disallow:\s*/\s*$", txt):
            out.append("robots.txt disallows the whole site")
    if sitemap.exists():
        locs = re.findall(r"<loc>([^<]+)</loc>", sitemap.read_text(encoding="utf-8", errors="ignore"))
        if len(locs) != len(set(locs)):
            out.append("sitemap.xml has duplicate URLs")
        for u in locs:
            if not u.startswith(origin):
                out.append(f"sitemap URL not on the origin: {u}")
                continue
            path = urlparse(u).path
            rel = path[len(urlparse(origin).path):].lstrip("/") if path.startswith(urlparse(origin).path) else path.lstrip("/")
            f = build / (rel + "index.html" if rel.endswith("/") or rel == "" else rel)
            if not f.exists():
                out.append(f"sitemap URL has no page in the build: {u}")
            elif f.suffix == ".html" and "noindex" in parse(f.read_text(encoding="utf-8", errors="ignore")).robots:
                out.append(f"sitemap lists a noindex page: {u}")
    for p in html_files(build):
        doc = parse(p.read_text(encoding="utf-8", errors="ignore"))
        if doc.canonical and not doc.canonical.startswith(origin):
            out.append(f"{p.relative_to(build).as_posix()}: canonical {doc.canonical} is not on the origin")
    return out


def outbound_urls(build: Path) -> dict[str, list[str]]:
    """{https url (no fragment): [pages]} for every outbound link in the HTML pages"""
    out: dict[str, list[str]] = {}
    for p in html_files(build):
        rel = p.relative_to(build).as_posix()
        for kind, url in parse(p.read_text(encoding="utf-8", errors="ignore")).links:
            if url.startswith("https://") or url.startswith("http://"):
                out.setdefault(urldefrag(url)[0], []).append(rel)
    return out


def data_urls(build: Path) -> dict[str, list[str]]:
    """outbound links that live in the generated DATA files rather than the HTML: resort sites, permit pages, avalanche-center forecasts, webcam links"""
    build, out = Path(build), {}

    def add(u, where):
        if isinstance(u, str) and u.startswith("http"):
            out.setdefault(urldefrag(u)[0], []).append(where)
    d = build / "data"
    for name, key in (("ski_areas.json", "areas"), ("rec_points.json", "areas")):
        f = d / name
        if f.exists():
            for a in json.loads(f.read_text(encoding="utf-8")).get(key, []):
                add(a.get("url"), name)
                add((a.get("permit_check") or {}).get("url"), name)
    f = d / "avalanche_ratings.json"
    if f.exists():
        js = json.loads(f.read_text(encoding="utf-8"))
        for z in (js.values() if isinstance(js, dict) else js):           # {zone id: {name, link, ...}}
            if isinstance(z, dict):
                add(z.get("link"), "avalanche_ratings.json")
    f = d / "webcams.json"
    if f.exists():
        for items in json.loads(f.read_text(encoding="utf-8")).values():
            for e in items:
                add(e.get("url"), "webcams.json")
    return out


def check_outbound(urls: dict[str, list[str]], session, pause: float = 1.0, sleep=time.sleep, limit: int | None = None) -> list[dict]:
    """one request per distinct URL, at least `pause` s between requests to the same host (HEAD, one streamed GET when HEAD is refused)"""
    rows, last = [], {}
    for u in sorted(urls)[: limit or None]:
        h = host_of(u)
        gap = max(pause, *(v for k, v in HOST_PAUSE.items() if h == k or h.endswith("." + k)), 0)
        wait = gap - (time.monotonic() - last.get(h, -1e9))
        if wait > 0:
            sleep(wait)
        r = check_url(session, u)
        last[h] = time.monotonic()
        r["pages"] = sorted(set(urls[u]))[:3]
        if r["status"] in UNVERIFIABLE:
            r["ok"] = None                                                       # blocked / rate limited: could not verify (a person can open it), not dead
        else:
            r["ok"] = r["status"] is not None and 200 <= r["status"] < 400
        rows.append(r)
    return rows


def run(build: Path, outbound: bool, data: bool, session, origin: str = "", base_path: str = "", report: Path | None = None, strict: bool = False,
        pause: float = 1.0, sleep=time.sleep) -> int:
    res = check_internal(build, base_path)
    seo = [f"{p}: {m}" for p, m in res["seo"]] + (check_seo_files(build, origin) if origin else [])
    for p, u, why in res["broken"]:
        log.error("BROKEN %s -> %s (%s)", p, u, why)
    for s in seo:
        log.warning("SEO %s", s)
    log.info("linkcheck: %d pages, %d links, %d broken internal, %d SEO findings", res["pages"], res["links"], len(res["broken"]), len(seo))
    dead = []
    rows = []
    if outbound or data:
        urls = outbound_urls(build) if outbound else {}
        if data:
            for u, w in data_urls(build).items():
                urls.setdefault(u, []).extend(w)
        rows = check_outbound(urls, session, pause=pause, sleep=sleep)
        dead = [r for r in rows if r["ok"] is False]
        unverified = [r for r in rows if r["ok"] is None]
        for r in dead:
            log.warning("DEAD %s -> %s %s (on %s)", r["url"], r["status"], r["error"] or "", ", ".join(r["pages"]))
        for r in unverified:
            log.info("could not verify (HTTP %s: blocked or rate limited) %s", r["status"], r["url"])
        log.info("outbound: %d distinct URLs, %d dead, %d could not be verified (403/429)", len(rows), len(dead), len(unverified))
    if report:
        from .common import write_json
        write_json(report, {"internal": res, "seo": seo, "outbound": rows})
    return 1 if (res["broken"] or dead or (strict and seo)) else 0
