# Snow-Wx — Archive (history; not read by default)

> Completed work and older decisions moved out of `PLAN.md` to keep it lean. Read only when you need history.

---

## A. Decisions log, Nov 6–8 2026

| Date | Decision |
|---|---|
| Nov 6 | Public site for owner + friends; may monetize later → only sources whose terms allow public display & commercial use. |
| Nov 6 | No Synoptic. Obs from NRCS AWDB, IEM, avalanche.org. |
| Nov 6 | Stack: Python pipeline on GitHub Actions → static site. Dev in VS Code + Claude Code; env `C:/miniforge3/envs/snow-wx`. |
| Nov 7 | Model images stored as GitHub Release assets; site pulls newest per model; 900 MB guard. |
| Nov 7 | Snow level (model maps) = wet-bulb 0 °C height, capped at lowest 0 °C height; free-atmosphere freezing level dashed. |
| Nov 7 | 700 mb temperature in °C; surface °F / in / mph or kt (see §6). |
| Nov 7 | **Product focus: OpenSnow competitor centered on ski-area point forecasts (western US first).** |
| Nov 7 | **Remove upper-air fields (500 mb, 700 mb) from HRRR and RRFS. Keep them for GFS (and ECMWF later).** |
| Nov 7 | **Model maps must be zoomable** → interactive data layers for surface fields (§5.4). |
| Nov 7 | **NBM is the primary point-forecast engine; NDFD shown as the NWS official forecast alongside it.** |
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
| ~~Nov 8~~ | ~~Monetization on the back burner; decision point fall 2027.~~ **Superseded Nov 15 (below).** The fall-2027 *full launch* target survives; preparation starts now. |

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
2. **Safety information is always free:** avalanche danger, NWS alerts, snow
   level/rain-at-base, data freshness. These are never gated.
3. **The free product must be genuinely good** — it *is* the marketing.
4. **Paid = convenience, personalization, compute** (alerts, unlimited saved
   places, exports/API, embeds) — never public data itself.
5. **Web/PWA first.** No native apps until demand is proven (avoids app-store
   fees and double the dev work).
6. **License-clean open data only** (§10).
7. **Automate over people.** Pipeline + rules engine, not human writers.
8. **Side-hustle realism.** Plan assumes roughly 8–12 focused hours/week with
   Claude Code doing most implementation **[assumption — owner to confirm]**.

### Audience
Skiers/riders (headline numbers, day/night snow, powder quality), backcountry
users (avalanche danger, wind, snow level), **snowmobile / Nordic / snowshoe /
sledding users** (Sno-Parks — underserved by incumbents), meteorologists
(models, percentiles, method, verification), and later **B2B**: lodging, guides,
ski shops, clubs, small ski areas, avalanche centers.

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

### 11.2 Owner decisions needed
1. **Name:** final brand + domain (blocks W1).
2. **Entity/tax:** sole prop vs LLC, state, CPA — and whether to use a merchant of
   record.
3. **Time budget:** is ~8–12 h/week right? (drives the cut list).
4. **Soft launch:** comfortable with a capped Founding Supporter launch in Feb
   2027 if Gate 3 passes, or wait for pre-season?
5. **Hosting move now** (W1) vs later — recommended now.
6. **Private vs public repo** long-term.
7. **SMS:** never / only if users ask / launch with it.
8. **External cron trigger** for the pipeline.
9. **avalanche.org permission:** who contacts them, and when.

#### PLAN §3 Nov 15 rows (long wording, until Nov 16)

| Nov 15 | **Business intent is active.** Free-first. No paywall before Feb 2027; optional Founding Supporter soft launch Feb 2027 (Gate 3); full paid launch Sep–Oct 2027. |
| Nov 15 | **Adopt** from the Gemini review: Daily Snow summaries (W3), offline-first PWA (W4), multi-model comparison incl. ECMWF (M7/M8). **Reshape** wind-loading (§5.9). **Reject** Open-Meteo API for production (rationale: `docs/BUSINESS.md` Appendix A). |
| Nov 15 | **Move to a custom domain + Cloudflare Pages (site) + R2 (frequently-updated data) before any public promotion** (W1). GitHub Pages stays as a redirect/canonical stub. Reason: GitHub Pages is not permitted for online businesses/SaaS, installed PWAs and SEO are tied to the origin, and Pages file-count limits may bite the model-map frames. |
| Nov 15 | **Path-based, prerendered area URLs** (`/ski/<state>/<id>/`), not hash routing, so ~600 pages are indexable (W2). Old `#id` links redirect. |
| Nov 15 | **Offline cache of the last-fetched forecast is free.** (Gemini proposed paywalling it.) It builds trust, drives PWA installs, and iOS push needs the install anyway. |
| Nov 15 | **No numeric "lee-aspect accumulation adjustment" until verified** (M9). Wind is shown as an informational flag, never as an avalanche rating. |
| Nov 15 | **Alerts: email + web push first; SMS is an optional later add-on** (carrier fees + registration + TCPA overhead; its advantage is working on weak signal). |
| Nov 15 | **Payments via a merchant of record at first** (Stripe Managed Payments / Paddle / Lemon Squeezy class) to offload sales-tax registration; revisit when volume justifies Stripe + Stripe Tax. Confirm with a CPA. |
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
- Repo visibility: GitHub Actions minutes are free for public repos; a private
  repo would cost money at current cadence — estimate before switching. Public
  code is copyable (acceptable; our moat is data operations, verification,
  brand and audience).
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
- Next (PLAN §8.2 Sprint 1): SNOTEL fix + W5a pipeline monitoring and data-status page, W1 hosting prep (brand name and domain
  not decided; configurable SITE_ORIGIN / DATA_ORIGIN, GitHub URLs as defaults), then W3 daily summaries (before W2), W2, W4.
- Not started: storm-total tracker (PLAN §8.4), M7, M8 (ECMWF via Herbie `ifs`/`aifs`, attribution "© ECMWF, CC BY 4.0"),
  M6, model-map NWS colors (§8.4), self-hosted PMTiles backup (§8.4).


---

## PLAN §3 row moved out of PLAN.md (dev16)

| Nov 17 | **dev13 UX package (overnight, assumptions flagged in the session report):** NBM-native P(≥2″) row for 24/48 h only (never derived); one combined snow-ratio + powder-quality panel; linked Finder state/region menus with counts; obs-map defaults (reference layer, ski areas, Sno-Parks, avalanche, **NWS winter hazards** ON; SNOTEL/ASOS/NOHRSC OFF, remembered, URL `ly=` overrides, Reset button), red alert rings removed; hazards from NOAA/NWS WWA map service with a visible fallback to our alerts index; config `hazards.enabled`. |


## Moved from PLAN §3 (dev17 trim)

| Nov 17 | **dev13 UX package** (NBM-native P(≥2″), combined snow-ratio/powder panel, linked Finder menus, obs-map layer defaults + NWS hazards layer): details in `docs/ARCHIVE.md`. |
| Nov 17 | **SNOTEL outage handling accepted:** previous good copy from the live site (option A, `SITE_ORIGIN`/`site.origin`, on the W1 cutover checklist); stale ≤ 48 h with original timestamps (never re-stamped), 24/72 h changes hidden when older than their window; data-health GitHub issues per source with limits from each source's real cadence (config `monitoring`), assigned to the owner, monitor can never fail the deploy. Independent "workflow did not run" check proposed in `docs/specs/data-pipeline.md` 5.2c (heartbeat service recommended). |
| Nov 17 | **Owner feedback (live review) → dev14:** the **default uncertainty range for snowfall, snow level and snow ratio is 25–75% ("likely", the middle half of NBM's outcomes)**; 10–90% is kept only where explicitly noted (Finder/W3 chance fields, M9 archive). Inline text says "likely X–Y in" with no "NBM 10–90%" label (source and issue time stay in run lines and captions). **One powder-quality definition** (config `powder_quality`: Dense < 10:1, Blower ≥ 15:1). Obs map first-load layers: relief + roads + ski areas + NWS winter hazards only; avalanche, Sno-Parks, SNOTEL, ASOS, NOHRSC off. W3 "Dry stretch" outranks "Wind-affected"; alert tag computed client-side from alerts/index.json. Obs-map Lighthouse target: no worse than main (≈ 82). |
