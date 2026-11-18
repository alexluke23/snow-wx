# snow-wx — notes for Claude Code

Public website of open weather, snowpack and avalanche data for western US
mountains, built for skiers and snow-science users. Owner is a meteorologist
comfortable with Python. Free-first, with a possible small business later.
Hosting today: GitHub Actions (hourly) builds static JSON/PNG + HTML and deploys
to GitHub Pages; the planned move to a custom domain + Cloudflare Pages + R2 is
milestone W1 (docs/specs/hosting-seo.md). No servers, no API keys so far (the W6
alerts backend will add a small one; see docs/specs/alerts-backend.md).

## Project docs (read only what the task needs)
- At the start of every session read `docs/PLAN.md` (lean plan: status, rules, roadmap, acceptance criteria).
- Before working on a feature, read ONLY its spec in `docs/specs/` (index in the "Where things live" table in PLAN.md).
- Read `docs/DESIGN.md` only when building or changing charts, maps legends, colors or layout.
- Do NOT read `docs/BUSINESS.md` (pricing, legal, go-to-market) or `docs/ARCHIVE.md` (history) unless the task explicitly asks for them.
- When a milestone lands, tick it in PLAN.md §8; move finished items and stale decisions to `docs/ARCHIVE.md` so PLAN.md stays around ~17 KB.
- Keep section numbers (§) stable; cross-references rely on them.
- Keep PLAN.md §2 Status and §3 Decisions log current as work lands.
- Reference docs (read only for that topic):
  - `docs/verification.md` — forecast archive and M9 verification
  - `docs/nbm_inventory.md`, `docs/nbm_prob_consistency_*.md`, `docs/nbm_validation_gsl_*.md` — NBM GRIB layouts, exceedance-probability consistency, GSL viewer validation (NBM fetch/decode work)
  - `docs/sources_recreation.md` — Sno-Park / recreation source research and licences
- Hard rules for all code are in PLAN §0 (safety info never gated or hidden; **percentiles are never summed across days or into 7/10-day totals; the 12-h day/night ranges add 6-h windows rank by rank, a documented, conservative approximation (slightly wide)**; label heuristics, never present
  them as accuracy or avalanche ratings; license-clean data with attribution; one accumulation period per
  chart axis and NEVER add, scale or interpolate percentiles across windows; offline tests; static-host
  limits of 20,000 files/deploy and 25 MiB/file, so bulk data goes to R2).
- Current priority order: PLAN §8.2 (Sprint 1 Foundations first). Model maps are low priority; do not work on
  them unless asked.

## Commands
Use the project's conda env Python for every Python command (no `conda activate`
needed), e.g.
- `C:/miniforge3/envs/snow-wx/python.exe -m pytest -q` — unit tests (offline; uses tests/fakes.py FakeSession)
- `C:/miniforge3/envs/snow-wx/python.exe -m pipeline build` — copy web/ to build/ and fetch fresh data into build/data
- `C:/miniforge3/envs/snow-wx/python.exe -m pipeline obs --only snotel -v` — fetch one source, verbose
- `C:/miniforge3/envs/snow-wx/python.exe -m pipeline models --model hrrr --fhours 0 6 12 --domains west wasatch --keep-grib`
  — quick model-map run into build/models (drop the limits for a full run; `build` then merges the catalog)
- `C:/miniforge3/envs/snow-wx/python.exe -m http.server 8000 -d build` — preview at http://localhost:8000
  (models viewer: http://localhost:8000/models.html)
- SNOTEL fetch takes 3–8 min (AWDB is slow). For front-end-only changes copy `web/*` over `build/`
  instead of re-running `build`. Headless Chrome screenshots work for checking pages
  (`chrome --headless=new --screenshot=out.png --window-size=1400,900 --virtual-time-budget=15000 URL`);
  the obs map accepts `#v=<var>&map=<z>/<lat>/<lon>&s=<station>`, the viewer `#m=&f=&d=&h=`.

Windows note: calling the env's python.exe directly (without `conda activate`) leaves
`envs/snow-wx/Library/bin` off PATH, so ecCodes can't find `eccodes.dll` and
cfgrib/Herbie fail to import. `pipeline/__init__.py` prepends that folder to PATH
on Windows, and `pipeline/__main__.py` makes stdout tolerate emoji (Herbie prints them).
Ad-hoc scripts that import eccodes/herbie should `import pipeline` first.

## Layout
- `docs/` — PLAN.md (lean plan), DESIGN.md (§6 chart/map/UI standards), specs/ (one per feature),
  BUSINESS.md and ARCHIVE.md (not read by default), plus the reference docs listed under "Project docs".
- `config/settings.yml` — region, states, windows, toggles. Prefer config over code.
- `pipeline/` — one module per source, each with `run(cfg, session, outdir) -> dict`
  registered in `pipeline/__main__.py:SOURCES`. Sources fail independently.
- `web/` — static site (Leaflet + Plotly from CDN, plain JS, no build step).
  `web/js/colors.js` holds color scales/legends (single definition of the NWS snowfall table).
- `tests/` — pytest; extend `tests/fakes.py` with canned responses for new sources.
- `pipeline/search.py` — header search index (data/search.json); `web/js/search.js` (header + shared ranking).
- `tools/browser_check.py` — headless-Chrome regression checks (basemap, fallback, layout, search, charts).
- `pipeline/archive.py` — forecast archive for verification (docs/verification.md);
  `pipeline/cache.py` — data_cache pruning at the start of every run.
- `config/models.yml` + `pipeline/models/` — model maps (see below); `web/models.html`
  + `web/js/models.js` — loop viewer.
- `.github/workflows/update-site.yml` (hourly obs + deploy) and `models.yml` (model maps, NBM points, NOHRSC
  and NDFD matrix entries).

## Conventions
- Keep fetch code separate from pure processing functions; test the pure parts.
- Write JSON via `common.write_json` (rounds floats, NaN -> null).
- US units on the site (in, °F, kt) for now. Exception (owner decision): 700 mb
  temperature is in °C (upper-air convention).
- Use a polite User-Agent (config `http.user_agent`) and few requests per run.
- Keep this file's handoff section short: when a session's work is merged, move its entry to
  `docs/ARCHIVE.md` and keep only the gotchas worth re-reading every session.

## Data licensing rules (free-first now; monetization planned, see PLAN §10 for the full table)
- OK: NOAA/NWS (NODD on AWS, api.weather.gov), USDA NRCS AWDB, IEM (states
  any lawful use incl. commercial), ECMWF open data (CC-BY-4.0, attribute).
- Synoptic API: NOT available to this project.
- Open-Meteo API: free tier is non-commercial only; NOT used in production (prototype only).
- MADIS: only distribution category 3 ("Public – full distribution") may be shown.
- Avalanche.org: show ratings unaltered, grey out expired ratings, always link
  to the center's full forecast.
- OpenStreetMap / OpenSkiMap derived data: ODbL, keep attribution.
- Ask before adding any source whose terms are unclear.

## Model maps (Phase 2; low priority, see PLAN §8; spec: docs/specs/model-maps.md)
- Flow: `fetch.py` (Herbie, `priority=["aws"]` = NODD only; one byte-range download per
  product and forecast hour; ecCodes decode cropped to the maps' lat/lon bounds) →
  `run.derive_frame` (in fhour order; QPF windows by differencing run-total APCP;
  snowfall accumulated per step) → `.npz` per frame → process pool `plot.render_task`.
- `plot.Canvas` is built once per (grid, domain) per worker: figure, basemap, and a
  precomputed pixel→grid bilinear sampling map. Shading = `map_coordinates` + `imshow`
  in the map projection; per-image artists are removed after each save. Fixed pixel
  size per domain; PNGs quantized to 128 colors.
- Output: `<out>/<model>/<YYYYMMDDHH>/<field>/<domain>/fNNN.png` + `<out>/<model>/index.json`;
  `build` merges all into `build/models/index.json` (catalog the viewer reads).
- CI: `models.yml` (cron 55 1-22/3) renders each model in a matrix job, tars
  `<model>/` to `<model>-<cycle>.tar` on the `model-maps` prerelease (race-safe create,
  deletes only that model's older assets), then dispatches `update-site.yml`, which
  downloads the newest tar per model before every build. `--published` makes runs
  with nothing new exit 0 without output.
- Adding a model: add it to `config/models.yml` (products, moisture `dpt|rh`,
  vorticity `native|compute`, levels, cycles, fhours, domains, fields), run a quick
  local render and look at every PNG, then add it to the matrix in `models.yml`.
- Known limitations / future work:
  - Kuchera Tmax and the wet-bulb-zero height use only 1000/925/850/700/500 mb (+2 m),
    so a shallow warm nose can be missed and WBZ is interpolated across ~5000-ft gaps.
    Future: pull TMP/DPT from the HRRR prs file at 25-mb spacing.
  - WBZ uses Stull (2011) Tw (fit near 1000 hPa; biased slightly warm aloft in dry
    air). WBZ is capped at the model's lowest 0 °C height (physically Tw <= T); the
    cap fixed WBZ > freezing level in NM precip on 2026-11-07.
  - Snow level shading is drawn only where WBZ is above ground; elsewhere one flat
    "at/below ground" color. Freezing-level contours use HGT:highest tropospheric
    freezing level (HRRR's lowest 0C isotherm follows valley cold pools).
  - Snowfall uses CPOFP (frozen %) at the end of each step for the whole step.
  - WBZ cross-check vs RRFS native `HGT:lowest level of the wet bulb zero`
    (gh/lowestLevelWetBulb0), RRFS 12Z 7 Nov 2026, f000–f048, western crop:
    precipitating points: computed − native median about −190 ft (per-hour −155 to −200,
    IQR about −390 to −10 ft); terrain > 5000 ft: median −180 ft but varies by time of
    day (IQR about ±600 ft); all above-ground points: about +300 ft (dry air aloft, Stull
    runs warm). At/below-ground classification agrees on 92–99.7% of points.
    The 0 °C cap barely changes RRFS (it has 925 mb heights).
  - Model-map snowfall colors still use the older NWS-style table; align them to `colors.js`
    in a future model-map session (owner decision, deferred).

## Ski areas and point forecasts (M1/M2; spec: docs/specs/data-pipeline.md)
- `python -m pipeline catalog` (on demand; needs build/data/snotel|asos.geojson from a
  `build`) → `data/ski_areas.json` (committed, ODbL) + `data/ski_areas_verify.csv`.
  Seeds: OpenSkiMap ski_areas + lifts GeoJSON (cached in data_cache/openskimap, ~140 MB).
  Base = lowest lift bottom terminal, skipping lifts that start > `transport_drop_m`
  below the lowest run (city trams/valley gondolas); summit = highest lift top
  terminal (lift-served, not hike-to). Elevations = USGS 3DEP ImageServer getSamples,
  checked against OpenSkiMap's per-vertex z (`verify`: ok | dem-only | review).
  Joins: region (config boxes), tz + NWS grid (api.weather.gov /points), avalanche
  zone (point in polygon; `zone_id` = avalanche.org feature id, now kept in
  avalanche.geojson), nearest SNOTEL/ASOS, NBM i/j + cell elevation (3DEP mean over
  the 2.5-km cell; NBM files have no terrain). Slow lookups cached in data_cache/catalog
  (3DEP ~1 s per point, cell stats ~10 s each). Fixes go in `config/ski_areas.yml`.
- `python -m pipeline points` → `build/data/points/<id>.json` + `summary.json`
  (CI: `points` entry in the models.yml matrix → `points-<cycle>.tar` on the
  model-maps release → update-site unpacks it into build/data). Code: `pipeline/nbm/`
  (inventory parse/select, fetch+decode+sample) and pure `pipeline/points.py`.
- NBM inventory: see **docs/nbm_inventory.md** (all 24 cycles, regenerate with
  `tools/nbm_inventory.py YYYYMMDD`). Layouts differ by cycle — never assume one:
  01/07/13/19Z core has ASNOW 6/24/48/72-h percentiles + exceedances, SNOWLVL and SNOWLR
  percentiles to ~f263, hourly files to f264, no qmd; 00/06/12/18Z have snowfall
  percentiles only to f048/f054 but carry qmd (QPF percentiles; day blocks vary by cycle:
  18Z f072 has only 2-3 day). Selection is rule-based (`inventory.classify/select`): only
  windows ending at the file's own hour count (later files repeat earlier windows with
  other values). Cycle order (S4): newest complete 01/07/13/19Z → previous full-suite
  (≤ 12 h old) → 00/06/12/18Z. Full-suite f264 lands ~1.7 h after init (points cron
  55 2,8,14,20); qmd lands ~7.5 h after its cycle, so liquid (QPF) percentiles come from the
  newest synoptic cycle with complete qmd (`liquid_source`, usually 7 h older; labelled
  `liquid_cycle`). Exceedance probabilities: NBM's own fields (`exceed` per point,
  `exceed_summary.json`); consistent with the percentiles (docs/nbm_prob_consistency_*.md). Missing
  messages are missing data (`required_keys` counted; fail > 20 %; summary.json `quality`).
  Percentiles match the GSL NBM 1-D viewer exactly at the nearest cell (KMLP, KSMP; see
  docs/nbm_inventory.md); its exceedance probabilities are not reproducible.
  SNOWLVL is metres MSL; SNOWLR is populated in dry hours too (valid percentiles at 99.6 % of cell-hours; zeros only in ~38 warm, low cells, Nov 17 check).
  ecCodes names these `unknown`. **core GRIB uses alternativeRowScanning** (odd rows
  stored reversed; qmd does not): index with `run.flat_index`. Check decodes against the
  NBS text bulletins (`blend.YYYYMMDD/HH/text/blend_nbstx.tHHz`: TMP, Q06, SLV).
- Methods (pure, tested): lapse 6.5 °C/km grid→point (cap 4000 ft); P(snow) = P(snow
  level < point) from p10/50/90 (det ±800 ft ramp later); 12-h day/night periods 00Z–12Z /
  12Z–00Z for temps and snow type; snow charts use 12Z–12Z days.
  **Snow ranges come only from native NBM snowfall percentile windows** (S10/dev11: 25/75 by day,
  10/50/90 for 24/48/72 h; liquid ranges from QPF percentiles). Never add, scale or interpolate percentiles
  across windows. The older 7/10-day ranges that added block percentiles rank by rank (wider than true) are
  being removed (owner decision Nov 16: show expected totals only; remove any remaining uses).
  Sanity vs NDFD: `python -m pipeline.nbm.sanity`.

## TODO / session handoff (keep current; newest state wins)
Milestones live in docs/PLAN.md §8; this list is the fine-grained handoff. Per-session history lives in docs/ARCHIVE.md.

**Current state (Nov 18 2026, dev17 run; the uncommitted dev17_report.md has the briefing)**
- main has dev13-dev16. Branch `dev17`: `alerts/hazard_text.json` (popup text for every layer alert from the one /alerts/active call; live fetch = last resort), Show-all tests,
  `decision` column in `data/rec_points_review.csv` (keep/drop/merge, applied by `catalog --rec`; never published), agreement badge now >= 80 % High / >= 66 % Medium (4 sources),
  forecast overlays (config `forecast_overlays`: enabled, stale_hours -> greyed + note, cycle/issue time), PROB palette fixed (monotone lightness).
- **Built but OFF (never enable from a dev session):** `ecmwf.enabled` (HRES line + ENS plume, `python -m pipeline ecmwf --force --out build/models`; 50 members, no control; owner wires
  `docs/workflow_snippets/ecmwf.yml`), `wind_exposure.enabled` (W7, reviewer checklist in the spec), `alerts_backend.enabled` (W6 offline skeleton + owner decisions in the spec), plus the earlier `pages`/`pwa`.
- Browser suite: `tools/browser_check.py` has 21 checks (adds showall, ensemble); `ensemble` needs ECMWF output in `build/models/ecmwf/` + `multimodel.merge` (skips with a note otherwise).
  Calibrate the badge with `node tools/agreement_calibration.js`.
- Open: W3 meta description (W2) + Low-confidence rule; `HEALTHCHECK_URL` secret; W1 then enable pwa/pages; real-device PWA tests; M9 verification when the archive grows.

**Reusable gotchas (earlier session log: docs/ARCHIVE.md)**
- Lighthouse: `PATH=/c/miniforge3/envs/tools:$PATH npx -y lighthouse@12.6.1 URL --only-categories=performance,accessibility`
  (Node lives in the `tools` conda env), against a gzip server (like Pages) of build/; the plain http.server understates
  mobile scores. Target: median of ≥ 3 interleaved runs ≥ 85. The obs map scores bimodally (71–88, tile-server timing);
  compare changes with interleaved A/B runs (dev vs main with the same data).
- Browser regression checks: `PYTHONIOENCODING=utf-8 C:/miniforge3/envs/snow-wx/python.exe tools/browser_check.py [-v] [--only ...]`
  (serves build/ itself, real headless Chrome via CDP); copy web/* to build/ first. `Page.navigate` with only a hash change does
  not reload; blocked URLs need cache off + an unvisited view. Element screenshots: CDP clip after scrollIntoView WITHOUT
  captureBeyondViewport (it resizes the viewport and Plotly re-lays out).
- `pipeline points --out` and `pipeline ndfd --out` take the points/ndfd folder itself (`build/data/points`, `build/data/ndfd`),
  never `build/data`. Cleanup deletes only files the previous run's `summary.json` lists, plus orphans that look like our own
  point files (`common.stale_point_files` / `orphan_point_files`; fresh runners have nothing to delete).
- Charts: shared theme `web/js/charts/theme.js` (always `C.plot`; summary + tableToggle + lazy). Snow charts use the `days`
  array (12Z–12Z) in the points JSON; percentiles only from one native NBM window (`points.native_window`). Colors:
  `colors.js` `SNOWFALL` (NWS table) + `snowLegendHtml`. about.html must be updated whenever methods change.
- Maps: obs-map symbols draw on one canvas (`points-canvas.js`; no marker keyboard focus: the search box is the keyboard path);
  overlays draw on a view-sized canvas (`overlays.js`), never an `L.ImageOverlay` of the whole West (GPU limit → grey map).
  USGSShadedReliefOnly has no z9 tiles (gaps at z10–11): `basemap.js snowTileLayer` fills holes from ancestor tiles. The OSM
  reference layer (`basemap-ref.js`, MapLibre vendored in web/vendor/) loads after the markers once the relief tiles are in
  (earlier loading slows the LCP tile).
- Powder Finder: keep its first paint static (buttons in the HTML, list reserves height) or Lighthouse CLS jumps.
- GitHub: no `gh` CLI here; read run status via the public REST API with `requests` (`/actions/workflows/<file>/runs`,
  release assets under `/releases/tags/model-maps`). The forecast archive never lives on the PC (`pipeline archive --local` into
  the scratchpad, then delete).
