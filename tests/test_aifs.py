"""dev20 Part 2: the ECMWF AIFS line. Pure document (units: AIFS tp is kg m-2 = mm, not metres; gaps never interpolated), isolation inside `pipeline ecmwf`
(an AIFS failure never breaks or blocks the HRES/ENS output), multimodel merge flags, the status entry, and the badge exclusion in the page's own JS."""
import json
import subprocess
from datetime import datetime, timezone

import numpy as np
import pytest

from pipeline import ecmwf as E
from pipeline.models import multimodel
from tests.test_ecmwf_resilience import CYC, PTS, mirrors, no_repo_cache, quick  # noqa: F401 - fixtures
from tests.test_ensemble_js import ROOT, _node

AIFS_RX = "aifs-single"


def go(tmp_path, base, aifs=None, **extra):
    cfg = {"ecmwf": {"enabled": True, "max_step_h": 144, "workers": 3, "attempts": 3, "trip_after": 2, "max_request_s": 20, "mirrors": [{"name": "aws", "base": base}], **extra},
           "aifs": {"enabled": True, "max_step_h": 144, "attempts": 2, "max_request_s": 10, **(aifs or {})}}
    gh = tmp_path / "gh.txt"
    res = E.run(cfg, None, tmp_path / "o", cycle=CYC, points=PTS, github_output=str(gh), cache_dir=False)
    return res, gh.read_text(encoding="utf-8") if gh.exists() else ""


def test_aifs_doc_converts_mm_to_inches_keeps_gaps_and_is_cumulative():
    steps = [0, 6, 12, 18, 24]
    pts = [{"id": "a"}, {"id": "b"}]
    fields = {6: np.array([2.54, 0.0]), 12: np.array([25.4, 0.0]), 24: np.array([25.0, np.nan])}      # 24 h dips (packing noise): running max; 18 h missing
    d = E.aifs_doc(pts, CYC, steps, fields, [18], in_badge=False)
    assert d["model"] == "aifs" and d["experimental"] is True and d["badge"] is False and "CC BY 4.0" in d["attribution"] and "AIFS" in d["label"]
    assert d["areas"]["a"]["q"] == [0.0, 0.1, 1.0, None, 1.0] and d["steps_missing"] == [18]
    assert d["areas"]["b"]["q"][:3] == [0.0, 0.0, 0.0] and d["areas"]["b"]["q"][3] is None


def test_aifs_line_is_written_inside_the_ecmwf_folder(tmp_path, mirrors):  # noqa: F811
    m = mirrors()
    res, gh = go(tmp_path, m.base)
    assert res["ok"] and "new=true" in gh and res["aifs"]["published"] is True and res["aifs"]["steps_missing"] == []
    doc = json.loads((tmp_path / "o" / "ecmwf" / "aifs" / "precip.json").read_text(encoding="utf-8"))
    assert doc["model"] == "aifs" and doc["hours"][-1] == 144 and doc["areas"]["alta"]["q"][0] == 0.0
    assert m.count(AIFS_RX) >= 2 * 24
    idx = json.loads((tmp_path / "o" / "ecmwf" / "index.json").read_text(encoding="utf-8"))
    assert idx["aifs"]["published"] is True


def test_an_unreachable_aifs_never_breaks_the_hres_ens_output(tmp_path, mirrors):  # noqa: F811
    m = mirrors()
    m.rules.append(lambda p, n: 503 if AIFS_RX in p else None)
    res, gh = go(tmp_path, m.base)
    assert res["ok"] and "new=true" in gh and res["steps_missing"] == []
    assert (tmp_path / "o" / "ecmwf" / "precip.json").exists() and (tmp_path / "o" / "ecmwf" / "plume" / "alta.json").exists()
    assert not (tmp_path / "o" / "ecmwf" / "aifs").exists() and res["aifs"]["published"] is False and "steps" in res["aifs"]["reason"]


def test_an_aifs_crash_is_recorded_not_raised(tmp_path, mirrors, monkeypatch):  # noqa: F811
    m = mirrors()
    monkeypatch.setattr(E, "run_aifs", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    res, _ = go(tmp_path, m.base)
    assert res["ok"] and res["aifs"] == {"enabled": True, "ok": False, "published": False, "reason": "RuntimeError: boom"}
    assert (tmp_path / "o" / "ecmwf" / "index.json").exists()


def test_aifs_has_a_time_budget(tmp_path, mirrors):  # noqa: F811
    m = mirrors()
    res, _ = go(tmp_path, m.base, aifs={"max_seconds": 0})
    assert res["ok"] and res["aifs"]["published"] is False and len(res["aifs"]["steps_missing"]) == 24 and m.count(AIFS_RX) == 0


def test_disabled_aifs_makes_no_request(tmp_path, mirrors):  # noqa: F811
    m = mirrors()
    res, _ = go(tmp_path, m.base, aifs={"enabled": False})
    assert res["aifs"] == {"enabled": False} and m.count(AIFS_RX) == 0


def test_merge_carries_the_experimental_flag_and_the_badge_switch(tmp_path):
    d = tmp_path / "models"
    (d / "ecmwf" / "aifs").mkdir(parents=True)
    base = {"cycle": "2026111912", "init": "2026-11-19T12:00Z", "hours": [0, 6], "areas": {"alta": {"q": [0.0, 0.1], "z": None}}}
    (d / "ecmwf" / "precip.json").write_text(json.dumps({**base, "model": "ecmwf", "label": "ECMWF", "plume": True}), encoding="utf-8")
    (d / "ecmwf" / "aifs" / "precip.json").write_text(json.dumps({**base, "model": "aifs", "label": E.AIFS_LABEL, "experimental": True, "badge": False}), encoding="utf-8")
    doc = multimodel.merge(d, tmp_path / "mm.json")
    m = {x["model"]: x for x in doc["models"]}
    assert m["aifs"]["experimental"] is True and m["aifs"]["badge"] is False and "experimental" not in m["ecmwf"] and doc["areas"]["alta"]["aifs"]["q"] == [0.0, 0.1]


def test_status_entry(tmp_path):
    from pipeline.__main__ import aifs_status
    assert aifs_status(tmp_path, {"ecmwf": {"enabled": True}, "aifs": {"enabled": False}})["detail"] == "not enabled"
    on = {"ecmwf": {"enabled": True}, "aifs": {"enabled": True}}
    assert aifs_status(tmp_path, on)["detail"] == "waiting for the first run"
    (tmp_path / "models" / "ecmwf").mkdir(parents=True)
    (tmp_path / "models" / "ecmwf" / "index.json").write_text(json.dumps({"aifs": {"enabled": True, "reason": "only 3 of 40 steps"}}), encoding="utf-8")
    assert "could not add AIFS (only 3 of 40 steps)" in aifs_status(tmp_path, on)["detail"]
    (tmp_path / "models" / "ecmwf" / "aifs").mkdir()
    (tmp_path / "models" / "ecmwf" / "aifs" / "precip.json").write_text(json.dumps({"cycle": "2026111912", "init": "2026-11-19T12:00Z", "hours": [0, 6, 12], "areas": {"a": {}},
                                                                                     "steps_missing": [12]}), encoding="utf-8")
    st = aifs_status(tmp_path, on)
    assert st["ok"] is True and "12Z" in st["detail"] and "1 missing" in st["detail"] and st["count"] == 1


@pytest.mark.skipif(_node() is None, reason="node not installed")
def test_the_badge_ignores_aifs_unless_configured_in(tmp_path):
    """3 agreeing models + AIFS far off: excluded -> High (3 of 3); included (badge: true) -> 3 of 4 = Medium"""
    init = "2026-11-19T12:00Z"
    hours = list(range(0, 73, 6))
    q = lambda per6: [round(per6 * h / 6, 3) for h in hours]  # noqa: E731
    doc = {"models": [{"model": "gfs", "label": "GFS", "init": init, "hours": hours}, {"model": "ecmwf", "label": "ECMWF", "init": init, "hours": hours},
                      {"model": "aifs", "label": "AIFS (AI, experimental)", "init": init, "hours": hours, "experimental": True, "badge": False}],
           "areas": {"x": {"gfs": {"q": q(0.1)}, "ecmwf": {"q": q(0.1)}, "aifs": {"q": q(0.5)}}}}
    nbm = {"initMs": 0, "precip": {"end": [f"2026-11-{19 + (12 + h) // 24:02d}T{(12 + h) % 24:02d}:00Z" for h in hours[1:]], "qpf_in": [0.1] * 12, "snow_in": [1] * 12}}
    script = tmp_path / "t.js"
    script.write_text("""
const fs = require('fs'), vm = require('vm'); const ctx = {}; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(%s + '/web/js/multimodel.js', 'utf8') + '\\nthis.MultiModel = MultiModel;', ctx);
const doc = %s, nbm = %s; nbm.initMs = Date.parse('2026-11-19T12:00Z');
const out = {};
out.off = ctx.MultiModel.build({doc, areaId: 'x', nbm, mode: 'liquid'}).agreement;
doc.models[2].badge = true;
out.on = ctx.MultiModel.build({doc, areaId: 'x', nbm, mode: 'liquid'}).agreement;
out.series = ctx.MultiModel.build({doc, areaId: 'x', nbm, mode: 'liquid'}).series.map((s) => s.key);
console.log(JSON.stringify({off: [out.off.label, out.off.within, out.off.n], on: [out.on.label, out.on.within, out.on.n], series: out.series}));
""" % (json.dumps(str(ROOT)), json.dumps(doc), json.dumps(nbm)), encoding="utf-8")
    r = subprocess.run([_node(), str(script)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    o = json.loads(r.stdout)
    assert "aifs" in o["series"]                                  # always DRAWN
    assert o["off"] == ["High", 3, 3] and o["on"] == ["Medium", 3, 4]
