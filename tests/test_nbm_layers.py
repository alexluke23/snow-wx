"""NBM forecast overlay helpers (pipeline/nbm/layers.py)."""

import numpy as np

from pipeline.nbm import layers as NL


def test_windows_end_at_12z():
    assert NL.first_end(1, 24, 5) == 35            # 01Z + 35 h = 12Z next day (window f011-f035)
    assert NL.first_end(19, 24, 5) == 41           # 19Z + 41 h = 12Z
    assert NL.first_end(1, 72, 5) == 83
    need = NL.plan(1, NL.layer_specs())
    assert need[35] and {k for k, *_ in need[35]} >= {"nbm24", "nbmp24_4", "det24_0"}
    assert {k for k, *_ in need[83]} >= {"nbm72", "nbmp72_12", "det24_2"}
    assert "det24_6" in {k for k, *_ in need[35 + 144]}


def test_regrid_marks_outside_cells():
    a = np.arange(12, dtype="float32").reshape(3, 4)
    jj = np.array([[0, 2], [-1, 1]]); ii = np.array([[0, 3], [1, -1]])
    out = NL.regrid(a, jj, ii)
    assert out[0, 0] == 0 and out[0, 1] == 11 and np.isnan(out[1, 0]) and np.isnan(out[1, 1])


def test_specs_ids_unique_and_palettes():
    s = NL.layer_specs()
    assert len({x["id"] for x in s}) == len(s) == 9
    assert {x["palette"] for x in s} == {"SNOWFALL", "PROB"}
