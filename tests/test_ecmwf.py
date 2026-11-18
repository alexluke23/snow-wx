"""ECMWF open data (pipeline/ecmwf.py): grid indexing, index parsing, per-member cumulative handling, across-member quantiles, units, missing members,
shares, documents, gating. Offline: small fixtures, no network, no eccodes."""

import json
from datetime import datetime, timezone

import numpy as np
import pytest

from pipeline import ecmwf as E

CYC = datetime(2026, 11, 18, 0, tzinfo=timezone.utc)
PTS = [{"id": "alta", "lat": 40.57, "lon": -111.63, "elev_ft": 10556}, {"id": "dateline", "lat": 10.0, "lon": 179.9, "elev_ft": 0}]


def test_grid_index_matches_ecmwf_layout_and_wraps_the_date_line():
    i, j = E.grid_index(40.57, -111.63)
    assert (i, j) == (198, 273)                                   # row 198 = 40.5 N; (-111.63 - 180) mod 360 = 68.37 deg east of 180 E -> column 273
    lat, lon = E.grid_latlon(i, j)
    assert abs(lat - 40.5) < 0.13 and abs(lon - (-111.75)) < 0.13  # nearest cell centre within half a cell
    assert E.grid_index(10.0, 179.9)[1] == 0 and E.grid_index(10.0, 179.7)[1] == 1439    # column 0 is 180 E; 179.9 rounds to it, 179.7 to 179.75: no off-the-end index
    assert E.grid_index(10.0, -180.0)[1] == 0 and E.grid_index(10.0, 180.0)[1] == 0
    assert E.grid_index(95, 0)[0] == 0 and E.grid_index(-95, 0)[0] == 720


def index_text(members=50, steps=(24,), with_control=False):
    rows = []
    off = 0
    for s in steps:
        for p in ("tp", "sf", "2t"):
            for n in range(1, members + 1):
                rows.append({"type": "pf", "stream": "enfo", "levtype": "sfc", "number": str(n), "step": str(s), "param": p, "_offset": off, "_length": 100})
                off += 100
    if with_control:
        rows.append({"type": "cf", "stream": "enfo", "levtype": "sfc", "step": "24", "param": "tp", "_offset": off, "_length": 100})
    return "\n".join(json.dumps(r) for r in rows) + "\n\nnot json\n"


def test_index_parsing_selects_members_and_survives_bad_lines():
    rows = E.parse_index(index_text())
    tp = E.select(rows, "tp", "pf")
    assert sorted(tp) == list(range(1, 51)) and len(tp) == 50 and all(r["param"] == "tp" for r in tp.values())    # 50 perturbed members, numbers 1-50
    assert len(E.select(rows, "2t", "pf")) == 50 and E.select(rows, "tp", "cf") == {}                            # no control in the file layout we found
    assert E.select(rows, "tp", "pf", step=12) == {}
    assert E.url(E.configure(None), CYC, "enfo", 24, "grib2") == "https://ecmwf-forecasts.s3.amazonaws.com/20261118/00z/ifs/0p25/enfo/20261118000000-24h-enfo-ef.grib2"
    assert E.url(E.configure(None), CYC, "oper", 240, "index").endswith("/oper/20261118000000-240h-oper-fc.index")


def test_quantiles_across_members_linear_method_and_mean():
    m = np.array([np.arange(1, 51, dtype=float)] * 2).copy()                     # 2 steps, members 1..50
    m[1] *= 2
    q = E.quantiles(m.T.T)                                                       # (steps, members)
    assert q["n"].tolist() == [50, 50]
    assert q["p50"][0] == pytest.approx(25.5) and q["p10"][0] == pytest.approx(5.9) and q["p90"][0] == pytest.approx(45.1)   # numpy linear / type 7
    assert q["p25"][0] == pytest.approx(13.25) and q["p75"][0] == pytest.approx(37.75) and q["mean"][1] == pytest.approx(51.0)
    assert q["p10"][0] <= q["p25"][0] <= q["p50"][0] <= q["p75"][0] <= q["p90"][0]


def test_missing_members_are_left_out_of_the_statistics_not_counted_as_zero():
    m = np.full((2, 10), np.nan)
    m[0] = np.arange(10)
    m[1, :4] = [10, 20, 30, 40]                                                  # only 4 valid members at step 2
    q = E.quantiles(m)
    assert q["n"].tolist() == [10, 4] and q["p50"][1] == pytest.approx(25.0) and q["mean"][1] == pytest.approx(25.0)
    assert np.isnan(E.quantiles(np.full((1, 5), np.nan))["p50"][0])             # a step with no member at all is NaN, never 0
    sh = E.member_shares(np.array([0.0, 10.0, 30.0, np.nan, 26.0]), [1.0])
    assert sh == {1.0: (2, 4)}                                                   # 25.4 mm = 1 in; N of VALID members (4 here), NaN not counted


def test_cumulative_totals_never_decrease_and_missing_steps_do_not_reset():
    steps = np.array([[0.0, 0.0], [0.002, 0.001], [0.0019, np.nan], [0.004, 0.0009], [np.nan, 0.003]])
    out = E.monotone(steps)
    assert out[2, 0] == 0.002 and out[3, 0] == 0.004 and out[3, 1] == 0.001            # packing noise: running maximum
    assert np.isnan(out[2, 1]) and np.isnan(out[4, 0]) and out[4, 1] == 0.003
    for k in range(out.shape[1]):
        col = out[:, k][np.isfinite(out[:, k])]
        assert (np.diff(col) >= 0).all()


def test_units_metres_to_tenths_of_a_millimetre_and_inches():
    assert E.to_tenths_mm(np.array([[0.0254, 0.0, np.nan]])) == [[254, 0, None]]       # 0.0254 m = 25.4 mm = 1 in
    assert 25.4 / E.MM_PER_M * E.MM_PER_M / 25.4 == pytest.approx(1.0)


def sampler(n=50, missing=()):
    s = E.Sampler(PTS[:1], n)
    s.z = np.array([2400.0 * 9.80665 / 9.80665])                                       # metres, already converted by run()
    full = np.zeros((721, 1440), dtype="float32")
    steps = [0, 6, 12]
    for st, val in ((6, 0.001), (12, 0.003)):
        for param, scale in (("tp", 1.0), ("sf", 0.5)):
            fields = {k: np.where(np.arange(721 * 1440).reshape(721, 1440) >= 0, val * scale * (1 + k / 100), 0).astype("float32") for k in range(1, n + 1) if k not in missing}
            s.add_ens(param, st, fields)
        s.add_hres("tp", st, full + val * 1.1)
        s.add_hres("sf", st, full + val * 0.4)
    return s, steps


def test_documents_carry_50_members_quantized_values_terrain_and_a_hres_line():
    s, steps = sampler()
    plume, hres = E.area_docs(s, CYC, steps)
    d = plume["alta"]
    assert d["n_members"] == 50 and len(d["tp"]) == 3 and len(d["tp"][0]) == 50 and d["tp"][0] == [0] * 50                 # step 0 is zero for every member
    assert d["unit"] == "0.1 mm" and d["init"] == "2026-11-18T00:00Z" and d["hours"] == [0, 6, 12] and d["z_ft"] == 7874
    assert d["tp"][1][0] == round(0.001 * 1.01 * 1000 / 0.1) and d["tp"][2][49] == round(0.003 * 1.5 * 1000 / 0.1)       # m -> 0.1 mm
    assert d["sf"][2][0] == round(0.003 * 0.5 * 1.01 * 1000 / 0.1) and d["hres_tp"] == [0, 11, 33]
    assert hres["model"] == "ecmwf" and hres["areas"]["alta"]["q"] == [0.0, 0.04, 0.13] and hres["areas"]["alta"]["z"] == 7874 and hres["hours"] == [0, 6, 12]
    assert all(b >= a for row_a, row_b in zip(d["tp"], d["tp"][1:]) for a, b in zip(row_a, row_b))                              # monotone per member


def test_a_missing_member_is_null_in_its_column_and_counted():
    s, steps = sampler(missing=(7,))
    d = E.area_docs(s, CYC, steps)[0]["alta"]
    assert d["tp"][1][6] is None and d["tp"][2][6] is None and d["tp"][1][5] is not None and s.missing == {6: 1, 12: 1}


def test_size_of_one_area_file_is_small():
    s, steps = sampler()
    full_steps = list(range(0, 241, 6))
    for st in full_steps[3:]:                                                      # fill the per-step arrays directly (no 4 MB fields)
        for param in ("tp", "sf"):
            s.ens[param][st] = (0.001 * st * (1 + np.arange(1, 51) / 100.0))[:, None] * (1.0 if param == "tp" else 0.5)
        s.hres["tp"][st] = np.array([0.001 * st]); s.hres["sf"][st] = np.array([0.0005 * st])
    d = E.area_docs(s, CYC, full_steps)[0]["alta"]
    import gzip
    raw = json.dumps(d, separators=(",", ":")).encode()
    assert len(d["hours"]) == 41 and len(raw) < 60_000 and len(gzip.compress(raw)) < 25_000


def test_run_is_gated_by_the_config_flag(monkeypatch):
    assert E.DEFAULTS["enabled"] is False
    called = []
    res = E.run({}, object(), __import__("pathlib").Path("."), force=False)
    assert res == {"ok": False, "skipped": "disabled"} and not called
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "settings.yml").read_text(encoding="utf-8"))
    assert cfg["ecmwf"]["enabled"] is False and E.steps_for(E.configure(cfg))[:3] == [0, 6, 12] and E.steps_for(E.configure(cfg))[-1] == 240


def test_attribution_names_the_source_licence_and_that_the_data_were_adapted():
    assert "ECMWF" in E.ATTRIBUTION and "CC BY 4.0" in E.ATTRIBUTION and "Adapted" in E.ATTRIBUTION and "https://data.ecmwf.int/forecasts/" in E.ATTRIBUTION
    assert E.LICENSE_URL.startswith("https://creativecommons.org/licenses/by/4.0") and "ecmwf.int" in E.TERMS_URL
