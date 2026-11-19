"""Failure-mode pass (dev18 stretch 2): each hourly source fails ONE AT A TIME (offline: FakeSession answers HTTP 503 for that source's URLs) for four runs in a row, with the
others healthy. For every source we check what the build leaves behind, what the monitor decides, and what the public status page (web/js/status.js, run in Node) draws:
  * the failing source is recorded ok:false with an error and a rising failure count; every other source stays ok;
  * the last good product files are never touched (hash-identical after the failures);
  * monitor and status page AGREE on every source after every run: the failing source breaches / reads "Late" exactly when its failure limit is reached, nothing else ever does;
  * the monitor's decision line names the source and its numbers."""
import hashlib
import json
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from pipeline import monitor
from pipeline.__main__ import run_obs
from pipeline.common import load_config
from tests.fakes import FakeResponse, FakeSession

ROOT = Path(__file__).resolve().parents[1]
# the URL fragment that identifies each source's requests, and the product files it writes
SOURCES = {
    "alerts": ("alerts/active", ["alerts/index.json", "alerts/details.json", "alerts/hazard_text.json"]),
    "afd": ("products/types/AFD", ["afd/index.json"]),
    "avalanche": ("api.avalanche.org", ["avalanche.geojson"]),
    "hazards": ("mapservices.weather.noaa.gov", ["hazards.json"]),
    "snotel": ("awdbRestApi", ["snotel.geojson"]),
    "asos": ("mesonet.agron.iastate.edu", ["asos.geojson"]),
}
NAMES = {"snotel": "SNOTEL snow observations", "asos": "Airport weather stations (ASOS/AWOS)", "alerts": "NWS alerts", "afd": "NWS forecast discussions",
         "avalanche": "Avalanche danger ratings", "hazards": "NWS winter hazards layer"}


class Healthy(FakeSession):
    """FakeSession (SNOTEL, ASOS, avalanche) plus canned answers for the alerts, forecast-discussion and winter-hazard sources; `fail` fragments answer HTTP 503"""

    def get(self, url, params=None, timeout=None, headers=None):
        if any(f in url for f in self.fail):
            self.calls.append((url, params))
            return FakeResponse({}, 503)
        if "alerts/active" in url:
            return FakeResponse({"features": []})
        if "products/types/AFD" in url:
            return FakeResponse({"@graph": [{"@id": "https://api.weather.gov/products/AFDX", "id": "AFDX", "issuanceTime": "2026-11-18T12:00:00+00:00"}]})
        if url.endswith("/products/AFDX"):
            return FakeResponse({"productText": "Area Forecast Discussion\nNational Weather Service Test\n.SYNOPSIS... snow.\n$$"})
        if "/MapServer/" in url:
            names = ["Winter Storm Warning", "Winter Storm Watch", "Winter Weather Advisory", "Blizzard Warning", "Avalanche Warning", "High Wind Warning", "Wind Advisory",
                     "Extreme Cold Warning", "Cold Weather Advisory", "Snow Squall Warning", "Lake Effect Snow Warning", "Ice Storm Warning"]
            cls = [{"label": n, "symbol": {"color": [i * 10, 20, 30, 255]}} for i, n in enumerate(names)]
            return FakeResponse({"drawingInfo": {"renderer": {"type": "uniqueValue", "uniqueValueGroups": [{"classes": cls}]}}})
        return super().get(url, params=params, timeout=timeout)


def _node():
    for p in (shutil.which("node"), r"C:\miniforge3\envs\tools\node.exe"):
        if p and os.path.exists(p):
            return p
    return None


@pytest.fixture(scope="module")
def cfg():
    c = load_config()
    c["region"]["states"] = ["CO"]
    return c


def digest(out: Path, rels):
    return {r: hashlib.sha1((out / r).read_bytes()).hexdigest() for r in rels if (out / r).exists()}


def status_rows(tmp_path: Path, meta: dict) -> dict[str, str]:
    """what the public status page draws, by source name -> css class (st-ok / st-late / ...), via Node"""
    f = tmp_path / "meta_for_status.json"
    f.write_text(json.dumps(meta), encoding="utf-8")
    r = subprocess.run([_node(), str(ROOT / "tests" / "status_harness.js"), str(f)], capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stderr
    return {row["name"]: row["cls"] for row in json.loads(r.stdout)["rows"]}


@pytest.mark.skipif(_node() is None, reason="node not installed")
@pytest.mark.parametrize("failing", list(SOURCES))
def test_one_source_failing_four_runs_in_a_row_monitor_and_status_page_agree(cfg, tmp_path, monkeypatch, failing):
    lim = cfg["monitoring"]["sources"]
    max_f = lim[failing]["max_failures"]
    out = tmp_path / "data"
    # run 0: everything healthy -> the "last good" files
    monkeypatch.setattr("pipeline.__main__.make_session", lambda c: Healthy())
    assert run_obs(cfg, out) == 0
    good = digest(out, [r for _, rels in SOURCES.values() for r in rels])
    assert SOURCES[failing][1][0] in good, "the healthy run must have written the product"
    n_snotel = len(json.loads((out / "snotel.geojson").read_text(encoding="utf-8"))["features"])
    # runs 1..4: only `failing` answers 503
    monkeypatch.setattr("pipeline.__main__.make_session", lambda c: Healthy(fail=[SOURCES[failing][0]]))
    for k in range(1, 5):
        run_obs(cfg, out)
        meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
        e = meta["sources"][failing]
        assert e["ok"] is False and e["error"] and e["consecutive_failures"] == k, (failing, k, e)
        assert all(meta["sources"][s]["ok"] is True for s in SOURCES if s != failing), f"{failing} failing must not mark others failed: {meta['sources']}"
        if failing == "snotel":              # SNOTEL has its own contract (tests/test_snotel_outage.py): the last good copy is kept, flagged stale, and still lists the same stations
            fc = json.loads((out / "snotel.geojson").read_text(encoding="utf-8"))
            assert len(fc["features"]) == n_snotel and e.get("stale") is True, (len(fc["features"]), e)
        else:
            assert digest(out, SOURCES[failing][1]) == {r: good[r] for r in SOURCES[failing][1] if r in good}, f"{failing}: the last good files changed after a failed run"
        now = datetime.now(timezone.utc)
        decisions = monitor.evaluate(meta, now, {"sources": lim})
        breached = {s for s, d in decisions.items() if d["problem"]}
        expect = {failing} if k >= max_f else set()
        assert breached & set(SOURCES) == expect, f"{failing}, run {k}: monitor breached {breached} (limit {max_f} failures)"
        if expect:
            assert f"failed {k} runs in a row (limit {max_f})" in decisions[failing]["problem"] and decisions[failing]["log"].startswith(f"{failing}: state={'stale' if failing == 'snotel' else 'failed'} failures={k}/{max_f}")
        # the public status page must say the same: Late exactly for the breached source, OK for every other reporting source
        meta["monitoring"] = {"sources": lim}
        rows = status_rows(tmp_path, meta)
        for s in SOURCES:
            # one deliberate difference: SNOTEL serving a STALE copy is "Late" on the public page at once (readers must not see an old depth as current), while the monitor pages the
            # owner only at its failure/age limits (no alert for a single bad run). Everything else agrees exactly.
            want = "st-late" if (s in expect or (s == failing == "snotel")) else "st-ok"
            assert rows.get(NAMES[s]) == want, f"{failing}, run {k}: the status page shows {s} as {rows.get(NAMES[s])}, the monitor says {want}"


@pytest.mark.skipif(_node() is None, reason="node not installed")
def test_every_source_failing_at_once_is_all_late_on_both_and_nothing_is_deleted(cfg, tmp_path, monkeypatch):
    out = tmp_path / "data"
    monkeypatch.setattr("pipeline.__main__.make_session", lambda c: Healthy())
    run_obs(cfg, out)
    good = digest(out, [r for _, rels in SOURCES.values() for r in rels])
    monkeypatch.setattr("pipeline.__main__.make_session", lambda c: Healthy(fail=[u for u, _ in SOURCES.values()]))
    for _ in range(3):
        assert run_obs(cfg, out) == 1
    others = {k: v for k, v in good.items() if k != "snotel.geojson"}                          # (SNOTEL rewrites its kept copy with a stale flag: its own contract)
    assert digest(out, list(others)) == others and (out / "snotel.geojson").exists()           # nothing deleted, nothing overwritten
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    meta["monitoring"] = {"sources": cfg["monitoring"]["sources"]}
    decisions = monitor.evaluate(meta, datetime.now(timezone.utc), {"sources": cfg["monitoring"]["sources"]})
    rows = status_rows(tmp_path, meta)
    for s in SOURCES:
        assert bool(decisions[s]["problem"]) is True and rows[NAMES[s]] == "st-late", (s, decisions[s]["problem"], rows.get(NAMES[s]))


def test_a_disabled_ecmwf_is_neither_late_nor_ok_on_the_status_page(cfg, tmp_path):
    if _node() is None:
        pytest.skip("node not installed")
    meta = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "sources": {"ecmwf": {"ok": None, "disabled": True, "detail": "not enabled"}},
            "monitoring": {"sources": {"ecmwf": {"max_age_hours": 30}}}}
    assert status_rows(tmp_path, meta)["ECMWF forecasts (HRES line + ensemble plume)"] == "st-off"
    assert monitor.evaluate(meta, datetime.now(timezone.utc), {"sources": {"ecmwf": {"max_age_hours": 30}}})["ecmwf"]["problem"] is None
