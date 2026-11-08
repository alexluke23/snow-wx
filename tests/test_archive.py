"""Forecast archive (pipeline/archive.py) and data_cache pruning (pipeline/cache.py)."""

import gzip
import json
import os
import time
from datetime import datetime, timezone

import numpy as np

from pipeline import archive as A
from pipeline.cache import prune


def _per(start, end, snow):
    return {"start": start, "end": end, "snow_in": snow}


PERIODS = [_per("2026-11-08T12:00Z", "2026-11-09T00:00Z", 1.0), _per("2026-11-09T00:00Z", "2026-11-09T12:00Z", 2.5),
           _per("2026-11-09T12:00Z", "2026-11-10T00:00Z", 0.5), _per("2026-11-10T00:00Z", "2026-11-10T12:00Z", 0.0),
           _per("2026-11-10T12:00Z", "2026-11-11T00:00Z", 4.0), _per("2026-11-11T00:00Z", "2026-11-11T12:00Z", 6.0)]


def _nbm_doc():
    ex24 = {"start": ["2026-11-08T12:00Z", "2026-11-09T12:00Z"], "end": ["2026-11-09T12:00Z", "2026-11-10T12:00Z"],
            "thr": [0.1, 1.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0], "p": [[90, 70, 50, 30, 20, 10, 5, 2], [40, 10, 5, 1, 0, 0, 0, 0]],
            "pct": {"10": [0.4, 0.0], "50": [3.1, 0.2], "90": [7.9, 1.4]}, "mean": [3.5, 0.5], "cell_mean": [4.0, 0.6]}
    pt = {"elev_ft": 10500, "grid_elev_ft": 9600, "periods": PERIODS, "exceed": {"24h": ex24}}
    return {"id": "alta-ski-area", "cycle": "2026110801", "points": {"summit": pt}}


def test_twelve_z_windows_need_exact_cover():
    w24 = A.twelve_z_windows(PERIODS, 24)
    assert w24 == [("2026-11-08T12:00Z", "2026-11-09T12:00Z", 3.5), ("2026-11-09T12:00Z", "2026-11-10T12:00Z", 0.5),
                   ("2026-11-10T12:00Z", "2026-11-11T12:00Z", 10.0)]
    assert A.twelve_z_windows(PERIODS, 72) == [("2026-11-08T12:00Z", "2026-11-11T12:00Z", 14.0)]
    gap = PERIODS[:2] + PERIODS[3:]                       # 12Z 9 Nov -> 00Z 10 Nov missing
    assert [w[1] for w in A.twelve_z_windows(gap, 24)] == ["2026-11-09T12:00Z", "2026-11-11T12:00Z"]


def test_nbm_rows_all_leads_with_cell_values():
    rows = A.nbm_rows(_nbm_doc())
    by = {(r["hours"], r["end"]): r for r in rows}
    assert len(rows) == 4                                 # three 24-h windows + one 72-h window
    r = by[("24", "2026-11-09T12:00Z")]
    assert (r["det"], r["det_cell"], r["p10"], r["p50"], r["p90"]) == ("3.5", "4", "0.4", "3.1", "7.9")
    assert (r["p_ge4"], r["p_ge8"], r["p_ge12"], r["lead_h"]) == ("30", "10", "2", "35")
    assert (r["elev_ft"], r["cell_elev_ft"], r["elev"]) == ("10500", "9600", "summit")
    late = by[("24", "2026-11-11T12:00Z")]                # beyond the exceedance windows: det only
    assert late["det"] == "10" and late["p50"] == "" and late["p_ge4"] == ""
    assert by[("72", "2026-11-11T12:00Z")]["det"] == "14"


def test_ndfd_rows_only_windows_after_issue():
    doc = {"id": "alta-ski-area", "issued": "2026-11-09T00:00Z",
           "points": {"summit": {"elev_ft": 10500, "grid_elev_ft": 9568, "periods": PERIODS}}}
    rows = A.ndfd_rows(doc)
    assert {(r["cycle"], r["end"], r["det"]) for r in rows} == {("2026110900", "2026-11-10T12:00Z", "0.5"),
                                                               ("2026110900", "2026-11-11T12:00Z", "10")}
    assert all(r["p50"] == "" for r in rows)


def test_snotel_rows_at_12z_with_offsets_and_gaps():
    times = [f"2026-11-0{d} {h:02d}:00" for d in (7, 8) for h in range(24)]
    n = len(times)
    sd = [10.0 + 0.1 * i for i in range(n)]
    sd[20] = None                                         # one gap inside the 24 h before 04:00 on the 8th
    ts = {"triplet": "1000:OR:SNTL", "times": times, "SNWD": sd, "SNWD_med3": sd, "WTEQ": [2.0] * n}
    rows = A.snotel_rows(ts, -8.0)                        # 12Z = 04:00 PST
    assert [r["end"] for r in rows] == ["2026-11-07T12:00Z", "2026-11-08T12:00Z"]
    first, second = rows
    assert first["d_depth_24h"] == "" and first["hours_present"] == "0"     # no value 24 h earlier
    assert second["depth_in"] == "12.8" and second["d_depth_24h"] == "2.4" and second["d_swe_24h"] == "0"
    assert second["hours_present"] == "23"
    assert [r["end"] for r in A.snotel_rows(ts, -7.0)] == ["2026-11-07T12:00Z", "2026-11-08T12:00Z"]  # 05:00 MST


def _write_build(tmp, cycle="2026110801"):
    data = tmp / "data"
    (data / "points").mkdir(parents=True)
    (data / "ndfd").mkdir()
    (data / "snotel").mkdir()
    doc = _nbm_doc() | {"cycle": cycle}
    (data / "points" / "alta-ski-area.json").write_text(json.dumps(doc))
    (data / "points" / "summary.json").write_text(json.dumps({"cycle": cycle, "areas": []}))
    (data / "ndfd" / "alta-ski-area.json").write_text(json.dumps(
        {"id": "alta-ski-area", "issued": "2026-11-08T12:00Z", "points": {"summit": {"elev_ft": 10500, "periods": PERIODS}}}))
    times = [f"2026-11-0{d} {h:02d}:00" for d in (7, 8) for h in range(24)]
    (data / "snotel" / "1000_OR_SNTL.json").write_text(json.dumps(
        {"triplet": "1000:OR:SNTL", "utc_offset_h": -8, "times": times, "SNWD": [5.0] * 48, "SNWD_med3": [5.0] * 48,
         "WTEQ": [1.0] * 48}))
    return data


def test_archive_idempotent_and_safe(tmp_path):
    data = _write_build(tmp_path)
    store = A.LocalStore(tmp_path / "release")
    now = datetime(2026, 11, 9, 3, tzinfo=timezone.utc)
    s1 = A.archive(data, store, tmp_path / "w1", now=now)
    assert set(s1) == {"nbm-202611.csv.gz", "ndfd-202611.csv.gz", "snotel-202611.csv.gz"}
    assert s1["nbm-202611.csv.gz"]["added"] == 4
    state = json.loads((tmp_path / "release" / "state.json").read_text())
    assert state["nbm"] == ["2026110801"] and state["ndfd"] == ["2026110812"]
    # same build again: nothing new, nothing uploaded
    before = {p.name: p.stat().st_mtime_ns for p in (tmp_path / "release").iterdir()}
    assert A.archive(data, store, tmp_path / "w2", now=now) == {}
    assert {p.name: p.stat().st_mtime_ns for p in (tmp_path / "release").iterdir()} == before
    # a new cycle is appended to the downloaded monthly file, never replacing it
    data2 = _write_build(tmp_path / "b2", cycle="2026110807")
    s3 = A.archive(data2, store, tmp_path / "w3", now=now)
    assert s3["nbm-202611.csv.gz"]["rows"] == 8 and "snotel-202611.csv.gz" not in s3
    with gzip.open(tmp_path / "release" / "nbm-202611.csv.gz", "rt") as f:
        lines = f.read().splitlines()
    assert lines[0] == ",".join(A.FORECAST_COLS) and len(lines) == 9


def test_archive_month_split_and_guard():
    assert A.month_of("nbm", {"cycle": "2026113019"}) == "202611"
    assert A.month_of("snotel", {"end": "2026-12-01T12:00Z"}) == "202612"
    assert A.allowed_months(datetime(2026, 12, 1, 2, tzinfo=timezone.utc)) == {"202612", "202611"}


def test_prune_keeps_recent_and_protected(tmp_path):
    root = tmp_path / "data_cache"
    for rel in ("herbie/hrrr/old.grib2", "herbie/hrrr/new.grib2", "nbm/2026110100_x/f001.npz",
                "catalog/dem_cells.json", "openskimap/lifts.geojson", "stray.csv"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * 100)
    old = time.time() - 3 * 86400
    for rel in ("herbie/hrrr/old.grib2", "nbm/2026110100_x/f001.npz", "catalog/dem_cells.json",
                "openskimap/lifts.geojson", "stray.csv"):
        os.utime(root / rel, (old, old))
    res = prune(root, days=2)
    assert res == {"files": 3, "bytes": 300}
    left = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert left == ["catalog/dem_cells.json", "herbie/hrrr/new.grib2", "openskimap/lifts.geojson"]
    assert not (root / "nbm").exists()                    # emptied folders removed


def test_exceedance_carries_cell_percentiles():
    from pipeline.nbm.run import cell_window_sums, exceedance
    init = datetime(2026, 11, 8, 1, tzinfo=timezone.utc)
    data = {35: {"snow24_gt4": np.array([12.0]), "snow24_p10": np.array([0.44]), "snow24_p50": np.array([2.0]),
                 "snow24_p90": np.array([6.06])}}
    ex = exceedance(data, [35], init, 0)
    assert ex["24h"]["pct"] == {"10": [0.4], "50": [2.0], "90": [6.1]}
    W = {h: {"raw": 1.5} for h in (17, 23, 29, 35)}
    assert cell_window_sums(W, init, ex["24h"]["start"], ex["24h"]["end"]) == [6.0]
    assert cell_window_sums({35: {"raw": 1.0}}, init, ex["24h"]["start"], ex["24h"]["end"]) == [None]
