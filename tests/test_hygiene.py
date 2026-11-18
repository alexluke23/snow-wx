"""Repo hygiene: no e-mail address hard-coded in the web code (owner Nov 17): the feedback address lives only in config/settings.yml."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_no_email_address_in_web_pages_or_scripts():
    pat = re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", re.I)
    hits = []
    for f in list((ROOT / "web").glob("*.html")) + list((ROOT / "web" / "js").rglob("*.js")) + list((ROOT / "web" / "css").glob("*.css")):
        for m in pat.finditer(f.read_text(encoding="utf-8")):
            hits.append(f"{f.name}: {m.group(0)}")
    assert not hits, hits


def test_feedback_links_use_the_shared_config_script():
    for f in ROOT.joinpath("web").glob("*.html"):
        s = f.read_text(encoding="utf-8")
        if 'class="site-feedback"' in s:
            assert "data-mailto" in s and "js/site-config.js" in s, f.name


def test_no_user_facing_link_points_at_the_nws_api_alert_record():
    """owner-reported bug (dev16): the hazard popup linked to api.weather.gov/alerts/urn:oid:... (raw GeoJSON-LD). No generated HTML/JS may use an
    api.weather.gov alert URL as an href or link target; the alert id may only be used for a lookup."""
    import re
    bad = re.compile(r"""(href\s*=\s*["'`][^"'`]*api\.weather\.gov|\.href\s*=\s*[^;]*api\.weather\.gov)""", re.I)
    hits = []
    for f in list((ROOT / "web").glob("*.html")) + list((ROOT / "web" / "js").rglob("*.js")) + [ROOT / "pipeline" / "pages.py"]:
        for ln, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if bad.search(line):
                hits.append(f"{f.name}:{ln}: {line.strip()[:120]}")
    assert not hits, hits
    hz = (ROOT / "web" / "js" / "hazards.js").read_text(encoding="utf-8")
    assert not re.search(r"\.href\s*=\s*[^;]*\.url", hz) and "alert data" not in hz
    assert "innerHTML" not in hz.split("function buildPopup")[1].split("async function fetchJSON")[0]
    # and the prerendered pages (pipeline/pages.py) never emit one for any area
    from pipeline import pages
    area = {"id": "x", "name": "X", "state": "UT", "region": "r", "summit": {"lat": 1, "lon": 2, "elev_ft": 9000}, "base": {"lat": 1, "lon": 2, "elev_ft": 8000}}
    html = pages.render_page(area, {"summary": {"tag": "Alert active", "sentence": "NWS alert in effect: High Wind Warning."}}, {"site": {"origin": "https://e.test"}})
    assert "api.weather.gov" not in html
