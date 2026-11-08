"""Ridge-top wind: interpolation, rotation, merge (offline)."""

import json
import math

import numpy as np

from pipeline.models import ridge as R


def test_interp_height_and_underground_levels():
    prof = [(1500.0, 10.0, 0.0), (3000.0, 20.0, 0.0), (5600.0, 40.0, 0.0)]
    assert R.interp_wind(2250.0, prof, ground_m=1000.0) == (15.0, 0.0)
    # 850 mb is below the model ground there -> a summit below 700 mb takes the 700 mb wind
    assert R.interp_wind(2250.0, prof, ground_m=2000.0) == (20.0, 0.0)
    assert R.interp_wind(7000.0, prof, None) == (40.0, 0.0)
    assert R.interp_wind(1000.0, [(float("nan"), 1.0, 1.0)], None) is None


def test_direction_and_rotation():
    assert R.speed_dir(0.0, -10.0)[1] == 0.0          # from the north
    assert R.speed_dir(10.0, 0.0)[1] == 270.0         # from the west
    crs = {"kind": "lcc", "lon0": -97.5, "lat1": 38.5, "lat2": 38.5}
    assert math.isclose(R.cone_constant(38.5, 38.5), math.sin(math.radians(38.5)))
    u, v = R.earth_relative(0.0, 10.0, -97.5, crs, True)
    assert abs(u) < 1e-9 and math.isclose(v, 10.0)    # no rotation on the central meridian
    u, v = R.earth_relative(0.0, 10.0, -111.6, crs, True)
    # west of the central meridian grid "up" points west of true north (cone constant 0.62 x -14.1 deg)
    assert math.isclose(u, 10 * math.sin(math.radians(0.6225 * -14.1)), rel_tol=0.01) and u < 0 and math.isclose(math.hypot(u, v), 10.0)
    assert R.earth_relative(1.0, 2.0, -111.6, {"kind": "latlon"}, False) == (1.0, 2.0)


def test_nearest_index():
    lat, lon = np.meshgrid(np.arange(40, 41, 0.03), np.arange(-112, -111, 0.03), indexing="ij")
    assert R.nearest_index(lat, lon, [(40.59, -111.64), (45.0, -111.6)]) == [(20, 12), None]


def test_merge_hrrr_then_rrfs(tmp_path):
    for m, valid, mph in [("hrrr", ["2026-11-08T00:00Z", "2026-11-09T00:00Z"], [10, 20]),
                          ("rrfs", ["2026-11-08T00:00Z", "2026-11-09T00:00Z", "2026-11-10T00:00Z"], [11, 21, 31])]:
        (tmp_path / m).mkdir()
        (tmp_path / m / "ridge.json").write_text(json.dumps({"model": m, "label": m.upper(), "cycle": "2026110800",
            "init": "2026-11-08T00:00Z", "valid": valid, "areas": {"alta": {"mph": mph, "dir": [270] * len(mph)}}}))
    d = R.merge(tmp_path, tmp_path / "ridge.json")
    assert d["valid"] == ["2026-11-08T00:00Z", "2026-11-09T00:00Z", "2026-11-10T00:00Z"]
    assert d["areas"]["alta"]["mph"] == [10, 20, 31] and d["src"] == [0, 0, 1]
