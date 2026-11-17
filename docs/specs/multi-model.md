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
