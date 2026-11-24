---
name: snow-wx-nbm-change
description: Safely change NBM fetch, decode, window selection or point-forecast maths in Snow-Wx (pipeline/nbm/, pipeline/points.py, summaries that read NBM fields). Use before editing any NBM code, adding an NBM field, or debugging wrong snowfall, SLR, snow level or exceedance values.
---

# Changing NBM code safely

NBM is the primary forecast. Errors here show up on every ski-area page. Read `docs/nbm_inventory.md` (cycle layouts)
and `docs/specs/data-pipeline.md` §5.2 before editing.

## Facts you must not get wrong

- **Cycle layouts differ.** 01/07/13/19Z *core*: ASNOW 6/24/48/72-h percentiles + exceedances, SNOWLVL and SNOWLR percentiles to
  ~f263, hourly files to f264, **no qmd**. 00/06/12/18Z: snowfall percentiles only to f048/f054, but carry **qmd** (QPF percentiles).
  Selection is rule-based (`pipeline/nbm/inventory.py` classify/select): only windows **ending at the file's own hour** count.
- **6-h window ends depend on the cycle.** On 01/07/13/19Z they end at f005, f011, … (valid 00/06/12/18Z). Index a 6-h window
  ending at or after hour `h` with `h + (-(init.hour + h) % 6)`. `h + (-h % 6)` is wrong past f036 (review H1).
- **core GRIB uses alternativeRowScanning** (odd rows reversed); qmd does not. Always index with `run.flat_index`.
- SNOWLVL is metres MSL. ecCodes names SNOWLVL/SNOWLR `unknown`: select by inventory, not by shortName.
- Missing messages are **missing data**: count them (`required_keys`), fail the run above 20 %, and check per field (review M4:
  a field missing entirely must fail even if the global share is < 20 %).
- QPF percentiles come from the newest synoptic cycle with complete qmd (`liquid_cycle`, usually ~7 h older); label it.
- Lapse rate 6.5 °C/km grid → point (cap 4000 ft). P(snow) = P(snow level < point elevation) from the snow-level percentiles; a window
  with **no** snow-level data is a gap, not P(snow) = 1.0 (review M3).

## Percentile rules (hard rule 4)

- Ranges only from one **native** NBM window: "likely" p25–p75 by day (native 24 h, 12Z–12Z); 10/50/90 on native 24/48/72 h totals.
- A total that needs several windows gets the expected amount only and `native: false` (consumers check it: `area.js`, `finder.js`,
  `mine.js`, `summary.py`). 7/10-day totals: expected amount only.
- Documented exception: 12-h day/night ranges add 6-h windows rank by rank (`P.rank_sum`), labelled conservative.

## Output contract (don't break it)

`build/data/points/<id>.json` per ski area: `id, name, tz, source, cycle, liquid_cycle, issued, generated_at, times, fhours, area,
summary, points.{summit,base}.{elev_ft, grid_elev_ft, grid, series, precip, periods, days, totals, exceed}`; plus `summary.json`
(`cycle, quality, issued, …`) and `exceed_summary.json`. SNOTEL-site files `snotel-<triplet>.json` are **kept** for verification
(review H6). Adding a field is fine; renaming/removing one needs a human decision and a check of every consumer
(`grep -rn "<field>" web/js pipeline tools tests`). Archive columns are append-only (`pipeline/archive.py` `NBM_COLS`).

## Procedure

1. Write a fixture-based test first (`tests/test_points.py` style); for cycle-dependent logic test both an 01/13Z and a 00/12Z init.
2. Make the change in the pure function where possible; keep fetch/decode separate.
3. `python -m pytest -q tests/test_points.py tests/test_summary.py tests/test_pipeline.py`, then the full suite.
4. If decode or selection changed, verify on real data **locally** (not in tests): run `python -m pipeline points --out <tmp>/points`
   for one cycle and compare TMP, Q06 and SLV at a few areas against the NBS text bulletin
   (`blend.YYYYMMDD/HH/text/blend_nbstx.tHHz`), and run `python -m pipeline.nbm.sanity`. Percentiles should match the GSL NBM
   1-D viewer at the nearest cell (`docs/reference/nbm_validation_gsl_2026110801.md`).
5. Run skill `snow-wx-hard-rules` (rule 4 especially) and update `web/about.html` if a method changed.
6. Note NBM version caveats: NBM v5.0 has been operational since May 5 2026; if behaviour depends on the version, record it in the spec.
