---
name: snow-wx-hard-rules
description: Check a Snow-Wx change against the six hard rules (safety info, heuristics, licensing, percentile windows, independent sources, host limits) before committing. Use for any change to web pages, charts, summaries, alerts, avalanche display, ranges/percentiles, data sources or published JSON.
---

# Snow-Wx hard-rules check

Run this before committing any change that users can see or that changes published data. It turns `docs/PLAN.md` §0
into concrete checks against this codebase. Report each check as PASS / FAIL / N/A with evidence (file:line, test name or
screenshot). Any FAIL blocks the merge unless the owner explicitly accepts it in the MR.

## Step 1 — Classify the change

List the files changed (`git diff --name-only origin/main...HEAD`). Mark which apply:
- **Safety surface:** `web/js/area.js` (alert banner, avalanche block, snow level), `web/js/app.js` (obs map avalanche/hazards),
  `web/js/mine.js`, `web/js/hazards.js`, `web/js/freshness.js`, `pipeline/alerts.py`, `pipeline/avalanche.py`, `pipeline/afd.py`,
  `pipeline/hazards.py`, `pipeline/restore.py`, `pipeline/pwa_sw.js`, `web/css/style.css` (`.danger-chip`, colours).
- **Ranges/percentiles:** `pipeline/points.py`, `pipeline/nbm/run.py`, `pipeline/summary.py`, `web/js/charts/*`, `web/js/finder.js`,
  `web/js/multimodel.js`, `web/js/ensemble.js`, `pipeline/models/multimodel.py`, `pipeline/ecmwf.py`, `pipeline/gefs.py`.
- **Sources/hosts:** new fetch code, `config/sources.yml`, any new URL in `web/`.
- **Published contracts:** points JSON fields, `summary.json`, `meta.json`, archive columns, URL scheme.

## Step 2 — Rule 1: safety info is never gated or hidden

- Avalanche danger: chip text uses the per-level text colour (`DANGER_TEXT` / `textOn()` in `web/js/colors.js`); contrast ≥ 4.5:1
  on all five levels (C2). Expiry computed **in the browser** from `end_date` vs `Date.now()`, not only the build-time `expired`
  flag (H2). The avalanche center link renders even when the rating is missing (H3).
- NWS alerts: banner filters `Date.parse(ends) > Date.now()` (M12); "alerts checked <time>" shown from `alerts/index.json`
  `generated_at`; a failed fetch shows a "could not be loaded" notice with a weather.gov link (H3) — never a silent empty banner.
- Snow level / rain-at-base still visible next to snowfall.
- PWA: safety data is network-first with a timeout, cache only offline with an age label (M16).
- Nothing safety-related is behind a flag, login or paywall.

## Step 3 — Rule 2: heuristics are labelled, never accuracy or avalanche ratings

- Powder quality / snow type, agreement badge, daily summary, wind-exposure flag each carry their "heuristic" label and an About link.
- No copy says or implies "accurate", "more accurate", "best" or a hazard rating unless it cites the published verification panel.
- The wind flag text says "Wind transport potential — not an avalanche rating".

## Step 4 — Rule 3: licence-clean with attribution

- New source? Its licence is in `config/sources.yml` and `docs/PLAN.md` §10, and allows public display. Unclear → stop and ask.
- Attribution visible where the data appears: NOAA/NWS, USDA NRCS (SNOTEL), avalanche.org, ECMWF ("Contains ECMWF open data … CC BY 4.0"),
  © OpenStreetMap contributors / OpenSkiMap (ODbL), OpenFreeMap. Known gaps to not widen: N1 in `docs/BACKLOG.md`.

## Step 5 — Rule 4: one native window per range; p25–p75 default

- Every range comes from **one** native NBM percentile window (`points.native_window`; totals carry `native: true`).
  If a value needs several windows: expected amount only, `native: false`, no range.
- No code adds, multiplies, averages or interpolates percentiles across windows or hours. Grep the diff for `p25`, `p75`, `q1`, `q3`,
  `lo`, `hi`, `Math.min(`, `Math.max(` near percentile arrays (M5 was a cross-hour envelope labelled "likely").
  Documented exception only: 12-h day/night ranges add 6-h windows rank by rank (`P.rank_sum`).
- Default range wording "likely" = p25–p75; 10–90 only where `docs/DESIGN.md` §6 allows (24/48/72 h totals, snow level, SLR).
- One accumulation period per chart axis. Missing steps are gaps (`connectgaps: false`, no interpolation in the badge: M6).
- Every module shows source + issue time; each model line shows its own run time (N2).

## Step 6 — Rule 5: sources fail independently; offline tests

- New/changed source code registered in `pipeline/__main__.py:SOURCES` and wrapped so its failure doesn't stop others.
- Fetch functions separate from pure functions; the pure part has tests with `tests/fakes.py` (no network, no real `data_cache`).
- A failure is visible in `meta.json` / the status page; a product that delivered before can't go back to "waiting" (H4).

## Step 7 — Rule 6: host limits

- Site build stays < 20,000 files and no file > 25 MiB (the size guard in `update-site.yml`); bulk data goes to R2 (after W1).

## Step 8 — Report

```
Hard-rules check for <branch> (<backlog IDs>)
1 Safety: PASS|FAIL|N/A — evidence
2 Heuristics: …
3 Licence/attribution: …
4 Percentile windows / p25–p75 / issue times: …
5 Independent sources / offline tests: …
6 Host limits: …
Blocking issues: <list or none>
```
Paste it into the MR description under "Safety / hard rules".
