"""web/js/multimodel.js `agreement` (the badge heuristic), executed with Node when installed. dev18: a window where every model is near zero is "Dry" /
"Little precipitation expected", never "High"; thresholds 80 % High / 66 % Medium are unchanged (dev17 calibration)."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _node():
    for p in (shutil.which("node"), r"C:\miniforge3\envs\tools\node.exe"):
        if p and os.path.exists(p):
            return p
    return None


pytestmark = pytest.mark.skipif(_node() is None, reason="node not installed")

T0 = 1_700_000_000_000
H = 3.6e6


def agreement(tmp_path, totals_by_model: dict, hours=(0, 72)):
    """each model: a cumulative liquid series 0 -> total over `hours` (linear), same start"""
    series = [{"label": k, "x": [T0 + h * H for h in hours], "y": [0, v]} for k, v in totals_by_model.items()]
    script = tmp_path / "t.js"
    script.write_text("""
const fs = require('fs'), vm = require('vm'); const ctx = {}; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(%s, 'utf8') + '\\nthis.M = MultiModel;', ctx);
const S = %s; console.log(JSON.stringify(ctx.M.agreement(S, %d)));
""" % (json.dumps(str(ROOT / "web" / "js" / "multimodel.js")), json.dumps(series), T0), encoding="utf-8")
    r = subprocess.run([_node(), str(script)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_every_model_near_zero_is_dry_not_high(tmp_path):
    for totals in ({"NBM": 0.0, "HRRR": 0.0, "RRFS": 0.0, "GFS": 0.0}, {"NBM": 0.02, "HRRR": 0.0, "GFS": 0.19}, {"NBM": 0.05, "HRRR": 0.01, "RRFS": 0.18, "GFS": 0.0, "ECMWF": 0.03}):
        ag = agreement(tmp_path, totals)
        assert ag["dry"] is True and ag["label"] == "Dry" and ag["text"] == "Little precipitation expected" and "High" not in ag["text"]


def test_a_wet_window_is_rated_by_the_share_within_tolerance(tmp_path):
    ag = agreement(tmp_path, {"NBM": 1.0, "HRRR": 1.1, "RRFS": 0.9, "GFS": 1.2})
    assert ag["dry"] is False and ag["label"] == "High" and ag["text"] == "High agreement" and ag["within"] == 4
    ag = agreement(tmp_path, {"NBM": 1.0, "HRRR": 1.1, "RRFS": 0.9, "GFS": 2.5})                 # 3 of 4 = 75 %: Medium (needs 80 % for High with four sources)
    assert ag["label"] == "Medium"
    ag = agreement(tmp_path, {"NBM": 1.0, "HRRR": 2.5, "RRFS": 0.1, "GFS": 3.0})
    assert ag["label"] == "Low" and ag["text"] == "Low agreement"


def test_one_wet_model_among_dry_ones_is_not_dry(tmp_path):
    ag = agreement(tmp_path, {"NBM": 0.0, "HRRR": 0.0, "RRFS": 0.0, "GFS": 0.3})                  # one model brings 0.3 in: the window is not "dry"
    assert agreement(tmp_path, {"NBM": 0.0, "HRRR": 0.0, "RRFS": 0.0, "GFS": 0.2})["dry"] is False         # 0.20 in is the boundary: under it is dry, at it is not
    assert ag["dry"] is False


def test_fewer_than_three_models_gives_no_badge(tmp_path):
    assert agreement(tmp_path, {"NBM": 1.0, "HRRR": 1.0}) is None
