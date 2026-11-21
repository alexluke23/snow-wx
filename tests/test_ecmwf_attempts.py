"""pipeline/ecmwf_attempts.py (dev22 Part 4): the per-cycle attempt log behind the status page. Frozen clocks, temp folders only."""
import json
from datetime import datetime, timezone

from pipeline import ecmwf_attempts as EA


def utc(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)


def test_results_are_classified_with_a_reason():
    assert EA.classify({"ok": True, "skipped": "published", "cycle": "2026112000-ab"})[0] == "published-already"
    assert EA.classify({"ok": True, "skipped": "not-released"})[0] == "not-released"
    r, why = EA.classify({"ok": True, "skipped": "incomplete", "fetch": {"steps_missing": [6, 12]}})
    assert r == "incomplete" and "2 steps missing" in why and "cached" in why
    assert EA.classify({"ok": True, "skipped": "unreachable"})[0] == "unreachable"
    assert EA.classify({"ok": True, "cycle": "2026112012", "steps_missing": []}) == ("published", "complete")
    assert EA.classify({"ok": True, "cycle": "2026112012", "steps_missing": [24]})[0] == "published-partial"
    assert EA.classify(None, error="RuntimeError: boom") == ("error", "RuntimeError: boom")


def test_expected_time_is_the_measured_lag_after_the_nominal_cycle():
    assert EA.expected_ready(utc("2026-11-20T12:00Z")) == utc("2026-11-20T19:45Z")


def test_the_owner_case_the_12z_cycle_was_due_and_no_run_looked_for_it(tmp_path):
    # Fri Nov 20 ~18:50 MST = 01:50 UTC Nov 21. GitHub ran ONE scheduled attempt that day, at 18:00 UTC (before the 12Z cycle was due at 19:45); the 21:40 and 23:40 events never arrived.
    att = [EA.entry(utc("2026-11-20T13:04Z"), "2026112000", "published", "complete"), EA.entry(utc("2026-11-20T18:00Z"), None, "published-already", "nothing newer")]
    rows = EA.cycles_view(att, utc("2026-11-21T01:50Z"), newest_published="2026112000-b3f7ceaa")
    by = {r["cycle"]: r for r in rows}
    assert rows[0]["cycle"] == "2026112012" and by["2026112012"]["due"] is True and by["2026112012"]["expected"] == "2026-11-20T19:45Z"
    assert by["2026112012"]["result"] == "no attempt" and by["2026112012"]["attempts"] == 0 and by["2026112012"]["last_attempt"] is None   # the 18:00 attempt was before it was due
    assert by["2026112000"]["result"] == "published" and by["2026112000"]["attempts"] == 2          # the 13:04 and the 18:00 attempts both looked for it (18:00 is after it was due)


def test_attempts_after_the_due_time_are_matched_to_the_cycle_they_looked_for():
    att = [EA.entry(utc("2026-11-20T20:10Z"), None, "not-released", "no cycle with its last file"), EA.entry(utc("2026-11-20T21:41Z"), "2026112012", "incomplete", "3 steps missing")]
    row = EA.cycles_view(att, utc("2026-11-20T22:00Z"), newest_published="2026112000")[0]
    assert row["cycle"] == "2026112012" and row["attempts"] == 2 and row["last_attempt"] == "2026-11-20T21:41Z" and row["result"] == "incomplete"


def test_a_cycle_that_is_not_due_yet_is_not_listed_as_missing():
    rows = EA.cycles_view([], utc("2026-11-20T10:00Z"), newest_published="2026112000")
    assert rows[0]["cycle"] == "2026112000" and rows[0]["result"] == "published"          # the 12Z cycle (due 19:45) is not in the view yet


def test_record_appends_trims_and_writes_both_copies(tmp_path):
    cache, out = tmp_path / "data_cache" / "ecmwf", tmp_path / "out"
    for i in range(5):
        EA.record(cache, out, utc(f"2026-11-20T0{i}:00Z"), {"ok": True, "skipped": "not-released"}, keep=3)
    doc = json.loads((cache / "attempts.json").read_text(encoding="utf-8"))
    assert len(doc["attempts"]) == 3 and doc["attempts"][-1]["at"] == "2026-11-20T04:00Z"
    assert json.loads((out / "ecmwf" / "attempts.json").read_text(encoding="utf-8")) == doc
    assert not (out / "ecmwf" / "index.json").exists()                  # the attempt log never writes the run's index.json


def test_a_corrupt_log_starts_a_fresh_one(tmp_path):
    (tmp_path / "attempts.json").write_text("{not json", encoding="utf-8")
    assert EA.load(tmp_path / "attempts.json") == []
    assert EA.load(tmp_path / "missing.json") == []


def test_the_status_entry_carries_the_cycle_rows(tmp_path):
    from pipeline.__main__ import ecmwf_status
    models = tmp_path / "models"
    (models / "ecmwf").mkdir(parents=True)
    (models / "ecmwf" / "index.json").write_text(json.dumps({"cycle": "2026112000", "init": "2026-11-20T00:00Z", "generated_at": "2026-11-20T13:09:00Z", "n_members": 50, "hours": [0, 6],
                                                           "fetch": {"mirror": "aws", "retries": 0}, "steps_missing": []}), encoding="utf-8")
    (models / "ecmwf" / "attempts.json").write_text(json.dumps({"attempts": [EA.entry(utc("2026-11-20T13:04Z"), "2026112000", "published", "complete")]}), encoding="utf-8")
    e = ecmwf_status(tmp_path, {"ecmwf": {"enabled": True}})
    assert e["init"] == "2026-11-20T00:00Z" and e["lag_h"] == 7.75 and len(e["cycles"]) == 4 and e["cycles"][-1]["cycle"] <= e["cycles"][0]["cycle"]
