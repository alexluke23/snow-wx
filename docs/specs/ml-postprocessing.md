---
status: current
owner: pipeline
last_reviewed: 2026-11-23
read_when: before any ML, SNOTEL QC or NBM backfill work
---

# Spec: Machine-learning post-processing of NBM (M12, research program)

> **Opened Nov 23 2026** (team request). Status: **RESEARCH ONLY, nothing on the site.** Index and priorities: `PLAN.md`.
> Covers three targets: **QPF**, **snowfall amount** and **snow-to-liquid ratio (SLR)**. The existing M11 track (`docs/specs/snow-ratio-ml.md`) becomes the SLR part of this program; its findings and gates still apply.
> Hard rules from `PLAN.md` §0 apply to everything here: label heuristics and experiments, no accuracy claims without published verification, license-clean data, **never sum or interpolate percentiles across windows**, "likely" = p25–p75, sources and issue times on every module, safety info never changed or gated.
> **[verify]** = re-check at the source before relying on it.

---

## 0. TL;DR

- **Goal:** a "Snow-Wx adjusted" probabilistic forecast (quantiles + chances of ≥ X) for QPF, snowfall and SLR at mountain points. It is trained on years of archived NBM forecasts paired with **quality-controlled SNOTEL observations**. It is shown **next to** NBM, never instead of it, until a public verification shows it is better.
- **Where the value should be:** (1) **SLR**, where operational methods are known to be weak; (2) **point-scale bias** where NBM's 2.5 km grid misrepresents a mountain site (elevation, orographic placement, rain/snow line); (3) **calibration** of the snowfall ranges at ski-area elevations. Gains on QPF at grid scale will likely be modest, because NBM is already calibrated.
- **Biggest risks:**
  - **Ground truth:** SNOTEL gauges undercatch snow, the depth sensor can't separate new snow from settling, and the 0.1 in resolution adds noise. Training toward bad observations makes forecasts *worse*. **The QC system (§4) is half of this project.**
  - **NBM version changes:** v5.0 went operational **May 5 2026** and changed the winter guidance. Most of the archive is v4.x, and there is no full winter of operational v5.0 yet.
  - **Ski areas aren't observed:** models train at SNOTEL sites and must transfer to ski-area points (§6.5).
- **Approach:** start with strong simple baselines (per-site quantile mapping, censored shifted gamma), then a **pooled gradient-boosting quantile model** across all stations. Validate by **season and by held-out site**, scored mainly with **CRPS**, reliability and p25–p75 coverage.
- **Timeline:** build the data lake + QC this winter (no site change). Train and evaluate in the 2027 off-season. Show an **experimental line in 2027–28** behind a flag. Promote only after a season of public verification.

---

## 1. Why this adds value

| Gap in what we show today | What ML post-processing can do | Evidence it's realistic |
|---|---|---|
| NBM SLR comes from formula-based methods (Cobb, Roebber, Kuchera, MaxTaloft family) that verify poorly in western mountains (R² 0.04–0.23 against manual boards, `snow-ratio-ml.md` §2) | Learn SLR from temperature, moisture, wind and QPF; random forest reached R² ≈ 0.43 against manual boards | Veals et al. 2025 (14 western sites); Pletcher et al. extended ML SLR to CONUS using manual observer data |
| NBM is a 2.5 km grid; a ski area's summit or a SNOTEL site sits at a different elevation and exposure than its grid cell | Site-specific bias and spread correction, learned from that site's history and from similar sites | Classic MOS / local post-processing; our own M9 note on elevation handling |
| NBM snowfall ranges may be over- or under-confident at specific mountain points | Recalibrate quantiles so p25–p75 really contains ~50% of outcomes there | Checkable with our archive (PIT / coverage) |
| Verification (M9) tells users how NBM did; it doesn't improve the forecast | Turn the verification archive into a correction | Same data, second use |

**Honest framing on the site:** "A Snow-Wx adjustment trained on N winters of NBM forecasts and SNOTEL observations. At these sites it reduced error by X% in out-of-sample tests (published here)." Never "more accurate than NBM" without that page (hard rule 2).

---

## 2. Targets and how each is observed

| Target | Forecast quantity (from NBM) | Observed "truth" at SNOTEL | Main truth problems |
|---|---|---|---|
| **QPF** | 6/12/24 h QPF percentiles + PoP, native windows | Accumulated-precip **weighing gauge** (hourly, 0.1 in) → increments on the NBM window (12Z–12Z etc.) | Snow **undercatch** in wind; delayed catch (snow capping the orifice, released later); thermal/evaporation **oscillations** in the weighing signal; 0.1 in resolution; gauge servicing resets |
| **Snowfall** | 6/24 h snowfall percentiles (ASNOW), native windows | **Ultrasonic depth sensor** → new snow estimate from hourly depth series | Depth change ≠ snowfall (**settlement** during and after storms, wind scouring/drifting, sensor noise of ~1–2 cm, sensor upgrades). Underestimates long storms; positive-increment sums overestimate noisy ones |
| **SLR** | SLR percentiles (where NBM has precip) | new snow ÷ new SWE (pillow ΔSWE or gauge Δprecip) over qualifying events | Inherits **both** problems above; tiny denominators at 0.1 in resolution explode the ratio; rain-on-snow and melt contaminate ΔSWE |

**Consequence:** each target gets an explicit **observation operator** (how we turn raw SNOTEL series into a value comparable with the forecast window) and a **truth-confidence weight** from QC (§4). Low-confidence observations are down-weighted or excluded from training and reported separately in verification.

### 2.1 Independent truth (to check we aren't fitting SNOTEL's biases)

| Source | Use | Licence / status |
|---|---|---|
| **CoCoRaHS** (manual 24 h snowfall, snow-core SWE, precip; 7 AM obs) | Independent evaluation of snowfall and SLR, mostly at lower elevations; mountain towns near ski areas | Site footer states CC BY 4.0 (the data-usage page cites CC BY 3.0): attribution required **[verify which applies; credit CoCoRaHS on About]** |
| **NOHRSC National Snowfall Analysis** (gridded 24 h snowfall) | Gridded sanity check and a second evaluation truth | NOAA, public; we already display it |
| **URMA / Stage IV / MRMS** precipitation analyses | QPF evaluation off-station; NBM itself calibrates against analyses | NOAA, public |
| **Partner study plots** (ski patrol / avalanche program interval boards) | **Best truth** for snowfall and SLR at ski areas | Needs written permission (`snow-ratio-ml.md` §7 (training-target choice)) |
| **Open interval-board data** (Utah CLN etc.) | SLR training/evaluation | Licence unresolved (`snow-ratio-ml.md` §6) |
| **PNNL BCQC SNOTEL** (Yan et al. 2018 QC + Sun et al. 2019 bias correction; daily, through WY2021) | **Benchmark for our QC** (compare our flags/corrections with theirs on overlapping years) | **[verify terms]** |

---

## 3. Data inventory

### 3.1 NBM archive

- **Where:** AWS Open Data `s3://noaa-nbm-grib2-pds` (`blend.YYYYMMDD/CC/core|qmd/`). NOAA's NBM documentation says the archive goes back to **about May 2020**; the v5.0 data guide says "since 2021" **[verify first usable date for our fields]**. A **cloud-optimized GeoTIFF** bucket (`s3://noaa-nbm-pds`) also exists and may allow much cheaper point reads **[verify start date and fields]**. NOAA open data on AWS: no account needed, free to download.
- **Versions in the archive (non-stationarity):**

| Version | Operational from | Winters covered (approx.) | Notes |
|---|---|---|---|
| v4.0 | 2020 | 2020–21, 2021–22, part of 2022–23 | **[verify dates]** |
| v4.1 | ~early 2023 (SCN 22-131) | 2022–23 (part), 2023–24 | **[verify date]** |
| v4.2 | May 15 2024 | 2024–25 | |
| v4.3 | May 27 2025 | 2025–26 | small change package |
| **v5.0** | **May 5 2026** (bug fix Jun 18 2026; v5.0.14 later) | **2026–27 (in progress)** | Winter suite changed: expert weighting of probabilistic members, removal of the 9-point stencil, WPC bias-corrected QPF added as an input (CONUS). v5.0 ran **in parallel** through 2025–26 (`noaa-nbm-parallel` bucket) **[verify retention]** |

- **What to extract** (byte-range per field, as the live pipeline already does): QPF 6/24 h percentiles + PoP; snowfall 6/24 h percentiles; SLR percentiles; snow level percentiles; T/Td/wind/gust; precip-type probabilities. Cycles **00Z and 12Z** only for training, forecast hours to day 10, native windows only.
- **Points:** every SNOTEL site (~836) **plus** ski-area base/summit (~320). Store the grid cell's own elevation for every point.
- **Volume:** full-field downloads for ~6 winters × 2 cycles/day × ~40 forecast steps × ~20 messages is in the **several-TB** range. Downloads are free and point extraction shrinks it to a few GB of Parquet. Budget days of container time, not hours. Run it as a resumable backfill job (same image as the pipeline, `platform-transition.md` §5.1), month by month, writing `archive/nbm_backfill/version=/year=/month=/`.
- **Cheaper alternative to test first:** NBM **text bulletins** (NBS/NBE/NBP) give station-level guidance including probabilistic QPF. Check whether SNOTEL sites are in the station list **[verify]**. If many are, they're a fast first dataset.

### 3.2 SNOTEL

- **Source:** NRCS AWDB (public domain). **Hourly** series: accumulated precip (PREC), SWE (WTEQ), snow depth (SNWD), air temperature (TOBS); some sites also have wind, RH, solar, soil.
- **Resolution:** precip and SWE **0.1 in**, temperature 0.1 °C (NRCS FAQ).
- **History caveats:**
  - **Temperature sensor bias:** NRCS is replacing air-temperature sensors west-wide to fix a known bias, and runs a database routine to **de-bias historic data** after each replacement. The same station's history can change between downloads. **Record the retrieval date and re-pull before each training run.**
  - **Depth sensor upgrades** (e.g., >90% replaced in Nevada/eastern Sierra by Dec 2025). Expect step changes in noise.
  - Outages (e.g., Nov 16–18 2026, already excluded in `config/settings.yml`).
- **Our own archive** (forecast archive + SNOTEL obs since Nov 2026, Parquet in R2 after the platform move) is the live continuation of this dataset.

### 3.3 Other predictors (later phases)

- Raw model fields we already sample for plumes (HRRR, RRFS, GFS, ECMWF HRES/ENS, AIFS, GEFS): live archive since late 2026 only. Backfill exists on AWS for HRRR/GFS/GEFS **[verify]**.
- Upper-air predictors that matter most for SLR (specific humidity and temperature ~400 m AGL, `snow-ratio-ml.md` §6) need HRRR pressure-level fetches. The pipeline is surface-only, and M6 was cancelled with the model maps. A **point-only** pressure-level fetch would have to be added if SLR work needs it.
- Static site features: elevation, grid-minus-point elevation, slope, aspect, distance/direction to the nearest crest, upwind barrier height (from USGS 3DEP, public domain); climatology normals (PRISM **[verify licence for commercial use]**).

---

## 4. SNOTEL quality-control system (the foundation)

### 4.1 Principles

1. **Flag, don't delete.** Keep raw values. Every observation gets QC flags + a **confidence score 0–1**. Training and verification choose thresholds explicitly.
2. **Versioned, tested code.** `pipeline/qc/` with pure functions, offline tests on fixture series that reproduce each known failure (spike, flatline, oscillation, capping release, reset, settling, rain-on-snow).
3. **Hourly first, then aggregate** to the NBM window (12Z–12Z, 6 h), so window alignment and QC are both exact.
4. **A hand-labelled gold set.** One team meteorologist labels ~200 station-events across regions (good / suspect / bad, with reason). It tunes thresholds and measures QC precision and recall. Re-label a sample each season.
5. **Publish the QC method** on About (trust), with per-station flag rates on the status/verification page.

### 4.2 Stages

| Stage | Checks | Applies to |
|---|---|---|
| **S0 Metadata** | Station elevation/location changes; sensor replacement dates (temperature, depth); known outages; water-year resets (Oct 1); gauge servicing/drain events | all |
| **S1 Range & physical limits** | Precip ≥ 0 and plausible hourly max; SWE ≤ plausible; depth 0–max; T within climatological bounds | PREC, WTEQ, SNWD, TOBS |
| **S2 Temporal consistency** | Spikes (z-score of first difference against a rolling MAD); **flatlines/stuck sensor** (no change for N hours while neighbours change); step changes; **non-monotonic accumulated precip** (negative increments → oscillation/servicing); missing-data gaps | all hourly series |
| **S3 Signal recovery** | **De-oscillate the weighing gauge:** smooth with a monotone filter (e.g. isotonic regression or a running-max-with-tolerance), then take increments on the window. Handle **delayed catch** (precip registered after the storm while T < 0 and depth isn't rising) by reassigning to the storm window only if the pillow confirms. Apply the 0.1 in **resolution floor**: an increment < 0.1 in is "trace / below detection", not zero | PREC, WTEQ |
| **S4 Internal consistency** | Gauge Δprecip vs pillow ΔSWE during cold periods (big disagreement = undercatch, bridging or pillow problem); depth increase without precip or SWE increase (drifting / sensor); precip with T < 0 and no depth rise (sensor or wind); **new-snow density bounds** (e.g. 2–40% unless confirmed); rain-on-snow / melt windows from T and ΔSWE < 0 | PREC × WTEQ × SNWD × TOBS |
| **S5 Spatial** | Compare with nearby SNOTEL (elevation-adjusted), ASOS, CoCoRaHS, and URMA/Stage IV/NOHRSC at the site. Flag an outlier only when several neighbours agree against it | event totals |
| **S6 Bias adjustment (optional, separate column)** | **Gauge undercatch** transfer function using wind and temperature (WMO SPICE-style). Most SNOTEL sites have **no wind sensor**, so wind would come from the model (circular, so keep the *unadjusted* target as primary). **Temperature warm bias** at cold temperatures: use NRCS de-biased data where available; otherwise flag | PREC, TOBS |
| **S7 Derived targets** | New-snow estimate from the depth series. Compare methods on the gold set: (a) window depth change, (b) sum of positive hourly changes above a noise threshold, (c) settlement-corrected (simple compaction model driven by T and load). Choose per region by gold-set error. SLR = new snow ÷ ΔSWE only when ΔSWE ≥ 0.3 in and new snow ≥ 2 in (tune), T guard, no melt flag | SNWD, WTEQ |

### 4.3 QC outputs (Parquet, R2 `archive/obs_qc/`)

`station, time_utc, var, raw, value_qc, flags (bitmask), confidence, method_version, retrieved_at`, plus window aggregates `station, window_start, window_hours, precip_obs, snow_obs, slr_obs, confidence, n_hours_valid`.

### 4.4 QC acceptance gate (before any training)

- Gold-set agreement: flags catch ≥ 90% of labelled "bad" events with ≤ 10% false flags on "good" ones (targets to confirm).
- Per-station flag-rate report; stations over a threshold are reviewed by hand or excluded.
- Agreement with the PNNL BCQC benchmark on overlapping years is reported (not required to match).

---

## 5. Training data design

- **Unit of a sample:** (station, NBM cycle, lead window, native window length) → NBM predictors at issue time + QC'd observation for that window.
- **Windows:** model **each native window separately** (6 h, 24 h; 48/72 h only where NBM has native percentiles). **Never build a 72 h answer by adding 24 h quantiles** (hard rule 4). For multi-day totals, see §6.4.
- **Season:** Oct 1–May 31 (water-year snow season); summer excluded for snow targets, optional for QPF.
- **Approximate size:** ~836 stations × ~240 season days × ~6 winters ≈ **1.2M station-days per lead**; with precipitation (wet) days ~30–40% → several hundred thousand wet samples per lead. That's ample for pooled models, thin for per-site ones (hence pooling, §6.2).
- **Version handling:** `nbm_version` as a feature *and* as a stratification for evaluation. Report skill on v5.0-only data separately as soon as it exists. Weight recent seasons more.
- **Leakage guards:** splits by **time (whole seasons)** and by **site**, never random rows (storms are correlated in space and time). Features must exist at issue time (no observed SWE as a predictor; that was the Veals "V4" after-the-event model).

---

## 6. Modelling approach

### 6.1 Baselines (must be beaten)

1. **Raw NBM** quantiles (the product we show).
2. **Per-site quantile mapping** of NBM against observed climatology (cheap, strong).
3. **EMOS / censored shifted gamma distribution (CSGD)** for precipitation: a parametric distribution that handles zeros and heavy tails; standard in NOAA precipitation post-processing research.
4. For SLR only: fixed 12:1 and NBM SLR p50 (already set up in `snow-ratio-ml.md`).

### 6.2 Candidate ML models

| Model | Output | Why | Watch out for |
|---|---|---|---|
| **Gradient boosting with quantile loss** (LightGBM/XGBoost), one pooled model across all stations | p10/p25/p50/p75/p90 + P(≥ thresholds) via a classification head | Fast on CPU, handles mixed features and missing values, strong on tabular data | Crossing quantiles: sort or use a monotone parameterisation |
| **Distributional gradient boosting** (NGBoost or a CSGD head) | Full distribution → any quantile/probability | Consistent quantiles and exceedances from one distribution | Distribution choice must fit zeros and tails |
| **Quantile regression forest** | Quantiles | Simple, robust; matches the Veals random-forest lineage for SLR | Large model files |
| **Neural distributional regression with station embeddings** (Rasp & Lerch-style) | Distribution parameters | Learns shared behaviour plus per-site quirks; best when per-site data is thin | Needs more care; phase 2 only |

**Recommendation:** baselines + **pooled LightGBM quantile model** first. Add the distributional and neural variants only if the pooled model beats the baselines and residual site effects remain.

### 6.3 Snowfall: direct vs components

- **Direct:** predict snowfall quantiles from NBM snowfall + predictors.
- **Components:** predict QPF and SLR (and P(snow)) separately, then combine by **sampling** (draw from both distributions, multiply, take quantiles). Never multiply quantiles directly.
- Evaluate both against the same truth; ship whichever verifies better. Components are easier to explain ("more snow because the air is colder and drier than NBM thinks").

### 6.4 Multi-day totals without breaking rule 4

Producing 48/72 h or storm totals from 24 h models needs a joint distribution. Use **ensemble copula coupling** or a **Schaake shuffle**: generate N calibrated "members" per window, reorder them using the rank structure of NBM/GEFS/ECMWF members, then sum members (not quantiles) and take quantiles of the sums. Label any total built this way as **derived**. Until this exists, show adjusted values on **native windows only**.

### 6.5 Getting from SNOTEL sites to ski areas

Ski-area base/summit points have no observations, so:
- Train on **site features** (elevation, grid-minus-point elevation, exposure, climate region) rather than site IDs alone, so the model can generalise to unseen points.
- **Leave-site-out validation** using SNOTEL sites near ski areas as stand-ins. Report the skill at *unseen* sites, since that is the honest number for ski areas.
- Show the adjustment at a ski area **only** where similar trained sites exist (same region, elevation band). Otherwise show NBM alone, with no gap and no error (pipeline rule 5).
- **Product implication:** the cleanest proof will be at SNOTEL sites themselves. The Nov 23 decision drops SNOTEL forecast pages; consider an **internal or verification-only SNOTEL forecast view** to publish the evidence.

---

## 7. Evaluation

| Metric | What it tells us | Target to ship as experimental |
|---|---|---|
| **CRPS / CRPSS vs raw NBM** (primary) | Whole-distribution skill | CRPSS > 0 with a 95% block-bootstrap interval above 0, per region |
| **Brier score / reliability diagrams** for P(≥ 4, 8, 12 in) and P(≥ 0.5, 1 in QPF) | Are probabilities honest? | Reliability at least as good as NBM |
| **p25–p75 coverage**, PIT histogram | Do "likely" ranges contain ~50%? | 45–55% coverage by region and lead |
| **MAE / bias of the median** | Easy to explain | Lower than NBM in most regions |
| **By stratum** | region, elevation band, lead time, month, NBM version, storm size, temperature | No stratum clearly worse than NBM (or the line is hidden there) |
| **Independent truth** | Same metrics vs CoCoRaHS / partner plots / NOHRSC | Same sign of improvement as against SNOTEL |

- **Splits:** leave-one-season-out (time) × leave-sites-out (space). Hyper-parameters tuned only inside training folds.
- **Significance:** block bootstrap by storm/day.
- **Publication:** results go to the public verification page (M9) before the line becomes default anywhere.

---

## 8. From research to product

| Stage | What | Gate to the next stage |
|---|---|---|
| **R0 Data lake** (Dec 2026–Feb 2027) | Backfill NBM point extracts; pull hourly SNOTEL history; build QC v1 + gold set; Parquet in R2 | QC acceptance (§4.4) |
| **R1 Baselines** (Mar–May 2027) | Score raw NBM vs QC'd SNOTEL by version/region; per-site quantile mapping + CSGD | Published internal report. **If NBM is already well calibrated and the baselines gain nothing, narrow scope to SLR** |
| **R2 ML candidates** (May–Aug 2027) | Pooled LightGBM quantile; components vs direct snowfall; leave-site-out | CRPSS > 0 vs best baseline, out of sample, in most regions |
| **R3 Experimental line** (2027–28 season) | `ml_adjusted.enabled=false` by default; turned on for staff, then a labelled public "Experimental: Snow-Wx adjusted" line beside NBM on native windows. Shows training sample size, region and last verification score | One full season of live, out-of-sample verification |
| **R4 Promotion** (2028+) | Adjusted values may feed Finder/summaries/alerts | Public verification shows it beats NBM; owner sign-off |

**Not in scope until R4:** using adjusted values in daily summaries, alerts, powder-quality classes or the agreement badge. **Never:** using ML to change or soften safety information.

### 8.1 Engineering

- **Training:** offline, in a container job (CPU is enough for gradient boosting), reading Parquet from R2. Track experiments with a simple, versioned results table in R2 (or MLflow if it earns its keep).
- **Artefacts:** model files versioned and hashed in R2 (`models/ml_adjusted/<version>/`), plus a model card (data window, versions, metrics, known weak strata).
- **Inference:** a pure function in the pipeline after NBM points are built; output written as **separate fields** in the points JSON (`ml.*`), never overwriting NBM fields (guard test). Missing model or inputs → no `ml.*` fields, no error banner.
- **Monitoring:** live verification of `ml.*` vs NBM every day (reuses `verify`); automatic disable if rolling CRPSS turns clearly negative.
- **Retraining:** each off-season, plus after any NBM version change (re-check v5.x drift).
- **Ownership:** Dev A (pipeline/data) leads, with a meteorologist reviewer for QC labels and verification. Consider collaboration with the University of Utah group behind the SLR papers (`snow-ratio-ml.md` §6.1 (contact the authors)).

### 8.2 Cost

Backfill: free NOAA downloads, roughly days of container time (tens of dollars). Training: CPU, small. Storage: a few GB of Parquet in R2 (cents/month). The main cost is **people time**, especially QC labelling.

---

## 9. Risks

| Risk | Mitigation |
|---|---|
| Training toward biased SNOTEL truth (undercatch, settling) makes real forecasts worse | QC + confidence weights; independent truth check (§2.1); keep unadjusted and adjusted truths separate |
| NBM v5.0 shift makes v4.x training stale | Version feature + v5.0-only evaluation; v5 parallel data for 2025–26 if retained; retrain after every upgrade |
| Overfitting to a few big storms | Season-out and site-out validation; block bootstrap; per-stratum reporting |
| Ski-area transfer fails | Leave-site-out skill as the headline; show adjustments only where supported |
| Scope creep for a 3-person team | Stage gates; R1 can stop the program or narrow it to SLR |
| Licence problems with extra truth data | Use only sources with confirmed terms; attribution on About |
| Users read "ML" as "more accurate" | Experimental label, model card, published verification, no accuracy claims before R4 |

---

## 10. Decisions needed

1. Approve M12 as a research program with gates R0–R4 (no site change before the 2027–28 season).
2. Who labels the QC gold set (a team meteorologist, ~2–3 days per season)?
3. Seek **partner study-plot data** (ski patrols / avalanche programs) for snowfall and SLR truth? (Same as `PLAN.md` §11 item 11.)
4. Keep an **internal SNOTEL forecast view** for verification, given SNOTEL forecast pages are leaving the public site?
5. Add a **point-only HRRR pressure-level fetch** for SLR predictors (needed for the strongest Veals predictors), or stay surface-only?
6. Contact the University of Utah SLR group about collaboration and data terms?

---

## Sources (checked Nov 23 2026)

- NBM archive and versions: https://blend.mdl.nws.noaa.gov/nbm-documentation · https://vlab.noaa.gov/web/mdl/nbm-versions · v5.0 upgrade (May 5 2026): https://vlab.noaa.gov/web/mdl/-/national-blend-of-models-nbm-upgraded-to-version-5.0-1 · SCN 26-24: https://www.weather.gov/media/notification/pdf_2026/scn26-24_Updated_NBM_V5.0_aac.pdf · v5.0 winter suite: https://vlab.noaa.gov/documents/6609493/7858320/Blend_Winter_v5.0-Configuration_and_Technical_Details.pdf · AWS registry: https://registry.opendata.aws/noaa-nbm · text archives: https://vlab.noaa.gov/web/mdl/nbm-text-archives
- NBM precipitation post-processing (quantile mapping, reforecasts): Hamill, Stovern & Smith 2023, https://repository.library.noaa.gov/view/noaa/53339/noaa_53339_DS1.pdf · ANN-CSGD post-processing: https://repository.library.noaa.gov/view/noaa/53237/noaa_53237_DS1.pdf
- SLR ML: Veals et al. 2025, https://repository.library.noaa.gov/view/noaa/71982/noaa_71982_DS1.pdf · Pletcher et al. (CONUS SLR ML): https://repository.library.noaa.gov/view/noaa/73136/noaa_73136_DS1.pdf
- SNOTEL sensor precision: NRCS FAQ, https://www.nrcs.usda.gov/wps/portal/wcc/ · sensor upgrades and temperature de-bias: https://www.nrcs.usda.gov/state-offices/nevada/news/nevada-snow-survey-whats-new-for-2026 · BCQC SNOTEL (Yan et al. 2018; Sun et al. 2019): https://www.pnnl.gov/data-products · gauge/pillow behaviour: https://westernsnowconference.org/node/658 · gauge resolution in Utah networks: https://home.chpc.utah.edu/~u0035056/old_content/alumni/lcheng/Thesis/chapter2.pdf · snow depth sensor evaluation (Ryan et al. 2008): https://climate.colostate.edu/pdfs/2008JAOT25_5_667-684~Ryan_etal-evaluating_snow_depth_sensors.pdf · SNOTEL characteristics/QC (Serreze et al. 1999): https://psl.noaa.gov/psd1/pubs/1999/details/serreze_01abs.html
- CoCoRaHS licence: https://cocorahs.org/Content.aspx?page=Help · data usage policy: https://edit.tosdr.org/documents/1205
