"""dev21 stretch 2: forecast-archive integrity guard (pipeline/archive_check.py). Fixture files only."""
import csv
import gzip
import json
from datetime import datetime, timezone

from pipeline import archive_check as AC
from pipeline.archive import FORECAST_COLS, OBS_COLS

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
