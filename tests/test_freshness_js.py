"""web/js/freshness.js (dev22 Part 4): the three states of a model run with FROZEN clocks, executed with Node when installed.
latest = no newer run due yet; late = a newer run is due but still inside the grace window; out of date = a newer run should exist and we failed to get it.
An old run is never 'out of date' just because it is more than N hours old."""
import json
import subprocess

import pytest

from tests.test_ensemble_js import ROOT, _node

pytestmark = pytest.mark.skipif(_node() is None, reason="node not installed")


def run(tmp_path, body: str):
    script = tmp_path / "t.js"
    script.write_text("const fs = require('fs'), vm = require('vm'); const ctx = {}; vm.createContext(ctx);\n"
                      "vm.runInContext(fs.readFileSync(%s + '/web/js/freshness.js', 'utf8') + '\\nthis.Freshness = Freshness;', ctx);\n"
                      "const F = ctx.Freshness; const t = (s) => Date.parse(s);\n%s" % (json.dumps(str(ROOT)), body), encoding="utf-8")
    res = subprocess.run([_node(), str(script)], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout)


def test_the_three_states_for_an_ecmwf_00z_run(tmp_path):
    out = run(tmp_path, """
const init = t('2026-11-20T00:00:00Z');
const at = (s) => F.state(init, t(s), 'ecmwf').state;
console.log(JSON.stringify({
  morning: at('2026-11-20T10:00:00Z'), just_before_due: at('2026-11-20T19:44:00Z'),
  due: at('2026-11-20T19:45:00Z'), inside_grace: at('2026-11-20T22:44:00Z'),
  grace_over: at('2026-11-20T22:45:00Z'), owner_case: at('2026-11-21T01:50:00Z'),
  due_ms: F.state(init, t('2026-11-21T01:50:00Z'), 'ecmwf').dueMs, past: F.state(init, t('2026-11-22T01:50:00Z'), 'ecmwf').pastDue }));
""")
    assert out["morning"] == "latest" and out["just_before_due"] == "latest"
    assert out["due"] == "late" and out["inside_grace"] == "late"
    assert out["grace_over"] == "out-of-date" and out["owner_case"] == "out-of-date"           # Fri Nov 20 18:50 MST = 01:50 UTC: the 12Z run was due at 19:45 UTC
    assert out["due_ms"] == 1795203900000                                                        # 2026-11-20T19:45:00Z
    assert out["past"] == 3                                                                      # two more cycles (00Z, 12Z) have been due since


def test_an_old_run_is_not_out_of_date_just_because_of_its_age(tmp_path):
    out = run(tmp_path, """
const init = t('2026-11-20T00:00:00Z');                               // 19.5 h old, still the newest run that can exist
console.log(JSON.stringify({ age19: F.state(init, t('2026-11-20T19:30:00Z'), 'ecmwf').state,
                              gefs12: F.state(t('2026-11-20T12:00:00Z'), t('2026-11-21T17:00:00Z'), 'gefs').state,        // 29 h old, next due 12Z+12+5.65 = 05:39 -> late/out of date
                              gefs_ok: F.state(t('2026-11-20T12:00:00Z'), t('2026-11-21T05:00:00Z'), 'gefs').state }));
""")
    assert out["age19"] == "latest" and out["gefs_ok"] == "latest" and out["gefs12"] == "out-of-date"


def test_the_words_name_the_due_time_and_the_state(tmp_path):
    out = run(tmp_path, """
const init = t('2026-11-20T00:00:00Z');
const w = (s) => F.words(F.state(init, t(s), 'ecmwf'), {label: 'run'});
console.log(JSON.stringify({ a: w('2026-11-20T10:00:00Z'), b: w('2026-11-20T20:30:00Z'), c: w('2026-11-21T01:50:00Z') }));
""")
    assert out["a"]["text"] == "latest run" and "19:45 UTC" in out["a"]["long"]
    assert out["b"]["text"].startswith("late: newer run expected about 19:45 UTC") and "not yet available" in out["b"]["text"]
    assert out["c"]["text"].startswith("out of date: a newer run should exist") and "19:45 UTC" in out["c"]["text"] and out["c"]["cls"] == "stale"
