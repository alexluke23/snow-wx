# Design & visualization standards (§6)

> Read when building or changing any chart, map legend, color or layout.
> Part of Snow-Wx docs v1.0 (Nov 15 2026). Index and priorities: `PLAN.md`.
> Section numbers (§) are kept from the original single plan so cross-references still work.

---

## 6. Visualization standards ("clean and sharp")

`docs/DESIGN.md` + shared `web/css/tokens.css` and `web/js/charts/theme.js`.

- **Mobile-first** (375 px, then desktop); tap targets ≥ 40 px; system UI font;
  tabular numerals.
- **Color:** one snowfall palette everywhere (maps, Finder, bars, legends): the **NWS snowfall color table**,
  defined once in `web/js/colors.js` (`SNOWFALL`; classes 0, T, 0.1, 1, 2, 3, 4, 6, 8, 12, 18, 24, 30, 36, 48, 60, 72,
  96, 120+ in), copied from the legend of NOAA/NWS NOHRSC's National Snowfall Analysis maps
  (https://www.nohrsc.noaa.gov/snowfall_v2/data/, e.g. `sfav2_CONUS_72h_*.png`, sampled Nov 9 2026). Pale swatches get
  outlines (`snowPale`). Model maps still use the older table (backlog §8.4). NAADS
  avalanche colors; temperature palette with a clear 32 °F break; color never the
  only carrier of meaning.
- **Numbers first:** each chart has a headline sentence above it (also its
  aria-label). **Uncertainty everywhere:** the **snowfall-by-day** chart uses floating **p25–p75 range bars** labelled "low–high″",
  colored by the median (no expected tick, no whiskers); **the default range everywhere is p25–p75, worded "likely X–Y in"** (owner Nov 17: the middle half of NBM's outcomes, about a
  1-in-4 chance of more than the high number and of less than the low number): 24/48/72 h totals, snow level, snow ratio,
  Finder, My mountains, summaries. 10–90% only where a chart or tooltip explicitly says so; no inline "NBM 10–90%" label. Accumulated snow shows expected amounts only.
  **Never sum, scale or interpolate percentiles across windows** (a range must come from one native NBM window).
- **Units:** in, °F, mph (kt on ASOS/model maps), ft; local time with zone;
  relative times ("issued 2 h ago").
- **Chart set:** (1) snowfall by day (12Z–12Z) p25–p75 range bars + accumulated running total (10 d); (2) snow-level
  band vs base/summit lines; (3) hourly meteogram; (4) precipitation by model;
  (5) recent obs (SNOTEL depth/SWE, storm total).
- **Freshness:** every module shows source + issue time; stale data is greyed
  (and, offline, flagged per §5.8).

### 6-B Chart readability & accessibility (every chart)
- Text: ticks ≥ 13 px desktop / 12 px mobile; axis titles 13–14 px, horizontal,
  top-left with units ("Snow (in)"); no rotated titles.
- Time axes: weekday + date ("Mon 9"), zone stated once, faint day separators,
  night shading; stacked panels share x-range and left margin.
- One idea per panel, ≤ 3 series; direct labels over legends (legend above if
  needed). Bars: labels ≥ 12 px never colliding with whiskers; whiskers thinner.
- **Never sum percentiles** (or scale/interpolate them): NBM percentiles of 6 h windows cannot be added into 12 h or
  longer ones. If no single native window covers a span, show the expected amount without a range (e.g. the
  hatched grey "partial day — expected amount, no range" bar).
- Probabilities: **heat table** (rows thresholds, columns windows), % in every
  cell, color-blind-safe sequential palette, auto-contrast text.
- **One accumulation period per axis** (never mix 1-h and 6-h amounts).
- Color-blind-safe palettes (Okabe–Ito for categories); summit solid vs base
  dashed; AA contrast (4.5:1) for all text incl. pale snowfall swatches.
- Reference lines labeled in place (32 °F, base/summit elevations, zero).
- **Snow ratio panel (dev14):** median (solid dark line) + the "likely" p25–p75 band (one translucent Okabe–Ito blue, ~25%) from
  the SAME percentile series over the whole run; powder-quality thresholds are thin dashed lines with direct labels in the right
  margin ("Blower ≥ 15:1", "Medium 10–15:1", "Dense < 10:1"), never full-height colour bands; undefined stretches get a light
  labelled "no snow forecast" strip, never zeros. **Snow level panel:** median + likely band over the whole run (solid where
  precipitation ≥ 20%, dotted elsewhere); no-data stretches labelled.
- Mobile: panels ≥ 200 px tall at 375 px; tap tooltips; disable chart drag/zoom
  on touch.
- Every chart: one-sentence summary + **"View as table"** toggle.
- **Acceptance:** Lighthouse accessibility ≥ 95 on every page; screenshots at
  375/1280 px; a "5-second test" note per chart.

### 6-C Basemap reliability
Set `maxNativeZoom` per tile layer and allow overzoom; watch `tileerror` and
fail over to a fallback provider (update attribution; check each provider's
terms); log tile failures in debug.

---
