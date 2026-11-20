# Spec: Multi-model comparison (M7 + M8)

> Read when working on per-model sampling, the model selector, agreement badge or ECMWF.
> Part of Snow-Wx docs v1.0 (Nov 15 2026). Index and priorities: `PLAN.md`.
> Section numbers (§) are kept from the original single plan so cross-references still work.

---

### 5.5 Multi-model comparison (M7 + M8) — *expanded*
**Goal:** let users see model agreement/disagreement for their mountain — the
confidence signal powder chasers want.

- **Models:** NBM (primary), HRRR (short range; the extended cycles reach ~48 h
  **[verify]**), RRFS (to ~84 h), GFS (to day 10+), **ECMWF IFS** (open data,
  0.25°; 0.1° available since Oct 20 2026) and later AIFS single/ensemble. Sampled
  from the *existing* model pipeline at every area's base/summit — no third-party
  API.
- **Apples-to-apples:** compare **liquid equivalent (SWE/QPF of snow)**
  cumulatively per model on one chart; toggle to inches using the NBM SLR median
  (label "inches assume NBM SLR"). Models' native snowfall products differ — do not
  mix them silently.
- **UI:** (1) a **model selector** (NBM · NWS · HRRR · RRFS · GFS · ECMWF) on the
  existing charts; (2) a **plume/lines chart** "Precipitation by model" with direct
  labels (§6-B); (3) a **Model agreement** badge — "High / Medium / Low" from a
  documented spread metric (e.g., share of models within ±25% of the median over
  the window); thresholds are a **heuristic until verified**.
- **Elevation:** each model has its own grid elevation → apply the same lapse/
  snow-level handling as §5.2 and show "model terrain vs point" in the tooltip.
- **Attribution (required):** ECMWF is CC BY 4.0 — credit "ECMWF" with the licence
  statement on charts/about.html **[verify exact current wording]**.
- **Verification hook:** the archive also stores each model, enabling a public
  "which model did best this season, by region" scorecard (M9) — highly shareable.
- Later (M10): ensemble members (GEFS, ECMWF ENS/AIFS ENS) as a true plume.

### M7 build (dev16)
- **Sampling:** `pipeline/models/multimodel.py` `PrecipSampler` records, for every ski area's SUMMIT coordinates, the run-total liquid precipitation (APCP since init, in; the array
  the QPF maps already difference, taken from `derive_frame`'s state) and the model's own terrain height, at every frame of HRRR / RRFS / GFS; `<models>/<model>/precip.json` per run
  (rides the existing model tars), merged at site build into `data/multimodel.json` (`models: [{model, label, cycle, init, hours}]`, `areas: {id: {model: {q, z}}}`). Nearest cell within 0.75 x the grid's cell diagonal (a point outside a cropped grid gets no series, not an edge cell). A model whose init is > 24 h older than the newest is dropped at merge, and each run deletes its old precip.json first. Config `models.yml` `multi_model.enabled` (default true; false = no sampling, no file, the page says "not available yet"). Ski areas only (Sno-Parks/SNOTEL: not built).
- **Alignment:** each series is cumulative from its OWN init; `js/multimodel.js` `rebase` re-expresses them from the newest model start (`pipeline.models.multimodel.rebase` is the tested Python
  twin; the browser check asserts they agree). The NBM line comes from the area's points file (`precip` windows, cumulative from the issue time). No percentiles are involved or added.
- **Units toggle:** liquid (default) or snow at NBM's median ratio (`slr_p50`, else `slr`) times NBM's chance of snow at the point (`p_snow`), per interval; the NBM line is NBM's own expected snowfall.
  Labelled "inches assume NBM SLR".
- **Agreement badge (heuristic until verified):** longest window H in {72, 48, 36, 24, 12, 6} h after the common start that >= 3 sources reach; median of their liquid totals; a source agrees if within
  +-25% of the median (or 0.10 in when small); >= 80% High, >= 66% Medium, else Low (dev17; was 75 / 50); all totals < 0.10 in = "High (all dry)". Always from liquid, so the toggle never changes it. about.html#model-agreement.
- **Budget (Nov 17, 3 models):** measured on a full HRRR run (29 frames) 27.6 KB for 160 areas (172 B per area); three models ~95 KB for the whole `multimodel.json` (~0.6 KB per area; gzip far less); sampling cost ~16 ms per frame plus a one-time
  ~0.9 s KD-tree nearest-cell index per model run on a 1000x1400 grid (the models.yml renders take 100-180 s), so under +1% runtime. Neither breaks a budget: enabled.
- ECMWF (M8) is not part of this step.

### Agreement-badge calibration (dev17 Part 0e)
Method: real runs (HRRR / RRFS / GFS `qpf_total` at summit points, `pipeline models --fields qpf_total --domains west`) merged into `multimodel.json`, NBM series from the committed points files,
the page's own `MultiModel.build` executed in Node over all 160 areas (`node tools/agreement_calibration.js <label> [multimodel.js]`, env `CALIB_FILE` = a multimodel.json, `SCRATCH` = output folder). Results, 160 areas:

| Cycle | High | Medium | Low | all-dry | window used |
|---|---|---|---|---|---|
| 2026-11-18 06Z (before = after: no change) | 74 (46%) | 62 (39%) | 24 (15%) | 20 | 72 h for all 160 |
| 2026-11-18 00Z | 73 (46%) | 60 (38%) | 27 (17%) | 16 | 72 h for all 160 |

Terrain gap: the largest |model terrain - summit| among the models in the window is NOT larger for Low areas (median 1,453-1,457 ft) than for High (1,614-1,939 ft); a model is outside the +-25% band in
37-39% of pairs with a gap < 1,000 ft vs 21-35% at >= 2,000-3,000 ft (RRFS median gap ~1,000 ft, GFS ~1,600 ft, p90 3,256 ft). Only 4-8 of the 24-27 Low areas have an outlier model > 2,000 ft off the summit.
Conclusion: neither trigger fired (no class > ~70%, terrain gap does not dominate), so the metric and thresholds are unchanged and no extra tooltip note was added; the finding is stated on about.html.
Observation: HRRR ends at 48 h, so the 72-h window (chosen because it is the longest that >= 3 sources reach) never includes it. A fixed 48-h window with all four sources was tried and
rejected: it made 71% of areas High (more windows are "all dry"). Single-cycle caveat: both cycles are the same storm period; re-check after a few weeks of archived multimodel files.

**Live-config re-run (dev18, Nov 18 22:04 MST, no `--force`, `ecmwf.enabled: true`):** cycle 2026-11-18 12Z, member count read from the first ensemble index = 50, 160 areas, 41 steps, **1,225 MB downloaded in 314 s**, 0 missing member messages, plume files 14.5 KB each; the output goes through `ecmwf_status` (ok), the monitor (`state=ok ... age 0.0 h / 30 h`) and `multimodel.merge` (`plumes: ["ecmwf"]`) unchanged. Release lag (S3 Last-Modified of the 240 h index files, six cycles Nov 16-18): 7.6 h (HRES), 7.8 h (ENS).

### NOAA GEFS plume (dev18 stretch; built, `gefs.enabled: false`, no workflow)
Code `pipeline/gefs.py` (`python -m pipeline gefs --out build/models [--force]`), same plume file format as ECMWF's (`models/gefs/plume/<area>.json`, `n_members` and `control_member` from the data), page: an "ECMWF | GEFS" switch in the Ensemble view, shown only when `data/multimodel.json` lists `gefs` in `plumes`. Tests `tests/test_gefs.py`. Workflow text for the owner: `docs/workflow_snippets/gefs.yml` (dev sessions create no second workflow file).
**Verified on the real mirror (Nov 18 2026, `noaa-gefs-pds.s3.amazonaws.com`, `gefs.YYYYMMDD/HH/atmos/pgrb2sp25/`):** members `gec00` (control) + `gep01`..`gep30` = **31**, plus `geavg` and `gespr` (not used); steps 0..240 every 3 h (81); 0.25 degree, 721 x 1440, rows from 90 N and columns from **0 E** (ECMWF's start at 180 E: `gefs.grid_index`); a wgrib2 `.idx` beside every file. Fields: `APCP:surface` in 6-h buckets (f006 = "0-6 hour acc", f012 = "6-12 hour acc", ...), `CSNOW:surface` (categorical-snow average over the same window); `WEASD` exists but is snow on the ground, not snowfall.
**Method:** each member's own 6-h buckets are summed over time (a member is one scenario; quantiles are taken across members in the browser, as for ECMWF); the snow plume is an **estimate**: bucket water x CSNOW share, then x NBM's median ratio on the page (GEFS has no snowfall accumulation field), labelled as such.
**Budget (one real run, cycle 2026-11-18 12Z, 160 areas, 41 steps, 31 members):** **380 MB downloaded in 137 s** (about 3,700 requests: one `.idx` + two byte-range messages per member and step), 0 missing member messages, plume files 8.7 KB each raw (161 files, ~1.4 MB); Alta's 72-h median 0.69 in liquid (ECMWF's previous cycle 1.2 in: different cycles, coarse grids, both unadjusted for terrain). Release lag: the last file (f240, control and member 30) lands 5.2-5.7 h after init (S3 Last-Modified, four cycles). About a third of the ECMWF job's volume and less than half its time.

### Badge calibration across day types and the dry state (dev18)
Recorded cycles re-run through the page's own `multimodel.js` (`tools/agreement_calibration.js`, env `CALIB_FILE` / `CALIB_POINTS`): HRRR/RRFS/GFS `precip.json` from `pipeline models --cycle`, ECMWF HRES-only sampled with `pipeline.ecmwf`, NBM from `pipeline points --cycle --max-hour 72`, all 160 areas. Day type = the 72-h ECMWF HRES mean precipitation over the ski areas.

| 00Z cycle | type (mean 72 h precip) | Little precip. | High | Medium | Low |
|---|---|---|---|---|---|
| Nov 5 | dry (0.09 in) | 128 (80%) | 2 (1%) | 12 (8%) | 18 (11%) |
| Nov 9 | dry (0.14 in) | 129 (81%) | 4 (3%) | 13 (8%) | 14 (9%) |
| Nov 13 | light (0.47 in) | 24 (15%) | 26 (16%) | 65 (41%) | 45 (28%) |
| Nov 15 | light-moderate (0.38 in) | 54 (34%) | 18 (11%) | 40 (25%) | 48 (30%) |
| Nov 17 | heavy (0.85 in) | 29 (18%) | 25 (16%) | 57 (36%) | 49 (31%) |
| Nov 18 (live run, 4 sources) | storm | 33 (21%) | 39 (24%) | 52 (33%) | 36 (23%) |

Among RATED areas (not "little precipitation"): High / Medium / Low = 6 / 38 / 56 % (Nov 5), 13 / 42 / 45 % (Nov 9), 19 / 48 / 33 % (Nov 13), 17 / 38 / 45 % (Nov 15), 19 / 43 / 37 % (Nov 17), 31 / 41 / 28 % (live). No class exceeds 70 % on any day type, and on the heavy day the largest model-terrain gap is not larger for Low (1,719 ft median) than for High (1,800 ft): **no retune of the 80 % / two-thirds thresholds**.
**One change, with its reason:** an all-dry window used to be "High (dry)" (dev17) and is now its own state "Little precipitation expected" (never "High agreement"), and the limit moved from 0.10 to 0.20 in. Reason: the agreement test has a 0.10 in absolute floor, so any set of totals under 0.20 in cannot be more than 0.20 in apart: it cannot disagree in a way that matters. At 0.10 in, 100 % of the dry-day "High" ratings (17 of 17 on Nov 5) were agreement at a median under 0.20 in. Effect of 0.20 vs 0.10 in on the heavy day: High 22 -> 16 %, Little precipitation 7 -> 18 % (desert areas at 0.1-0.2 in). With 5 sources a 3-of-5 majority (60 %) is below the two-thirds line and rates "Low" (Medium is impossible with exactly five sources); this does not occur today because HRRR stops at 48 h and the 72-h window has four sources. Re-check after the season has more storms (single month, one winter).

### ECMWF: operational HRES line + IFS ENS plume (built dev17; **live since dev18**: `ecmwf.enabled: true`, workflow `.github/workflows/ecmwf.yml`)
Code `pipeline/ecmwf.py` (`python -m pipeline ecmwf --out out/models [--force]`), page `web/js/ensemble.js` + `area.js` (`ensembleChart`), tests `tests/test_ecmwf.py`,
`tests/test_ensemble_js.py`, browser check `ensemble`, standalone workflow `.github/workflows/ecmwf.yml` (dev18; operating notes in `docs/workflow_snippets/ecmwf.yml`, tests in `tests/test_ecmwf_workflow.py`: YAML keys, action versions copied from models.yml, `environment.yml` covers the imports, CLI `new=false` exit 0 for already-published / not-yet-released, upload-cleanup step under `bash -e` with a fake `gh`). Monitored as source `ecmwf` (`monitoring.sources.ecmwf.max_age_hours: 30`; status "not enabled" while the flag is false, "waiting for the first run" before the first delivery). **Member count is read from the data** (`n_members` = the perturbed members listed in the first ensemble step's index; today 50, no control member): no page, headline, aria-label or doc hard-codes 50 or 51 (`tests/test_ecmwf_wording.py`). HRES is drawn on the plume as a labelled dashed "HRES (single run)" reference line, not a member. **Verified live Nov 18 2026 against the real mirror and `.index` files:**

| Item | Found |
|---|---|
| Source | ECMWF Open Data, **AWS mirror** `ecmwf-forecasts` over anonymous HTTPS (dev19: the REGIONAL endpoint `https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com`, with Google and the ECMWF portal as failover, see below; the original global host `https://ecmwf-forecasts.s3.amazonaws.com` is what throttled the first live run) (`/<yyyymmdd>/<HH>z/ifs/0p25/{enfo,oper}/<yyyymmddHH>0000-<step>h-{enfo-ef,oper-fc}.{grib2,index}`); no key, no portal |
| Members | **50 perturbed members** (type `pf`, numbers 1-50). **No control member (`cf`) in any enfo file on the mirror** (index of the 0 h and 24 h files: 8,850 messages, all `pf`; the `-ep` file holds `em`/`es`/`ep` summaries) → the plume has **50 members, not 51**; the control is not drawn and the UI, aria text and table say "N of 50" |
| Resolution | 0.25° (721 × 1440, scanning from 90 N and 180 E). **0.1° ENS exists since 20 Oct 2026** (`ifs/0p1/enfo/...-ef-sfc.grib2`, 3.5-4.7 GB per step), but `tp` alone is **72 MB per step** (50 members) = ~2.9 GB per cycle for tp, ~6 GB with sf: not used |
| Cycles / steps | ENS 00/06/12/18Z; 00/12Z run to 360 h (3-hourly to 144 h, then 6-hourly), 06/18Z to 144 h. We use **00Z and 12Z, every 6 h to 240 h** (41 steps including 0) |
| Fields | `tp` total precipitation (**m**, `stepType=accum`, accumulated since the run start; 12 bits/value) and **`sf` snowfall water equivalent (m of water, accum, 11 bits)**: both exist for ENS, so the plume has a true snow-water series. HRES `z` (surface geopotential, m²/s², 0.25°) gives the model terrain. `sf` can exceed `tp` by up to 0.3 mm (GRIB packing precision; 79 of 2,050 member-steps at Jackson Hole), negligible |
| Release | files published ~7-9 h after the nominal time (the 00Z ENS 24 h file was written 07:40Z); the 0.1° files ~2 h after the 0.25° ones |
| Throttle | the mirror answers HTTP 503 `SlowDown` under bursts (seen after ~10 rapid requests). Since dev19 every request goes through `pipeline/fetch_resilient.py` (3 workers, adaptive; see "Fetch resilience" below) |

**Budgets (full real run, 00Z Nov 18, 160 ski areas, tp + sf, 50 members, 41 steps, HRES + ENS):** **1,214 MB downloaded in 300 s** (second run, the 12Z cycle of Nov 17: 1,205 MB in 336 s, 0 missing messages) wall clock (download + decode + sample; ~5 s per ENS step; the ENS index files are 2 MB each = ~80 MB of the total),
0 missing member messages. Output: **162 files** (160 plume files + `precip.json` + `index.json`; the site build is ~5.6 k files, limit 20,000); plume file **avg 14.9 KB raw / 3.7 KB gzip (max 19.1 / 5.6 KB), total 2.4 MB raw / 0.60 MB gzip**;
HRES `precip.json` 37 KB raw / 7 KB gzip, merged into `multimodel.json`. The per-area point JSON (target < 150 KB) is unchanged (no ensemble data in it); plume files are fetched only when the Ensemble view is selected (the browser check
asserts 0 requests before and 1 after). Values are integers in 0.1 mm. 6-hourly to 240 h was affordable, so no extension toward 360 h was attempted (it would add ~0.45 GB).

**Statistics:** each member is one scenario. `tp`/`sf` are already cumulative per member; the pipeline enforces a per-member running maximum (GRIB packing noise) and stores the members. The page aligns each member to the common start (linear
interpolation of that member's own cumulative series), then takes quantiles **across members** at each time (10/25/50/75/90 and the mean; linear, Hyndman-Fan type 7; `ecmwf.quantiles` and `ensemble.js` `quantile` are the same method and a test
compares them). Nothing is summed or interpolated across percentiles or windows; NBM's percentile products are not used. Shares are "N of the valid members" at or above 0.5 / 1 / 2 in (liquid) or 2 / 6 / 12 in (snow).

**UI:** `Models | Ensemble` toggle (a `role=group` of two `aria-pressed` buttons, ≥ 40 px, the change announced in an `aria-live` region, state kept for the visit only, default Models, shown only when `multimodel.json` marks ECMWF `plume: true`).
Ensemble view: ALL members as ONE faint multi-segment trace (null breaks), 10-90 % and 25-75 % bands, median, mean, HRES dashed, direct labels, Okabe-Ito colours; the headline sentence is also the aria-label; "View as table" holds percentiles at
24-h marks and the member-share rows; cycle and issue time, the model-terrain mismatch, the "raw guidance at 0.25°, not bias-corrected, not elevation-adjusted, not the same product as NBM" label and the CC BY 4.0 attribution (with the "adapted"
statement and the Terms-of-Use link) are on the chart and in about.html#ecmwf; a run older than 24 h is greyed and says "Out of date". Snow (in) = `sf` × NBM's median ratio ("inches assume NBM SLR"); liquid = `tp`.

**Validation (3 areas, independent read with `eccodes.codes_grib_find_nearest`, not our own index arithmetic):** Alta, Jackson Hole and Mt Bachelor at 24 / 120 / 240 h, members 1 / 25 / 50 and HRES: **36 of 36 values match the files to < 0.1 mm**; units
`m` → mm correct (Alta 24 h member 1: 7.69 mm); `stepType accum`; nearest cell identical (Alta summit 40.57, -111.63 → cell 40.50, -111.75, terrain 7,397 ft vs the 10,556 ft summit); every member's cumulative series non-decreasing; 50 members in each file.
Control vs HRES could not be compared (no control on the mirror). Ensemble median vs HRES at 240 h: Alta 40.5 vs 48.3 mm, Jackson 32.5 vs 55.4, Bachelor 71.4 vs 98.9 (HRES is a single higher-resolution run and is wetter than the ensemble median at long
leads: inside the members' 10-90 % range at Alta, above it at Jackson and Bachelor; the usual smoothing of an ensemble median, not an error).

**Fallback evaluated, not built:** the dynamical.org ECMWF IFS ENS Zarr mirror (area-subset reads, CC BY 4.0 plus ECMWF Terms of Use, one initialisation per day) would cut the download to a few MB, at the cost of a third-party dependency and a 24-h cadence
(no 12Z cycle; the plume would be up to ~32 h old). Not needed: the direct-GRIB job is 1.2 GB / 5 min, well inside a 30-minute runner. (Not measured here: `zarr`/`s3fs` are not in the environment.)

**Agreement badge with ECMWF as a fourth source:** the old rule (≥ 75 % within ±25 % of the median) made 78 % of areas High, so it is now ≥ 80 % High / ≥ 66 % Medium (identical for three sources); see the calibration section above.

#### Fetch resilience (dev19; the first live GitHub run failed with 503 SlowDown -> `RetryError`)
Cause: the global S3 endpoint throttled the runner's shared IP range, and the shared `make_session` adapter (urllib3 Retry) raised `RetryError` instead of backing off. Fix, all in `pipeline/fetch_resilient.py` (shared with GEFS, tested with a real local HTTP server in `tests/test_fetch_resilient.py`, `tests/test_ecmwf_resilience.py`):
- **Mirrors**, same path layout, all byte-range capable: AWS regional (`...s3.eu-central-1.amazonaws.com`) -> Google (`https://storage.googleapis.com/ecmwf-open-data`) -> ECMWF portal (`https://data.ecmwf.int/forecasts`, max 2 concurrent: ~500 connections shared by every user). Azure is skipped (needs a SAS token). A per-run circuit breaker switches to the next mirror after `trip_after` (6) consecutive failures; the mirror actually used is recorded.
- **Retry:** 429/500/502/503/504 and network errors, up to `attempts` (8), full-jitter exponential backoff (1 s base, 30 s cap), `Retry-After` honoured (capped), a total-time cap per request (`max_request_s` 300), a global cool-down after throttling and modest pacing; workers 3, halved while throttled.
- **Graceful degradation:** a step that cannot be fetched is dropped for ALL members and HRES (never interpolated). `steps_missing` is in `index.json`, `precip.json`, every plume file and meta.json; the plume and the precipitation chart draw the gap and say so. A run needs >= 90 % of the planned steps AND the first 120 h (`min_steps_frac`, `required_hours`), else it exits 0 with `new=false` and a warning (not an error). A partial run gets a different tag hash (`partial_tag`) so a later complete attempt of the same cycle replaces it.
- **Resume:** sampled values per (cycle, step) in `data_cache/ecmwf/<cycle>/` (npz); `ecmwf.yml` restores and saves it with `actions/cache` (`if: always()`), so a retry only fetches what is missing.
- **Fetch health** (mirror, retries, steps missing, status counts, switches): `index.json` `fetch`, meta.json and one line on the status page.
- **Measured Nov 19 2026 (12Z cycle, local PC):** regional AWS tripped the breaker, the run switched to Google: 41 steps, 0 missing, 1,275 MB in 456 s, 18 retries; the immediate re-run read every step from the cache (0 MB, 3.9 s). `--published <tag>` of the newest cycle: exit 0, `new=false`, no output (the tag is `<cycle>-<hash>`, a bare cycle counts as new).
- **Not testable offline:** real GitHub-runner throttling.
