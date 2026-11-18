"""M7 end to end (dev17 Part 0f): model run frames -> precip.json per model -> site-build merge -> data/multimodel.json -> the area page's own
MultiModel code (web/js/multimodel.js, executed with Node when it is installed; the schema checks always run)."""

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from pipeline.models import multimodel as mm

ROOT = Path(__file__).resolve().parents[1]
POINTS = [{"id": "alta", "lat": 40.0, "lon": -111.0, "elev_ft": 10500}, {"id": "snowbird", "lat": 40.05, "lon": -111.05, "elev_ft": 11000}]


def grid():
    lat, lon = np.meshgrid(np.linspace(39.0, 41.0, 41), np.linspace(-112.0, -110.0, 41), indexing="ij")
    return SimpleNamespace(lat=lat, lon=lon)


def run_model(models_dir, key, label, init, hours, totals, orog):
    """what pipeline/models/run.py does per frame: derive_frame output -> sampler.add; then document -> <model>/precip.json"""
    s = mm.PrecipSampler(POINTS)
    g = grid()
    for f, t in zip(hours, totals):
        arrays = {"orog_ft": np.full((41, 41), orog, np.float32)}
        if f:
            arrays["qpf_total"] = np.full((41, 41), t, np.float32)
        s.add(f, arrays, g)
    d = Path(models_dir) / key
    d.mkdir(parents=True)
    (d / "precip.json").write_text(json.dumps(s.document(key, label, init)), encoding="utf-8")


def nbm_points(issued: datetime):
    """the part of a points file the panel reads (summit): precip windows (end, qpf_in, snow_in), hourly series for the snow toggle"""
    times = [(issued + timedelta(hours=h)).strftime("%Y-%m-%dT%H:00Z") for h in range(0, 49)]
    ends = [(issued + timedelta(hours=h)).strftime("%Y-%m-%dT%H:00Z") for h in (6, 12, 18, 24, 30, 36, 42, 48)]
    return {"issued": issued.strftime("%Y-%m-%dT%H:00Z"), "times": times,
            "precip": {"end": ends, "qpf_in": [0.1] * 8, "snow_in": [1.0] * 8},
            "ratio": [12] * 49, "psnow": [100] * 49}


def test_run_to_merge_to_panel_schema(tmp_path):
    models = tmp_path / "models"
    run_model(models, "hrrr", "HRRR", datetime(2026, 11, 18, 12, tzinfo=timezone.utc), [0, 3, 6, 12], [0, 0.1, 0.3, 0.6], 8000.0)
    run_model(models, "gfs", "GFS", datetime(2026, 11, 18, 6, tzinfo=timezone.utc), [0, 6, 12, 24], [0, 0.2, 0.5, 1.2], 6600.0)
    out = tmp_path / "data" / "multimodel.json"
    out.parent.mkdir()
    doc = mm.merge(models, out)
    on_disk = json.loads(out.read_text(encoding="utf-8"))
    assert on_disk["models"] == doc["models"] and [m["model"] for m in on_disk["models"]] == ["hrrr", "gfs"]
    for aid in ("alta", "snowbird"):
        for m in on_disk["models"]:
            a = on_disk["areas"][aid][m["model"]]
            assert len(a["q"]) == len(m["hours"]) and a["z"] in (8000, 6600)      # one cumulative value per model hour, terrain in feet
            assert all(b is None or a_ is None or b >= a_ for a_, b in zip(a["q"], a["q"][1:]))      # run totals never decrease
    assert on_disk["areas"]["alta"]["gfs"]["z"] == 6600 and "units" in on_disk and on_disk["generated_at"].endswith("Z")


def _node():
    import os
    for p in (shutil.which("node"), r"C:\miniforge3\envs\tools\node.exe", r"C:/miniforge3/envs/tools/node.exe"):
        if p and os.path.exists(p):
            return p
    return None


@pytest.mark.skipif(_node() is None, reason="node not installed")
def test_the_merged_file_feeds_the_panels_own_javascript(tmp_path):
    models = tmp_path / "models"
    run_model(models, "hrrr", "HRRR", datetime(2026, 11, 18, 12, tzinfo=timezone.utc), [0, 3, 6, 12], [0, 0.1, 0.3, 0.6], 8000.0)
    run_model(models, "rrfs", "RRFS", datetime(2026, 11, 18, 12, tzinfo=timezone.utc), [0, 6, 12, 24], [0, 0.15, 0.35, 0.7], 7500.0)
    run_model(models, "gfs", "GFS", datetime(2026, 11, 18, 6, tzinfo=timezone.utc), [0, 6, 12, 24], [0, 0.2, 0.5, 1.2], 6600.0)
    mm.merge(models, tmp_path / "multimodel.json")
    nb = nbm_points(datetime(2026, 11, 18, 13, tzinfo=timezone.utc))
    script = tmp_path / "run.js"
    script.write_text("""
const fs = require('fs'), vm = require('vm');
const ctx = {}; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(%s, 'utf8') + '\\nthis.MultiModel = MultiModel;', ctx);
const doc = JSON.parse(fs.readFileSync(%s, 'utf8')), nb = JSON.parse(fs.readFileSync(%s, 'utf8'));
const nbm = {initMs: Date.parse(nb.issued), precip: nb.precip, times: nb.times, ratio: nb.ratio, psnow: nb.psnow};
const out = {};
for (const mode of ['liquid', 'snow']) {
  const r = ctx.MultiModel.build({doc, areaId: 'alta', nbm, mode});
  out[mode] = {t0: r.t0, labels: r.series.map(s => s.label), last: r.series.map(s => s.y[s.y.length - 1]), z: r.series.map(s => s.z), ag: r.agreement && {label: r.agreement.label, n: r.agreement.n, H: r.agreement.H}};
}
out.none = ctx.MultiModel.build({doc, areaId: 'nowhere', nbm, mode: 'liquid'}).series.map(s => s.label);
console.log(JSON.stringify(out));
""" % (json.dumps(str(ROOT / "web" / "js" / "multimodel.js")), json.dumps(str(tmp_path / "multimodel.json")), json.dumps(str(tmp_path / "nb.json"))),
                      encoding="utf-8")
    (tmp_path / "nb.json").write_text(json.dumps(nb), encoding="utf-8")
    res = subprocess.run([_node(), str(script)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    got = json.loads(res.stdout)
    liquid = got["liquid"]
    assert liquid["labels"] == ["NBM", "HRRR", "RRFS", "GFS"]                       # every source is drawn, NBM first
    assert liquid["z"] == [None, 8000, 7500, 6600]                                  # model terrain rides along for the tooltip
    assert liquid["t0"] == int(datetime(2026, 11, 18, 13, tzinfo=timezone.utc).timestamp() * 1000)    # newest start = the NBM issue time
    assert liquid["ag"] and liquid["ag"]["n"] >= 3 and liquid["ag"]["label"] in ("High", "Medium", "Low")
    assert got["snow"]["labels"] == liquid["labels"] and got["snow"]["ag"] == liquid["ag"]   # the badge always comes from the liquid series
    assert got["none"] == ["NBM"]                                                    # an area without model data still gets the NBM line
