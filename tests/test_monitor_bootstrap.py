"""Monitor bootstrap (dev15 Part 0): the real SNOTEL outage opened no Data health issue because the outage predated the monitor, so
meta.json had no history and the counters restarted at 1. These replays show which meta.json states alert under the OLD rules
(`old_problem`, a copy of the pre-dev15 logic) and under the new ones, including the real-outage path through run_obs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from pipeline import monitor, snotel
from pipeline.__main__ import run_obs
from pipeline.common import load_config, utcnow

from .test_snotel_outage import Down, good_copy

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)
LIM = {"max_failures": 3, "max_age_hours": 6}


def iso(h):
    return (NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def old_problem(e, lim=LIM):
    """The pre-dev15 rule, verbatim: failures >= limit, or age of last_success_at/at (ok only) > limit."""
    reasons = []
    fails = int(e.get("consecutive_failures") or 0)
    if lim.get("max_failures") and fails >= int(lim["max_failures"]):
        reasons.append("fails")
    ref = e.get("last_success_at") or (e.get("at") if e.get("ok") else None)
    age = monitor.age_hours(ref, NOW)
    if age is not None and age > float(lim["max_age_hours"]):
        reasons.append("age")
    if e.get("ok") is False and "consecutive_failures" not in e and not reasons:
        reasons.append("missing")
    return bool(reasons)


def new_problem(e, lim=LIM):
    return monitor.evaluate({"sources": {"snotel": e}}, NOW, {"sources": {"snotel": lim}})["snotel"]


# (label, meta entry, alerts under OLD rules, alerts under NEW rules)
STATES = [
    ("i  old-format meta (pre-fix-snotel), ok:false, no history", {"ok": False, "error": "502", "at": iso(0)}, True, True),
    ("i  new-format meta, ok:false, first failing run", {"ok": False, "error": "502", "at": iso(0), "consecutive_failures": 1}, False, False),
    ("i  old-format meta, ok:false, outage_since 20 h ago (counter restarted at 1)", {"ok": False, "error": "502", "at": iso(0), "outage_since": iso(20), "consecutive_failures": 1}, False, True),
    ("ii unavailable since 30 h, counter 1, no last_success", {"ok": False, "unavailable": True, "last_observed": iso(30), "outage_since": iso(29), "consecutive_failures": 1, "at": iso(0)}, False, True),
    ("ii unavailable, no clock at all, counter 1", {"ok": False, "unavailable": True, "at": iso(0), "consecutive_failures": 1}, False, False),
    ("iii consecutive_failures 1 (no age known)", {"ok": False, "error": "x", "at": iso(0), "consecutive_failures": 1}, False, False),
    ("iii consecutive_failures 2 (no age known)", {"ok": False, "error": "x", "at": iso(0), "consecutive_failures": 2}, False, False),
    ("iii consecutive_failures 3", {"ok": False, "error": "x", "at": iso(0), "consecutive_failures": 3}, True, True),
    ("iv stale copy 8 h old, counter restarted at 1", {"ok": False, "stale": True, "age_h": 8, "observed_through": iso(8), "at": iso(0), "consecutive_failures": 1}, False, True),
    ("iv stale copy 2 h old, counter 1 (not yet)", {"ok": False, "stale": True, "age_h": 2, "observed_through": iso(2), "at": iso(0), "consecutive_failures": 1}, False, False),
    ("iv stale, last_success 7 h ago", {"ok": False, "stale": True, "last_success_at": iso(7), "consecutive_failures": 1, "at": iso(0)}, True, True),
    ("healthy", {"ok": True, "at": iso(0), "last_success_at": iso(0), "consecutive_failures": 0}, False, False),
]


@pytest.mark.parametrize("label,entry,old,new", STATES, ids=[s[0][:24] for s in STATES])
def test_replayed_meta_states(label, entry, old, new):
    assert old_problem(entry) is old, f"old rule: {label}"
    res = new_problem(entry)
    assert bool(res["problem"]) is new, f"new rule: {label}: {res['problem']}"
    assert res["log"].startswith("snotel: state=")            # one explanatory line per source


def test_log_line_explains_the_decision():
    line = new_problem({"ok": False, "stale": True, "observed_through": iso(9), "at": iso(0), "consecutive_failures": 1})["log"]
    assert "state=stale" in line and "failures=1/3" in line and "age=9.0h(data time)/6h" in line and "BREACH" in line


def test_check_prints_one_decision_per_source_and_opens_the_issue():
    mcfg = {"sources": {"snotel": LIM, "asos": LIM}, "issue_label": "data-health"}
    meta = {"sources": {"snotel": {"ok": False, "unavailable": True, "last_observed": iso(30), "consecutive_failures": 1, "at": iso(0)},
                        "asos": {"ok": True, "at": iso(0), "last_success_at": iso(0), "consecutive_failures": 0}}}
    calls = []
    lines = monitor.check(mcfg, meta, NOW, [], gh=lambda a, i=None: calls.append(a) or "")
    assert lines[0].startswith("snotel:") and "action: open issue" in lines[0]
    assert lines[1].startswith("asos:") and "action: none" in lines[1]
    assert any(a[:2] == ["issue", "create"] for a in calls)


def test_real_outage_path_alerts_even_when_history_is_lost_every_run(tmp_path, monkeypatch):
    """Not the simulate_failure input: SNOTEL really down for hours, the stale copy ages, and every run starts on a fresh runner whose
    meta.json has NO history (counter stuck at 1). Old rules never alert; the new ones breach as soon as the data is older than 6 h."""
    cfg = load_config()
    cfg["region"]["states"] = ["CO", "UT"]
    cfg["snotel"]["chunk_size"] = 1
    cfg["snotel"]["max_age_hours"] = 48
    good_copy(cfg, tmp_path, hours_old=2)
    import pipeline.__main__ as m
    monkeypatch.setattr(m, "make_session", lambda c: Down())
    clock = [utcnow()]
    monkeypatch.setattr(snotel, "utcnow", lambda: clock[0])
    monkeypatch.setattr(m, "utcnow", lambda: clock[0])
    mcfg = cfg["monitoring"]
    decisions = []
    for i in range(9):
        clock[0] += timedelta(hours=1)
        meta_path = tmp_path / "meta.json"
        if meta_path.exists():                               # fresh runner: previous history gone (restore brings only the station files)
            meta_path.unlink()
        run_obs(cfg, tmp_path, ["snotel"])
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        e = meta["sources"]["snotel"]
        assert e["consecutive_failures"] == 1                # the lost-history situation of the real outage
        old = old_problem(e, mcfg["sources"]["snotel"])
        res = monitor.evaluate(meta, clock[0], mcfg)["snotel"]
        decisions.append((e["age_h"], old, bool(res["problem"])))   # age of the carried copy in hours
    assert not any(d[1] for d in decisions)                  # old logic: never alerted
    assert all(d[2] for d in decisions if d[0] > 7)         # new logic: breach once the data is clearly past the 6 h limit...
    assert not any(d[2] for d in decisions if d[0] < 5)     # ...and not before it is near
    assert decisions[-1][2] and any(not d[2] for d in decisions)      # it turns on during the outage and stays on


def test_unavailable_after_48h_still_alerts(tmp_path, monkeypatch):
    cfg = load_config()
    cfg["region"]["states"] = ["CO", "UT"]
    cfg["snotel"]["chunk_size"] = 1
    cfg["snotel"]["max_age_hours"] = 48
    good_copy(cfg, tmp_path, hours_old=60)
    import pipeline.__main__ as m
    monkeypatch.setattr(m, "make_session", lambda c: Down())
    run_obs(cfg, tmp_path, ["snotel"])
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["sources"]["snotel"].get("unavailable") is True
    res = monitor.evaluate(meta, utcnow(), cfg["monitoring"])["snotel"]
    assert res["problem"] and "BREACH" in res["log"]
