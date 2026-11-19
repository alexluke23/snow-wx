"""Whole-site link check (pipeline/linkcheck.py), offline: HTML parsing, internal links and #ids, <base> handling (the 404 page), robots/sitemap/canonical sanity,
outbound checks with fakes (HEAD first, per-host pause, soft error pages), data-file links, exit codes. Plus: the real web/ folder has no broken internal link."""
import json
from pathlib import Path

from pipeline import linkcheck as L

REPO = Path(__file__).resolve().parents[1]


def site(tmp_path, files: dict[str, str]) -> Path:
    for rel, txt in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(txt, encoding="utf-8")
    return tmp_path


def doc(body="", head="", title="T", desc="d"):
    return f'<!DOCTYPE html><html><head><title>{title}</title><meta name="description" content="{desc}">{head}</head><body>{body}</body></html>'


def test_parse_collects_links_ids_title_description_canonical_robots_and_base():
    p = L.parse(doc('<a href="x.html#a">x</a><img src="i.png"><script src="s.js"></script><p id="sec"></p><a name="old"></a>',
                    '<link rel="stylesheet" href="c.css"><link rel="icon" href="data:,"><link rel="canonical" href="https://e.test/p/"><meta name="robots" content="NoIndex"><base href="/b/">'))
    assert [k for k, _ in p.links] == ["link", "a", "img", "script"] and p.ids == {"sec", "old"}
    assert p.title == "T" and p.description == "d" and p.canonical == "https://e.test/p/" and p.robots == "noindex" and p.base == "/b/"


def test_internal_links_files_fragments_and_assets(tmp_path):
    b = site(tmp_path, {
        "index.html": doc('<a href="about.html#methods">m</a><a href="about.html#nope">n</a><a href="gone.html">g</a><a href="area.html#some-id">dyn</a>'
                          '<a href="https://x.example/">ext</a><a href="mailto:a@b.c">mail</a><link rel="stylesheet" href="css/s.css"><script src="js/missing.js"></script><a href="#top">top</a><p id="top"></p>'),
        "about.html": doc('<h2 id="methods">m</h2>'), "area.html": doc(), "css/s.css": "",
    })
    res = L.check_internal(b)
    broken = {(p, u): why for p, u, why in res["broken"]}
    assert broken == {("index.html", "about.html#nope"): "no element id 'nope' in about.html", ("index.html", "gone.html"): "missing file", ("index.html", "js/missing.js"): "missing file"}
    assert res["pages"] == 3 and res["links"] >= 8                                          # hash-routed pages (area.html#id) are not id-checked


def test_root_relative_links_with_a_base_path_and_directory_index(tmp_path):
    b = site(tmp_path, {"index.html": doc('<a href="/snow-wx/ski/ut/alta/">alta</a><a href="/snow-wx/css/s.css">c</a><a href="/other/">o</a>'), "ski/ut/alta/index.html": doc(), "css/s.css": ""})
    res = L.check_internal(b, base_path="/snow-wx")
    assert res["broken"] == [("index.html", "/other/", "missing file")]


def test_404_page_base_is_honoured(tmp_path):
    b = site(tmp_path, {"404.html": doc('<a href="index.html">home</a><link rel="stylesheet" href="css/s.css">', '<base href="/snow-wx/">'), "index.html": doc(), "css/s.css": ""})
    assert L.check_internal(b, base_path="/snow-wx")["broken"] == []
    assert L.check_internal(b)["broken"]                                                    # without the base path the page really would be broken


def test_seo_findings_title_description_and_noindex_canonical(tmp_path):
    b = site(tmp_path, {"a.html": doc(title="", desc=""), "b.html": doc(head='<meta name="robots" content="noindex"><link rel="canonical" href="https://e.test/b">')})
    seo = dict.fromkeys(L.check_internal(b)["seo"])
    assert ("a.html", "no <title>") in seo and ("a.html", "no meta description") in seo and ("b.html", "noindex page with a canonical tag") in seo


def test_robots_sitemap_and_canonical_sanity(tmp_path):
    origin = "https://e.test/snow-wx"
    good = site(tmp_path / "good", {"robots.txt": f"User-agent: *\nAllow: /\nSitemap: {origin}/sitemap.xml\n",
                                    "sitemap.xml": f"<urlset><url><loc>{origin}/ski/ut/alta/</loc></url><url><loc>{origin}/about.html</loc></url></urlset>",
                                    "ski/ut/alta/index.html": doc(head=f'<link rel="canonical" href="{origin}/ski/ut/alta/">'), "about.html": doc()})
    assert L.check_seo_files(good, origin) == []
    bad = site(tmp_path / "bad", {"robots.txt": "User-agent: *\nDisallow: /\nSitemap: https://other.test/sitemap.xml\n",
                                  "sitemap.xml": f"<urlset><url><loc>{origin}/gone.html</loc></url><url><loc>{origin}/gone.html</loc></url><url><loc>https://other.test/x</loc></url><url><loc>{origin}/n.html</loc></url></urlset>",
                                  "n.html": doc(head='<meta name="robots" content="noindex">'), "c.html": doc(head='<link rel="canonical" href="https://other.test/c">')})
    out = " | ".join(L.check_seo_files(bad, origin))
    for needle in ("not on the site origin", "disallows the whole site", "duplicate URLs", "not on the origin: https://other.test/x", "no page in the build", "noindex page", "canonical https://other.test/c"):
        assert needle in out, (needle, out)
    assert L.check_seo_files(tmp_path / "empty", origin) == []                              # no robots/sitemap (pages flag off) is not a finding


class R:
    def __init__(self, status=200, url=None):
        self.status_code, self.url = status, url

    def close(self):
        pass


class FakeSession:
    def __init__(self, routes=None):
        self.routes, self.calls = routes or {}, []

    def head(self, u, **k):
        self.calls.append(("HEAD", u))
        r = self.routes.get(u)
        if isinstance(r, Exception):
            raise r
        return r or R(200, u)

    def get(self, u, **k):
        assert k.get("stream") is True
        self.calls.append(("GET", u))
        r = self.routes.get(("GET", u)) or self.routes.get(u)                     # a GET answers like the HEAD route unless a ("GET", url) route says otherwise
        if isinstance(r, Exception):
            raise r
        return r or R(200, u)


def test_outbound_urls_dedupe_and_check_with_fakes_and_a_pause_per_host(tmp_path):
    b = site(tmp_path, {"a.html": doc('<a href="https://x.example/p#frag">1</a><a href="https://x.example/p">2</a><a href="https://y.example/">3</a><a href="https://x.example/q">4</a><a href="http://z.example/">5</a>'),
                        "sub/b.html": doc('<a href="https://y.example/">6</a>')})
    urls = L.outbound_urls(b)
    assert sorted(urls) == ["http://z.example/", "https://x.example/p", "https://x.example/q", "https://y.example/"] and urls["https://y.example/"] == ["a.html", "sub/b.html"]
    s = FakeSession({"https://x.example/q": R(404, "https://x.example/q"), "https://y.example/": RuntimeError("timeout")})
    sleeps = []
    rows = L.check_outbound(urls, s, pause=1.0, sleep=sleeps.append)
    by = {r["url"]: r for r in rows}
    assert by["https://x.example/q"]["ok"] is False and by["https://y.example/"]["error"].startswith("RuntimeError") and by["https://x.example/p"]["ok"] and by["http://z.example/"]["ok"]
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 1.0                                         # the second x.example request waits; other hosts do not
    assert [c for c in s.calls if c[0] == "HEAD"].__len__() == 4 and len(s.calls) == 5       # one HEAD per distinct URL; the 404 is confirmed by one GET (a server may mishandle HEAD)


def test_blocked_and_rate_limited_answers_are_unverified_not_dead_and_connection_hints_are_ignored(tmp_path):
    b = site(tmp_path, {"a.html": doc('<a href="https://x.example/blocked">1</a><a href="https://fs.usda.gov/a">2</a><a href="https://fs.usda.gov/b">3</a><a href="https://y.example/gone">4</a>',
                                      '<link rel="preconnect" href="https://cdn.example"><link rel="dns-prefetch" href="https://dns.example">')})
    urls = L.outbound_urls(b)
    assert "https://cdn.example" not in urls and "https://dns.example" not in urls
    s = FakeSession({"https://x.example/blocked": R(403, "x"), ("GET", "https://x.example/blocked"): R(403, "x"), "https://fs.usda.gov/a": R(429, "x"), "https://y.example/gone": R(404, "y")})
    sleeps = []
    rows = {r["url"]: r for r in L.check_outbound(urls, s, pause=1.0, sleep=sleeps.append)}
    assert rows["https://x.example/blocked"]["ok"] is None and rows["https://fs.usda.gov/a"]["ok"] is None and rows["https://y.example/gone"]["ok"] is False and rows["https://fs.usda.gov/b"]["ok"] is True
    assert any(3.0 < x <= 4.0 for x in sleeps)                                               # fs.usda.gov gets the longer 4 s gap
    assert L.run(b, True, False, FakeSession({"https://y.example/gone": R(404, "y")}), sleep=lambda x: None) == 1       # the 404 still fails the run ...
    only = site(tmp_path / "o", {"a.html": doc('<a href="https://x.example/blocked">1</a>')})
    assert L.run(only, True, False, FakeSession({"https://x.example/blocked": R(403, "x"), ("GET", "https://x.example/blocked"): R(403, "x")}), sleep=lambda x: None) == 0    # ... but a 403 alone does not


def test_data_file_links_are_collected(tmp_path):
    b = site(tmp_path, {"data/ski_areas.json": json.dumps({"areas": [{"url": "https://resort.example/"}, {"url": None}]}),
                        "data/rec_points.json": json.dumps({"areas": [{"url": "https://parks.example/x", "permit_check": {"url": "https://permit.example/"}}]}),
                        "data/avalanche_ratings.json": json.dumps({"1": {"name": "A", "link": "https://avy.example/a#top"}, "2": {"name": "B"}}),
                        "data/webcams.json": json.dumps({"alta": [{"url": "https://cam.example/"}]})})
    assert sorted(L.data_urls(b)) == ["https://avy.example/a", "https://cam.example/", "https://parks.example/x", "https://permit.example/", "https://resort.example/"]


def test_run_exit_codes_and_report(tmp_path):
    b = site(tmp_path / "ok", {"index.html": doc('<a href="https://x.example/">x</a>')})
    rep = tmp_path / "rep.json"
    assert L.run(b, True, False, FakeSession(), origin="https://e.test", report=rep, sleep=lambda s: None) == 0
    assert json.loads(rep.read_text(encoding="utf-8"))["outbound"][0]["ok"] is True
    assert L.run(b, True, False, FakeSession({"https://x.example/": R(500, "https://x.example/")}), sleep=lambda s: None) == 1       # a dead outbound link
    bad = site(tmp_path / "bad", {"index.html": doc('<a href="nope.html">x</a>')})
    assert L.run(bad, False, False, FakeSession()) == 1                                                                           # a broken internal link
    seo = site(tmp_path / "seo", {"index.html": doc(desc="")})
    assert L.run(seo, False, False, FakeSession()) == 0 and L.run(seo, False, False, FakeSession(), strict=True) == 1             # SEO findings fail only with --strict


def test_the_real_web_folder_has_no_broken_internal_link():
    res = L.check_internal(REPO / "web", base_path="/snow-wx")
    real = [b for b in res["broken"] if b[1] not in ("data/meta.json",)]
    assert real == [], real
    missing_desc = [p for p, m in res["seo"] if m == "no meta description"]
    assert not missing_desc, missing_desc
