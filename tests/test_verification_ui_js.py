"""web/js/verification-ui.js pure functions (Node): the "Collecting data: X of 14 days" state, the one-sentence summary, the table rows, the caveats and the scorecard HTML.
Skipped when node is missing. The browser check `verifyui` covers the page integration."""
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

INDEX = {"min_days": 14, "min_pairs": 30, "span": ["2026-12-01", "2026-12-20"], "outage_excluded": ["2026-11-16T12:00Z", "2026-11-18T00:45Z"],
         "stations": {"1:UT:SNTL": {"d": 6, "n": 24}, "2:UT:SNTL": {"d": 20, "n": 40, "ready": True}, "3:UT:SNTL": {"d": 16, "n": 20}},
         "scorecard": {"ready": True, "days": 20, "pairs": 400, "rows": [{"source": "NBM expected", "n": 300, "bias_in": 0.12, "mae_in": 0.4, "events_1": 50, "hit_1": 0.62},
                                                                          {"source": "NWS (NDFD)", "n": 280, "bias_in": -0.05, "mae_in": 0.35, "events_1": 48, "hit_1": 0.5}]}}
DOC = {"triplet": "2:UT:SNTL", "d": 20, "n": 40, "span": ["2026-12-01", "2026-12-20"],
       "metrics": {"NBM expected": {"n": 20, "bias_in": 0.12, "mae_in": 0.4, "events_1": 8, "hit_1": 0.75}, "NWS (NDFD)": {"n": 20, "bias_in": -0.2, "mae_in": 0.3, "events_1": 8, "hit_1": 0.5}},
       "daily": {"dates": ["2026-12-01", "2026-12-02"], "obs": [0, 2.5], "nbm": [0.1, 2.0], "ndfd": [None, 1.5]}}


def js(tmp_path, body):
    (tmp_path / "d.json").write_text(json.dumps({"index": INDEX, "doc": DOC}), encoding="utf-8")
    (tmp_path / "t.js").write_text("const fs=require('fs'),vm=require('vm');const ctx={};vm.createContext(ctx);"
                                   "vm.runInContext(fs.readFileSync(%s,'utf8')+'\\nthis.V=VerificationUI;',ctx);const V=ctx.V,D=JSON.parse(fs.readFileSync(%s,'utf8'));\n%s"
                                   % (json.dumps(str(ROOT / "web" / "js" / "verification-ui.js")), json.dumps(str(tmp_path / "d.json")), body), encoding="utf-8")
    r = subprocess.run([_node(), str(tmp_path / "t.js")], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_status_and_the_collecting_message(tmp_path):
    out = js(tmp_path, """console.log(JSON.stringify({a: V.status(D.index, '1:UT:SNTL'), b: V.status(D.index, '2:UT:SNTL'), c: V.status(D.index, 'nope'), d: V.status(D.index, '3:UT:SNTL'),
      ma: V.collecting(V.status(D.index, '1:UT:SNTL')), mc: V.collecting(V.status(D.index, 'nope')), md: V.collecting(V.status(D.index, '3:UT:SNTL'))}))""")
    assert out["a"]["state"] == "collecting" and out["b"]["state"] == "ready" and out["c"]["state"] == "none" and out["d"]["state"] == "collecting"
    assert out["ma"].startswith("Collecting data: 6 of 14 days; 24 of 30 forecast pairs.") and "Collecting data: 0 of 14 days" in out["mc"]
    assert out["md"].startswith("Collecting data: 16 of 14 days; 20 of 30 forecast pairs.") or "20 of 30 forecast pairs" in out["md"]      # days met, pairs missing: says which


def test_sentence_states_bias_error_hit_rate_sample_and_the_lower_bound_caveat(tmp_path):
    out = js(tmp_path, """console.log(JSON.stringify({own: V.sentence(D.doc, {name: 'Atwater', proxy: false}), proxy: V.sentence(D.doc, {name: 'Atwater', proxy: true, distKm: 1.5})}))""")
    s = out["own"]
    assert s.startswith("At Atwater, over 20 days and 40 forecasts issued up to 48 h ahead:") and "NBM's expected 24-h snowfall ran 0.12 in above the observed snow-depth gain on average (typical error 0.40 in)" in s
    assert "caught 75% of the 8 days with at least 1 in" in s and "the NWS forecast ran 0.20 in below" in s and "lower bound of snowfall" in s
    assert "the SNOTEL site nearest this ski area, 1.5 km away" in out["proxy"]
    assert "accurate" not in s.lower() and "reliable" not in s.lower()                                        # no accuracy claim


def test_rows_and_caveats(tmp_path):
    out = js(tmp_path, """console.log(JSON.stringify({m: V.metricRows(D.doc), d: V.dailyRows(D.doc), cols: V.METRIC_COLS,
      c: V.caveats(D.doc, {name: 'A', proxy: true, distKm: 1.5, dz: 213}, D.index), c2: V.caveats(D.doc, {name: 'A', proxy: false}, D.index)}))""")
    assert out["m"][0] == ["NBM expected", "20", "0.12", "0.40", "75% of 8"] and out["d"][1] == ["2026-12-02", "2.50", "2.00", "1.50"] and out["d"][0][3] == "–"
    joined = " ".join(out["c"])
    assert "lower bound for snowfall" in joined and "Sample size: 40 forecasts over 20 days" in joined and "outage (2026-11-16 to 2026-11-18)" in joined
    assert "nearest SNOTEL site (1.5 km away, 213 ft higher than the base), not the ski area itself" in joined
    assert not any("nearest SNOTEL site" in c for c in out["c2"])


def test_scorecard_html_hidden_until_the_minimum_and_escapes(tmp_path):
    out = js(tmp_path, """const idx = JSON.parse(JSON.stringify(D.index)); const ready = V.scorecardHtml(idx);
      idx.scorecard = {ready: false, days: 9, pairs: 70, rows: []}; const wait = V.scorecardHtml(idx);
      idx.scorecard.ready = true; idx.scorecard.rows = [{source: '<b>x</b>', n: 1, bias_in: 0, mae_in: 0, events_1: 0, hit_1: null}]; const esc = V.scorecardHtml(idx);
      console.log(JSON.stringify({ready, wait, esc, none: V.scorecardHtml(null)}))""")
    assert "NBM expected" in out["ready"] and "62% of 50" in out["ready"] and "caption" in out["ready"]
    assert out["wait"] == "<p><b>Collecting data:</b> 9 of 14 days, 70 of 30 forecast pairs. Results appear here once both minimums are met.</p>"
    assert "<b>x</b>" not in out["esc"] and "&lt;b&gt;x&lt;/b&gt;" in out["esc"] and "No verification results" in out["none"]
