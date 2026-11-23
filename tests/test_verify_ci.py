"""dev21 Part 1: the daily verification job (`pipeline verify-ci`, .github/workflows/verify.yml). Fixture archives only (no download).

The job must score exactly like the local scorer (same outage window, same stale-observation rule), publish into <out>/verify/ (update-site extracts the tar into
build/models/verify/, where the panel reads), exit 0 with new=false when there is nothing new or the input is missing/stale (the last good result stays), and say
how far the data are from the panel minima."""
import csv
import gzip
import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from pipeline import verify
from tests.test_verify import FC, FC_SLR, OB, archive, nbm, obs, write_gz

CFG = {"verification": {"snotel_outage": {"start": "2026-11-16T12:00Z", "end": "2026-11-18T00:45Z"}}, "verification_ui": {"enabled": False, "min_days": 14, "min_pairs": 30}}
NOW = datetime(2026, 11, 23, 15, tzinfo=timezone.utc)


def arc(path):
    path.mkdir(parents=True, exist_ok=True)
    return archive(path)


def go(arch, out, published="", now=NOW, cfg=CFG, tmp=None):
    gh = (tmp or out) / "gh.txt"
    res = verify.ci_run(arch, out, cfg, published, str(gh), now)
    return res, gh.read_text(encoding="utf-8") if gh.exists() else ""


def big_archive(path, days=20, start="2026-11-19", cycles=(19, 7)):
    """one SNOTEL site with `days` observation days and two cycles per day (2 pairs a day), plus a second site with half as many days"""
    fc, ob = [], []
    for k in range(days):
        end = (pd.Timestamp(start, tz="UTC") + pd.Timedelta(days=k)).strftime("%Y-%m-%dT12:00Z")
        for lead in (20, 32):
            fc.append(nbm("snotel-1000-OR-SNTL", end, 1.0 + k % 3, 1.0, 10, lead=lead))
            if k % 2 == 0:
                fc.append(nbm("snotel-2000-UT-SNTL", end, 0.5, 0.5, 5, lead=lead))
        ob.append(obs("1000:OR:SNTL", end, 1.0 + (k % 2)))
        ob.append(obs("2000:UT:SNTL", end, 0.0))
    path.mkdir(parents=True, exist_ok=True)
    write_gz(path / "nbm-202611.csv.gz", FC, fc)
    write_gz(path / "snotel-202611.csv.gz", OB, ob)
    return path


def test_not_enough_data_yet_publishes_counts_only_and_projects_the_date(tmp_path):
    arch = arc(tmp_path / "a")
    res, gh = go(arch, tmp_path / "out", tmp=tmp_path)
    assert res["new"] is True and "new=true" in gh and "cycle=2026112212-" in gh
    v = tmp_path / "out" / "verify"
    idx = json.loads((v / "verification.json").read_text(encoding="utf-8"))
    run = json.loads((v / "run.json").read_text(encoding="utf-8"))
    assert idx["stations"]["1000:OR:SNTL"] == {"d": 2, "n": 2}
    assert not list((v / "verification").glob("*.json"))                         # no site meets the minima: no results file, counts only
    assert run["stations_ready"] == 0 and run["days"] == 2 and run["pairs"] == 2 and run["newest_obs"] == "2026-11-22T12:00Z"
    # 2 days, 2 pairs (1 per day): 12 more days for the days rule, 28 more for the pairs rule -> 28 days after the newest observation
    assert run["first_station_days_to_go"] == 28 and run["first_station_ready"] == "2026-12-20"
    assert not (v / "index.json").exists()                                         # never an index.json: the model-map catalog collects */index.json


def test_same_scores_as_the_local_scorer_outage_and_stale_obs_excluded(tmp_path):
    arch = arc(tmp_path / "a")
    res, _ = go(arch, tmp_path / "out", tmp=tmp_path)
    local = verify.run(arch, tmp_path / "local", CFG)
    assert res["pairs"] == local["by_source"]["nbm"]["pairs"] and res["exclusions"] == {"nbm": local["exclusions"]["nbm"]}       # public numbers = the NBM part of the local scorer's
    assert res["exclusions"]["nbm"]["outage_window"] == 1 and res["exclusions"]["nbm"]["low_coverage"] == 1
    assert res["outage_excluded"] == ["2026-11-16T12:00Z", "2026-11-18T00:45Z"] or res["outage_excluded"] == ("2026-11-16T12:00Z", "2026-11-18T00:45Z")


def test_enough_data_writes_the_site_file_and_the_scorecard(tmp_path):
    arch = big_archive(tmp_path / "a")
    res, _ = go(arch, tmp_path / "out", now=datetime(2026, 12, 8, 15, tzinfo=timezone.utc), tmp=tmp_path)
    v = tmp_path / "out" / "verify"
    assert res["new"] and res["stations_ready"] == 1 and (v / "verification" / "1000_OR_SNTL.json").exists()
    assert not (v / "verification" / "2000_UT_SNTL.json").exists()                # 10 days only: still collecting
    idx = json.loads((v / "verification.json").read_text(encoding="utf-8"))
    assert idx["scorecard"]["ready"] is True and res["scorecard_days_to_go"] == 0


def test_nothing_new_when_this_observation_day_is_published(tmp_path):
    arch = arc(tmp_path / "a")
    first, _ = go(arch, tmp_path / "o1", tmp=tmp_path)
    res, gh = go(arch, tmp_path / "o2", published=first["key"], tmp=tmp_path)
    assert res["new"] is False and res["reason"] == "already published" and "new=false" in gh and not (tmp_path / "o2" / "verify").exists()


def test_missing_archive_is_not_an_error(tmp_path):
    (tmp_path / "empty").mkdir()
    res, gh = go(tmp_path / "empty", tmp_path / "out", tmp=tmp_path)
    assert res["new"] is False and "new=false" in gh and "warning=" in gh and not (tmp_path / "out" / "verify").exists()


def test_stale_observations_warn_but_a_new_day_still_publishes(tmp_path):
    arch = arc(tmp_path / "a")
    res, gh = go(arch, tmp_path / "out", now=datetime(2026, 11, 26, 15, tzinfo=timezone.utc), tmp=tmp_path)
    assert res["new"] is True and "old" in res["warning"] and "warning=" in gh
    # and when that stale day is already published, nothing changes (the last good result stays)
    res2, _ = go(arch, tmp_path / "o2", published=res["key"], now=datetime(2026, 11, 26, 15, tzinfo=timezone.utc), tmp=tmp_path)
    assert res2["new"] is False and "old" in res2["warning"]


def test_switch_off(tmp_path):
    res, gh = go(arc(tmp_path / "a"), tmp_path / "out", cfg={**CFG, "verification": {**CFG["verification"], "ci_enabled": False}}, tmp=tmp_path)
    assert res["new"] is False and "ci_enabled" in res["reason"]


@pytest.mark.parametrize("d,n,want", [(14, 30, 0), (2, 2, 28), (10, 40, 4), (0, 0, 14)])
def test_ready_estimate(d, n, want):
    idx = {"stations": {"x": {"d": d, "n": n}}, "scorecard": {"days": d, "pairs": n}}
    est = verify.ready_estimate(idx, pd.Timestamp("2026-11-20T12:00Z"), 14, 30)
    if want == 14 and n == 0:
        assert est["first_station_ready"] is None                                 # no pace yet: no date
    else:
        assert est["first_station_days_to_go"] == want


def test_status_entries(tmp_path):
    from pipeline.__main__ import gefs_status, verify_status
    assert verify_status(tmp_path, {"verification": {"ci_enabled": False}})["detail"] == "not enabled"
    assert verify_status(tmp_path, CFG)["detail"] == "waiting for the first run"
    go(arc(tmp_path / "a"), tmp_path / "models", tmp=tmp_path)
    st = verify_status(tmp_path, CFG)
    assert st["ok"] is True and "2 observation days" in st["detail"] and "panel switched off" in st["detail"] and st["count"] == 0
    assert gefs_status(tmp_path, {"gefs": {"enabled": False}})["detail"] == "not enabled"
    assert gefs_status(tmp_path, {"gefs": {"enabled": True}})["detail"] == "waiting for the first run"
    (tmp_path / "models" / "gefs").mkdir(parents=True)
    (tmp_path / "models" / "gefs" / "index.json").write_text(json.dumps({"cycle": "2026112000", "n_members": 31, "areas": 160, "generated_at": "2026-11-20T06:00Z"}), encoding="utf-8")
    g = gefs_status(tmp_path, {"gefs": {"enabled": True}})
    assert g["ok"] is True and "31 members" in g["detail"] and g["count"] == 160


def test_new_format_archive_with_slr_columns_gives_the_same_result_as_the_old_format(tmp_path):
    """dev23: the nbm file carries slr_p25/p50/p75 (read next to older months without them): verify-ci scores and publishes exactly as before"""
    old, new = big_archive(tmp_path / "old"), big_archive(tmp_path / "new")
    with gzip.open(old / "nbm-202611.csv.gz", "rt", encoding="utf-8", newline="") as f:
        rows = [{**r, "slr_p25": "9", "slr_p50": "11", "slr_p75": "14"} for r in csv.DictReader(f)]
    write_gz(new / "nbm-202611.csv.gz", FC_SLR, rows)
    later = datetime(2026, 12, 8, 15, tzinfo=timezone.utc)
    (tmp_path / "t1").mkdir()
    (tmp_path / "t2").mkdir()
    r_old, _ = go(old, tmp_path / "out_old", now=later, tmp=tmp_path / "t1")
    r_new, _ = go(new, tmp_path / "out_new", now=later, tmp=tmp_path / "t2")
    assert r_old["new"] is True and r_new["new"] is True and r_old["pairs"] == r_new["pairs"] > 0
    for name in ("verification.json", "verification/1000_OR_SNTL.json"):
        a = json.loads((tmp_path / "out_old" / "verify" / name).read_text(encoding="utf-8"))
        b = json.loads((tmp_path / "out_new" / "verify" / name).read_text(encoding="utf-8"))
        assert a == b, name
