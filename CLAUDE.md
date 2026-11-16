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
- When a milestone lands, tick it in PLAN.md §8; move finished items and stale decisions to `docs/ARCHIVE.md` so PLAN.md stays under ~15 KB.
- Keep section numbers (§) stable; cross-references rely on them.
- Keep PLAN.md §2 Status and §3 Decisions log current as work lands.
- Reference docs (read only for that topic):
  - `docs/verification.md` — forecast archive and M9 verification
  - `docs/nbm_inventory.md`, `docs/nbm_prob_consistency_*.md`, `docs/nbm_validation_gsl_*.md` — NBM GRIB layouts, exceedance-probability consistency, GSL viewer validation (NBM fetch/decode work)
  - `docs/sources_recreation.md` — Sno-Park / recreation source research and licences
- Hard rules for all code are in PLAN §0 (safety info never gated or hidden; label heuristics, never present
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
  SNOWLVL is metres MSL; SNOWLR is ~0 where no snow falls (average over snowy steps).
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
Milestones live in docs/PLAN.md §8; this list is the fine-grained handoff.

**Current state**
- Branch `dev11` (not pushed at last update). dev11 follow-up decided Nov 16, pending: drop the 7/10-day summed
  ranges (expected totals only; keep native 24/48/72 h ranges); keep the hatched grey expected bar for a
  partial first day (legend/aria say "partial day — expected amount, no range"); SNOTEL 24 h depth gains use the
  NWS colors, losses stay brown, legend titled "Snow depth change"; check the new "delete only files in the old
  summary.json" cleanup on a FRESH CI runner (stale files for areas removed from the catalog) with a test; then
  push and open a PR. Also confirm why the points data was ~a week old (NBM 19Z 8 Nov / NWS 04Z 9 Nov): cached
  local data or a stale live pipeline.
- Next (PLAN §8.2 Sprint 1): data-freshness check, W5a pipeline monitoring + data-status page, W1 hosting prep
  (brand name and domain not decided yet; use configurable SITE_ORIGIN / DATA_ORIGIN with today's GitHub URLs
  as defaults). Then W3 daily summaries (before W2: W2's meta descriptions use the summary), W2 prerendered
  pages, W4 PWA.
- Not started: storm-total tracker (PLAN §8.4 backlog), M7 precipitation by model, M8 ECMWF (IFS 0p1 / AIFS 0p25
  via Herbie `ifs`/`aifs`, IDX_STYLE eccodes; attribution "© ECMWF, CC BY 4.0" on images + page), M6 zoomable
  model layers + HRRR prs file (last, Track 3), self-hosted western-US PMTiles as an OpenFreeMap backup
  (PLAN §11.2).

**Done log (history; move to docs/ARCHIVE.md after merge)**
Done earlier (branch `dev`, merged): Phase-1 polish A1–A5; model maps HRRR/RRFS/GFS
(B6–B10) + CI. Full local runs 12Z 7 Nov: HRRR 1361 img / 114 MB / 214 s,
RRFS 1349 / 100 MB / 240 s, GFS 362 / 23 MB / 178 s (before M0 removed upper air
from HRRR/RRFS). Terrain contours roughly doubled HRRR PNG size.
- [x] M0 upper air (h500/t700) removed from HRRR/RRFS; snow-level note on maps +
      viewer caption; Actions bumped to node24 majors (checkout v7, cache v6,
      setup-micromamba v3, configure-pages v6, upload-pages-artifact v5,
      deploy-pages v5), runners pinned `ubuntu-24.04`.
- [x] M1 ski-area catalog: 161 areas, `data/ski_areas.json` (+ `_verify.csv`), map layer,
      search, area.html stub. Full run ~21 min cold (3DEP), ~7 s cached. Open items:
      Kirkwood / Olympic Valley summits unverified (see PLAN.md Status).
- [x] M2 NBM point pipeline: `pipeline/nbm/`, `pipeline/points.py`, `points` CI matrix
      entry, sanity script. Known weak spot: when NBM's deterministic QPF is ~0 but its QPF
      percentiles are not, the fallback ratio (SLR × P(snow)) can overstate trace snow
      (Mission Ridge 1.1 vs det 0.2 in).
- [x] M3 ski-area page: owner decisions applied (means for bars/totals, NBM snowfall pct
      ranges 0–48 h, extended outlook after, P(snow at elevation), local period labels).
      Lighthouse via `PATH=/c/miniforge3/envs/tools:$PATH npx -y lighthouse@12.6.1 URL
      --only-categories=performance` (Node lives in a separate `tools` conda env).
      Points files embed the area record; `avalanche_ratings.json` = zone_id → rating.
- [x] M3.5 B obs-map performance: SNOTEL/ASOS/ski symbols on one canvas
      (`web/js/points-canvas.js`, declutter cached per zoom, capture-phase hit testing so
      points win over avalanche polygons), Plotly lazy + idle prefetch. Benchmark:
      `tools/mapbench.py URL` (CDP, 4x CPU). Lighthouse obs map 46 -> 72, TBT 1270 -> 132 ms.
      Keyboard focus on individual markers is gone (search box is the keyboard path).
- [x] M3.5 C NOHRSC overlays: `python -m pipeline nohrsc` -> build/data/nohrsc/ (6 layers,
      ~0.9 MB, 25 s; CI `nohrsc` in the models.yml matrix). Layer system = `pipeline/layers.py`
      (EPSG:3857 grid, nearest regrid, 16-bit value code in R/G of an RGBA PNG, alpha =
      no data) + `web/js/overlays.js` (decode once with createImageBitmap(premultiplyAlpha:
      none, colorSpaceConversion: none), colourize with colors.js palettes, exact hover value).
      SNODAS glacier cells are capped at 32767 mm (shown as "glacier / permanent snow").
- [x] M3.5 D forecasts at every SNOTEL site + NWS official:
      `python -m pipeline catalog --snotel` -> data/snotel_points.json (NBM cell + elevation;
      new cells use a 5-point 3DEP mean, the full-cell statistics call is too slow for ~800
      cells). NBM points now include SNOTEL (`snotel-<triplet with dashes>` files).
      `python -m pipeline ndfd` samples NDFD GRIB2 (whole files from noaa-ndfd-pds
      opnl/AR.conus/VP.001-003 + VP.004-007, ~320 MB, no .idx) at all points -> build/data/ndfd/,
      same JSON shape as NBM so area.js toggles NBM <-> NWS. NDFD has snowlevel in GRIB
      (api.weather.gov not needed); snow/QPF/snowlevel only to 72 h. Values checked against
      api.weather.gov gridpoints (temps within 0.1 F, 6-h snow exact).
- [x] S3 (dev3): owner decisions 1-8 (see PLAN.md); M4 Powder Finder (`web/finder.html`,
      `web/js/finder.js`; data: points/summary.json, ndfd/summary.json, nohrsc/ski.json,
      alerts/index.json). Keep its first paint static: buttons are in the HTML and the list
      reserves height, otherwise Lighthouse CLS jumps to 0.7.
- [x] M5 part 1 alerts: `pipeline/alerts.py` is an obs SOURCE (runs in every hourly build) ->
      build/data/alerts/index.json (+ details.json). Matching needs each point's NWS forecast
      zone + county: ski areas `nws.<pt>.zone/county`, SNOTEL `nws.zone/county`
      (`python -m pipeline catalog --snotel` fetches /points). Most winter alerts have no polygon.
- [x] S4 (dev4): NBM full-suite cycle order + liquid_source, own exceedance probabilities
      (`exceed` per point incl. window `mean`; `exceed_summary.json`), decisions 2-5, A Powder
      Finder "Chance of" view (PROB palette in colors.js) + area-page exceedance chart.
- [x] S4 B: AFD = obs SOURCE `afd` (`pipeline/afd.py` -> build/data/afd/<WFO>.json + index.json; WFOs
      from catalog `nws.*.wfo`); area-page section; `web/about.html` (methods: keep it in sync
      when methods change).
- [x] S4 C ridge-top wind: `pipeline/models/ridge.py`. Model runs with `ridge: {levels: [...]}` in
      config/models.yml (HRRR 850/700/500, RRFS 850-600 every 50 mb) sample u/v/HGT at every frame
      at each ski-area summit (nearest column, linear in height, levels below model terrain skipped,
      Lambert grid winds rotated with the cone constant) -> `<model>/ridge.json` (inside the model tar);
      `build` merges HRRR (to 48 h) then RRFS (to 84 h) -> build/data/ridge.json (~60 KB). Area
      meteogram trace + note; Powder Finder "Ridge" column (max in the window; lazy-loaded).
      (Since dev10 ridge wind is off forecast pages and the Finder; ridge.json is still built.)
- [x] S5 (dev5): M9-prep archive + data_cache pruning, bugs B1-B7 (PLAN.md §8 M3.6), §6-B chart overhaul
      (shared web/js/charts/theme.js, heat table, lazy charts below the fold). M4.5 Sno-Parks followed in dev8.
- [x] S5 item 1 (M9-prep): forecast archive -> docs/verification.md. `python -m pipeline archive
      --data build/data [--local DIR]` (CI: update-site.yml step, gh release "verification"; use
      --local into the scratchpad for dry runs and delete the output: the archive never lives on the
      PC). Every run prunes data_cache > 2 days (`pipeline/cache.py`; keeps catalog/, openskimap/).
- [x] S5 items 2-3: bugs B1-B7 + §6-B chart rework. Charts use `web/js/charts/theme.js` (SnowCharts: local-time
      axes via wall-clock strings, Okabe-Ito, axis titles as top-left annotations, summary() + tableToggle(),
      heatTable(), lazy(); always C.plot so the container gets an explicit height). Base maps: `web/js/basemap.js`.
      Lighthouse: scratchpad lh_all.sh pattern (perf + a11y, 6 pages). Element screenshots: CDP clip after
      scrollIntoView WITHOUT captureBeyondViewport (that resizes the viewport and Plotly re-lays out).
- [x] Archive live: PR #6 merged, verification release has nbm/ndfd/snotel-202611.csv.gz.
- [x] S6 Part A (dev6): fixes 1-9 from the dev5 live review (PLAN.md §8 M3.6). Browser regression checks:
      `C:/miniforge3/envs/snow-wx/python.exe tools/browser_check.py [-v] [--only basemap,fallback,layout,search,charts]`
      (serves build/ itself, real headless Chrome via CDP; `SNOWWX_BROWSER=1 pytest` runs them too). Copy web/* to
      build/ first. Notes: Page.navigate with only a hash change does not reload (open() goes via about:blank);
      blocked URLs need cache off + an unvisited view. Overlays draw on a view-sized canvas (overlays.js ViewOverlay),
      never an L.ImageOverlay of the whole West (GPU limit -> grey map). Document pages: body.doc-page.
- [x] S7 (dev7): "Expected" rename (colors.js EXPECTED_TIP / expectedInfo()); hour-by-hour temp + wind to day 10
      (area.js detailWindow/extendedShade); docs/sources_recreation.md written; M4.5 build waited for owner approval.
- [x] (done S7) rename "most likely" -> "Expected" site-wide (area tiles, day/night bars + hovers,
      Powder Finder amount + chance modes, legend notes, headline, about.html) with an ⓘ tooltip: "NBM's average
      amount; it typically has about a 1-in-3 chance of being reached" (link about.html#nbm). Owner decision S6.
- [x] (done S7) area page "Hour by hour" — extend temperature + wind panels to day 10 with NBM 3/6-hourly values,
      lightly shaded and labelled "extended (6-hourly)"; hourly detail stays ~3.5 days; snow stays as
      day/night bars beyond 3.5 days (owner decision S5-2; superseded for snow by the dev11 "Snowfall by day" bars).
- [x] (S7) M4.5 Sno-Parks research: sources + licences first (USFS EDW, state Sno-Park lists, OSM gap-fill;
      public-domain, key-free preferred), write docs/sources_recreation.md, ask the owner to approve BEFORE
      building (owner decision S5-3). RIDB only if asked (key = Actions secret). NBM cell elev = full 3DEP mean.
- [x] S8 (dev8): M4.5 Sno-Parks built (`catalog --rec` -> data/rec_points.json; kind "snopark", base = trailhead,
      summit = high terrain; `common.forecast_areas()` = ski areas + Sno-Parks for every point product). Obs map perf
      pass (map_points.json, vendored Leaflet, parallel loads). Lighthouse realistic numbers: serve build/ with gzip
      (scratchpad gzserve.py pattern); the plain http.server has no gzip and understates mobile scores.
- [x] (done S8) build M4.5 Sno-Parks per PLAN.md §5.6 with the APPROVED sources (S7): USFS EDW backbone
      (EDW_RecInfraRecreationSites_02 layer 0: SNOWPARK, SNOWPLAY AREA, SKI AREA NORDIC, winter TRAILHEADs) + OSM
      gap-fill (ODbL, dedupe ~400 m); state lists = manual cross-check only. See docs/sources_recreation.md.
- [x] S8 follow-up (owner decisions 2-5): Sno-Park facts only as stated by the source (rec.activities/permit_for);
      no permit -> "Parking permits may be required — check <permit_check link>" (state program, else agency page,
      else fs.usda.gov); "NWS alerts not available" when a site has no NWS grid point. Finder default stays Ski areas.
- [x] S9 (dev9): NBM forecast overlays (pipeline/nbm/layers.py in the points job -> data/points/layers/; overlays.js
      loads Observed + Forecast indexes) and "My mountains" (mine.html, js/mine.js; favorites in localStorage
      "snowwx.favorites"). Browser checks: forecast, mine. Follow-up (owner S9): landing banner on the obs map
      for visitors with favorites (app.js homeBanner; pref localStorage "snowwx.home" = "mine", toggle on mine.html),
      forecast-overlay grid note, "Send feedback" mailto in every footer.
- [x] S10 (dev10): ridge wind off forecast pages; SNOTEL panel overlap fix; snow redesign (NBM 25/75 snowfall + SNOWLR
      10/90 selected, SELECTION_VERSION 6; periods snow_q1/q3 + snow_type; totals 48h + q1/q3; summary window[5] = main
      snow type; area.js periodChart range bars, accumChart, slrChart + strip). Points fetch ~+60 % (391 s local).
      Basemap (owner picked design 3): shaded relief + "Roads, towns & peaks" reference layer = js/basemap-ref.js
      (OpenFreeMap vector tiles, MapLibre GL 4.7.1 + maplibre-gl-leaflet 0.0.22 vendored in web/vendor/, pane
      "reference" z 250, hidden on Topo/Imagery). Loads right after the markers (app.js calls basemaps.loadReference()),
      once the visible relief tiles are in and the browser is idle, 2 s cap (owner S10; starting it before the relief
      tiles finish slows the LCP tile: obs map 71-76 vs 86-87). USGSShadedReliefOnly has NO z9 tiles
      (gaps at z10-11 too): basemap.js `snowTileLayer` fills holes from ancestor tiles. OpenTopoMap removed; marker
      halos; compact map credits under 600 px (tap to expand).
      Follow-up: Powder Finder Ridge column removed (ridge.json still built, shown nowhere); about.html ridge section
      removed. dev10 pushed.
- [x] S11 (dev11, not pushed): snow charts on NATIVE NBM percentile windows only (never add percentiles).
      points JSON `days` (12Z-12Z; nbm/run.py + ndfd.py): snow_in (sum of 6-h det windows), snow_p25/p50/p75 from the
      one native window that exactly covers the day (snow24, or snow6 for a 6-h first day; P.native_window), else
      None (01Z/19Z first day is 11-17 h: no range). area.js periodChart = "Snowfall by day" (p25-p75 bars coloured by
      p50, "low–high″" labels, muted < 0.5 in, hatched expected when no native window); accumChart = expected running
      total by day ending at the 10-day total's horizon. 12-h `periods` stay (temps, snow type, mine.js, Finder).
      colors.js SNOWFALL = NWS snowfall table (NOHRSC legend, 0/T/0.1/1/2/3/4/6/8/12/18/24/30/36/48/60/72/96/120+),
      snowLegendHtml() + snowPale() shared by area, overlays, Finder. `points --out` / `ndfd --out` = the points
      folder itself (build/data/points, build/data/ndfd); cleanup now only deletes files listed in its old summary.json.
