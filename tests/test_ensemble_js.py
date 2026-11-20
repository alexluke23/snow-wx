"""web/js/ensemble.js (the Ensemble view's maths), executed with Node when installed: quantiles equal the pipeline's (numpy linear), per-member rebasing to a common
start, snow conversion with NBM's ratio, missing members, stale run, headline + table rows. Skipped when node is missing."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from pipeline import ecmwf as E

ROOT = Path(__file__).resolve().parents[1]


def _node():
    for p in (shutil.which("node"), r"C:\miniforge3\envs\tools\node.exe"):
        if p and os.path.exists(p):
            return p
    return None


pytestmark = pytest.mark.skipif(_node() is None, reason="node not installed")


def run_js(tmp_path, body: str, data: dict) -> dict:
    (tmp_path / "d.json").write_text(json.dumps(data), encoding="utf-8")
    script = tmp_path / "t.js"
    script.write_text("""
const fs = require('fs'), vm = require('vm');
const ctx = {}; vm.createContext(ctx);
for (const f of ['web/js/multimodel.js', 'web/js/ensemble.js']) vm.runInContext(fs.readFileSync(%s + '/' + f, 'utf8') + '\\nthis.' + (f.includes('ensemble') ? 'Ensemble' : 'MultiModel') + ' = ' + (f.includes('ensemble') ? 'Ensemble' : 'MultiModel') + ';', ctx);
const E = ctx.Ensemble, D = JSON.parse(fs.readFileSync(%s, 'utf8'));
%s
""" % (json.dumps(str(ROOT)), json.dumps(str(tmp_path / "d.json")), body), encoding="utf-8")
    res = subprocess.run([_node(), str(script)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def doc(n=50, hours=(0, 6, 12, 18, 24), init="2026-11-18T00:00Z", scale=1.0):
    """tp members: member k accumulates k * 2.54 mm per 6 h (so member totals are 0.1*k in at step 1 ...), sf = half of it"""
    tp = [[round(k * 25.4 * (h / 6) * scale) for k in range(1, n + 1)] for h in hours]       # 0.1 mm integers
    sf = [[round(v / 2) for v in row] for row in tp]
    return {"id": "x", "init": init, "hours": list(hours), "n_members": n, "tp": tp, "sf": sf, "hres_tp": [r[0] for r in tp], "hres_sf": [r[0] for r in sf], "z_ft": 7000}


def test_js_quantiles_equal_the_pipelines(tmp_path):
    rng = np.random.default_rng(3)
    vals = [rng.gamma(2.0, 1.5, 50).tolist() for _ in range(4)] + [[1.0] * 7 + [None] * 3, [None] * 4]
    got = run_js(tmp_path, "console.log(JSON.stringify(D.map(v => E.stats(v))));", vals)
    for v, g in zip(vals[:4], got[:4]):
        py = E.quantiles(np.array(v).reshape(1, -1))
        for q in (10, 25, 50, 75, 90):
            assert g[f"p{q}"] == pytest.approx(float(py[f"p{q}"][0]), abs=1e-9)
        assert g["mean"] == pytest.approx(float(py["mean"][0])) and g["n"] == 50
    assert got[4]["n"] == 7 and got[4]["p50"] == 1.0 and got[5]["n"] == 0 and got[5]["p50"] is None


def test_members_are_rebased_per_member_then_quantiled_across_members(tmp_path):
    d = doc()
    body = """
const t0 = Date.parse('2026-11-18T06:00Z') + 3 * 3.6e6;           // 09Z: half way between the 06Z and 12Z steps
const b = E.build(D, {mode: 'liquid', t0Ms: t0});
const st = E.summarize(b);
console.log(JSON.stringify({x0: b.x[0] === t0, n: b.members.length, first: b.members.map(m => m[0]).every(v => v === 0),
  m1_end: b.members[0][b.x.length - 1], m50_end: b.members[49][b.x.length - 1], med_end: st[st.length - 1].p50, hres_end: b.hres[b.x.length - 1],
  nx: b.x.length, mono: b.members.every(m => m.every((v, i) => i === 0 || v >= m[i - 1]))}));
"""
    got = run_js(tmp_path, body, d)
    # member k: cumulative 0.1*k in per 6 h (0.1 mm ints x 0.1 / 25.4): at 24 h = 4 * 0.1k; at 09Z = 1.5 * 0.1k  -> since 09Z = 2.5 * 0.1k
    assert got["x0"] and got["n"] == 50 and got["first"] and got["mono"]
    assert got["m1_end"] == pytest.approx(0.1 * 2.5, abs=0.01) and got["m50_end"] == pytest.approx(5.0 * 2.5, abs=0.02)
    assert got["med_end"] == pytest.approx(25.5 * 0.1 * 2.5, abs=0.02) and got["hres_end"] == pytest.approx(0.25, abs=0.01)


def test_snow_mode_uses_sf_times_nbm_ratio_and_a_missing_ratio_gives_zero(tmp_path):
    d = doc(n=5)
    body = """
const t0 = Date.parse('2026-11-18T00:00Z');
const times = [0, 6, 12, 18, 24].map(h => t0 + h * 3.6e6);
const a = E.build(D, {mode: 'snow', t0Ms: t0, ratio: [10, 10, 10, 10, 10], ratioTimes: times});
const b = E.build(D, {mode: 'snow', t0Ms: t0, ratio: [20, 20, 20, 20, 20], ratioTimes: times});
const c = E.build(D, {mode: 'snow', t0Ms: t0, ratio: [], ratioTimes: []});
const L = E.build(D, {mode: 'liquid', t0Ms: t0});
const end = (x) => x.members[4][x.x.length - 1];
console.log(JSON.stringify({snow10: end(a), snow20: end(b), none: end(c), liquid: end(L)}));
"""
    got = run_js(tmp_path, body, d)
    # member 5: tp total at 24 h = 4 * 0.5 in?  (k=5: 0.1*5 in per 6 h = 0.5 -> 2.0 in); sf is half -> 1.0 in w.e.; x ratio
    assert got["liquid"] == pytest.approx(2.0, abs=0.02)
    assert got["snow10"] == pytest.approx(10.0, abs=0.1) and got["snow20"] == pytest.approx(20.0, abs=0.2)
    assert got["none"] == 0                                                         # no ratio: never a silent 10:1


def test_missing_members_stale_run_headline_and_table(tmp_path):
    d = doc()
    for r in d["tp"][1:]:
        r[6] = None                                                                  # member 7 missing from step 6 h on
    body = """
const t0 = Date.parse('2026-11-18T00:00Z');
const b = E.build(D, {mode: 'liquid', t0Ms: t0});
const st = E.summarize(b);
const i = b.x.length - 1;
const rows = E.tableRows(b, st, {mode: 'liquid', fmtTime: (ms) => new Date(ms).toISOString().slice(11, 16), thresholds: [0.5, 1, 2]});
console.log(JSON.stringify({n: st[i].n, valid_members: b.members.length, stale: E.staleness(D, Date.parse('2026-11-19T05:00Z'), 24), fresh: E.staleness(D, Date.parse('2026-11-18T20:00Z'), 24),
  head: E.headline(b, st, {mode: 'liquid', h: 24, thr: 1, weekday: 'Thu'}), rows0: rows[0], shares: rows.filter(r => r[0].includes('at least')).map(r => r[0] + '|' + r[1])}));
"""
    got = run_js(tmp_path, body, d)
    assert got["n"] == 49 and got["valid_members"] == 50                             # the member with missing steps is left out of the quantiles at those steps
    assert got["stale"]["stale"] is True and got["fresh"]["stale"] is False
    assert got["head"].startswith("ECMWF ensemble (49 members): median ") and "by Thu" in got["head"] and "of 49 members above 1 in" in got["head"]
    assert got["rows0"][0].startswith("+24 h") and any(s.startswith("+24 h: at least 1 in|") and s.endswith("of 49 members") for s in got["shares"])


def test_a_missing_step_is_a_gap_in_every_member_and_nothing_is_interpolated(tmp_path):
    """dev19: a step the ECMWF job could not fetch is null for all members and HRES; the plume keeps its x, the series break there (the page draws gaps), and the
    cross-member statistics at that x are empty (null), never filled from the neighbours"""
    d = doc(n=10, hours=(0, 6, 12, 18, 24))
    d["tp"][2] = [None] * 10
    d["sf"][2] = [None] * 10
    d["hres_tp"][2] = None
    d["hres_sf"][2] = None
    body = """
const t0 = Date.parse('2026-11-18T00:00Z');
const b = E.build(D, {mode: 'liquid', t0Ms: t0});
const st = E.summarize(b);
const i = b.x.indexOf(Date.parse('2026-11-18T12:00Z'));
const snow = E.build(D, {mode: 'snow', t0Ms: t0, ratio: [10, 10, 10, 10, 10], ratioTimes: [0, 1, 2, 3, 4].map(k => t0 + k * 6 * 3.6e6)});
console.log(JSON.stringify({n: b.x.length, i, gap: b.members.every(m => m[i] === null), others: b.members.every(m => m.filter(v => v === null).length === 1),
  stat_n: st[i].n, stat_p50: st[i].p50, hres_gap: b.hres[i] === null, after: st[i + 1].p50 > st[i - 1].p50, snow_gap: snow.members.every(m => m[i] === null),
  snow_after: snow.members[0][i + 1] > snow.members[0][i - 1]}));
"""
    got = run_js(tmp_path, body, d)
    assert got["n"] == 5 and got["i"] == 2 and got["gap"] and got["others"] and got["stat_n"] == 0 and got["stat_p50"] is None and got["hres_gap"]
    assert got["after"] and got["snow_gap"] and got["snow_after"]                                                         # the series continue after the gap with their own cumulative values


def test_interpat_does_not_interpolate_across_a_missing_value(tmp_path):
    body = """
const M = ctx.MultiModel;
console.log(JSON.stringify([M.interpAt([0, 1, 2, 3], [0, 1, null, 3], 1.5), M.interpAt([0, 1, 2, 3], [0, 1, 2, 3], 1.5), M.interpAt([0, 1, 2, 3], [0, 1, null, 3], 3), M.interpAt([0, 1, 2, 3], [0, 1, null, 3], 0.5)]));
"""
    assert run_js(tmp_path, body, {}) == [None, 1.5, 3, 0.5]
