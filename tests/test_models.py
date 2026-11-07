"""Offline tests for the model-map pipeline (no network, no Natural Earth)."""

import json
from datetime import datetime

import numpy as np
import pytest

from pipeline.models import derive as d
from pipeline.models.catalog import collect
from pipeline.models.config import (expand_fhours, field_domains, field_fhours, image_count,
                                    load_models_config, total_image_count)
from pipeline.models.fetch import Grid, candidate_cycles, latest_cycle, needed_vars, var_catalog
from pipeline.models.run import RunState, build_index, derive_frame, run_model


@pytest.fixture(scope="module")
def mcfg():
    return load_models_config()


# ---------------------------------------------------------------- config

def test_expand_fhours():
    assert expand_fhours([[0, 3, 1], [6, 12, 3]]) == [0, 1, 2, 3, 6, 9, 12]
    assert expand_fhours([[0, 48, 3], 1]) [:3] == [0, 1, 3]


def test_field_fhours_need_history():
    fh = expand_fhours([[0, 18, 1], [21, 48, 3]])
    assert field_fhours("qpf1", fh) == list(range(1, 19))           # no f20 to difference f21
    assert field_fhours("qpf24", fh) == [24, 27, 30, 33, 36, 39, 42, 45, 48]
    assert field_fhours("snow", fh)[0] == 1 and 0 not in field_fhours("qpf_total", fh)
    assert field_fhours("t2m", fh) == fh


def test_image_budget(mcfg):
    assert field_domains(mcfg, "hrrr", "h500") == ["west"]
    assert len(field_domains(mcfg, "hrrr", "t2m")) == 6
    assert image_count(mcfg, "hrrr") == 1361
    assert total_image_count(mcfg) <= mcfg["budget"]["max_images"]


# ---------------------------------------------------------------- derive

def test_qpf_window_and_frozen_fraction():
    totals = {0: np.zeros(3), 6: np.array([0.0, 0.5, 1.0]), 12: np.array([0.0, 0.7, 0.9])}
    np.testing.assert_allclose(d.qpf_window(totals, 12, 6), [0.0, 0.2, 0.0])  # never negative
    assert d.qpf_window(totals, 12, 24) is None
    np.testing.assert_allclose(d.frozen_fraction(np.array([-50.0, 0, 40, 100])), [0, 0, 0.4, 1])
    np.testing.assert_allclose(d.frozen_fraction(None, np.array([0.0, 1.0])), [0, 1])


def test_kuchera_slr():
    t = np.array([271.16, 266.16, 273.16, 280.0, 230.0])
    np.testing.assert_allclose(d.kuchera_slr(t), [12, 17, 8, 0, 30], atol=1e-6)


def test_column_tmax_masks_below_ground_levels():
    t2m = np.array([268.0, 268.0])
    levels = {850: np.array([280.0, 280.0]), 700: np.array([270.0, 270.0]),
              500: np.array([250.0, 250.0])}
    psfc = np.array([80000.0, 95000.0])      # point 0: 850 mb is underground
    tmax = d.column_tmax(t2m, levels, psfc)
    np.testing.assert_allclose(tmax, [270.0, 280.0])
    # height test catches it too, even if surface pressure were missing/odd
    tmax_z = d.column_tmax(t2m, levels, np.array([95000.0, 95000.0]),
                           {850: np.array([1400.0, 1400.0])}, np.array([2000.0, 1000.0]))
    np.testing.assert_allclose(tmax_z, [270.0, 280.0])


def test_wetbulb_and_rh():
    assert d.wetbulb_stull(20.0, 50.0) == pytest.approx(13.7, abs=0.1)   # Stull (2011) example
    assert d.rh_from_dewpoint(5.0, 5.0) == pytest.approx(100.0)
    assert d.height_lnp(100.0, 1000, 1500.0, 850, 925) == pytest.approx(
        100 + 1400 * np.log(1000 / 925) / np.log(1000 / 850))


def test_wetbulb_zero_height():
    one = lambda v: np.array([v], dtype=float)  # noqa: E731
    levels = lambda tw850: [(1000, one(100.0), one(10.0)),   # below ground -> skipped  # noqa: E731
                            (850, one(1500.0), one(tw850)),
                            (700, one(3000.0), one(-5.0)),
                            (500, one(5600.0), one(-20.0))]
    psfc = one(90000.0)
    z = d.wetbulb_zero_height(one(1000.0), one(2.0), levels(1.0), psfc)
    assert z[0] == pytest.approx(1750.0)                       # 1 -> -5 between 1500 and 3000 m
    assert d.wetbulb_zero_height(one(1000.0), one(-1.0), levels(1.0), psfc)[0] == 1000.0  # at ground
    warm = [(p, z_, one(5.0)) for p, z_, _ in levels(1.0)]
    assert np.isnan(d.wetbulb_zero_height(one(1000.0), one(2.0), warm, psfc)[0])
    np.testing.assert_allclose(d.cap_at(np.array([3000.0, 1000.0, np.nan]),
                                        np.array([2500.0, 2500.0, 2000.0])), [2500, 1000, np.nan])


def test_vorticity_solid_body():
    omega = 1e-4
    y, x = np.mgrid[0:20, 0:30] * 3000.0
    u, v = -omega * y, omega * x
    zeta = d.relative_vorticity(u, v, 3000.0, 3000.0)
    np.testing.assert_allclose(zeta, 2 * omega)
    absv = d.absolute_vorticity(u, v, np.full(u.shape, 45.0), 3000.0, 3000.0)
    np.testing.assert_allclose(absv, 2 * omega + 2 * d.OMEGA * np.sin(np.pi / 4))


# ---------------------------------------------------------------- frames

def _grid(shape=(4, 5)):
    lat, lon = np.meshgrid(np.linspace(40, 41, shape[0]), np.linspace(-112, -111, shape[1]), indexing="ij")
    return Grid(lat=lat, lon=lon, crs={"kind": "latlon"}, uv_grid_relative=False,
                dx_m=3000.0, dy_m=3000.0, rows=slice(None), cols=slice(None))


def _raw(apcp_mm, shape=(4, 5)):
    f = lambda v: np.full(shape, v, dtype=np.float32)  # noqa: E731
    raw = {"orog": f(1500.0), "sp": f(85000.0), "t2m": f(268.15), "d2m": f(266.0),
           "cpofp": f(100.0), "gust": f(10.0), "gh500": f(5600.0), "gh700": f(3000.0),
           "gh850": f(1450.0), "gh1000": f(100.0), "t700": f(263.15), "u700": f(10.0),
           "v700": f(0.0), "u500": f(20.0), "v500": f(0.0), "hgt0c": f(1500.0), "fzl_top": f(1500.0)}
    for p, t in ((1000, 280.0), (925, 275.0), (850, 268.0), (700, 263.15), (500, 245.0)):
        raw[f"t{p}"] = f(t)
        raw[f"dpt{p}"] = f(t - 1.0)
    if apcp_mm is not None:
        raw["apcp"] = f(apcp_mm)
    return raw


def test_derive_frame_accumulates(mcfg):
    m = mcfg["models"]["hrrr"]
    st, grid = RunState(), _grid()
    out0 = derive_frame(_raw(None), grid, m, m["fields"], 0, st)
    assert "qpf_total" not in out0 and "snow10" not in out0 and "t2m_f" in out0
    out6 = derive_frame(_raw(25.4), grid, m, m["fields"], 6, st)        # 1.00 in by f006
    out12 = derive_frame(_raw(38.1), grid, m, m["fields"], 12, st)      # 1.50 in by f012
    assert out6["qpf6"][0, 0] == pytest.approx(1.0) and out12["qpf6"][0, 0] == pytest.approx(0.5)
    assert out12["qpf_total"][0, 0] == pytest.approx(1.5)
    assert "qpf24" not in out12
    assert out12["snow10"][0, 0] == pytest.approx(15.0, rel=1e-4)     # all frozen at 10:1
    # Tmax: 850 mb is below ground (psfc 850 mb == level -> kept), so Tmax = 268.15 K -> SLR 15
    assert out12["snowku"][0, 0] == pytest.approx(1.5 * d.kuchera_slr(np.array(268.15)), rel=1e-3)
    assert out12["t2m_f"][0, 0] == pytest.approx(23.0, abs=0.05)
    assert out12["precip_now"][0, 0] == 1.0


def test_needed_vars_follow_config(mcfg):
    hrrr = needed_vars(mcfg["models"]["hrrr"], ["h500", "snowlevel"])
    assert {"u500", "v500", "dpt850", "fzl_top"} <= set(hrrr) and "absv500" not in hrrr
    gfs = needed_vars(mcfg["models"]["gfs"], ["h500", "snowlevel"])
    assert "absv500" in gfs and "rh850" in gfs and "dpt850" not in gfs
    cat = var_catalog([700])
    assert cat["apcp"].idx.startswith(":APCP:surface:0-")


# ---------------------------------------------------------------- cycles / skip

def test_candidate_and_latest_cycle():
    now = datetime(2026, 11, 7, 9, 30)
    c = candidate_cycles(now, [0, 6, 12, 18])
    assert c[:3] == [datetime(2026, 11, 7, 6), datetime(2026, 11, 7, 0), datetime(2026, 11, 6, 18)]
    assert latest_cycle(c, lambda x: x.hour == 0) == datetime(2026, 11, 7, 0)
    assert latest_cycle(c, lambda x: False) is None


def test_run_model_skips_when_already_published(mcfg, tmp_path, monkeypatch):
    # Cron runs 10-60 min late: whatever "now" is, if the newest complete cycle is
    # the published one the job must exit 0 and write nothing.
    monkeypatch.setattr("pipeline.models.run.cycle_complete", lambda m, c, f, s: c.hour == 0)
    gh = tmp_path / "gh_output"
    code = run_model(mcfg, "hrrr", tmp_path / "out", published="2026110700",
                     github_output=str(gh), now=datetime(2026, 11, 7, 4, 55))
    assert code == 0
    assert not (tmp_path / "out").exists()
    assert "new=false" in gh.read_text()


def test_run_model_no_complete_cycle_is_clean(mcfg, tmp_path, monkeypatch):
    monkeypatch.setattr("pipeline.models.run.cycle_complete", lambda m, c, f, s: False)
    assert run_model(mcfg, "hrrr", tmp_path / "out", now=datetime(2026, 11, 7, 4)) == 0
    assert not (tmp_path / "out").exists()


# ---------------------------------------------------------------- index / catalog

def test_build_index_and_catalog(mcfg, tmp_path):
    ok = [{"field": "t2m", "domain": "wasatch", "f": 6, "bytes": 10},
          {"field": "t2m", "domain": "west", "f": 0, "bytes": 10},
          {"field": "h500", "domain": "west", "f": 0, "bytes": 5}]
    idx = build_index(mcfg, "hrrr", datetime(2026, 11, 7, 0), ok)
    assert idx["fields"]["t2m"]["domains"] == ["west", "wasatch"]      # config order
    assert idx["fields"]["t2m"]["fhours"] == [0, 6]
    assert list(idx["fields"]) == ["h500", "t2m"]                       # model field order
    assert idx["path"].format(field="t2m", domain="west", fhour="006") == "2026110700/t2m/west/f006.png"
    for name in ("gfs", "hrrr"):
        p = tmp_path / name / "index.json"
        p.parent.mkdir()
        p.write_text(json.dumps({**idx, "model": name}))
    cat = collect(tmp_path, ["hrrr", "rrfs", "gfs"])
    assert list(cat["models"]) == ["hrrr", "gfs"] and cat["models"]["gfs"]["base"] == "gfs/"


# ---------------------------------------------------------------- plotting smoke test

def test_crop_bounds_cover_lambert_corners(mcfg):
    # First render left the western map's NE corner empty: a Lambert box built from
    # [-125.5, -102, 31, 49.5] reaches well east of -102 at its northern edge.
    from pipeline.models.plot import map_lonlat_bounds
    w, e, s, n = mcfg["domains"]["west"]["extent"]
    bw, be, bs, bn = map_lonlat_bounds([mcfg["domains"]["west"]["extent"]], pad_deg=0)
    assert be > e + 1.0 and bw < w - 1.0 and bs <= s and bn >= n




def test_render_fixed_size_png(mcfg, tmp_path):
    from PIL import Image
    from pipeline.models import plot
    lat, lon = np.meshgrid(np.linspace(38, 43, 60), np.linspace(-114, -108, 70), indexing="ij")
    src = plot.SourceGrid(lat, lon, {"kind": "latlon"}, False)
    canvas = plot.Canvas("wasatch", mcfg["domains"]["wasatch"], src, basemap=False)
    meta = {"label": "TEST", "cycle": datetime(2026, 11, 7, tzinfo=__import__("datetime").timezone.utc),
            "attribution": "test"}
    data = {"t2m_f": (20 + 20 * np.sin(lat) * np.cos(lon)).astype(np.float32),
            "gust_kt": (30 + 10 * np.cos(lat * 3)).astype(np.float32)}
    sizes = []
    for field in ("t2m", "gust", "t2m"):
        path = tmp_path / f"{field}.png"
        n = plot.render_field(canvas, field, data, meta, 12, path)
        assert 5_000 < n < 200_000
        sizes.append(Image.open(path).size)
    assert len(set(sizes)) == 1 and sizes[0][0] >= 900
    # artists are removed between renders: the same field renders identically
    assert (tmp_path / "t2m.png").stat().st_size == n
