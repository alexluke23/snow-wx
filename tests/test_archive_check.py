"""dev21 stretch 2: forecast-archive integrity guard (pipeline/archive_check.py). Fixture files only."""
import csv
import gzip
import json
from datetime import datetime, timezone

from pipeline import archive_check as AC
from pipeline.archive import FORECAST_COLS, NBM_COLS, OBS_COLS

NOW = datetime(2026, 12, 3, 12, tzinfo=timezone.utc)


def gz(path, cols, rows):
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow(r)


def fc_row(cycle, point="alta-ski-area", end="2026-11-21T12:00Z"):
    d = {c: "" for c in FORECAST_COLS}
    d.update(cycle=cycle, point=point, elev="summit", hours="24", end=end, lead_h="20", det="1.0")
    return [d[c] for c in FORECAST_COLS]


def ob_row(end, trip="1000:OR:SNTL"):
    d = {c: "" for c in OBS_COLS}
    d.update(end=end, triplet=trip, depth_in="10")
    return [d[c] for c in OBS_COLS]


def good(folder, months=("202611", "202612")):
    folder.mkdir(parents=True, exist_ok=True)
    for m in months:
        gz(folder / f"nbm-{m}.csv.gz", FORECAST_COLS, [fc_row(f"{m}2019"), fc_row(f"{m}2101")])
        gz(folder / f"ndfd-{m}.csv.gz", FORECAST_COLS, [fc_row(f"{m}2018")])
        gz(folder / f"snotel-{m}.csv.gz", OBS_COLS, [ob_row(f"{m[:4]}-{m[4:]}-02T12:00Z")])
    return folder


def test_a_clean_archive_passes(tmp_path):
    res = AC.check(good(tmp_path / "a"), now=NOW)
    assert res["problems"] == [] and res["months"]["nbm"] == ["202611", "202612"] and res["files"]["nbm-202611.csv.gz"]["rows"] == 2


def test_columns_changed_or_extra_are_flagged(tmp_path):
    d = good(tmp_path / "a")
    gz(d / "nbm-202612.csv.gz", list(FORECAST_COLS) + ["new_col"], [fc_row("2026122019") + ["x"]])
    res = AC.check(d, now=NOW)
    assert any("columns differ" in p and "new_col" in p for p in res["problems"])


def test_header_change_and_shrinking_rows_since_the_last_check(tmp_path):
    d = good(tmp_path / "a")
    prev = AC.check(d, now=NOW)["files"]
    prev["nbm-202612.csv.gz"]["rows"] = 5                                         # the last check saw more rows
    prev["ndfd-202612.csv.gz"]["header"] = list(FORECAST_COLS)[:-1]               # ... and another header
    res = AC.check(d, prev, now=NOW)
    assert any("row count shrank" in p and "5 -> 2" in p for p in res["problems"])
    assert any("ndfd-202612.csv.gz: columns changed" in p for p in res["problems"])


def test_missing_month_gap_and_current_month(tmp_path):
    d = good(tmp_path / "a", months=("202610", "202612"))
    res = AC.check(d, now=NOW)
    assert any("nbm: missing months 202611" in p for p in res["problems"])
    d2 = good(tmp_path / "b", months=("202611",))
    res2 = AC.check(d2, now=NOW)
    assert any("no file for the current month 202612" in p for p in res2["problems"])
    assert not any("current month" in p for p in AC.check(d2, now=datetime(2026, 12, 1, 3, tzinfo=timezone.utc))["problems"])   # first day: not yet


def test_bad_rows_duplicates_and_wrong_month(tmp_path):
    d = good(tmp_path / "a")
    gz(d / "nbm-202612.csv.gz", FORECAST_COLS, [fc_row("2026122019"), fc_row("2026122019"), fc_row("2026112019"), ["short", "row"]])
    res = AC.check(d, now=NOW)
    f = res["files"]["nbm-202612.csv.gz"]
    assert f["dup_keys"] == 1 and f["wrong_month"] == 1 and f["bad_rows"] == 1 and len(f["problems"]) == 3


def test_a_file_that_disappeared(tmp_path):
    d = good(tmp_path / "a")
    prev = AC.check(d, now=NOW)["files"]
    (d / "snotel-202611.csv.gz").unlink()
    assert any("snotel-202611.csv.gz: present at the last check, missing now" in p for p in AC.check(d, prev, now=NOW)["problems"])


def test_run_writes_the_state_and_exits_1_on_a_problem(tmp_path, capsys):
    d = good(tmp_path / "a")
    st = tmp_path / "state.json"
    assert AC.run(d, st, now=NOW) == 0 and json.loads(st.read_text(encoding="utf-8"))["files"]["nbm-202611.csv.gz"]["rows"] == 2
    gz(d / "nbm-202612.csv.gz", FORECAST_COLS, [fc_row("2026122019")])           # 2 -> 1 row
    assert AC.run(d, st, now=NOW) == 1 and "row count shrank" in capsys.readouterr().out


# ---------------------------------------------------------------- dev23: NBM snow-ratio columns (old and new format)
def nbm_row(cycle, slr=("", "", ""), end="2026-11-21T12:00Z", point="alta-ski-area"):
    d = {c: "" for c in NBM_COLS}
    d.update(cycle=cycle, point=point, elev="summit", hours="24", end=end, lead_h="20", det="1.0", slr_p25=slr[0], slr_p50=slr[1], slr_p75=slr[2])
    return [d[c] for c in NBM_COLS]


def test_old_and_new_nbm_headers_are_both_valid(tmp_path):
    d = good(tmp_path / "a")                                                         # nbm-202611 and nbm-202612 in the pre-dev23 format
    gz(d / "nbm-202612.csv.gz", NBM_COLS, [nbm_row("2026121907", ("9", "11", "13"))])      # ... plus one in the new format
    res = AC.check(d, now=NOW)
    assert res["problems"] == []
    assert res["files"]["nbm-202611.csv.gz"]["slr"]["filled"] == 0 and "written before dev23" in AC.slr_line(res["files"]["nbm-202611.csv.gz"]["slr"], res["files"]["nbm-202611.csv.gz"]["header"])
    assert "ndfd" not in {f["kind"] for f in res["files"].values() if "slr" in f}


def test_slr_fill_rate_counts_from_the_first_cycle_with_values(tmp_path):
    d = good(tmp_path / "a")
    rows = [nbm_row("2026120801", end="2026-12-09T12:00Z"),                                 # before the columns were filled: not counted as missing
            nbm_row("2026121007", ("9", "11", "13"), end="2026-12-11T12:00Z"),             # first cycle with values
            nbm_row("2026121007", ("9", "", "13"), end="2026-12-12T12:00Z"),               # one percentile blank still counts as filled
            nbm_row("2026121013", end="2026-12-11T12:00Z"),                                # core cycle, blank
            nbm_row("2026121012", end="2026-12-11T12:00Z", point="x")]                     # synoptic cycle, blank
    gz(d / "nbm-202612.csv.gz", NBM_COLS, rows)
    s = AC.check(d, now=NOW)["files"]["nbm-202612.csv.gz"]["slr"]
    assert s["first_cycle"] == "2026121007" and (s["rows_since"], s["filled_since"]) == (4, 2) and (s["core_rows_since"], s["core_filled_since"]) == (3, 2)
    line = AC.slr_line(s, list(NBM_COLS))
    assert "2 of 4 rows since cycle 2026121007 (50.0 %)" in line and "01/07/13/19Z cycles 2 of 3 (66.7 %)" in line
    assert "no values yet" in AC.slr_line(AC._slr_fill({"2026121007": [1, 0]}), list(NBM_COLS))


def test_header_growth_between_checks_is_allowed_once_and_only_for_nbm(tmp_path):
    d = good(tmp_path / "a")
    prev = AC.check(d, now=NOW)["files"]                                                # last check: the old 16-column header
    gz(d / "nbm-202612.csv.gz", NBM_COLS, [nbm_row("2026122019"), nbm_row("2026122101")])
    assert AC.check(d, prev, now=NOW)["problems"] == []                                 # old -> new: additive, fine
    prev2 = AC.check(d, now=NOW)["files"]
    gz(d / "nbm-202612.csv.gz", FORECAST_COLS, [nbm_row("2026122019")[:16], nbm_row("2026122101")[:16]])
    assert any("columns changed" in p for p in AC.check(d, prev2, now=NOW)["problems"])   # new -> old is not
    prev3 = AC.check(good(tmp_path / "b"), now=NOW)["files"]
    gz(tmp_path / "b" / "ndfd-202612.csv.gz", NBM_COLS, [nbm_row("2026122018")])
    assert any("ndfd-202612.csv.gz: columns differ" in p for p in AC.check(tmp_path / "b", prev3, now=NOW)["problems"])   # NDFD never gets the SLR columns


def test_run_prints_the_slr_fill_line(tmp_path, capsys):
    d = good(tmp_path / "a")
    gz(d / "nbm-202612.csv.gz", NBM_COLS, [nbm_row("2026121907", ("9", "11", "13"))])
    assert AC.run(d, None, now=NOW) == 0
    out = capsys.readouterr().out
    assert "SLR p25/p50/p75 filled: 1 of 1 rows since cycle 2026121907 (100.0 %)" in out and "written before dev23" in out
