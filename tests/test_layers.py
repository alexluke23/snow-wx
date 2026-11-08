"""Value-encoded EPSG:3857 layers and NOHRSC/SNODAS helpers (offline)."""

from datetime import datetime, timezone

import numpy as np
import pytest

from pipeline import layers as L
from pipeline import nohrsc as N


def test_mercator_round_trip_and_grid_bounds():
    assert float(L.lat_of_y(L.merc_y(40.0))) == pytest.approx(40.0)
    assert float(L.lon_of_x(L.merc_x(-111.5))) == pytest.approx(-111.5)
    g = L.TargetGrid.from_bbox(-125.0, 31.0, -102.0, 49.5, 1500.0)
    (s, w), (n, e) = g.bounds_latlon()
    assert w == pytest.approx(-125.0) and n == pytest.approx(49.5)
    assert e >= -102.0 and s <= 31.0                        # ceil() covers the whole bbox
    assert g.center_lats()[0] < 49.5 and g.center_lats()[0] > g.center_lats()[-1]


def test_nearest_index_both_directions():
    asc = np.arange(10) * 0.5          # 0..4.5
    assert L.nearest_index(asc, [0.2, 0.3, 4.6, 4.8, -0.3]).tolist() == [0, 1, 9, -1, -1]
    desc = 50.0 - np.arange(5)         # 50..46 (north first)
    assert L.nearest_index(desc, [49.9, 46.4, 45.4]).tolist() == [0, 4, -1]


def test_regrid_and_sample():
    lats = np.linspace(45.0, 40.0, 51)                      # 0.1 deg, north first
    lons = np.linspace(-115.0, -110.0, 51)
    src = np.add.outer(np.arange(51) * 100.0, np.arange(51)).astype("float32")   # row*100 + col
    g = L.TargetGrid.from_bbox(-114.0, 41.0, -111.0, 44.0, 5000.0)
    out = L.regrid_regular(src, lats, lons, g)
    # every target cell holds the value of the source cell that contains its centre
    i, j = 3, 7
    lat, lon = float(g.center_lats()[i]), float(g.center_lons()[j])
    assert out[i, j] == L.sample(src, lats, lons, lat, lon)
    assert L.sample(src, lats, lons, 30.0, -112.0) is None


def test_encode_decode_round_trip():
    v = np.array([[0.0, 1.23, np.nan], [-0.4, 650.0, 12.0]])          # max code 65535 -> 654.35
    rgba = L.encode(v, 0.01, -1.0)
    assert rgba.dtype == np.uint8 and rgba[0, 2, 3] == 0 and rgba[0, 0, 3] == 255
    back = L.decode(rgba, 0.01, -1.0)
    assert np.isnan(back[0, 2])
    assert back[np.isfinite(back)] == pytest.approx(v[np.isfinite(v)], abs=0.005)
    assert L.png_bytes(rgba)[:8] == b"\x89PNG\r\n\x1a\n"


HDR = """Description: Modeled snow water equivalent, total of snow layers
Data units: Meters / 1000.000000
Data intercept: 0.00000000000000
Data slope: 1.00000000000000
No data value: -9999.00000000000
Number of columns: 4
Number of rows: 3
Benchmark x-axis coordinate: -124.729166666662
Benchmark y-axis coordinate: 52.8708333333312
X-axis resolution: 0.00833333333333300
Y-axis resolution: 0.00833333333333300
"""


def test_snodas_header_and_grid():
    h = N.parse_snodas_header(HDR)
    assert (h["ncols"], h["nrows"], h["nodata"]) == (4, 3, -9999.0)
    raw = np.array([[0, 254, -9999, 10], [1, 2, 3, 4], [5, 6, 7, 8]], dtype=">i2").tobytes()
    vals, lats, lons = N.snodas_grid(raw, h)
    assert vals[0, 1] == 254 and np.isnan(vals[0, 2])
    assert lats[0] > lats[-1] and lons[1] - lons[0] == pytest.approx(1 / 120)


def test_snowfall_candidates_and_run_key():
    now = datetime(2026, 11, 8, 3, 30, tzinfo=timezone.utc)
    c = N.snowfall_candidates(now, days=1)
    assert c[0] == datetime(2026, 11, 8, 0, tzinfo=timezone.utc) and c[1].hour == 12 and len(c) == 3
    sf = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
    assert N.run_key(sf, datetime(2026, 11, 7, tzinfo=timezone.utc)) == "2026110712"
    assert N.run_key(sf, datetime(2026, 11, 8, tzinfo=timezone.utc)) == "2026110806"     # SNODAS 06Z newer
    assert N.run_key(None, None) == ""


def test_crop():
    lats = np.linspace(55, 21, 851); lons = np.linspace(-126, -66, 1501)
    v = np.zeros((851, 1501))
    c, la, lo = N.crop(v, lats, lons, [-125.0, 31.0, -102.0, 49.5])
    assert la.max() <= 49.7 and la.min() >= 30.8 and lo.min() >= -125.2 and lo.max() <= -101.8
    assert c.shape == (len(la), len(lo))
