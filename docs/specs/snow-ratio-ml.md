# Spec: M11 machine-learned snow-to-liquid ratio (research; no site change)

> Status (dev22): **S0 research done**. Nothing here is on the site and nothing is switched on. Sections 1-5 and 7 were NOT supplied with the dev22 brief (it said "content below" but
> none followed): they are drafted from the brief's own wording and marked *(draft: replace with the owner's Project copy)*. Section 6 is the dev22 finding.

## 1. Goal *(draft)*
Test whether a learned snow-to-liquid ratio (SLR) can beat NBM's own SLR for ski-area and SNOTEL points, offered at most as an **experimental line next to NBM, never replacing it**.

## 2. Reference *(draft, from the brief)*
Veals et al. 2025, Weather and Forecasting 40, DOI 10.1175/WAF-D-24-0233.1 (University of Utah). Random forest / linear regression SLR from HRRR / GFS / ERA5 (temperature, specific humidity and wind at 400 m and
2400 m above ground, QPF, CAPE, solar angle); R2 0.43, MAE 2.94 versus R2 0.04-0.23 for NBM-family methods; trained on manual interval-board observations at 14 mountain sites. Code: github.com/pveals/Veals_etal_2025.

## 3. Hard constraints *(draft; they come from PLAN §0)*
Quantile output (p25/p50/p75), never a single number; labelled "experimental"; falls back silently to NBM SLR when an input is missing; never summed or interpolated across windows; license-clean inputs and attribution; offline tests;
the forecast archive's existing columns and the points JSON's NBM field names stay unchanged.

## 4. Stages *(draft)*
S0 research (this) · S1 baseline scoring after >= 4 weeks of archive · S2 offline candidate (quantile output, hold out whole sites) · S3 experimental line behind `snow_ratio_ml.enabled=false` · S4 promotion only after verification.

## 5. Interfaces *(draft)*
Config flag `snow_ratio_ml.enabled` (off, not yet in `config/settings.yml`); the candidate would write a separate points field (e.g. `series.slr_ml_p25/p50/p75`), never overwrite `slr_p*`.

## 6. Findings (dev22, Nov 20-21 2026)

### 6.1 The paper's code and data (5a)
Read through a fetch tool (page text only; nothing downloaded or vendored):
- **Repository** github.com/pveals/Veals_etal_2025: 8 commits, folders `Models/`, `Data/`, `Notebooks/` and a short README. **No licence file** (the raw LICENSE URL answers 404): default copyright applies, so reuse is not granted.
- **What is included:** trained model files and their key files (`Models/`: V1a, V1b, V1c, V2 as `.npy`, V3 and V4 as `.pickle`), six "Load_Use" notebooks, sample atmospheric/observed-ratio datasets per version and three raw station files named `CLN_2004_2024.csv`,
  `CSSL_2021_2024.csv` and `HLY_2019_2024.csv`. **No standalone code files and no requirements file** are listed; the notebooks were not opened. Pickled models are also a security risk to load (arbitrary code): never `pickle.load` them.
- **"CLN"** appears only as a station/site code in that file name. No Hive dataset page for it could be retrieved (the Hive search is rendered client-side), so its terms are **unknown**. The paper itself (journals.ametsoc.org) answered 403, so its Data Availability statement was not read.
- **Decision:** do not vendor or download any of it. The README names the author's contact (peter.veals@utah.edu): the owner can ask for a licence and for the data terms before S2. Our own model would be trained on our own data (6.3) and the paper used only as a method reference.

### 6.2 Predictors versus what the pipeline fetches today (5b)
| Paper predictor | Today | Needed |
|---|---|---|
| 2 m temperature, 2 m humidity | HRRR / RRFS / GFS surface fields (t2m, dpt or rh) in the model-map runs; NBM TMP/DPT at points | available; point sampling for ML would be new |
| Wind (10 m) | HRRR/RRFS/GFS gust and 10 m wind; NBM wind | available (but the paper uses 400 m and 2400 m AGL) |
| Temperature, specific humidity, wind at **400 m and 2400 m AGL** | not fetched (surface-only maps; ridge-wind samples a few pressure levels only for ski-area summits) | **pressure-level or native-level HRRR/GFS**: interpolate to height AGL with HGT. HRRR `prs` per forecast hour at 21 levels (1000-500 mb) measured earlier: TMP 12.3, RH 16.6, DPT 22.6, HGT 15.3, U+V 25.7 MB (about 93 MB per hour, about 2.2 GB per 24 h); only 3-5 levels would be needed (about 15-25 MB per hour). Native-level files are far larger (not measured here) |
| QPF | NBM and model APCP | available |
| CAPE | not fetched (one more HRRR/GFS surface field, small) | new field |
| Solar angle | none | computed from time and latitude, free |
| ERA5 (training) | not used by the project | **licence and download volume unchecked**; training could instead use the HRRR/GFS analyses and our own archive |
Time cost estimate: a points-only extraction (sample ~600 points, a few levels) fits inside the existing HRRR job's budget (+1-3 min) if byte-range requests of only the needed messages are used, as the NBM fetch does.

### 6.3 Ground-truth audit (5c) with the forecast archive
`tools/slr_baseline.py` (read-only, offline, tested) derives an observed ratio per SNOTEL site and 12Z day from the archive's `d_depth_med3_24h / d_swe_24h` with the paper's filters
(new snow > 2 in, SWE > 0.11 in; ratio <= 2, >= 50 and exactly 10.0 dropped; >= 20 hourly reports). Real archive, Nov 20 2026 (SNOTEL file only, deleted after the run):
- 15,436 rows -> 3,900 with both changes -> 3,765 with enough reports -> 639 with new snow and SWE above the minima -> **524 qualifying events** (weeks 2026-W46: 34, W47: 490), by state UT 153, NV 78, ID 76, CA 74, MT 49, WY 31, CO 27, OR 21, WA 8, NM 6, AZ 1. At most 4 events at any one site yet.
- Observed ratio: **median 8.0:1** (p25 6.7, p75 12.0): clearly low against the 12-15:1 typical of dry Intermountain snow.
- Baseline of fixed ratios against these derived values: 10:1 MAE 3.59, bias +0.71, R2 -0.03; 12:1 MAE 4.42, bias +2.71, R2 -0.40; 15:1 MAE 6.38, bias +5.71, R2 -1.76.
- **Caveats (always state them):** (1) a 24 h depth change includes compaction and settling, so these ratios are a lower bound of the ratio of the new snow (the paper used interval-board measurements): the numbers above are biased LOW and
  must not be quoted as "the real ratio"; (2) the archive has **no temperature or precipitation-type column**, so warm and rain-affected days cannot be skipped (the 2-in depth gain and the ratio > 2 rule are the only guards);
  (3) the archive has **no forecast snow ratio**, so **NBM's SLR p50 cannot be scored from it**. Scoring it needs a new, additive archive file (e.g. `slr-YYYYMM.csv.gz` with `end,triplet,slr_p50,slr_p25,slr_p75`);
  existing archive columns stay as they are. `slr_baseline.py --nbm-slr` already accepts such a file.
- Not published; nothing on the site.

### 6.4 Recommendation
1. Keep S0 closed. The decision that matters is the **ground truth**: SNOTEL depth change is a poor proxy (6.3 caveat 1), and the training target in the paper is a different instrument. Without a better target (interval-board or SNOTEL-derived with a compaction correction), a model trained here
   learns to predict compaction. Ask the paper's author about licensing and about the CLN observations before S2.
2. S1 needs (a) >= 4 weeks of archive (about Dec 18) and (b) the additive SLR archive file above, started now so it has data by then. This is a small owner-authorised change to the archive writer, not made in dev22.
3. S2 (offline candidate) uses 3-5 HRRR pressure levels at the point cells, quantile gradient boosting or quantile forest, whole-site hold-out; S3 only after S2 beats NBM p50 in held-out MAE and calibration of the p25-p75 band.

## 7. Open decisions *(draft)*
Licence/terms answer from the paper's author; training-target choice; whether to add the SLR archive file; whether ERA5 is acceptable for training; the label text for the experimental line.
