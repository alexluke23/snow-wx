---
status: current
owner: team
last_reviewed: 2026-11-23
read_when: you meet an unfamiliar weather, data or project term
---

# Glossary

Weather and snow-science terms, data sources, and project shorthand. Agents: prefer these meanings when a term is ambiguous.

## Forecast and snow science

| Term | Meaning in this project |
|---|---|
| **NBM** | National Blend of Models (NOAA/NWS MDL): calibrated blend of many models on a 2.5 km grid; the **primary** forecast here. v5.0 operational since May 5 2026. |
| **core / qmd** | The two NBM file families. *core*: deterministic fields, snowfall/snow-level/SLR percentiles (full on 01/07/13/19Z). *qmd*: quantile-mapped probabilistic fields incl. QPF percentiles (00/06/12/18Z). |
| **Cycle / init / fNNN** | Model run time (e.g. 13Z) and forecast hour after it (f036 = 36 h later). `cycle` in our JSON = `YYYYMMDDHH`. |
| **Native window** | An accumulation window NBM itself publishes percentiles for (e.g. 24 h ending 12Z). Ranges may come only from one native window (hard rule 4). |
| **Percentile (p10, p25, p50, p75, p90)** | Value below which that share of NBM's outcomes fall. **"Likely" = p25–p75** (middle half), the default range. 10–90 only where DESIGN §6 says. |
| **Rank sum (`P.rank_sum`)** | Adding percentiles window by window at the same rank; only allowed for the documented 12-h day/night ranges (slightly wide). |
| **Exceedance / chance of ≥ X** | Probability of at least X inches in a window, from NBM's own exceedance fields (not derived from percentiles). |
| **QPF** | Quantitative precipitation forecast: liquid-equivalent precipitation (in). Models are compared in liquid. |
| **SWE** | Snow water equivalent: liquid water in the snowpack or in new snow (in). |
| **SLR / snow ratio** | Snow-to-liquid ratio: inches of snow per inch of liquid (e.g. 15:1). Drives powder quality. NBM's SLR is formula-based (Cobb/Roebber family); M11/M12 study ML alternatives. |
| **Powder quality / snow type** | Labelled heuristic from SLR p50: Dense < 10, Medium 10–15, Blower ≥ 15; "wind-affected" when summit gusts are high during snow. |
| **Snow level** | Height where snow turns to rain (≈ wet-bulb 0 °C), in ft MSL; compared with base and summit. NBM SNOWLVL is metres MSL. |
| **P(snow)** | Probability that the snow level is below the point's elevation, from snow-level percentiles; scales point snowfall. |
| **Lapse rate** | Temperature change with height; we use 6.5 °C/km to move grid temperature to the point (cap 4000 ft). |
| **Grid vs point elevation** | NBM's 2.5 km cell has one elevation; a summit or base may differ by thousands of feet. Shown in tooltips. |
| **Day / night periods** | 12-h periods 00Z–12Z and 12Z–00Z, labelled in local time; snow charts use 12Z–12Z days. |
| **HRRR / RRFS / GFS** | NOAA deterministic models: HRRR (3 km, to ~48 h), RRFS (to ~84 h), GFS (global, to day 16). Plume lines. |
| **GEFS** | NOAA Global Ensemble Forecast System: ensemble members for the GEFS plume. |
| **ECMWF IFS HRES / ENS / AIFS** | ECMWF deterministic model, its ensemble (member count read from the data; the open-data mirror has 50 perturbed members), and its AI model (experimental line, excluded from the badge). CC BY 4.0. |
| **Plume** | Chart of many forecasts over time: per-model lines (Precipitation by model) or ensemble members (ECMWF ENS / GEFS). |
| **Agreement badge** | Labelled heuristic: how closely ≥ 3 models agree on precipitation for a window. Never "High" when all models are < 0.20 in. |
| **NDFD** | NWS National Digital Forecast Database (the official human forecast grid). Fetched and archived for verification only; not shown since dev22. |
| **AFD** | Area Forecast Discussion: NWS forecaster's text reasoning, per office. |
| **NOHRSC / SNODAS** | NOAA snow analysis center; SNODAS = modelled snowpack (SWE, depth) used for map overlays. |
| **SNOTEL** | USDA NRCS automated snow stations (~836 in our region): snow pillow SWE, depth sensor, precip gauge, temperature. Public domain. Ground truth for verification (with QC caveats: undercatch, settlement, 0.1 in resolution). |
| **AWDB** | NRCS Air and Water Database: the SNOTEL data service (slow: 3–8 min per fetch). |
| **ASOS / AWOS** | Airport weather stations, via the Iowa Environmental Mesonet. |
| **Avalanche danger** | North American scale 1–5 (Low … Extreme) from avalanche centers via avalanche.org. Shown unaltered, greyed when expired, always linked. |
| **Undercatch** | Precipitation gauges catch less snow than falls, especially in wind; a key SNOTEL QC issue (M12). |
| **Interval board** | Manual snow board wiped after each observation; the best snowfall/SLR ground truth (not available in SNOTEL). |
| **CRPS / reliability / PIT** | Probabilistic verification scores (M9, M12): CRPS = error of a whole forecast distribution; reliability = do stated probabilities happen that often; PIT = calibration histogram. |

## Platform and code

| Term | Meaning |
|---|---|
| **build/** | Local/CI output folder: the deployable site plus `build/data/` and `build/models/`. Never committed. |
| **data_cache/** | Local download cache (GRIB subsets, resume caches); auto-pruned; tests must never write it. |
| **Product tar / `model-maps` release** | Today each job publishes `<product>-<cycle>.tar` as a GitHub Release asset; `update-site` unpacks the newest. Replaced by R2 in the move. |
| **`verification` release** | GitHub Release holding the forecast archive CSVs (the only copy until R2). |
| **meta.json** | Per-source health written by the build; drives the status page and the monitor. |
| **Frozen fixtures** | Recorded inputs for browser checks so they never depend on live data (`tools/browser_fixtures.py`). |
| **Feature flag** | `*.enabled` in `config/settings.yml`; built-but-off features stay off until the owner flips them. |
| **W1–W7** | Web/launch milestones: W1 domain + hosting, W2 indexable pages, W3 daily summaries, W4 PWA, W5 analytics/monitoring, W6 alerts backend, W7 wind flag. |
| **M7–M12** | Model/data milestones: M7 precipitation by model, M8 ECMWF, M9 verification, M10 later items, M11 ML snow ratio, M12 ML post-processing. |
| **C/H/M/L + ID, N1/N2** | Code-review findings (Critical/High/Medium/Low) in `docs/BACKLOG.md`; N = unnumbered review gaps. |
| **MR 1–10, PR B** | Merge-request groups for the review fixes (`docs/BACKLOG.md` §1). |
| **A-NN** | Roadmap action items (`docs/ROADMAP.md`). |
| **Scope trim** | Nov 23 decision: remove model maps, Sno-Parks and SNOTEL-site pages (keep SNOTEL-site forecasts). |
| **Shadow run / parity check** | Running a moved pipeline job in parallel and comparing outputs before cutover. |
| **Workers / Static Assets / R2 / D1 / Containers / Workflows / Queues** | Cloudflare products: serverless functions / static hosting / object storage / SQLite database / container jobs / durable multi-step jobs / message queues. |
| **WX API** | The planned `/v1` read API Worker serving web, mobile apps and the AI agent. |
| **Set by owner** | A technical item that waits on a business decision kept outside the repo. |
