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
  (rides the existing model tars), merged at site build into `data/multimodel.json` (`models: [{model, label, cycle, init, hours}]`, `areas: {id: {model: {q, z}}}`). Nearest cell within
  0.3° (GFS is 0.25°). Config `models.yml` `multi_model.enabled` (default true; false = no sampling, no file, the page says "not available yet"). Ski areas only (Sno-Parks/SNOTEL: not built).
- **Alignment:** each series is cumulative from its OWN init; `js/multimodel.js` `rebase` re-expresses them from the newest model start (`pipeline.models.multimodel.rebase` is the tested Python
  twin; the browser check asserts they agree). The NBM line comes from the area's points file (`precip` windows, cumulative from the issue time). No percentiles are involved or added.
- **Units toggle:** liquid (default) or snow at NBM's median ratio (`slr_p50`, else `slr`) times NBM's chance of snow at the point (`p_snow`), per interval; the NBM line is NBM's own expected snowfall.
  Labelled "inches assume NBM SLR".
- **Agreement badge (heuristic until verified):** longest window H in {72, 48, 36, 24, 12, 6} h after the common start that >= 3 sources reach; median of their liquid totals; a source agrees if within
  +-25% of the median (or 0.10 in when small); >= 75% High, >= 50% Medium, else Low; all totals < 0.10 in = "High (all dry)". Always from liquid, so the toggle never changes it. about.html#model-agreement.
- **Budget (Nov 17, 3 models):** a full run is ~99 frames x 160 areas: ~130 KB for the whole `multimodel.json` (~0.8 KB per area; gzip far less); sampling cost ~16 ms per frame plus a one-time
  ~4.6 s nearest-cell index per model run on a 1000x1400 grid (the models.yml renders take 100-180 s), so +3-5% runtime. Neither breaks a budget: enabled.
- ECMWF (M8) is not part of this step.
