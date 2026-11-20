"""W2 prerendered pages (pipeline/pages.py): content, canonical, JSON-LD, sitemap, redirects, and the disabled flag."""

import json

from pipeline import pages

A = {"id": "alta-ski-area", "name": "Alta Ski Area", "state": "UT", "region": "Wasatch", "summit": {"lat": 40.59, "lon": -111.63, "elev_ft": 10550},
     "base": {"lat": 40.58, "lon": -111.64, "elev_ft": 8530}}
CFG = {"site": {"origin": "https://example.test", "base_path": "/snow-wx"}, "pages": {"enabled": False}}
DOC = {"summary": {"tag": "Storm cycle", "sentence": "Multi-day storm: likely 24–26 in at the summit over the next 72 h.", "bullets": ["Wind <b>x</b>"]},
       "points": {"summit": {"totals": {"72h": {"snow_in": 28.5}}}}}


def test_page_has_title_description_h1_canonical_og_and_jsonld():
    h = pages.render_page(A, DOC, CFG)
    assert "<title>Alta Ski Area snow forecast (UT) · Snow-Wx</title>" in h and "<h1>Alta Ski Area snow forecast</h1>" in h
    assert 'name="description" content="Multi-day storm: likely 24–26 in at the summit over the next 72 h."' in h
    assert 'rel="canonical" href="https://example.test/snow-wx/ski/ut/alta-ski-area/"' in h and 'property="og:url"' in h
    ld = json.loads(h.split('application/ld+json">')[1].split("</script>")[0])
    assert ld["@type"] == "WebPage" and ld["about"]["@type"] == "Place" and ld["about"]["geo"]["latitude"] == 40.59
    assert "&lt;b&gt;" in h and "about 28 in" in h and 'href="/snow-wx/area.html#alta-ski-area"' in h      # escaped; links to the app


def test_page_without_points_uses_a_generic_description():
    assert "Snow forecast, snow level" in pages.render_page(A, None, CFG)


def test_sitemap_robots_redirect_and_flag(tmp_path):
    assert "https://example.test/snow-wx/ski/ut/alta-ski-area/" in pages.sitemap(CFG, [A])
    assert "Sitemap: https://example.test/snow-wx/sitemap.xml" in pages.robots(CFG)
    assert '"alta-ski-area":"/snow-wx/ski/ut/alta-ski-area/"' in pages.redirect_js([A], "/snow-wx")
    (tmp_path / "data" / "points").mkdir(parents=True)
    (tmp_path / "data" / "ski_areas.json").write_text(json.dumps({"areas": [A]}), encoding="utf-8")
    (tmp_path / "area.html").write_text("<html><head></head></html>", encoding="utf-8")
    assert pages.run(CFG, tmp_path) == 0
    assert not (tmp_path / "ski").exists() and not (tmp_path / "sitemap.xml").exists()      # flag off: nothing changes
    assert "pages.enabled" not in (tmp_path / "area.html").read_text(encoding="utf-8")
    on = {**CFG, "pages": {"enabled": True}}
    assert pages.run(on, tmp_path) == 0
    assert (tmp_path / "ski" / "ut" / "alta-ski-area" / "index.html").exists() and (tmp_path / "robots.txt").exists()
    area = (tmp_path / "area.html").read_text(encoding="utf-8")
    assert '<script src="js/id-redirect.js"></script>' in area and "<script>" not in area and area.count("id-redirect.js") == 1      # a file, never an inline script (CSP)
    assert "old #id links go to the indexable path" in (tmp_path / "js" / "id-redirect.js").read_text(encoding="utf-8")
    assert pages.run(on, tmp_path) == 0 and (tmp_path / "area.html").read_text(encoding="utf-8").count("id-redirect.js") == 1      # idempotent
    assert pages.run({"site": {}, "pages": {"enabled": True}}, tmp_path) == 1           # canonical needs site.origin
