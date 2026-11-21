"""web/js/charts/segments.js (dev22 Part 3): mask -> contiguous runs, one closed polygon per run, nothing bridged across a gap, p50 outside p25-p75 reported not altered."""
import json
import subprocess

import pytest

from tests.test_ensemble_js import ROOT, _node

pytestmark = pytest.mark.skipif(_node() is None, reason="node not installed")


def run(tmp_path, body: str):
    script = tmp_path / "t.js"
    script.write_text("const fs = require('fs'), vm = require('vm'); const ctx = {}; vm.createContext(ctx);\n"
                      "vm.runInContext(fs.readFileSync(%s + '/web/js/charts/segments.js', 'utf8') + '\\nthis.Segments = Segments;', ctx);\n"
                      "const S = ctx.Segments;\n%s" % (json.dumps(str(ROOT)), body), encoding="utf-8")
    res = subprocess.run([_node(), str(script)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_runs_and_gaps_including_edges_and_single_points(tmp_path):
    out = run(tmp_path, """
const f = (a) => a.map(Boolean);
console.log(JSON.stringify({
  empty: S.runs([]), none: S.runs([0, 0, 0]), all: S.runs([1, 1, 1]), one: S.runs([0, 1, 0]), first: S.runs([1, 0, 0]), last: S.runs([0, 0, 1]),
  two: S.runs([1, 1, 0, 1, 0, 0, 1, 1, 1]), nulls: S.runs([null, 5, undefined, 7]),
  gaps: S.gapRuns([0, 1, 1, 0, 0, 1, 0]), gapsAllWet: S.gapRuns([1, 1]), gapsAllDry: S.gapRuns([0, 0, 0]) }));
""")
    assert out["empty"] == [] and out["none"] == [] and out["all"] == [[0, 2]]
    assert out["one"] == [[1, 1]] and out["first"] == [[0, 0]] and out["last"] == [[2, 2]]                     # single points are runs of length 1, edges included
    assert out["two"] == [[0, 1], [3, 3], [6, 8]] and out["nulls"] == [[1, 1], [3, 3]]
    assert out["gaps"] == [[0, 0], [3, 4], [6, 6]] and out["gapsAllWet"] == [] and out["gapsAllDry"] == [[0, 2]]


def test_a_polygon_covers_one_run_only_and_never_bridges_a_gap(tmp_path):
    out = run(tmp_path, """
const xs = ['a', 'b', 'c', 'd', 'e', 'f'], lo = [1, 2, 3, 4, 5, 6], hi = [11, 12, 13, 14, 15, 16];
const runs = S.runs([1, 1, 0, 0, 1, 1]);
console.log(JSON.stringify({ runs, polys: runs.map((r) => S.polygon(xs, lo, hi, r)) }));
""")
    assert out["runs"] == [[0, 1], [4, 5]]
    p0, p1 = out["polys"]
    assert p0["x"] == ["a", "b", "b", "a"] and p0["y"] == [11, 12, 2, 1]                  # forward along the top, back along the bottom: closed
    assert p1["x"] == ["e", "f", "f", "e"] and p1["y"] == [15, 16, 6, 5]
    assert not ({"c", "d"} & set(p0["x"] + p1["x"]))                                       # nothing inside the gap


def test_p50_outside_the_likely_range_is_reported_and_the_data_is_unchanged(tmp_path):
    out = run(tmp_path, """
const p25 = [10, 10, 12, null], p50 = [11, 9, 12, 8], p75 = [13, 13, 11, 9], mask = [1, 1, 1, 1], before = JSON.stringify([p25, p50, p75]);
const bad = S.outside(p25, p50, p75, mask);
console.log(JSON.stringify({ bad, same: before === JSON.stringify([p25, p50, p75]), masked_out: S.outside(p25, p50, p75, [0, 0, 0, 0]) }));
""")
    assert out["bad"] == [1, 2] and out["same"] is True and out["masked_out"] == []       # index 3 has no p25: not judged
