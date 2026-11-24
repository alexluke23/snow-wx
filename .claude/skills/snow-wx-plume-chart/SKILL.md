---
name: snow-wx-plume-chart
description: Build or change Snow-Wx model plume and multi-model charts (Precipitation by model lines, ECMWF ENS / NOAA GEFS ensemble plumes, model chips, agreement badge) in web/js/multimodel.js, web/js/ensemble.js and their pipeline producers. Use for any plume UI pass or multi-model data change.
---

# Plume and multi-model charts

Spec: `docs/specs/multi-model.md` (focus area since Nov 23). Design rules: `docs/DESIGN.md` §6 / §6-B.

## Data producers (pipeline)

| Line / plume | Producer | Output (today) | Notes |
|---|---|---|---|
| NBM | `pipeline/nbm/run.py` | in points JSON | liquid from qmd (`liquid_cycle`) |
| HRRR, RRFS, GFS | `pipeline/models/multimodel.py` `PrecipSampler` (fed inside the map render loop in `pipeline/models/run.py`) | `precip.json` per model | **Review H5:** must become a sample-only job before map rendering is deleted |
| Ridge winds | `pipeline/models/ridge.py` | `ridge.json` | same coupling as above |
| ECMWF HRES + ENS, AIFS | `pipeline/ecmwf.py` (+ `fetch_resilient.py`) | `build/models/ecmwf/…` | member count read from the data; AIFS tp in mm, IFS tp in metres |
| NOAA GEFS | `pipeline/gefs.py` | `build/models/gefs/…` | resume cache `data_cache/gefs/<cycle>` (make writes atomic: M8) |

`load_points` currently lives in `pipeline/models/multimodel.py` and is imported by `ecmwf.py` and `gefs.py`; move it to a neutral
module as part of H5 rather than duplicating it.

## Rules

1. **Compare liquid equivalent.** Inches toggle uses NBM SLR p50 and says "inches assume NBM SLR". Never mix models' native snowfall.
2. **Gaps are gaps.** A missing step is null: keep nulls, `connectgaps: false`, and `interpAt` returns null across a gap (M6).
   A failed GEFS message is missing, not zero (M7). Never interpolate an ECMWF step (dev19 rule).
3. **Run times.** Each model line shows its own run time (e.g. "HRRR 12Z"); models older than the newest by > 24 h are dropped or
   flagged (N2). The module shows one source line and the issue time.
4. **Agreement badge** = documented heuristic: needs ≥ 3 models, uses every model regardless of chips, AIFS excluded unless
   `aifs.in_badge`. "Little precipitation expected" when every model < 0.20 in (never "High"). Label + About link.
5. **Ensemble plume** (ECMWF ENS | GEFS): members as thin lines or a percentile fan computed **per time step across members** (that is
   a valid ensemble statistic, not a cross-window percentile sum). Show member count from the data. Don't present ENS percentiles as NBM.
6. **Chips** change only what's drawn, never the badge or table.
7. **Lean module** (DESIGN): title, one takeaway, chart + legend, "View as table", one source/issue-time line, "How it works" link.
8. Colours: Okabe–Ito categorical per model, consistent across charts; AIFS dotted ("experimental"); ≥ 13 px ticks; direct labels.
9. ECMWF attribution on every panel that shows ECMWF data: "Contains ECMWF open data … CC BY 4.0", noting adaptation.

## Tests

- JS logic: `tests/test_agreement_js.py`, `tests/test_ensemble_js.py` (node). Add gap cases.
- Python: `tests/test_multimodel.py`, `tests/test_multimodel_e2e.py`, `tests/test_gefs.py`, `tests/test_ecmwf*.py`, `tests/test_aifs.py`.
- Browser: `mmodel`, `mmchips`, `ensemble` checks — on **frozen** snowy and dry Alta fixtures (PR B), never live data.
- Run skill `snow-wx-hard-rules` before the MR.
