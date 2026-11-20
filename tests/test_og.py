"""dev20 Part 1: share-card images (pipeline/og.py) and their og:image reference in pages.py (both behind flags)."""
import io
import json

import pytest
from PIL import Image

from pipeline import og, pages

CFG = {"site": {"name": "Placeholder Name", "tagline": "Placeholder tagline for the brand", "origin": "https://example.test", "base_path": ""},
       "og_images": {"enabled": True}, "pages": {"enabled": True}}
AREA = {"id": "alta-ski-area", "name": "Alta Ski Area", "state": "UT", "region": "Wasatch", "base": {"elev_ft": 8530, "lat": 40.58, "lon": -111.63},
        "summit": {"elev_ft": 10550, "lat": 40.57, "lon": -111.63}}


def day(label, p25, p50, p75, snow, partial=False):
    return {"label": label, "partial": partial, "snow_in": snow, "snow_p25": p25, "snow_p50": p50, "snow_p75": p75}


DOC = {"issued": "2026-11-17T19:00Z", "tz": "America/Denver",
       "summary": {"tag": "Storm cycle", "sentence": "Multi-day storm: likely 24–26 in at the summit over the next 72 h."},
       "points": {"summit": {"days": [day("Tue 17", None, None, None, 9.6, partial=True), day("Wed 18", 0, 0, 0, 0), day("Thu 19", 2.7, 8.4, 12.2, 9.4),
                                      day("Fri 20", 9.0, 11.0, 13.0, 11.0), day("Sat 21", None, None, None, 3.2), day("Sun 22", 0, 0.3, 0.8, 0.4)]}}}


def check_layout(png: bytes, lay: dict):
    im = Image.open(io.BytesIO(png))
    assert im.size == (1200, 630) and len(png) < 60_000
    for b in lay["boxes"]:
        x0, y0, x1, y1 = b["box"]
        assert 0 <= x0 and 0 <= y0 and x1 <= 1200 and y1 <= 630, f"text outside the card: {b}"
        assert og.contrast(b["fg"], b["bg"]) >= 4.5, f"contrast below 4.5:1: {b}"
    names = {b["name"] for b in lay["boxes"]}
    assert {"site", "name", "summary", "issued", "credit"} <= names
    foot_top = min(b["box"][1] for b in lay["boxes"] if b["name"] in ("issued", "credit"))
    body = [b for b in lay["boxes"] if b["name"] in ("name", "meta", "tag", "summary")]
    assert all(b["box"][3] <= foot_top for b in body), "body text runs into the footer"
    return im


def test_card_has_the_summary_chart_issue_time_brand_and_credit():
    png, lay = og.render(AREA, DOC, CFG)
    check_layout(png, lay)
    text = " | ".join(b["text"] for b in lay["boxes"])
    assert "Placeholder Name" in text and "Placeholder tagline" in text and "Storm cycle" in text and "Data: NOAA/NWS" in text
    assert "likely 24–26 in" in text and "NBM forecast issued Tue Nov 17, 12 PM MST" in text
    labels = {b["name"]: b["text"] for b in lay["boxes"] if b["name"].startswith("bar-label")}
    # whole days only (the partial first day is skipped); a day without a native range shows the EXPECTED amount ("~"), never an invented range
    assert labels["bar-label-1"] == "3–12″" and labels["bar-label-3"].startswith("~") and labels["bar-label-0"] == "0″"


def test_output_is_deterministic():
    assert og.render(AREA, DOC, CFG)[0] == og.render(AREA, DOC, CFG)[0]


def test_no_summary_and_no_forecast_fall_back_to_plain_text():
    doc = {**DOC, "summary": None}
    png, lay = og.render(AREA, doc, CFG)
    check_layout(png, lay)
    assert any("Snow forecast for Alta Ski Area" in b["text"] for b in lay["boxes"])
    png2, lay2 = og.render(AREA, None, CFG)
    check_layout(png2, lay2)
    assert not any(b["name"].startswith("bar-label") for b in lay2["boxes"])


@pytest.mark.parametrize("name", ["Mount Bachelor Ski And Summer Resort At The Very Long Name Junction Of Central Oregon Cascades",
                                  "Supercalifragilisticexpialidociousmountainresortwithoutanyspaces"])
def test_long_names_and_long_summaries_are_fitted_never_clipped(name):
    doc = {**DOC, "summary": {"tag": "Wind-affected snow likely, with a long tag", "sentence": "Mixed signals: " + "likely 1–3 in each day with a rain/snow line near the base; " * 6}}
    png, lay = og.render({**AREA, "name": name, "region": "Central Oregon Cascades and the High Desert"}, doc, CFG)
    check_layout(png, lay)
    assert len([b for b in lay["boxes"] if b["name"] == "name"]) <= 2


def test_generic_cards_and_brand_from_config():
    png, lay = og.render_generic(CFG, "Sno-Park forecasts", "Snow, wind and avalanche context.")
    check_layout(png, lay)
    assert any(b["text"] == "Placeholder Name" for b in lay["boxes"])


def test_colors_come_from_the_one_nws_table_in_colors_js():
    bins, colors = og.snowfall_table()
    assert bins[0] == 0.01 and len(colors) == len(bins) + 1 and og.color_for(7.9, (bins, colors)) == "#fffe95" and og.color_for(8.4, (bins, colors)) == "#ffc400" and og.color_for(12.0, (bins, colors)) == "#ff8700"


def test_run_is_a_no_op_while_the_flag_is_off(tmp_path):
    assert og.run({"og_images": {"enabled": False}}, tmp_path) == 0 and not (tmp_path / "og").exists()


def test_run_writes_one_card_per_ski_area_plus_generic(tmp_path):
    (tmp_path / "data" / "points").mkdir(parents=True)
    (tmp_path / "data" / "ski_areas.json").write_text(json.dumps({"areas": [AREA, {**AREA, "id": "other", "name": "Other"}]}), encoding="utf-8")
    (tmp_path / "data" / "points" / "alta-ski-area.json").write_text(json.dumps(DOC), encoding="utf-8")
    assert og.run(CFG, tmp_path) == 0
    assert sorted(p.name for p in (tmp_path / "og").iterdir()) == ["alta-ski-area.png", "other.png", "site.png", "snopark.png"]


def test_pages_reference_og_image_only_when_both_flags_are_on():
    for pe, oe, want in ((True, True, True), (True, False, False), (False, True, False), (False, False, False)):
        cfg = {**CFG, "pages": {"enabled": pe}, "og_images": {"enabled": oe}}
        h = pages.render_page(AREA, DOC, cfg)
        assert ('property="og:image"' in h) is want and ("summary_large_image" in h) is want
        assert "· Placeholder Name</title>" in h and 'og:site_name" content="Placeholder Name"' in h
    h = pages.render_page({**AREA, "id": "sp-wing-mountain"}, DOC, CFG)
    assert 'content="https://example.test/og/snopark.png"' in h
