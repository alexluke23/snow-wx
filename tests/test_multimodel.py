"""M7 precipitation by model (pipeline/models/multimodel.py): sampling at summit points, merge into one site file, alignment to a common start."""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np

from pipeline.models import multimodel as mm

T = lambda h: datetime(2026, 11, 18, h, tzinfo=timezone.utc)  # noqa: E731
POINTS = [{"id": "alta", "lat": 40.0, "lon": -111.0, "elev_ft": 10500}, {"id": "far", "lat": 10.0, "lon": -50.0, "elev_ft": 5000}]


def grid():
    lat, lon = np.meshgrid(np.linspace(39.0, 41.0, 21), np.linspace(-112.0, -110.0, 21), indexing="ij")
    return SimpleNamespace(lat=lat, lon=lon)


def frame(total_in, orog_ft=7000.0):
    return {"qpf_total": np.full((21, 21), total_in, np.float32), "orog_ft": np.full((21, 21), orog_ft, np.float32)}


def test_sampler_keeps_run_total_at_the_nearest_cell_and_terrain_once():
    s = mm.PrecipSampler(POINTS)
    g = grid()
    s.add(0, {"orog_ft": np.full((21, 21), 7000.0, np.float32)}, g)             # f000: no total yet = 0
    s.add(3, frame(0.256), g)
    s.add(6, frame(0.71, orog_ft=1.0), g)
    doc = s.document("hrrr", "HRRR", T(0))
    assert doc["hours"] == [0, 3, 6] and doc["areas"]["alta"]["q"] == [0.0, 0.26, 0.71] and doc["areas"]["alta"]["z"] == 7000   # terrain from the first frame
    assert "far" not in doc["areas"]                                              # outside the grid: no series
    assert doc["init"] == "2026-11-18T00:00Z"


def test_a_frame_without_run_total_is_a_gap_not_a_zero():
    s = mm.PrecipSampler(POINTS[:1])
    g = grid()
    s.add(0, {}, g)
    s.add(3, {"orog_ft": np.zeros((21, 21), np.float32)}, g)                     # f003 failed to derive a total: skipped
    s.add(6, frame(0.5), g)
    assert s.document("gfs", "GFS", T(0))["areas"]["alta"]["q"] == [0.0, 0.5] and s.hours == [0, 6]


def test_merge_one_file_each_model_keeps_its_own_hours_and_init(tmp_path):
    for m, init, hours, q in (("hrrr", T(18), [0, 1, 2], [0.0, 0.1, 0.3]), ("gfs", T(12), [0, 6, 12], [0.0, 0.2, 0.9])):
        s = mm.PrecipSampler(POINTS[:1])
        for f, v in zip(hours, q):
            s.add(f, frame(v) if f else {}, grid())
        (tmp_path / m).mkdir()
        (tmp_path / m / "precip.json").write_text(json.dumps(s.document(m, m.upper(), init)), encoding="utf-8")
    out = tmp_path / "multimodel.json"
    doc = mm.merge(tmp_path, out)
    assert [m["model"] for m in doc["models"]] == ["hrrr", "gfs"] and doc["areas"]["alta"]["hrrr"]["q"] == [0.0, 0.1, 0.3]
    assert doc["areas"]["alta"]["gfs"]["z"] == 7000 and json.loads(out.read_text(encoding="utf-8"))["models"][1]["init"] == "2026-11-18T12:00Z"
    assert mm.merge(tmp_path / "nothing", tmp_path / "x.json") is None


def test_rebase_aligns_cumulative_series_to_a_common_start_by_linear_interpolation():
    # GFS init 12Z, 6-hourly: 0, 0.2, 0.9 in at 12Z, 18Z, 00Z. Rebased to 15Z (midway 12Z-18Z): cumulative at 15Z = 0.1
    q = mm.rebase(T(12), [0, 6, 12], [0.0, 0.2, 0.9], datetime(2026, 11, 18, 15, tzinfo=timezone.utc))
    assert q == [-0.1, 0.1, 0.8]                      # values before t0 are negative (not plotted); after t0 = precipitation since 15Z
    assert mm.rebase(T(12), [0, 6], [0.0, 0.2], datetime(2026, 11, 19, 0, tzinfo=timezone.utc)) is None      # t0 past the end of the run
    assert mm.rebase(T(18), [0, 1], [0.0, None], T(18)) == [0.0, None]
