"""tools/slr_baseline.py (dev22 Part 5c): derived observed snow ratios and the baseline score, on synthetic rows only."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import slr_baseline as B  # noqa: E402


def rows(*r):
    return pd.DataFrame([{"end": e, "triplet": t, "d_depth_med3_24h": d, "d_swe_24h": s, "hours_present": h} for e, t, d, s, h in r])


def test_filters_follow_the_paper_and_count_what_they_remove():
    o = rows(("2026-11-18T12:00Z", "1:ID:SNTL", 6.0, 0.5, 24),      # 12:1 qualifies
             ("2026-11-18T12:00Z", "2:ID:SNTL", 1.5, 0.2, 24),      # < 2 in of new snow
             ("2026-11-18T12:00Z", "3:UT:SNTL", 5.0, 0.05, 24),     # SWE too small
             ("2026-11-18T12:00Z", "4:UT:SNTL", 4.0, 2.0, 24),      # ratio 2: dropped (<= 2)
             ("2026-11-18T12:00Z", "5:UT:SNTL", 30.0, 0.5, 24),     # ratio 60: dropped
             ("2026-11-18T12:00Z", "6:UT:SNTL", 5.0, 0.5, 24),      # exactly 10.0: dropped (board/pillow artefact)
             ("2026-11-18T12:00Z", "7:WA:SNTL", 6.0, 0.5, 12),      # too few hourly reports
             ("2026-11-19T12:00Z", "8:WA:SNTL", float("nan"), 0.5, 24))
    ev, st = B.derive_events(o)
    assert list(ev["triplet"]) == ["1:ID:SNTL"] and abs(ev["ratio"][0] - 12) < 1e-9 and ev["state"][0] == "ID"
    assert st["rows"] == 8 and st["qualifying"] == 1 and st["enough_reports"] < st["with_both_changes"]


def test_fixed_ratio_scores_and_regions():
    rng = np.random.default_rng(1)
    n = 40
    ev = pd.DataFrame({"end": pd.date_range("2026-12-01", periods=n, tz="UTC"), "triplet": [f"{i}:{'ID' if i % 2 else 'UT'}:SNTL" for i in range(n)],
                       "ratio": 12 + rng.normal(0, 2, n)})
    ev["state"] = ev["triplet"].str.split(":").str[1]
    s = B.score(ev, fixed=(12, 8))
    allr = s[s.region == "all"].set_index("predictor")
    assert allr.loc["fixed 12:1", "mae"] < allr.loc["fixed 8:1", "mae"] and abs(allr.loc["fixed 8:1", "bias"] + 4) < 1.5
    assert set(s.region) == {"all", "ID", "UT"}


def test_nbm_slr_is_scored_only_when_a_file_supplies_it():
    ev = pd.DataFrame({"end": pd.to_datetime(["2026-12-01T12:00Z"] * 6 + ["2026-12-02T12:00Z"] * 6, utc=True), "triplet": [f"{i}:ID:SNTL" for i in range(12)], "ratio": [12.0] * 12})
    ev["state"] = "ID"
    assert "NBM SLR p50" not in set(B.score(ev).predictor)
    nbm = pd.DataFrame({"end": ev["end"].dt.strftime("%Y-%m-%dT%H:%MZ"), "triplet": ev["triplet"], "slr_p50": [14.0] * 12})
    s = B.score(ev, nbm=nbm)
    row = s[(s.predictor == "NBM SLR p50") & (s.region == "all")].iloc[0]
    assert abs(row.bias - 2) < 1e-9 and row.mae == 2


def test_nbm_slr_from_the_archive_columns_newest_cycle_wins_and_old_format_is_skipped():
    """dev23: the nbm archive rows carry slr_p50 at the 12Z end; the shortest lead per (end, triplet) is used, blank / old-format rows give nothing"""
    rows = [{"point": "snotel-1000-ID-SNTL", "hours": 24, "end": "2026-12-20T12:00Z", "lead_h": 44, "slr_p50": 9.0},
            {"point": "snotel-1000-ID-SNTL", "hours": 24, "end": "2026-12-20T12:00Z", "lead_h": 20, "slr_p50": 13.0},
            {"point": "snotel-1000-ID-SNTL", "hours": 72, "end": "2026-12-20T12:00Z", "lead_h": 20, "slr_p50": 99.0},
            {"point": "alta-ski-area", "hours": 24, "end": "2026-12-20T12:00Z", "lead_h": 20, "slr_p50": 12.0},
            {"point": "snotel-2000-UT-SNTL", "hours": 24, "end": "2026-12-20T12:00Z", "lead_h": 20, "slr_p50": None}]
    got = B.nbm_slr_from_archive(pd.DataFrame(rows))
    assert got.to_dict("records") == [{"end": "2026-12-20T12:00Z", "triplet": "1000:ID:SNTL", "slr_p50": 13.0}]
    assert B.nbm_slr_from_archive(pd.DataFrame(rows).drop(columns="slr_p50")) is None and B.nbm_slr_from_archive(pd.DataFrame()) is None
