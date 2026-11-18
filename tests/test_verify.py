"""M9-prep scorer (pipeline/verify.py): pairing, the SNOTEL outage / coverage exclusions, scores, README. Fixtures only (no archive download)."""

import csv
import gzip
import json

import pandas as pd

from pipeline import verify

OUTAGE = ("2026-11-16T12:00Z", "2026-11-18T00:45Z")


def write_gz(path, cols, rows):
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


FC = ("cycle", "point", "elev", "elev_ft", "cell_elev_ft", "hours", "end", "lead_h", "det", "det_cell", "p10", "p50", "p90", "p_ge4", "p_ge8", "p_ge12")
OB = ("end", "triplet", "depth_in", "depth_med3_in", "swe_in", "d_depth_24h", "d_depth_med3_24h", "d_swe_24h", "hours_present")


def nbm(point, end, det, p50, p4, lead=20, elev=7000):
    return {"cycle": "2026112019", "point": point, "elev": "point", "elev_ft": elev, "hours": 24, "end": end, "lead_h": lead, "det": det, "p50": p50, "p_ge4": p4}


def obs(triplet, end, d, hours=24):
    return {"end": end, "triplet": triplet, "d_depth_med3_24h": d, "hours_present": hours}


def archive(tmp_path):
    rows = [nbm("snotel-1000-OR-SNTL", "2026-11-21T12:00Z", 6.0, 4.0, 60),            # day 1 pair: obs 5.0
            nbm("snotel-1000-OR-SNTL", "2026-11-22T12:00Z", 0.2, 0.0, 2, lead=44),      # day 2 pair: obs 0 (clipped from -1)
            nbm("snotel-2000-UT-SNTL", "2026-11-21T12:00Z", 1.0, 1.0, 5, elev=9000),    # obs in the outage window? no: coverage too low
            nbm("snotel-3000-CO-SNTL", "2026-11-17T12:00Z", 3.0, 2.0, 20),             # inside the outage window: excluded
            nbm("snotel-4000-WA-SNTL", "2026-11-21T12:00Z", 2.0, 2.0, 10),             # no observation row
            nbm("alta-ski-area", "2026-11-21T12:00Z", 5.0, 5.0, 40)]                  # ski area: not scored
    write_gz(tmp_path / "nbm-202611.csv.gz", FC, rows)
    write_gz(tmp_path / "ndfd-202611.csv.gz", FC, [{**nbm("snotel-1000-OR-SNTL", "2026-11-21T12:00Z", 4.0, "", ""), "cycle": "2026112018"}])
    write_gz(tmp_path / "snotel-202611.csv.gz", OB, [obs("1000:OR:SNTL", "2026-11-21T12:00Z", 5.0), obs("1000:OR:SNTL", "2026-11-22T12:00Z", -1.0),
                                                     obs("2000:UT:SNTL", "2026-11-21T12:00Z", 1.0, hours=10), obs("3000:CO:SNTL", "2026-11-17T12:00Z", 4.0)])
    return tmp_path


def test_pairs_exclude_outage_low_coverage_missing_and_non_snotel_points(tmp_path):
    nb, nd, ob = verify.load_archive(archive(tmp_path))
    pairs, ex = verify.pair(nb, ob, OUTAGE)
    assert sorted(zip(pairs["triplet"], pairs["end"])) == [("1000:OR:SNTL", "2026-11-21T12:00Z"), ("1000:OR:SNTL", "2026-11-22T12:00Z")]
    assert ex == {"forecast_rows": 5, "no_observation": 1, "outage_window": 1, "low_coverage": 1, "missing_value": 0}   # alta-ski-area is never a SNOTEL pair
    assert list(pairs["obs"]) == [5.0, 0.0] and set(pairs["state"]) == {"OR"} and set(pairs["lead_bucket"]) == {"day 1 (0-24 h)", "day 2 (24-48 h)"}
    # without the outage window the CO pair comes back (so the exclusion is what removes it)
    again, ex2 = verify.pair(nb, ob, None)
    assert "3000:CO:SNTL" in set(again["triplet"]) and ex2["outage_window"] == 0


def test_scores_bias_mae_and_event_skill_and_brier(tmp_path):
    nb, nd, ob = verify.load_archive(archive(tmp_path))
    pairs, _ = verify.pair(nb, ob, OUTAGE)
    pairs["_src"] = "nbm"
    s = verify.score(pairs, [])
    det = s[s["source"] == "NBM expected"].iloc[0]
    assert det["n"] == 2 and det["bias_in"] == 0.6 and det["mae_in"] == 0.6 and det["pod_4"] == 1.0 and det["far_4"] == 0.0
    assert round(det["brier_p_ge4"], 3) == round(((0.6 - 1) ** 2 + (0.02 - 0) ** 2) / 2, 3)
    assert s[s["source"] == "NBM median"].iloc[0]["bias_in"] == -0.5


def test_run_writes_csvs_and_a_readme_that_states_the_limits(tmp_path):
    cfg = {"verification": {"snotel_outage": {"start": OUTAGE[0], "end": OUTAGE[1]}}}
    out = tmp_path / "out"
    summary = verify.run(archive(tmp_path), out, cfg)
    assert summary["pairs"] == 3 and summary["days"] == 2                       # NBM 2 + NDFD 1
    assert {p.name for p in out.iterdir()} >= {"README.md", "summary.json", "scores_by_lead.csv", "scores_by_state_days12.csv", "scores_by_elevation_days12.csv"}
    text = (out / "README.md").read_text(encoding="utf-8")
    assert "2026-11-18T00:45Z" in text and "Temperature is not scored" in text and "10 days of archive" in text and "NWS (NDFD)" in text
    assert json.loads((out / "summary.json").read_text(encoding="utf-8"))["outage_excluded"] == list(OUTAGE)
    assert not pd.read_csv(out / "scores_by_lead.csv").empty


def test_outage_exclusion_is_an_overlap_test_and_duplicate_observations_do_not_inflate_n(tmp_path):
    rows = [nbm("snotel-1-OR-SNTL", e, 2.0, 2.0, 10) for e in ("2026-11-16T12:00Z", "2026-11-18T12:00Z", "2026-11-19T12:00Z", "2026-11-15T12:00Z")]
    write_gz(tmp_path / "nbm-202611.csv.gz", FC, rows)
    ob = [obs("1:OR:SNTL", e, 1.0) for e in ("2026-11-16T12:00Z", "2026-11-18T12:00Z", "2026-11-19T12:00Z", "2026-11-15T12:00Z")]
    write_gz(tmp_path / "snotel-202611.csv.gz", OB, ob + [obs("1:OR:SNTL", "2026-11-19T12:00Z", 1.0)])      # one duplicated observation row
    nb, _, o = verify.load_archive(tmp_path)
    pairs, ex = verify.pair(nb, o, OUTAGE)
    # 11-15T12Z window ends before the outage and is kept; 11-16T12Z (ends at the start), 11-18T12Z (starts before the recovery) are excluded; 11-19T12Z kept once
    assert sorted(pairs["end"]) == ["2026-11-15T12:00Z", "2026-11-19T12:00Z"] and ex["outage_window"] == 2
