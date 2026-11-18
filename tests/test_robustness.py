"""Pipeline robustness (dev17 stretch 2): every obs source gets empty / malformed / error responses. The contract:
  * a source that cannot make a good product RAISES (run_obs records ok:false with the error) instead of writing an empty or half product;
  * the files of the last good run are never touched by a failed run (nothing is written before the payload is validated);
  * one broken source never stops the others, run_obs never raises, and meta.json carries per-source status + failure history;
  * the monitor turns repeated failures into a BREACH with the per-source decision line, and a healthy source never alerts.
The only "empty is fine" case: alerts with a well-formed empty feature list (no active alerts)."""

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import requests

from pipeline import afd, alerts, asos, avalanche, hazards, monitor, snotel
from pipeline.__main__ import run_obs
from pipeline.common import load_config

MODES = ("empty_dict", "empty_list", "null", "malformed", "html", "http500", "timeout")


class Resp:
    def __init__(self, mode):
        self.mode = mode
        self.status_code = 500 if mode == "http500" else 200
        self.text = "<html>maintenance page</html>" if mode == "html" else ""
        self.content = self.text.encode()
        self.headers = {}
        self.ok = self.status_code < 400

    def json(self):
        if self.mode == "empty_dict":
            return {}
        if self.mode == "empty_list":
            return []
        if self.mode == "null":
            return None
        raise ValueError("Expecting value: line 1 column 1 (char 0)")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class BadSession:
    request_timeout = 5
    headers: dict = {}

    def __init__(self, mode):
        self.mode = mode

    def get(self, *a, **k):
        if self.mode == "timeout":
            raise requests.exceptions.Timeout("timed out")
        return Resp(self.mode)

    post = get
    head = get


@pytest.fixture(scope="module")
def cfg():
    c = load_config()
    c["region"]["states"] = ["CO", "UT", "ID"]
    return c


SOURCES = {"alerts": alerts, "afd": afd, "avalanche": avalanche, "hazards": hazards, "snotel": snotel, "asos": asos}
# what each source writes (relative to its out dir): the last-good product
PRODUCTS = {"alerts": ["alerts/index.json", "alerts/details.json", "alerts/hazard_text.json"], "afd": ["afd/index.json"], "avalanche": ["avalanche.geojson"],
            "hazards": ["hazards.json"], "snotel": ["snotel.geojson"], "asos": ["asos.geojson"]}


def seed(out: Path, name: str) -> dict:
    """pretend a previous good run exists: sentinel files, returns {path: sha1}"""
    sums = {}
    for rel in PRODUCTS[name]:
        f = out / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"last_good": name, "rel": rel}), encoding="utf-8")
        sums[rel] = hashlib.sha1(f.read_bytes()).hexdigest()
    return sums


@pytest.mark.parametrize("name", [n for n in SOURCES if n != "snotel"])      # SNOTEL has its own keep-last-good / stale contract (tests/test_snotel_outage.py)
@pytest.mark.parametrize("mode", MODES)
def test_bad_responses_raise_and_never_touch_the_last_good_files(cfg, tmp_path, name, mode):
    before = seed(tmp_path, name)
    with pytest.raises(Exception):
        SOURCES[name].run(cfg, BadSession(mode), tmp_path)
    after = {rel: hashlib.sha1((tmp_path / rel).read_bytes()).hexdigest() for rel in PRODUCTS[name]}
    assert after == before, f"{name}/{mode}: a failed run changed the last good files"
    assert not [p for p in tmp_path.rglob("*") if p.is_file() and p.relative_to(tmp_path).as_posix() not in PRODUCTS[name]]      # and wrote nothing else


@pytest.mark.parametrize("mode", MODES)
def test_snotel_bad_responses_raise_unavailable_and_publish_nothing_without_a_usable_copy(cfg, tmp_path, mode):
    with pytest.raises(snotel.SnotelUnavailable):
        snotel.run(cfg, BadSession(mode), tmp_path)
    assert not (tmp_path / "snotel.geojson").exists()                              # no previous copy: nothing is invented, the source reports unavailable


def test_alerts_with_a_well_formed_empty_feature_list_means_no_alerts(cfg, tmp_path, monkeypatch):
    class Ok(BadSession):
        def get(self, *a, **k):
            r = Resp("empty_dict")
            r.json = lambda: {"features": []}
            return r
    monkeypatch.setattr(alerts, "load_sites", lambda: ([], []))
    res = alerts.run(cfg, Ok("x"), tmp_path)
    assert res["count"] == 0 and json.loads((tmp_path / "alerts" / "index.json").read_text(encoding="utf-8"))["count"] == 0


def test_run_obs_survives_every_source_failing_and_records_it(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.__main__.make_session", lambda c: BadSession("http500"))
    assert run_obs(cfg, tmp_path) == 1                                               # nothing ok, but no exception
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert set(meta["sources"]) == set(SOURCES) and all(s["ok"] is False and s["error"] for s in meta["sources"].values())
    assert all(s.get("consecutive_failures") == 1 for s in meta["sources"].values())
    # a second failing run counts up (history is carried in meta.json)
    run_obs(cfg, tmp_path)
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert all(s["consecutive_failures"] == 2 for s in meta["sources"].values())


@pytest.mark.parametrize("mode", ["empty_dict", "malformed", "timeout"])
def test_a_broken_source_leaves_the_others_untouched(cfg, tmp_path, monkeypatch, mode):
    """only one source sees the bad answers; the others run on the normal fake"""
    from tests.fakes import FakeSession
    good = FakeSession()

    class Mixed:
        request_timeout = 5
        headers: dict = {}

        def get(self, url, *a, **k):
            if "avalanche.org" in url:
                return BadSession(mode).get(url)
            return good.get(url, *a, **k)
    monkeypatch.setattr("pipeline.__main__.make_session", lambda c: Mixed())
    run_obs(cfg, tmp_path, only=["avalanche", "asos", "snotel"])
    meta = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert meta["sources"]["avalanche"]["ok"] is False
    assert meta["sources"]["asos"]["ok"] is True and meta["sources"]["snotel"]["ok"] is True
    assert (tmp_path / "asos.geojson").exists() and not (tmp_path / "avalanche.geojson").exists()


# ---------------------------------------------------------------- monitor decisions on those failures
NOW = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)
LIM = {"alerts": {"max_failures": 3, "max_age_hours": 6}, "asos": {"max_failures": 3, "max_age_hours": 6}}


def iso(h):
    return (NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_monitor_breaches_after_the_limit_and_the_decision_line_names_the_source():
    healthy = {"ok": True, "at": iso(0), "last_success_at": iso(0), "consecutive_failures": 0}
    failing = lambda n: {"ok": False, "error": "HTTP 500", "at": iso(0), "last_success_at": iso(n), "consecutive_failures": n}      # noqa: E731
    res = monitor.evaluate({"sources": {"alerts": failing(2), "asos": healthy}}, NOW, {"sources": LIM})
    assert not res["alerts"].get("problem") and not res["asos"].get("problem")             # 2 failures, last success 2 h ago: not yet
    res = monitor.evaluate({"sources": {"alerts": failing(3), "asos": healthy}}, NOW, {"sources": LIM})
    assert res["alerts"].get("problem") and not res["asos"].get("problem")                 # the third consecutive failure breaches; the healthy source stays quiet
    res = monitor.evaluate({"sources": {"alerts": {**failing(1), "last_success_at": iso(9)}, "asos": healthy}}, NOW, {"sources": LIM})
    assert res["alerts"].get("problem") and "9 h" in res["alerts"]["problem"]              # one failure but 9 h without success also breaches (data age)


def test_a_source_missing_from_meta_is_a_logged_no_alarm_decision():
    res = monitor.evaluate({"sources": {"asos": {"ok": True, "at": iso(0), "last_success_at": iso(0), "consecutive_failures": 0}}}, NOW, {"sources": LIM})
    assert res["alerts"].get("problem") is None and "no status in meta.json -> no alarm" in res["alerts"]["log"]      # explicit, logged decision (a brand-new source must not page anyone)


# ---------------------------------------------------------------- the products made by the models.yml jobs
@pytest.mark.parametrize("mode", MODES)
def test_ndfd_and_nohrsc_fail_without_writing_anything(cfg, tmp_path, mode):
    from pipeline import ndfd, nohrsc
    for fn in (ndfd.run, nohrsc.run):
        out = tmp_path / fn.__module__.split(".")[-1]
        try:
            res = fn(cfg, BadSession(mode), out)
            assert res == 0                                                         # ndfd: "not reachable" exits 0 with new=false (nothing to publish)
        except Exception:
            pass                                                                    # nohrsc raises; either way:
        assert not [p for p in out.rglob("*") if p.is_file()] if out.exists() else True


@pytest.mark.parametrize("mode", MODES)
def test_points_that_cannot_read_a_cycle_report_new_false_and_publish_nothing(cfg, tmp_path, mode):
    """no NBM cycle can be read (bad answers everywhere): `new=false` and no file written, so the last published product stays (exit 0 when no cycle is
    complete, exit 1 when a cycle lists no forecast hours: the job shows red); the monitor judges the product's age (monitoring.sources.points.max_age_hours = 14)"""
    from pipeline.nbm import run as nbm
    out = tmp_path / "pts"
    gh = tmp_path / "gh.txt"
    assert nbm.run_points(cfg, BadSession(mode), out, github_output=str(gh)) in (0, 1)
    assert not [p for p in out.rglob("*") if p.is_file()] if out.exists() else True
    assert "new=false" in gh.read_text(encoding="utf-8")
