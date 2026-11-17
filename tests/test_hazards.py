"""NWS winter-hazards product list (dev13 item 2): built from the service's current product names (fakes only)."""

from __future__ import annotations

import json

import pytest

from pipeline import hazards
from pipeline.common import load_config

from .fakes import FakeResponse


def classes(*names):
    return {"type": "uniqueValue", "uniqueValueGroups": [{"classes": [
        {"label": n, "symbol": {"color": [i * 10, 20, 30, 255]}} for i, n in enumerate(names)]}]}


NAMES = ["Winter Storm Warning", "Winter Storm Watch", "Winter Weather Advisory", "Blizzard Warning", "Avalanche Warning",
         "High Wind Warning", "Wind Advisory", "Extreme Cold Warning", "Cold Weather Advisory", "Snow Squall Warning",
         "Lake Effect Snow Warning", "Ice Storm Warning",
         "Flood Warning", "Tornado Warning", "Gale Warning", "Storm Warning", "Small Craft Advisory",
         "Hurricane Force Wind Warning", "Heavy Freezing Spray Warning", "High Surf Advisory", "Special Weather Statement",
         "Dense Fog Advisory", "Extreme Wind Warning", "Winter Storm Outlook"]


def test_winter_products_selected_by_patterns_from_current_names():
    cfg = load_config()["hazards"]
    got = hazards.winter_products(classes(*NAMES), cfg["include"], cfg["exclude"])
    names = [p["name"] for p in got]
    for want in NAMES[:12]:
        assert want in names, want
    for bad in NAMES[12:]:          # not winter, marine, or no watch/warning/advisory level
        assert bad not in names, bad
    levels = [p["level"] for p in got]
    assert levels == sorted(levels, key=["warning", "watch", "advisory"].index)        # warnings first
    assert all(p["color"].startswith("#") and len(p["color"]) == 7 for p in got)


def test_hazards_source_writes_list_and_fails_without_winter_products(tmp_path):
    cfg = load_config()

    class S:
        request_timeout = 5

        def __init__(self, renderer):
            self.renderer = renderer

        def get(self, url, params=None, timeout=None):
            assert url.endswith("/MapServer/1") and params == {"f": "json"}
            return FakeResponse({"drawingInfo": {"renderer": self.renderer}})

    info = hazards.run(cfg, S(classes(*NAMES)), tmp_path)
    assert info["count"] >= 12
    doc = json.loads((tmp_path / "hazards.json").read_text(encoding="utf-8"))
    assert doc["field"] == "prod_type" and doc["layer"] == 1 and doc["products"][0]["level"] == "warning"
    with pytest.raises(RuntimeError, match="no winter products"):
        hazards.run(cfg, S(classes("Flood Warning", "Tornado Warning")), tmp_path)
