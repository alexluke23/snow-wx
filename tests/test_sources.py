"""dev18 Part 2a/2b: the Sources register (config/sources.yml) covers every external host the code or config mentions, every entry has a licence and a credit, the
generated pages (sources / privacy / terms / disclaimer / 404) are up to date, and the privacy page matches what the code does (storage keys, third-party requests,
no cookies). Offline."""
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import gen_site_pages as G  # noqa: E402

SRC = yaml.safe_load((REPO / "config" / "sources.yml").read_text(encoding="utf-8"))
HOST_RX = re.compile(r"https?://((?:\{[a-z]\}\.)?[A-Za-z0-9][A-Za-z0-9.-]*\.[A-Za-z]{2,})")


def covered(host: str, entries: list[str]) -> bool:
    host = host.lower().removeprefix("{s}.")
    return any(host == e or host.endswith("." + e) for e in entries)


def code_hosts():
    files = [p for pat in ("pipeline/**/*.py", "web/*.html", "web/js/*.js", "web/js/charts/*.js", "web/css/*.css", "config/*.yml") for p in REPO.glob(pat)
             if p.name not in ("webcams.yml", "sources.yml") and p.name not in ("sources.html", "privacy.html", "terms.html", "disclaimer.html", "404.html")]
    out = {}
    for p in files:
        for h in HOST_RX.findall(p.read_text(encoding="utf-8", errors="ignore")):
            out.setdefault(h.lower(), set()).add(p.relative_to(REPO).as_posix())
    return out


def test_every_external_host_in_code_and_config_has_a_source_entry():
    known = [h for s in SRC["sources"] for h in (s.get("hosts") or []) + (s.get("browser") or [])] + [i["host"] for i in SRC["ignore_hosts"]]
    missing = {h: sorted(f)[:2] for h, f in code_hosts().items() if not covered(h, known)}
    assert not missing, f"hosts without a Sources entry (add them to config/sources.yml hosts/browser, or to ignore_hosts with a reason): {missing}"


def test_webcam_hosts_are_covered_by_one_link_out_entry():
    """webcam pages are only ever linked (never requested by a page), so one `links` entry covers them all; no webcam host may appear in a browser: list"""
    from pipeline import webcams as W
    entry = next(s for s in SRC["sources"] if s["id"] == "webcam-links")
    assert entry["kind"] == "links" and not entry.get("browser")
    browser = {h for s in SRC["sources"] for h in (s.get("browser") or [])}
    assert not browser & {W.host_of(e["url"]) for items in W.load()["areas"].values() for e in items}


def test_every_entry_has_a_licence_and_a_credit_and_ids_are_unique():
    ids = [s["id"] for s in SRC["sources"]]
    assert len(ids) == len(set(ids))
    kinds = {k for k, _ in G.KINDS}
    for s in SRC["sources"]:
        assert s["kind"] in kinds, s["id"]
        assert s["name"] and s["role"] and s["licence"], s["id"]
        assert s["licence_url"].startswith("https://"), s["id"]
        assert s["kind"] in ("hosting",) or s["credit"], f"{s['id']}: needs credit text"
        for h in (s.get("hosts") or []) + (s.get("browser") or []):
            assert "/" not in h and h == h.lower(), (s["id"], h)


def test_required_sources_and_credit_texts_are_present():
    by = {s["id"]: s for s in SRC["sources"]}
    for must in ("noaa-nws", "nohrsc", "nrcs-snotel", "iem", "usgs", "avalanche-org", "osm", "openfreemap", "ecmwf", "plotly", "leaflet", "hosting"):
        assert must in by, must
    assert "CC BY 4.0" in by["ecmwf"]["licence"] and "ADAPTED" in by["ecmwf"]["licence"] and "Adapted from" in by["ecmwf"]["credit"]
    assert "ODbL" in by["osm"]["licence"] and "OpenStreetMap contributors" in by["osm"]["credit"]
    assert "OpenMapTiles" in by["openfreemap"]["credit"] and "OpenStreetMap" in by["openfreemap"]["credit"]
    assert "public domain" in by["noaa-nws"]["licence"].lower() and "NOAA" in by["noaa-nws"]["credit"]
    assert "NRCS" in by["nrcs-snotel"]["credit"] and "USGS" in by["usgs"]["credit"] or "U.S. Geological Survey" in by["usgs"]["credit"]
    assert by["avalanche-org"].get("verify") is True                                       # commercial terms still to be confirmed (PLAN §10)


def test_generated_pages_are_up_to_date_and_show_every_credit():
    assert G.main(["--check"]) == 0, "run: python tools/gen_site_pages.py"
    page = (REPO / "web" / "sources.html").read_text(encoding="utf-8")
    import html
    for s in SRC["sources"]:
        assert html.escape(s["name"]) in page, s["id"]
        if s.get("credit"):
            assert html.escape(s["credit"]) in page, s["id"]
    assert "ODbL" in page or "Open Database Licence" in page


def test_legal_pages_are_drafts_noindex_and_say_the_important_things():
    for name in ("disclaimer", "terms", "privacy"):
        txt = (REPO / "web" / f"{name}.html").read_text(encoding="utf-8")
        assert 'class="draft-banner"' in txt and "<b>DRAFT</b>" in txt and 'name="robots" content="noindex"' in txt and "not legal advice" in txt, name
    d = (REPO / "web" / "disclaimer.html").read_text(encoding="utf-8").lower()
    assert "not for avalanche" in d and "avalanche.org" in d and "weather.gov" in d and "full forecast" in d and "911" in d
    p = (REPO / "web" / "privacy.html").read_text(encoding="utf-8")
    assert "sets no cookies" in p and "no accounts" in p and "analytics" in p and "Do Not Track" in p and "Global Privacy Control" in p


def test_privacy_page_lists_every_storage_key_the_code_uses_and_no_cookies_are_written():
    keys = set()
    for p in (REPO / "web" / "js").glob("*.js"):
        txt = p.read_text(encoding="utf-8")
        assert "document.cookie" not in txt, f"{p.name} writes a cookie"
        keys |= set(re.findall(r"[\"'](snowwx\.[a-z.]+)[\"']", txt))
    listed = {k for k, *_ in G.STORAGE}
    assert keys <= listed, f"storage keys the page does not disclose: {sorted(keys - listed)}"
    page = (REPO / "web" / "privacy.html").read_text(encoding="utf-8")
    for k in listed:
        assert f"<code>{k}</code>" in page
    assert not (REPO / "web" / "js" / "analytics.js").exists() or "enabled" in (REPO / "web" / "js" / "analytics.js").read_text(encoding="utf-8")


def test_privacy_page_lists_every_browser_side_third_party_host():
    hosts = [h for s in SRC["sources"] for h in (s.get("browser") or [])]
    assert {"basemap.nationalmap.gov", "tiles.openfreemap.org", "cdn.plot.ly", "api.weather.gov"} <= set(hosts)
    page = (REPO / "web" / "privacy.html").read_text(encoding="utf-8")
    for h in hosts:
        assert f'<th scope="row">{h}</th>' in page
    for s in SRC["sources"]:
        if s.get("browser"):
            assert s.get("browser_when"), f"{s['id']}: say WHEN the browser makes the request"


def test_every_page_footer_links_to_sources_disclaimer_privacy_and_terms():
    for name in ("index", "area", "finder", "mine", "models", "about", "status", "sources", "disclaimer", "privacy", "terms"):
        footer = (REPO / "web" / f"{name}.html").read_text(encoding="utf-8").split("<footer")[1]
        for href in ("sources.html", "disclaimer.html", "privacy.html", "terms.html", "status.html"):
            assert f'href="{href}"' in footer, f"{name}.html footer lacks {href}"


def test_404_page_base_follows_config(tmp_path):
    from pipeline.__main__ import fill_404_base
    (tmp_path / "404.html").write_text((REPO / "web" / "404.html").read_text(encoding="utf-8"), encoding="utf-8")
    fill_404_base(tmp_path, {"site": {"base_path": "/snow-wx"}})
    assert '<base href="/snow-wx/">' in (tmp_path / "404.html").read_text(encoding="utf-8")
    (tmp_path / "404.html").write_text((REPO / "web" / "404.html").read_text(encoding="utf-8"), encoding="utf-8")
    fill_404_base(tmp_path, {"site": {"base_path": ""}})
    assert '<base href="/">' in (tmp_path / "404.html").read_text(encoding="utf-8") and "__BASE_HREF__" not in (tmp_path / "404.html").read_text(encoding="utf-8")
