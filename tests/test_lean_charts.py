"""dev22 guards: the site is NBM-only (no 'NWS official' choice anywhere), and every chart module's 'How it works' link lands on an existing About anchor."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def text_files():
    for p in WEB.rglob("*"):
        if p.is_file() and p.suffix in (".html", ".js", ".css") and "vendor" not in p.parts:
            yield p


def test_no_nws_official_toggle_or_wording_in_the_site():
    bad = []
    for p in text_files():
        t = p.read_text(encoding="utf-8", errors="replace")
        for needle in ("NWS official", "data-src", 'aria-label="Forecast source"', "data/ndfd/", "NWS blend"):
            if needle in t:
                bad.append((str(p.relative_to(ROOT)), needle))
    assert bad == [], bad


def test_alerts_and_hazard_wording_is_still_there():
    area = (WEB / "js" / "area.js").read_text(encoding="utf-8")
    assert "NWS alerts not available" in area and "forecast.weather.gov" in area            # alerts and the NWS point-forecast LINK stay
    assert "afdSection" in area


def about_ids():
    return set(re.findall(r'\bid="([\w-]+)"', (WEB / "about.html").read_text(encoding="utf-8")))


def test_every_how_it_works_anchor_exists_in_about():
    ids = about_ids()
    area = (WEB / "js" / "area.js").read_text(encoding="utf-8")
    used = set(re.findall(r'about\.html#([\w-]+)', area)) | set(re.findall(r'srcLine\("([\w-]+)"', area)) | set(re.findall(r'how\("([\w-]+)"\)', area))
    assert used, "no About anchors found in area.js"
    # the W7 wind-exposure flag is OFF and its About section is written when the reviewer enables it (a pre-existing anchor, reported in the dev22 notes)
    missing = sorted(a for a in used if a not in ids and a != "wind-exposure")
    assert missing == [], f"area.js links to About anchors that do not exist: {missing}"
    for a in ("snowfall-by-day", "accumulated-snow", "snow-ratio", "chance-of", "snow-level", "precip-by-model", "ensemble", "hour-by-hour"):
        assert a in ids and a in used, a                                                    # one anchored section per chart, each linked from its module


def test_chart_modules_have_one_source_line_and_no_long_notes():
    area = (WEB / "js" / "area.js").read_text(encoding="utf-8")
    for note in ("period-note", "acc-note", "slr-note", "ex-note", "sl-note", "mm-note", "met-note"):
        assert f'id="{note}"' in area and 'class="note src"' in area
    assert "NBM's forecast snow ratio over the whole forecast: the line is the median" not in area      # the long grey paragraph moved to About


def test_the_ecmwf_panels_keep_a_one_line_credit_and_the_gefs_credit():
    area = (WEB / "js" / "area.js").read_text(encoding="utf-8")
    assert "Contains ECMWF open data" in area and "CC BY 4.0" in area and "adapted" in area
    assert "NOAA/NCEP GEFS" in area and "public domain" in area
    about = (WEB / "about.html").read_text(encoding="utf-8")
    assert 'adapted from "ECMWF IFS 15-day Forecast Data" by ECMWF' in about                  # the full statement is kept in About


def test_about_keeps_the_text_that_left_the_charts():
    about = re.sub(r"\s+", " ", (WEB / "about.html").read_text(encoding="utf-8"))
    for phrase in ("partial day — expected amount, no range", "a hatched \"dry: ratio not shown\" strip", "calibrated separately from the expected-amount bars",
                   "Below the line precipitation falls as rain", "6.5 °C per km", "no control member", "never interpolated", "within ±25% of the median total",
                   "Dense below 10:1, Medium 10–15, Blower 15 and up", "narrower last bar"):
        assert phrase in about, phrase


# ---------------------------------------------------------------- dev23: the verification panel is NBM only too (NDFD stays in the archive, never on the surface)
NDFD_WORDS = re.compile(r"ndfd|nws official|nws \(|the nws forecast|national digital forecast", re.I)


def test_verification_panel_markup_has_no_ndfd_or_nws_forecast_wording():
    ui = (WEB / "js" / "verification-ui.js").read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", ui)                                                     # comments may explain the history; strings and code may not name it
    assert not NDFD_WORDS.search(code), NDFD_WORDS.search(code)
    area = (WEB / "js" / "area.js").read_text(encoding="utf-8")
    chart = area[area.index("function verifyChart"):area.index("function snowLevelChart")]
    assert not NDFD_WORDS.search(chart) and "d.ndfd" not in chart
    about = (WEB / "about.html").read_text(encoding="utf-8")
    sec = about[about.index('<section id="scorecard"'):about.index("</section>", about.index('<section id="scorecard"'))]
    assert not NDFD_WORDS.search(sec)


def test_verification_payload_has_no_ndfd_even_when_the_archive_has_ndfd_rows(tmp_path):
    """the archive keeps NDFD rows (fixture below has them); the files the panel reads (verification.json, per-site files, run.json) must carry none of it"""
    import json
    from datetime import datetime, timezone

    from pipeline import verify
    from tests.test_verify_ui import make_archive
    arch = tmp_path / "arch"
    arch.mkdir()
    make_archive(arch, 16, 2)
    assert (arch / "ndfd-202612.csv.gz").exists()                                              # NDFD really is in the archive
    out = tmp_path / "models"
    res = verify.ci_run(arch, out, {"verification": {}, "verification_ui": {"min_days": 14, "min_pairs": 30}}, now=datetime(2026, 12, 20, 15, tzinfo=timezone.utc))
    assert res["new"] is True and res["stations_ready"] == 1
    files = sorted((out / "verify").rglob("*.json"))
    assert {f.name for f in files} == {"verification.json", "run.json", "1000_OR_SNTL.json"}
    for f in files:
        txt = f.read_text(encoding="utf-8")
        assert not NDFD_WORDS.search(txt) and '"nws' not in txt.lower(), f.name
        assert "ndfd" not in json.dumps(json.loads(txt)).lower(), f.name
