"""Hotfix fix-models-page: the models catalog (models/index.json, read by the map viewer) lists real MAP models only.

The live catalog listed `ecmwf` and `gefs` too (their plume products keep a models/<product>/index.json with no label or domains), so the page showed "undefined 00Z",
blank dropdown options and threw a TypeError on selection. Fixture: tests/fixtures/models_catalog/ = the real per-product index.json files of the Nov 21 2026 build
(hrrr, rrfs, gfs map models; ecmwf, gefs plume products) plus a `verify/` product folder that has no index.json at all (by design)."""
import json
import logging
import shutil
from pathlib import Path

import pytest

from pipeline.__main__ import product_status
from pipeline.models.catalog import collect, is_map_model, write_catalog

REPO = Path(__file__).resolve().parents[1]
FIX = REPO / "tests" / "fixtures" / "models_catalog"
ORDER = ["hrrr", "rrfs", "gfs"]


@pytest.fixture()
def models_dir(tmp_path):
    d = tmp_path / "models"
    shutil.copytree(FIX, d)
    return d


def test_the_fixture_has_the_shape_of_the_real_build(models_dir):
    assert sorted(p.parent.name for p in models_dir.glob("*/index.json")) == ["ecmwf", "gefs", "gfs", "hrrr", "rrfs"]
    ec = json.loads((models_dir / "ecmwf" / "index.json").read_text(encoding="utf-8"))
    ge = json.loads((models_dir / "gefs" / "index.json").read_text(encoding="utf-8"))
    assert "label" not in ec and "domains" not in ec and ec["n_members"] == 50 and "label" not in ge and "domains" not in ge and ge["n_members"] == 31
    assert not (models_dir / "verify" / "index.json").exists()


def test_collect_lists_only_map_models_in_config_order(models_dir, caplog):
    with caplog.at_level(logging.INFO, logger="snow-wx.models"):
        cat = collect(models_dir, ORDER)
    assert list(cat["models"]) == ["hrrr", "rrfs", "gfs"]
    assert all(m["label"] and m["domains"] and m["base"] == f"{k}/" for k, m in cat["models"].items())
    notes = [r.getMessage() for r in caplog.records if "skipped" in r.getMessage()]
    assert any("ecmwf/index.json" in n for n in notes) and any("gefs/index.json" in n for n in notes) and len(notes) == 2     # one line per skipped product, none for map models or verify/


def test_without_an_order_the_names_are_sorted_and_the_plumes_still_skipped(models_dir):
    assert list(collect(models_dir)["models"]) == ["gfs", "hrrr", "rrfs"]


def test_a_new_map_model_is_listed_and_a_new_non_map_product_is_logged_not_silent(models_dir, caplog):
    (models_dir / "newmodel").mkdir()
    idx = json.loads((models_dir / "gfs" / "index.json").read_text(encoding="utf-8"))
    (models_dir / "newmodel" / "index.json").write_text(json.dumps({**idx, "model": "newmodel", "label": "NEW"}), encoding="utf-8")
    (models_dir / "aifsplume").mkdir()
    (models_dir / "aifsplume" / "index.json").write_text(json.dumps({"cycle": "2026112100", "n_members": 1}), encoding="utf-8")
    with caplog.at_level(logging.INFO, logger="snow-wx.models"):
        cat = collect(models_dir, ORDER)
    assert list(cat["models"]) == ["hrrr", "rrfs", "gfs", "newmodel"]
    assert any("aifsplume/index.json" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("idx", [None, [], {}, {"label": "X"}, {"label": "", "domains": {"west": {}}}, {"label": "X", "domains": {}}, {"label": "X", "domains": ["west"]}, {"domains": {"west": {}}}])
def test_is_map_model_rejects_everything_without_label_and_domains(idx):
    assert is_map_model(idx) is False


def test_write_catalog_writes_a_file_the_viewer_can_use(models_dir):
    cat = write_catalog(models_dir, ORDER)
    on_disk = json.loads((models_dir / "index.json").read_text(encoding="utf-8"))
    assert list(on_disk["models"]) == list(cat["models"]) == ORDER
    assert "undefined" not in json.dumps(on_disk)


def test_the_status_row_counts_map_models_only(tmp_path, models_dir):
    """the one other reader of the catalog: product_status() -> meta.json `models` (count, detail, newest `at`). The plume products have their own rows (ecmwf, gefs)."""
    out = tmp_path / "site"
    (out / "models").parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(models_dir, out / "models")
    write_catalog(out / "models", ORDER)
    row = product_status(out, {})["models"]
    assert row["ok"] is True and row["count"] == 3 and row["detail"] == "HRRR 12Z, RRFS 12Z, GFS 12Z"
    newest_map = max(json.loads((models_dir / m / "index.json").read_text(encoding="utf-8"))["generated_at"] for m in ORDER)
    assert row["at"] == newest_map                                   # a fresh GEFS run no longer makes the map models look fresher than they are


def test_catalog_contract_over_a_real_local_build():
    """if a local build exists: every catalog entry is a drawable map model (what models.js needs without a fallback). Skipped without a build."""
    p = REPO / "build" / "models" / "index.json"
    if not p.exists():
        pytest.skip("no local build (build/models/index.json)")
    cat = json.loads(p.read_text(encoding="utf-8"))
    assert cat["models"], "an empty catalog"
    for k, m in cat["models"].items():
        assert m.get("label") and isinstance(m.get("domains"), dict) and m["domains"], f"{k}: no label/domains"
        assert isinstance(m.get("fields"), dict) and m["fields"] and all(f.get("domains") and f.get("fhours") for f in m["fields"].values()), f"{k}: fields"
        assert all(isinstance(m.get(x), str) and m[x] for x in ("cycle", "init", "path", "base")), f"{k}: cycle/init/path/base"
