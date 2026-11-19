"""dev18 Part 0e: `ecmwf` is a monitored source. Flag off -> "not enabled" (never failing); flag on without a first run -> "waiting"; a run is judged by its age
against monitoring.sources.ecmwf (30 h for two cycles a day); the status page and the monitor agree."""
import json
from datetime import datetime, timedelta, timezone

from pipeline import monitor
from pipeline.__main__ import ecmwf_status, product_status
from pipeline.common import load_config

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
LIM = {"sources": {"ecmwf": {"max_age_hours": 30}}}


def iso(h):
    return (NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def write_index(out, hours_old, cycle="2026111800", n=50):
    d = out / "models" / "ecmwf"
    d.mkdir(parents=True)
    (d / "index.json").write_text(json.dumps({"cycle": cycle, "n_members": n, "generated_at": iso(hours_old)}), encoding="utf-8")


def test_config_monitors_ecmwf_with_a_limit_sized_for_two_cycles_a_day():
    lim = load_config()["monitoring"]["sources"]["ecmwf"]
    assert lim["max_age_hours"] == 30                    # 12 h cycle + ~8 h release lag + one retry window; two missed attempts breach


def test_flag_off_reads_not_enabled_and_never_alarms(tmp_path):
    e = ecmwf_status(tmp_path, {"ecmwf": {"enabled": False}})
    assert e == {"ok": None, "disabled": True, "detail": "not enabled"} and ecmwf_status(tmp_path, None)["disabled"] is True
    res = monitor.evaluate({"sources": {"ecmwf": e}}, NOW, LIM)
    assert res["ecmwf"]["problem"] is None and "not enabled -> no alarm" in res["ecmwf"]["log"]
    write_index(tmp_path, 100)                           # even with an old file lying around, a disabled feature is not judged
    assert monitor.evaluate({"sources": {"ecmwf": ecmwf_status(tmp_path, {"ecmwf": {"enabled": False}})}}, NOW, LIM)["ecmwf"]["problem"] is None


def test_enabled_without_a_run_is_waiting_not_failing(tmp_path):
    e = ecmwf_status(tmp_path, {"ecmwf": {"enabled": True}})
    assert e["waiting"] is True and e["ok"] is None
    assert monitor.evaluate({"sources": {"ecmwf": e}}, NOW, LIM)["ecmwf"]["problem"] is None


def test_a_delivered_run_is_judged_by_its_age(tmp_path):
    cfg = {"ecmwf": {"enabled": True}}
    write_index(tmp_path, 21)                            # the worst healthy case: 21 h old
    e = ecmwf_status(tmp_path, cfg)
    assert e["ok"] is True and "00Z run, 50 ensemble members" in e["detail"]
    assert monitor.evaluate({"sources": {"ecmwf": e}}, NOW, LIM)["ecmwf"]["problem"] is None
    e["at"] = iso(31)                                    # one missed cycle too many
    res = monitor.evaluate({"sources": {"ecmwf": {**e, "last_success_at": e["at"]}}}, NOW, LIM)
    assert res["ecmwf"]["problem"] and "31 h ago (limit 30 h)" in res["ecmwf"]["problem"]


def test_product_status_carries_the_entry(tmp_path):
    ps = product_status(tmp_path, {"ecmwf": {"enabled": False}})
    assert ps["ecmwf"]["disabled"] is True and "points" in ps and "models" in ps
    assert product_status(tmp_path)["ecmwf"]["disabled"] is True                         # callers that pass no config see the safe default
