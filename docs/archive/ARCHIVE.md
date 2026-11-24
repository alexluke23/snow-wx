---
status: reference
owner: team
last_reviewed: 2026-11-23
read_when: only when a task asks for history
---

# Snow-Wx — Archive (history; not read by default)

> Completed work and older decisions moved out of `PLAN.md` to keep it lean. Read only when you need history.

---

## A. Decisions log, Nov 6–8 2026

| Date | Decision |
|---|---|
| Nov 6 | Public site → only sources whose terms allow public display and reuse (licence table: PLAN §10). |
| Nov 6 | No Synoptic. Obs from NRCS AWDB, IEM, avalanche.org. |
| Nov 6 | Stack: Python pipeline on GitHub Actions → static site. Dev in VS Code + Claude Code; env `C:/miniforge3/envs/snow-wx`. |
| Nov 7 | Model images stored as GitHub Release assets; site pulls newest per model; 900 MB guard. |
| Nov 7 | Snow level (model maps) = wet-bulb 0 °C height, capped at lowest 0 °C height; free-atmosphere freezing level dashed. |
| Nov 7 | 700 mb temperature in °C; surface °F / in / mph or kt (see §6). |
| Nov 7 | **Product focus: ski-area point forecasts (western US first).** |
| Nov 7 | **Remove upper-air fields (500 mb, 700 mb) from HRRR and RRFS. Keep them for GFS (and ECMWF later).** |
| Nov 7 | **Model maps must be zoomable** → interactive data layers for surface fields (§5.4). |
| Nov 7 | **NBM is the primary point-forecast engine; NDFD shown as the NWS official forecast alongside it.** *Superseded Nov 21 (dev22): the site shows NBM only; NDFD is still fetched and archived for verification.* |
| Nov 7 (S2) | Day/night = 12Z–00Z periods, labeled in local time. |
| Nov 7 (S2) | Snowfall: NBM snowfall percentiles 0–48 h; beyond 48 h QPF pct × SLR × P(snow), styled "extended outlook". |
| Nov 7 (S2) | Bars/headline/totals use NBM deterministic (mean) so bars sum to totals; percentiles only as 10–90% ranges; zero snow when QPF < 0.01". |
| Nov 7 (S2) | Point snow scaled by P(snow level below point elevation); "mostly rain"/"mixed" labels. |
| Nov 7 (S2) | NBM points 4×/day; Plotly kept but loaded after HTML headline; merge Snoqualmie summits, Alpental separate. |
| Nov 7 (S2) | NBM + NDFD forecasts for all SNOTEL sites; NDFD sampled from GRIB2 on AWS (api.weather.gov only for alerts/AFD/missing elements). |
| Nov 7 (S2) | NOHRSC overlays on obs map (SNODAS SWE, depth, 24 h SWE change; gridded snowfall 24/48/72 h); builds the interactive-layer system (§5.4). |
| Nov 7 (S2) | Obs map performance work (canvas rendering, lazy charts). |
| Nov 8 | dev4 verified on GitHub: Model maps #8 all green; RRFS job 3 m 50 s with ridge wind — no runtime concern. |
| Nov 8 | Forecast archive stores **all daily leads** (every 24 h window ending 12Z days 1–10 + every 72 h window; det/p10/p50/p90/P(≥4/8/12"); plus NDFD). Release assets only — never on the owner's PC or in git history. |
| Nov 8 | **Chart readability is a priority;** §6-B standards apply site-wide. |
| Nov 8 | **Basemaps must never go blank** — overzoom + fallback provider (§6-C). |
| Nov 8 | **Add Sno-Parks / winter recreation points** as a point type (§5.6, M4.5). |
| Nov 8 | Keep local disk small: auto-prune `data_cache` (> 2 days); report disk use in summaries. |
| Nov 8 | Priority: Obs map + per-site Forecast pages first; model maps last (models.html on low maintenance). Model pipeline keeps running — it feeds point products. |
| Nov 8 | Consumer snow-forecast map (NBM expected snowfall + chance-of) lives on the Obs map as overlays, not on models.html. |

---

## B. Completed milestones (as of Nov 8 2026)

M0 Housekeeping · M1 Ski-area catalog · M2 NBM point pipeline · M3 Ski-area page v1 · M3.5 Snowpack overlays/SNOTEL forecasts/speed · M3.6 Chart readability, accessibility & basemap reliability (bugs B1–B7 resolved) · M4 Powder Finder · M5 NWS official · M9-prep Forecast archive · dev6 fixes · dev7 (Expected rename, day-10 temp/wind panels, Sno-Park research).

Acceptance criteria for these live in git history and the original v0.6 plan (superseded).

---

## C. Original M-numbered roadmap notes

Track 1/2/3 ordering from Nov 8(b) was merged into PLAN.md §8 (sprint table + backlog).


---

## dev11 (Nov 9–16 2026): snow charts on native NBM windows, NWS colors (moved from PLAN.md §2 and the CLAUDE.md log)

- Finding: the old day/night ranges added two 6 h percentile windows per 12 h period (NBM has no 12 h snowfall
  percentiles). Replaced by "Snowfall by day" (12Z–12Z) from native 24 h p25/p50/p75 (`days` in the points JSON).
- Accumulated snow = expected running total by day, ending at the 10-day total horizon.
- NWS snowfall color table in `colors.js` (`SNOWFALL`, `snowLegendHtml`, `snowPale`); about.html sections added.
- points/ndfd cleanup only deletes files a previous run wrote (a mistaken `--out build/data` had deleted site data).
- Previous PLAN.md §2 status (Nov 8): M0–M5, M3.5, M3.6, M9-prep done; obs-map Lighthouse mobile 47–71 (now 85);
  M4.5 Sno-Parks approved, not built (built in dev8: USFS EDW + OSM, ~450 points).
- Finished milestone moved out of PLAN §8.3: **M4.5 Sno-Parks** (done dev8; catalog `catalog --rec`).


### Long-form text moved out of PLAN.md on Nov 16 (to keep PLAN.md under ~15 KB)

#### PLAN §1 Principles & audience (full text, until Nov 16)

## 1. Principles & audience

### Principles

1. **Trust first.** Show uncertainty, issue times and sources; publish our misses.
2. **Safety information is always shown:** avalanche danger, NWS alerts, snow
   level/rain-at-base, data freshness. These are never gated or hidden.
3. **Web/PWA first.** No native apps.
4. **License-clean open data only** (§10).
5. **Automate.** Pipeline + rules engine, not human writers.

### Users
Skiers/riders (headline numbers, day/night snow, powder quality), backcountry
users (avalanche danger, wind, snow level), **snowmobile / Nordic / snowshoe /
sledding users** (Sno-Parks), meteorologists (models, percentiles, method, verification).

---

#### PLAN §11 (long form, until Nov 16)

## 11. Known limitations & open questions

### 11.1 Limitations
- Kuchera/snow level from 5 pressure levels; Stull wet-bulb warm bias in dry air.
- NBM 2.5 km grid under-resolves narrow ridges/valleys → elevation adjustment is
  approximate; verification (M9) will quantify.
- Raw model snowfall products differ → compare in liquid equivalent (§5.5).
- Model-agreement thresholds and summary rules are heuristics until verified.
- GitHub cron reliability for hourly runs.

### 11.2 Owner decisions
Tracked privately (business planning is not part of this repo).

#### PLAN §3 Nov 15 rows (technical, long wording, until Nov 16)

| Nov 15 | **Adopt:** Daily Snow summaries (W3), offline-first PWA (W4), multi-model comparison incl. ECMWF (M7/M8). **Reshape** wind-loading (§5.9). **Open-Meteo API not used in production** (free tier is non-commercial only; PLAN §10). |
| Nov 15 | **Move to a custom domain + Cloudflare Pages (site) + R2 (frequently-updated data)** (W1; domain set by owner at W1). GitHub Pages stays as a redirect/canonical stub. Reason: installed PWAs and SEO are tied to the origin, and Pages file-count limits may bite the model-map frames. |
| Nov 15 | **Path-based, prerendered area URLs** (`/ski/<state>/<id>/`), not hash routing, so ~600 pages are indexable (W2). Old `#id` links redirect. |
| Nov 15 | **Offline cache of the last-fetched forecast is always available.** It builds trust and iOS push needs the install anyway. |
| Nov 15 | **No numeric "lee-aspect accumulation adjustment" until verified** (M9). Wind is shown as an informational flag, never as an avalanche rating. |
| Nov 15 | **Alerts: email + web push first; SMS is an optional later add-on** (carrier fees + registration + TCPA overhead; its advantage is working on weak signal). |
| Nov 15 | Models compared primarily in **liquid-equivalent (SWE/QPF)**, with an inches toggle using the NBM SLR — apples-to-apples across models. |

#### PLAN §8.3 W1-W7 and M4.5 (long form, until Nov 16)

**W1 — Domain & hosting migration** — ✅ when: custom domain serves the site from
Cloudflare Pages with data from R2; ≤ 20,000 files and no file > 25 MiB per
deployment; old GitHub Pages URL redirects/canonicalizes; Lighthouse scores not
worse; rollback plan written.

**W2 — Indexable pages & share cards** — ✅ when: ≥ 161 area pages return
server-rendered title/description/summary without JS; sitemap submitted;
`#id` links redirect; OG cards render in a share debugger for top 60 areas.

**W3 — Daily Snow summaries** — ✅ when: every area/Sno-Park has a summary in
`points/<id>.json`; rules covered by fixture tests; summary appears on area cards,
Finder rows and meta descriptions; weekly review process documented.

**W4 — Offline-first PWA** — ✅ when: §5.8 acceptance tests pass on a real iPhone
and Android phone; staleness banners verified; install analytics event fires.

**W5 — Analytics, feedback & monitoring** — ✅ when: cookieless analytics with
custom events (favorite added, install, signup, alert created, outbound
avalanche-center click, "view as table"); feedback/"report a bust" link live;
pipeline-failure notifications tested; public data-status page live.

**W6 — Alerts backend (free preset first)** — ✅ when: double opt-in works;
unsubscribe one-click; an alert for a test threshold arrives by email and push
within one points-run; rate limits verified.

**W7 ◇ — Wind-exposure flag** — ✅ when: flag + disclaimer + avalanche-center link
render for 5 test cases; reviewed by an avalanche-literate person before launch.

#### PLAN §7 schedule/repo/size notes (long form, until Nov 16)

- Schedules are best-effort on GitHub. If gaps persist, add an external trigger
  (cron service calling `workflow_dispatch` with a fine-grained token) — owner
  decision.
- Size budget: points ≈ 600 pages/areas × ≤ 150 KB ≈ 90 MB in R2 (not in the
  site bundle).


---

## CLAUDE.md done log, moved Nov 16 2026 (sessions up to dev11)

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


---

## CLAUDE.md current-state log as of the Nov 17 overnight run (moved out of CLAUDE.md)

**Current state (Nov 17 2026, overnight run: fix-snotel finished, dev13 in progress; see the uncommitted dev13_report.md)**
- dev13 item 3 done: NBM-native P(>=2") row in the area heat table + Finder chips for 24/48 h (none for 72 h, never derived).
- dev13 item 4 done: one snow-ratio + powder-quality panel (Dense<10/Medium 10-15/Blower>=15 heuristic bands, wind marker); strip removed.
- dev13 item 1 done: Finder state/region menus are linked with counts (disabled when empty), regions N->S, sort direction button + hash `dir`.
- dev13 item 2 done: obs-map layer defaults/memory/`ly=` hash/Reset; NWS winter hazards layer (hazards.js + pipeline/hazards.py -> data/hazards.json; live official WWA polygons, fallback to alerts index, config hazards.enabled); red alert rings removed.
- dev13 B1 (W3) partly done: pipeline/summary.py + config/summary_rules.yml + tests; `summary` in points JSON; area-card display. TODO: Finder rows, My mountains, meta description/OG, alert rule (needs summaries after alerts).
- Branch `dev11` is pushed; the owner opens the PR (no `gh` CLI or token here; branches have no CI, only main/schedule run
  the workflows). Contents: snow charts on native NBM windows ("Snowfall by day" p25–p75 bars, expected running total), NWS
  snowfall colors site-wide (colors.js), no 7/10-day ranges (expected total only), **no composite ranges anywhere** (points
  JSON `totals[...].native`, summary window `[6]`; front end shows a range only when native), partial-day labelling, SNOTEL
  depth-change colors, strict points/ndfd cleanup (tests prove `points/layers/` and `ndfd/` are never touched).
- Archive (docs/verification.md): `nbm_rows` builds det from the 12 h periods and p10/p50/p90 + P(≥X) from the native
  `exceed` windows (24/48/72 h ending 12Z); it never reads `totals` ranges, so composite ranges are not in the monthly CSVs
  (test `test_archive_rows_never_contain_composite_totals_ranges`). M9 needs no exclusion beyond that.
- **NRCS AWDB (SNOTEL) outage since Nov 16 (upstream; whole host returns 502).** Branch `fix-snotel` handles it: fail-fast
  probe (a down run costs ~2 s), last good copy ≤ 48 h flagged stale then "unavailable", auto-recovery, per-source history in
  meta.json, status wording in `web/js/snotel-status.js`, PR workflow `.github/workflows/tests.yml`. Owner decisions Nov 17
  implemented: previous copy restored from the live site (`pipeline restore`, `SITE_ORIGIN`/`site.origin`, W1 checklist in
  docs/specs/hosting-seo.md), 24/72 h changes hidden when older than their window, per-source data-health issues
  (`pipeline/monitor.py`, config `monitoring`, `monitor` job after the deploy; check `gh`-created issues are assigned and
  e-mails reach the owner after the first failure). Open: independent "workflow did not run" check (spec 5.2c, heartbeat
  service recommended, needs the owner's account/secret).
- Next (PLAN §8.2 Sprint 1): SNOTEL fix + W5a pipeline monitoring and data-status page, W1 hosting prep (domain set by owner at W1;
  configurable SITE_ORIGIN / DATA_ORIGIN, GitHub URLs as defaults), then W3 daily summaries (before W2), W2, W4.
- Not started: storm-total tracker (PLAN §8.4), M7, M8 (ECMWF via Herbie `ifs`/`aifs`, attribution "© ECMWF, CC BY 4.0"),
  M6, model-map NWS colors (§8.4), self-hosted PMTiles backup (§8.4).


---

## PLAN §3 row moved out of PLAN.md (dev16)

| Nov 17 | **dev13 UX package (overnight, assumptions flagged in the session report):** NBM-native P(≥2″) row for 24/48 h only (never derived); one combined snow-ratio + powder-quality panel; linked Finder state/region menus with counts; obs-map defaults (reference layer, ski areas, Sno-Parks, avalanche, **NWS winter hazards** ON; SNOTEL/ASOS/NOHRSC OFF, remembered, URL `ly=` overrides, Reset button), red alert rings removed; hazards from NOAA/NWS WWA map service with a visible fallback to our alerts index; config `hazards.enabled`. |


## Moved from PLAN §3 (dev17 trim)

| Nov 17 | **dev13 UX package** (NBM-native P(≥2″), combined snow-ratio/powder panel, linked Finder menus, obs-map layer defaults + NWS hazards layer): details in `docs/ARCHIVE.md`. |
| Nov 17 | **SNOTEL outage handling accepted:** previous good copy from the live site (option A, `SITE_ORIGIN`/`site.origin`, on the W1 cutover checklist); stale ≤ 48 h with original timestamps (never re-stamped), 24/72 h changes hidden when older than their window; data-health GitHub issues per source with limits from each source's real cadence (config `monitoring`), assigned to the owner, monitor can never fail the deploy. Independent "workflow did not run" check proposed in `docs/specs/data-pipeline.md` 5.2c (heartbeat service recommended). |
| Nov 17 | **Owner feedback (live review) → dev14:** the **default uncertainty range for snowfall, snow level and snow ratio is 25–75% ("likely", the middle half of NBM's outcomes)**; 10–90% is kept only where explicitly noted (Finder/W3 chance fields, M9 archive). Inline text says "likely X–Y in" with no "NBM 10–90%" label (source and issue time stay in run lines and captions). **One powder-quality definition** (config `powder_quality`: Dense < 10:1, Blower ≥ 15:1). Obs map first-load layers: relief + roads + ski areas + NWS winter hazards only; avalanche, Sno-Parks, SNOTEL, ASOS, NOHRSC off. W3 "Dry stretch" outranks "Wind-affected"; alert tag computed client-side from alerts/index.json. Obs-map Lighthouse target: no worse than main (≈ 82). |


## Moved from PLAN §3 / §2 on Nov 19 2026 (dev18)

Decision rows (dev15–dev17):

| Nov 17 | **Monitor bootstrap (dev15):** a failing/stale/unavailable source is judged by the data's own age, last success and `outage_since`, not only the restarted failure counter; one decision log line per source. |
| Nov 17 | **dev16:** hazard popups show the NWS product text in-page (never an api.weather.gov link; untrusted text escaped); M7 precipitation by model built (agreement badge = documented heuristic); M9 scorer excludes the SNOTEL outage window and stale obs. |
| Nov 18 | **dev17:** ECMWF (HRES line + IFS ENS plume, 50 members: the mirror has no control) built behind `ecmwf.enabled=false`; W7 wind flag (`wind_exposure.enabled=false`, reviewer checklist in the spec) and W6 alerts skeleton (`alerts_backend.enabled=false`) are offline-built only: **never enable without the owner/reviewer**; agreement badge now ≥ 80 % High / ≥ 66 % Medium (4 sources). |

Former §2 "Known issues" text: NRCS AWDB (SNOTEL) outage over. Last good run before it ≈ 11:25 UTC Nov 16; first failing run seen 22:07 UTC Nov 16; still down 02:21 UTC Nov 17. Recovery time was unconfirmed;
first confirmed live 00:45Z Nov 18 (owner checked the Actions logs). The archive's 821 stations at 2026-11-17 12Z may be carried-forward data. No Data-health issue was opened: the monitor (merged 13:26 UTC Nov 17) probably
started after recovery, or history was lost; dev15 hardened the bootstrap. Handling: probe, last good copy <= 48 h flagged stale, auto-recovery.

---

## Moved on Nov 23 2026 (docs reorganisation, branch `docs/reorg-2026-11`)

Text moved out of `docs/PLAN.md` v1.1 and `CLAUDE.md` when they were slimmed. Kept word for word for history; current state is in `docs/STATUS.md`, decisions in `docs/DECISIONS.md`, work in `docs/BACKLOG.md`.

### PLAN v1.1 §2 Status (as of Nov 21 2026) (Nov 21 2026, through dev22; dev23 in progress)

- **Live:** https://alexluke23.github.io/snow-wx/ — repo `alexluke23/snow-wx` (custom domain: W1).
- **Done:** M0–M5, M3.5, M3.6, M4.5 Sno-Parks, M9-prep archive (running), "My mountains", NBM forecast overlays, dev10 basemap, **dev11–dev14** ("likely" p25–p75 wording, one powder-quality definition, W3, status page),
  **dev15/16** (monitor bootstrap, W4 PWA built but off, storm totals, hazard text, M7 precipitation by model, M9 scorer), **dev17** (merged: `hazard_text.json`, ECMWF built, W7/W6 skeletons built but off, overlay stale/flag),
  **dev18** (merged): **ECMWF live** (standalone `ecmwf.yml`, monitored source, member count read from the data), models-page layout shift fixed (fixture frames), agreement badge "Little precipitation expected" + day-type calibration,
  webcam LINKS (60 areas), Sources / disclaimer / privacy / terms drafts, cookieless analytics (off), `linkcheck`, `404.html`, draft Cloudflare `_headers` + CSP check, verification UI (behind `verification_ui.enabled=false`). Details: `docs/ARCHIVE.md`.
  **dev19** (merged): **ECMWF fetch resilience** (shared `pipeline/fetch_resilient.py`: backoff + jitter, Retry-After, mirror failover AWS regional -> Google -> ECMWF portal, graceful degradation with `steps_missing`, per-cycle resume cache restored/saved by `ecmwf.yml`, fetch health on the status page), webcam link corrections + dead-link removal,
  **Plotly self-hosted** (`web/vendor/plotly-2.35.2/`; no third-party script host left in the browser), hazard popups served only from our own files (the browser-side api.weather.gov fetch is gone; the pipeline fills missing alert texts).
  **dev20** (merged): ECMWF mirror preference + 2-cycle cache bound; browser suite ~32 -> ~5 min (parallel isolated workers, frozen inputs, `--quick`); share cards (`pipeline og`, OFF);
  **ECMWF AIFS line** (on, experimental, out of the badge); `docs/STATE_SNAPSHOT.md` (owner notes).
  **dev21** (merged, PR #30): **verification scores in CI** (`verify.yml`, daily; panel still behind its flag; minima projected ~Nov 30), **NOAA GEFS plume live** (`gefs.yml`), Safari/iPhone guards,
  model chips, alert-banner CLS fix, WebKit/Firefox smoke suite (`tools/xbrowser_smoke.py`), `pipeline archive-check`.
  **scrub-business** (branch): business planning moved out of the repo (local, gitignored `private/`); guard test `tests/test_no_business_content.py`.
  **dev22** (merged, PR #32): NBM only (NWS official toggle removed), lean chart modules + About "Reading the charts", snow-ratio chart redesign (drawn only where precipitation is likely), ECMWF freshness states (latest / late / out of date) + per-cycle attempt log + hourly attempts, M11 ML snow-ratio research (`docs/specs/snow-ratio-ml.md`, `tools/slr_baseline.py`).
  **dev23** (branch): reliability round: tests find a working bash on Windows (`tests/_shell.py`) + `.gitattributes` (LF); NBM snow-ratio percentiles (`slr_p25/p50/p75`) added to the forecast archive (M11 prep); verification panel is NBM only; NDFD files no longer deployed (`update-site.yml`, one step); **external scheduler built, not deployed** (`infra/scheduler/`, Cloudflare Worker); W1 staging prep (`pipeline r2-plan`, config-driven stub target, root-base browser check).
- **Product:** obs map (SNOTEL 836, ASOS 544, avalanche, NOHRSC + NBM overlays); ~607 forecast points (ski areas, Sno-Parks) + 837 SNOTEL sites, NBM to day 10–11, NDFD, alerts, AFDs; Powder Finder; model maps on `models.yml`.
- **Known issues:** the NRCS AWDB (SNOTEL) outage of Nov 16–18 is over (first confirmed live 00:45Z Nov 18); **M9 excludes SNOTEL obs from 2026-11-16 12Z through 2026-11-18 00:45Z** (`config/settings.yml`
  `verification.snotel_outage`). Obs map Lighthouse mobile 71–91 (bimodal; compare with interleaved runs, median of ≥ 3 ≥ 85); site ≈ 220 MB / 5.7 k files.

### PLAN v1.1 §8.2 sprint table (before the Nov 23 re-plan) — Nov 16 2026 → Feb 15 2027 (engineering)

**◇ = drop first if behind.** Peak-traffic windows: Thanksgiving (Nov 26), holidays (Dec 24–Jan 2), Presidents' Day weekend
(Feb 13–15). **Deploy freeze Dec 23–Jan 2** (fixes only). Owner-side tasks are tracked privately.

| Sprint | Dates | Dev (Claude Code) |
|---|---|---|
| **S1 Foundations** | Nov 16–29 | **W1** domain + Cloudflare Pages + R2 + redirect stub (domain set by owner at W1; check file-count/size; parity test). **W5a** cookieless analytics + pipeline-failure alerts. Refresh §2 status. |
| **S2 Indexable + summaries** | Nov 30–Dec 13 | **W2** prerendered area pages, sitemap, canonical, OG cards (top 60). **W3** Daily Snow summaries v1 + tests. |
| **S3 PWA** | Dec 14–27 | **W4** PWA (manifest, SW, offline favorites, staleness, install coach, "My mountains" start page). **M4.5** Sno-Parks (if not done) on the new URL scheme. ◇ obs-map performance pass. |
| **S4 Multi-model** | Dec 28–Jan 10 | **M7** HRRR/RRFS/GFS/NBM plumes + model-agreement badge. **M8-lite** ECMWF IFS point sampling + attribution. **Verification panel v0** (~7 weeks of archive). |
| **S5 Free alerts** | Jan 11–24 | **W6** alerts backend: magic-link accounts, free preset email alert, web push for installed PWAs. ◇ storm-total tracker. |
| **S6** | Jan 25–Feb 7 | Scope set by owner. ◇ **W7** wind-exposure flag (informational). |
| **Wrap** | Feb 8–15 | Stabilize for Presidents' Day weekend; no risky deploys. |

**If behind, cut in this order:** W7 → storm-total tracker → obs-map perf pass →
M8-lite → W6 (shift alerts to the off-season). **Never cut:** W1, W2, W3, W4,
analytics, pipeline monitoring.


### PLAN v1.1 §8.4 Backlog (dev18 reconciliation) — reconciled with the code (dev18, Nov 19 2026)

Key: ✅ built and live · ⏸ built, behind a flag or waiting on the owner · ◐ partly built · ○ open. (dev17 found the NBM overlays already existed: this table is the audit.)

| Item | State | What the code has / what is missing |
|---|---|---|
| Storm-total tracker (SNOTEL 24/48/72 h/7 d, NOHRSC) | ✅ | dev15: area page + map variables |
| NBM forecast overlays on the obs map | ✅ | `overlays.js`, 9 layers, stale-grey, `forecast_overlays.enabled` (dev17 audit) |
| Powder-quality surfaces / Daily Snow summaries (W3) | ✅ | dev14; open: "Low confidence" rule, meta description (needs W2) |
| "My mountains" refinements | ○ | page exists (`mine.html`); no refinement was ever specified: drop unless the owner lists some |
| Mobile performance pass (obs map) | ◐ | canvas symbols, deferred OSM reference layer, preconnect, tile fallback done; Lighthouse mobile 71–91 (bimodal); remaining ideas: smaller first payload |
| Webcams (links only) | ◐ | dev18 Part 1 (`config/webcams.yml` + area-page row); embeds stay out |
| Resort-reported snowfall | ○ | licensing research only (`docs/sources_resort_snowfall.md`); build waits for a written answer |
| Obs time slider (24–72 h) | ○ | not started |
| Slope-angle / aspect layer (3DEP) | ○ | not started (W7 flag uses model wind, not terrain aspect) |
| More observation networks (MADIS cat. 3, RWIS, center telemetry) | ○ | research licences first; **ask before building** |
| Model-map snowfall colors → NWS table | ○ | owner deferred (low priority; model maps use their own table) |
| PMTiles backup of the OSM reference layer | ○ | not started |
| W2 prerendered pages + sitemap/robots | ⏸ | `pipeline/pages.py`, `pages.enabled=false`; not wired into update-site; OG cards not built |
| W4 PWA | ⏸ | `pwa.enabled=false` until the W1 domain; real-device tests open |
| W5 analytics | ◐ | status page, feedback links, monitor issues ✅; cookieless analytics: dev18 Part 2c (provider chosen by the owner) |
| W6 alerts backend | ⏸ | offline skeleton + tests (`alerts_backend.enabled=false`); 10 owner decisions in the spec |
| W7 wind-exposure flag | ⏸ | built, `wind_exposure.enabled=false`; needs the reviewer checklist |
| M7/M8 multi-model + ECMWF | ✅ | HRES line + ENS plume; **live since dev18** (`ecmwf.yml`); NOAA GEFS plume ✅ live from dev21 (`gefs.yml`, `gefs.enabled=true`) |
| M9 verification | ◐ | archive running, scorer built (`pipeline verify`), **daily CI scores from dev21** (`verify.yml` -> `models/verify/`), UI behind `verification_ui.enabled=false`; minima ~Nov 30 |
| M6 interactive model layers + HRRR pressure levels | ○ | last |

### CLAUDE.md "Model maps" (Phase 2; low priority, see PLAN §8; spec: now `docs/specs/retired/model-maps.md`)
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

### CLAUDE.md "Ski areas and point forecasts" (full text before Nov 23) (M1/M2; spec: docs/specs/data-pipeline.md)
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

### CLAUDE.md "TODO / session handoff" (as of Nov 21 2026) (keep current; newest state wins)
Milestones live in docs/PLAN.md §8; this list is the fine-grained handoff. Per-session history lives in docs/ARCHIVE.md.

**Current state (Nov 21 2026: main has dev13-dev22; branch dev23 in progress; owner summary: docs/STATE_SNAPSHOT.md)**
- **dev23 (branch):** `tests/_shell.py` finds a bash that really runs (the WSL stub in System32 does not): workflow-snippet tests use it and skip, never fail; `.gitattributes` forces LF. Archive NBM files have 3 new columns `slr_p25/p50/p75` (`archive.NBM_COLS`; NDFD keeps `FORECAST_COLS`; old files load everywhere as blanks; `archive-check` accepts both headers and prints the fill rate). Verification payload (`verification.json`, `verification/<site>.json`, `run.json`) is NBM only (`verify.public_docs`). `update-site.yml` has one extra step that deletes `build/data/ndfd` after the archive step (the NDFD fetch and archive are unchanged; guards `tests/test_ndfd_not_deployed.py`, browser check `nondfd`). `pipeline r2-plan` prints an R2 sync plan (never uploads; `r2.enabled` false); `pipeline stub` reads `site.stub_target_origin` (empty = writes nothing); browser check `rootbase` builds with `site.base_path: "/"`. Browser suite: 38 checks in the full run (35 named, `failure` split in 3 shards).
- **dev22 (branch):** NBM ONLY (the "NWS official" toggle, its state and `data/ndfd/` browser fetches are gone; the NDFD fetch and archive rows stay: guard `tests/test_lean_charts.py`); lean chart modules (takeaway + chart + legend + table + one `.note.src` source line + `how()` link;
  all explanations in About "Reading the charts"; `C.summary(el, short, aria)`, `C.legend`); snow-ratio chart per run (`web/js/charts/segments.js`, browser check `slrchart`); freshness `web/js/freshness.js` (latest / late / out of date, lags measured) + `pipeline/ecmwf_attempts.py` + `ecmwf.yml` hourly attempts
  (the ONLY .github edit, schedule + comment; a proposed extra publish step was denied by the tool classifier and is NOT applied); `tools/page_metrics.py` (area-page height / CLS on frozen fixtures), `tools/slr_baseline.py` + `docs/specs/snow-ratio-ml.md` (research only).
  GitHub delivers few cron events here (6 of ~46 hourly runs): never assume a scheduled job ran.
- **dev21 (merged, PR #30):** TWO new owner-authorized workflows (the only `.github/` change): `verify.yml` (daily 15:25 UTC: archive CSVs -> `pipeline verify-ci` = the same
  `verify.run` -> `verify-<YYYYMMDDHH>-<hash>.tar` on model-maps -> update-site's existing unpack -> `build/models/verify/`; the panel reads `models/verify/` (`VerificationUI.BASE`), flag
  `verification_ui.enabled` still OFF; switch `verification.ci_enabled`; NEVER an index.json in models/verify: the model catalog collects */index.json) and `gefs.yml` (06:10/08:10/18:10/20:10
  UTC from MEASURED S3 release times; `gefs.enabled: true`; resume cache `data_cache/gefs/<cycle>`; too many missing members = new=false). Monitored sources `verify` (50 h) and `gefs` (30 h).
  Safari: idle/observer guards use `typeof x === "function"` (never `"x" in window`); model chips on Precipitation by model (`#mm-chips`, sessionStorage; badge/table use every model);
  area-page alert CLS fixed (the summary's mailto link reserves its space); tap targets >= 40 px at phone width also in WebKit/Firefox. `pipeline archive-check` (archive integrity).
  Cross-browser smoke (optional): `C:/miniforge3/envs/pw/python.exe tools/xbrowser_smoke.py` (Playwright 1.49.1 WebKit + Firefox in the separate `pw` env; ~1 min; screenshots in data_cache/xbrowser).
- **dev20 (merged):** ECMWF mirror preference + 2-cycle cache; AIFS line (`aifs.enabled: true`, `in_badge: false`; AIFS tp in MM, IFS tp in METRES); share cards `pipeline og` (OFF); browser suite rework.
  Tests must never write the real data_cache (autouse fixtures patch `E.REPO_ROOT` / `G.REPO_ROOT`).
- **dev19 (merged):** `pipeline/fetch_resilient.py` (shared `Fetcher`: backoff + jitter, Retry-After, mirror failover AWS regional -> Google -> ECMWF portal); a missing step is a GAP, never
  interpolated; ECMWF resume cache restored/saved by `ecmwf.yml`. **Plotly self-hosted** (`web/vendor/plotly-2.35.2/`, hash pinned). No browser call to api.weather.gov.
- main has dev13-dev20 (ECMWF LIVE since dev18 via `ecmwf.yml`; member counts are read from the data, never hard-coded). dev18 extras: models-page fixture frames (`tools/model_fixture.py`),
  webcam LINKS, Sources register (`config/sources.yml` -> `web/sources.html` via `tools/gen_site_pages.py`), DRAFT legal pages, `pipeline linkcheck`, W1 rehearsal tools.
- **Built but OFF (never enable from a dev session):** `wind_exposure.enabled` (W7), `alerts_backend.enabled` (W6), `analytics.enabled`, `verification_ui.enabled`, `pages.enabled`, `pwa.enabled` (W1 first).
- Browser suite (dev20/21): `tools/browser_check.py` 32 checks (dev21: `noidle`, `mmchips`, `alertcls`) (the full run splits `failure` into failure1-3), 4 parallel workers (`--jobs`), each check in its own Chrome profile + server port on a
  private build copy with FROZEN inputs (`tools/browser_fixtures.py`: recorded alert snapshot shifted to "active now"; third-party hosts answered from `tests/fixtures/browser/`, anything
  else refused). Full run ~5-6 min; `--quick` (8 checks) ~1.5 min for per-item runs. No fixed sleeps: `open()` waits for the page's READY signal then for quiet (`settle`); background
  work with no page signal (service worker, analytics queue) must be POLLED, never slept on. Re-record fixtures only with `tools/browser_fixtures.py record` (network once).
- Open: W3 meta description (W2) + Low-confidence rule; `HEALTHCHECK_URL` secret; W1 then enable pwa/pages; real-device PWA tests; M9: verify.yml publishes daily, the minima (14 days, 30 pairs) are projected for about Nov 30, then the owner flips verification_ui.enabled; owner: analytics provider, legal review, W6 decisions, W7 reviewer.

