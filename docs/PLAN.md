# Snow-Wx — Product Plan & Development Framework (v0.6, Nov 8 2026)

> Drop this file into the repo as `docs/PLAN.md`. Claude Code should read it
> together with `CLAUDE.md` at the start of every session and tick off
> milestones in §8 as they land.

---

## 1. Vision

**A free, open-data alternative to OpenSnow for the western US**, built around
**point forecasts for every ski area**, with the meteorological depth a
forecaster trusts and the clean, fast presentation a skier wants.

Positioning — where we win:

| | OpenSnow | Snow-Wx |
|---|---|---|
| Price | Free tier; Base/Premium subscriptions | Free |
| Forecast | One blended forecast weighted to proprietary PEAKS 2.0 | Transparent: NBM probabilistic range **+** NWS official (NDFD) **+** raw models side by side |
| Uncertainty | Forecast range view | Percentile ranges (10/50/90) everywhere, by default |
| Rain/snow line | — | Snow level vs base/summit elevation for every area |
| Context | Avalanche forecasts, webcams, snow reports | Avalanche danger, nearest SNOTEL/ASOS obs, NWS alerts + forecaster discussion |
| Trust | Accuracy claims | **Public verification** vs SNOTEL ("how did the forecasts do last storm") |

Where OpenSnow leads (don't try to match yet): terrain downscaling (~50 ft),
human local forecasters, resort snow reports, webcams, 3D/offline maps, native
apps + push alerts. Our long-term answer to PEAKS is a simple, transparent
station-based bias correction (§8, M9) — we already ingest the observations.

Audience: skiers/riders (headline numbers, day/night snow, powder quality),
backcountry users (avalanche danger, wind, snow level), meteorologists (models,
percentiles, snow level method, verification).

---

## 2. Status (Nov 8 2026)

- **Live:** https://alexluke23.github.io/snow-wx/ — repo `alexluke23/snow-wx`.
- **Observations map:** SNOTEL (837), ASOS (545), avalanche danger (70 zones);
  search, shareable URL hash, declutter, smoothed depth charts.
- **Model maps:** HRRR, RRFS, GFS — 10 fields, 6 domains (GFS west only), loop
  viewer; `models.yml` CI every 3 h → Release assets (`model-maps`) → site.
  Site ≈ 240 MB. First CI run green.
- **Session 1 (dev2, Nov 7):** M0 done; M1 catalog (161 areas, 60 major,
  3DEP elevations); M2 NBM points (fixed NBM alternating-row decode bug;
  matches NBM bulletins); M3 area page v1 reviewed — consistent with NWS.
- **Done since:** NDFD, NOHRSC overlays, Powder Finder (+ chance-of view, S4), alerts.
- **dev4 merged (Nov 8, PR #5):** NBM full-suite snowfall percentiles to day 10–11, Powder
  Finder "Chance of", AFDs, about.html, ridge-top wind. Verified on GitHub (Model maps #8 green).
- **Session 5 (dev5, Nov 8):** M9-prep forecast archive + local cache pruning, bugs B1–B7
  (§8 M3.6), chart readability (§6-B), then Sno-Parks (M4.5). M6 zoomable layers and the HRRR
  pressure-level file are deferred to session 6.
- **Session 6 handoff (M6 + HRRR prs), measured Nov 8:** release tars HRRR 98.0 MB, RRFS
  82.6 MB, GFS 23.4 MB; CI "Render maps" HRRR 111–117 s, RRFS 115–181 s before ridge wind
  (3 m 21 s with it), GFS 66–68 s. HRRR `wrfprs` has 25-mb levels 1000–50 mb; per forecast hour,
  the 21 levels 1000–500 mb cost TMP 12.3 MB, RH 16.6 MB (DPT 22.6 MB), HGT 15.3 MB,
  UGRD+VGRD 25.7 MB (byte ranges from the idx).
- **Session 9 (dev9, Nov 8):** snow forecast overlays on the obs map (Track 2 item 7), "My mountains" favorites page (Track 1 item 4). Powder quality and M7 not started.
- **Session 7 (dev7, Nov 8):** "Expected" rename done; hour-by-hour temperature/wind to day 10 (6-hourly,
  shaded); Sno-Park source research written up (docs/sources_recreation.md), awaiting approval.
- **Session 6 (dev6, Nov 8):** Part A fixes 1–9 from the dev5 live review done (PLAN.md §8 M3.6); Part B
  (hour-by-hour to day 10, Sno-Park source research) next.
- **Not started:** ECMWF.
- **CI housekeeping:** Node 20 deprecation warnings (bump action versions);
  `ubuntu-latest` → Ubuntu 26 migration notice (pin `ubuntu-24.04`).
  GitHub hourly schedule is best-effort (only 2 runs overnight) — monitor.

---

## 3. Decisions log

| Date | Decision |
|---|---|
| Nov 6 | Public site for owner + friends; may monetize later → only sources whose terms allow public display & commercial use. |
| Nov 6 | No Synoptic. Obs from NRCS AWDB, IEM, avalanche.org. |
| Nov 6 | Stack: Python pipeline on GitHub Actions → static site on GitHub Pages. Dev in VS Code + Claude Code; env `C:/miniforge3/envs/snow-wx`. |
| Nov 7 | Model images stored as GitHub Release assets; site pulls newest per model; 900 MB guard. |
| Nov 7 | Snow level (model maps) = wet-bulb 0 °C height, capped at lowest 0 °C height; free-atmosphere freezing level dashed. |
| Nov 7 | 700 mb temperature in °C; surface °F / in / mph or kt (see §6). |
| **Nov 7** | **Product focus: OpenSnow competitor centered on ski-area point forecasts (western US first).** |
| **Nov 7** | **Remove upper-air fields (500 mb, 700 mb) from HRRR and RRFS. Keep them for GFS (and ECMWF later).** |
| **Nov 7** | **Model maps must be zoomable** → interactive data layers for surface fields (§5.4). |
| **Nov 7** | **NBM is the primary point-forecast engine; NDFD shown as the NWS official forecast alongside it.** |
| Nov 7 (S2) | 1. Day/night = 12Z–00Z / 00Z–12Z periods, labeled in local time (e.g. "5 AM–5 PM MST"). |
| Nov 7 (S2) | 2. Snowfall ranges: NBM snowfall percentiles for 0–48 h; beyond 48 h QPF percentiles × SLR × P(snow at elevation), styled as "extended outlook". Report how the two methods compare over 0–48 h. |
| Nov 7 (S2) | 3. Bars, the headline "most likely" and totals use NBM deterministic (mean) values so bars sum to totals; percentiles only as 10–90% whiskers/ranges. Zero snowfall when expected QPF < 0.01". |
| Nov 7 (S2) | 4. Point snow = snowfall × P(snow level below point elevation) from the snow-level percentiles; label "mostly rain" / "mixed". |
| Nov 7 (S2) | 5. NBM points stay at 4×/day (00/06/12/18Z). |
| Nov 7 (S2) | 6. Catalog: merge Three Summits + Summit West/Central/East into "The Summit at Snoqualmie"; Alpental stays separate. Kirkwood / Palisades summit overrides only if OSM lift data is incomplete, with the source cited. |
| Nov 7 (S2) | 7. Keep Plotly, but render the headline + tiles as plain HTML first and load charts afterwards; measure with Lighthouse (mobile) and report. |
| Nov 7 (S2) | Add NBM + NDFD forecasts for all SNOTEL sites; NDFD sampled from GRIB2 on AWS (api.weather.gov only for alerts/AFD/missing elements). |
| Nov 7 (S2) | Add NOHRSC overlays to obs map: SNODAS SWE, snow depth, 24 h SWE change; National Gridded Snowfall Analysis 24/48/72 h. Builds the interactive-layer system (§5.4) first used here. |
| Nov 7 (S2) | Obs map performance work (canvas rendering, lazy charts). |
| Nov 7 (S3) | 1. Extended outlook (>48 h): NBM deterministic and probabilistic fields are calibrated independently, so the deterministic value may fall outside the percentile range — no clamping. Bars = NBM deterministic (additive, sum to totals); whiskers = NBM probabilistic guidance; beyond 48 h QPF 25th–75th × SLR × P(snow), labelled "likely range". A tooltip explains when the deterministic value lies outside the range. Keep the calibration report for rechecks after real storms. |
| Nov 7 (S3) | 2. NWS view shows NDFD raw: no elevation/temperature adjustment and no snow-level scaling (NDFD snow already contains the forecasters' rain/snow decisions). Label "NWS forecast for the 2.5 km grid cell (elev. X ft)". |
| Nov 7 (S3) | 3. SNOTEL NBM cell elevation = full 3DEP cell average, computed once and stored in the catalog (no 5-point shortcut). |
| Nov 7 (S3) | 4. With a NOHRSC overlay on, avalanche zones draw as outlines only; SWE overlay palette stays the SNOTEL SWE palette. |
| Nov 7 (S3) | 5. Keyboard: search is the only keyboard route to individual stations for now (known accessibility gap, §10). |
| Nov 7 (S3) | 6. NDFD stays on the 3-hourly schedule. |
| Nov 7 (S3) | 7–8. CI: one job saves the micromamba cache; "already published" includes a renderer/config version so config changes re-render the current cycle. |
| Nov 8 (S4) | 1. Snowfall ranges: NBM's own snowfall percentiles (6/24/48/72 h) from the 01/07/13/19Z full-suite cycles for all periods and totals (docs/nbm_inventory.md). The QPF-based range is a fallback only, labelled as such. Bars stay NBM deterministic; never clamp deterministic and probabilistic fields to agree. Calibration report rerun before/after. |
| Nov 8 (S4) | 1a. Liquid (QPF) ranges come from the companion 00/06/12/18Z cycle (the hour before the full-suite cycle), labelled with that cycle. Fallback order: newest complete full-suite cycle → previous full-suite cycle (≤ 12 h old) → only then a 00/06/12/18Z cycle. Points schedule aligned with full-suite completion. |
| Nov 8 (S4) | 1b. Exceedance probabilities: NBM's own probability fields (consistency with percentiles checked and reported). Thresholds as NBM provides (24 h to 24", 48 h to 36", 72 h to 48"); skier chips 4/6/8/12/18/24" (+30/36/48" for 48/72 h). GSL viewer mismatch stays documented as unresolved. |
| Nov 8 (S4) | 2. NWS cell elevation: drop the "≈" only if NBM and NDFD CONUS share the identical 2.5 km grid; otherwise compute NDFD cell elevations. |
| Nov 8 (S4) | 3. Alerts: show all types (never hide a warning), sorted winter / wind / avalanche / blizzard / extreme cold first; others collapsed under "Other alerts (n)". |
| Nov 8 (S4) | 4. Powder Finder: default 72 h summit for first-time visitors, then each visitor's last choice (localStorage, try/catch); a shared URL overrides. |
| Nov 8 (S4) | 5. Powder Finder snow level shows "–" when little precipitation is expected in the window (same rule as the area page: chance of precip < 20 %). |
| Nov 8 (S5) | 1. Liquid (QPF) ranges from the newest complete 00/06/12/18Z cycle (~7 h older than the snowfall), labelled with that cycle: accepted. Never delay the snow forecast to wait for the companion cycle. |
| Nov 8 (S5) | 2. Exceedance chances stay per 2.5 km grid cell (no elevation adjustment), with the existing note. |
| Nov 8 (S5) | 3. HRRR pressure-level file (25 mb) approved for ridge wind, Kuchera Tmax and the wet-bulb snow level — deferred to session 6. |
| Nov 8 (S5) | 4. M6 zoomable model layers approved — deferred to session 6. |
| Nov 8 | dev4 verified on GitHub: Model maps #8 all green; RRFS job 3 m 50 s total (render 3 m 21 s) with ridge wind — no runtime concern. |
| Nov 8 | Forecast archive stores **all daily leads**: every 24 h window ending 12Z (days 1–10) + every 72 h window, det/p10/p50/p90/P(≥4/8/12"), plus NDFD. ~30–40 MB/month gzipped, kept as GitHub release assets (never on the owner's PC, never in git history). |
| Nov 8 | **Chart readability is a priority.** Adopt the chart standards in §6-B site-wide before adding more charts. |
| Nov 8 | **Basemaps must never go blank.** Overzoom + automatic fallback provider (§6-C). |
| Nov 8 | **Add Sno-Parks / winter recreation points** (snowmobile, snowshoe, XC ski, sledding) as a new point type alongside ski areas and SNOTEL (§5.6, milestone M4.5). |
| Nov 8 | Keep local disk use small: auto-prune `data_cache` (> 2 days) at the start of local runs; report project disk use in summaries. |
| Nov 8 (S5) | Approval amendments: Sno-Park NBM cell elevation = full 3DEP cell average (as SNOTEL); push dev5 right after the archive so it can be merged early; area-page charts below the fold render lazily (Lighthouse performance ≥ 90); Sno-Park sources public-domain and key-free first (USFS EDW, state lists, OSM gap-fill) — Recreation.gov RIDB only after asking, key as an Actions secret. |
| Nov 8 (S5) | Archive PR #6 merged; the `verification` release has the nbm/ndfd/snotel 2026-11 files (M9-prep ✅). |
| Nov 8 (S5) | 2. Area page "Hour by hour" keeps hourly detail to ~3.5 days. Next session: extend the temperature and wind panels to day 10 with NBM's 3/6-hourly values, lightly shaded and labelled "extended (6-hourly)". Snow stays as day/night bars beyond 3.5 days. |
| Nov 8 (S5) | 3. Sno-Parks (M4.5), next session: research sources and licences first (USFS EDW, state Sno-Park lists, OSM gap-fill; public-domain and key-free preferred), write docs/sources_recreation.md, and get owner approval before building. |
| Nov 8 (S6) | Rename "most likely" to **"Expected"** site-wide (next session): area tiles, day/night bars, Powder Finder (amount and chance modes), about.html; with an ⓘ tooltip: NBM's average amount, which typically has about a 1-in-3 chance of being reached (S6 fix 8 analysis). |
| Nov 8 (S7) | Sno-Park sources approved: USFS EDW (public domain) as backbone + OpenStreetMap gap-fill (ODbL, attributed like the ski areas). WA/OR/CA/ID state lists only as a manual cross-check, never copied. Scope: Sno-Parks + snowplay areas + Nordic sites (+ winter trailheads named as such), ~450 points. Build M4.5 next session. |
| Nov 8 | **Priority order: Obs map and per-site Forecast pages first; model maps last.** Keep models.html live as-is (low maintenance only; no new model-map features until the obs/forecast work is done). |
| Nov 8 | Keep the model pipeline running: it feeds point products (ridge-top wind, future "precipitation by model"). |
| Nov 8 | Consumer **snow forecast map** (NBM expected snowfall + chance-of layers) belongs on the Obs map as overlays, not on the models page (reuses the NOHRSC layer system). |
| Nov 8 | **Monetization is on the back burner.** §11 records what must be true before charging money. Do not build §11 items unless the owner asks. |
| Nov 8 (S8) | 1. dev8 pushed. 2. Powder Finder first-visit default stays "Ski areas" (each visitor's choice is remembered). |
| Nov 8 (S8) | 3. Sno-Park activities only as the source states them (no inferred list: motorized vs non-motorized mistakes matter); otherwise show the site type and a link to the managing agency. |
| Nov 8 (S8) | 4. Sno-Park permits: the source's permit text only; otherwise "Parking permits may be required — check [official state program or managing national forest]" with the link. Never "Likely". |
| Nov 8 (S8) | 5. Sites with no NWS grid point show "NWS alerts not available for this location". |

Defaults chosen in this plan (owner may override): ski-area scope = all
western US downhill areas with lifts (~150–200), major resorts curated first;
forecast horizon = 10 days (hourly to 36 h, then 3/6-hourly); day/night periods
6 AM–6 PM / 6 PM–6 AM local; wind in **mph** on point pages (kt on model maps
and ASOS); elevations in feet.

---

## 4. Site map

| Page | Purpose | Status |
|---|---|---|
| `index.html` — **Map** | Observations + ski areas + avalanche; later an optional model/NBM overlay | Live; add ski-area layer |
| `area.html#<id>` — **Ski area** | The core product: point forecast + recent obs + context | New (M3) |
| `finder.html` — **Powder Finder** | Map + sortable table of every area's 24 h / 72 h / 7-day snow | New (M4) |
| `models.html` — **Models** | Tab 1 "Interactive" (zoomable surface layers); Tab 2 "Synoptic charts" (GFS/ECMWF PNGs) | Live; rework (M6) |
| `about.html` | Methods, data sources, attribution, disclaimers, verification | New (M5/M8) |

Global nav on every page; favorites (localStorage, try/catch) shown first in
search, Finder and the home page.

---

## 5. Product specs

### 5.1 Ski-area catalog (`data/ski_areas.json`)
One record per area:
`id` (slug), `name`, `state`, `region` (e.g. Wasatch, Tahoe, Front Range,
Cascades), `base {lat, lon, elev_ft}`, `summit {lat, lon, elev_ft}`, optional
`mid`, `tz`, `url`, `avalanche_zone_id`, `nearest {snotel[], asos[]}` (with
distance + elevation difference), `nws {wfo, grid_x, grid_y}` for base & summit,
`nbm_grid {i, j, elev_ft}` for base & summit.

- **Seed** from OpenSkiMap ski-area GeoJSON (OpenStreetMap-derived, **ODbL**:
  attribute "© OpenStreetMap contributors / OpenSkiMap" and publish our
  derived catalog under ODbL). Filter: western states, downhill, has lifts,
  operating.
- **Curate** base/summit points: lowest/highest lift terminal from OSM where
  available; elevations from a DEM (USGS 3DEP) — never trust a single source.
  Hand-check the top ~60 resorts.
- Spatial joins computed once in `pipeline/catalog.py`; re-run on demand, not
  hourly. Catalog is versioned in git (`config/ski_areas.yml` overrides).
- Avoid resort logos/trademarked imagery; names and links are fine. Don't
  scrape resort snow reports (proprietary).

### 5.2 NBM point forecasts (primary engine)
- Source: NBM GRIB2 on AWS (`noaa-nbm-grib2-pds`, `core` + `qmd`), byte-range
  via Herbie. Evaluate the COG bucket (`noaa-nbm-pds`) only if it is materially
  cheaper for point reads.
- **Download each field once per cycle and sample all points** (ski-area base +
  summit + SNOTEL sites) — the same download later feeds Powder Finder and the
  interactive NBM layer.
- Elements (verify each in the `.idx` inventory before coding):
  - Snowfall: 1 h (to 36 h), 6/12/24 h; **percentiles 10/25/50/75/90**
  - QPF + PQPF percentiles; PoP
  - **Snow level percentiles** (10/50/90) and **snow-liquid ratio percentiles**
  - Temperature, dewpoint, apparent temp, max/min
  - Wind speed, direction, gust (+ 24 h peak gust percentiles if available)
  - Sky cover; precip type / probability of snow vs rain; ice (FRAM) if present
- Cadence: NBM runs hourly; process the cycles that extend furthest (check
  which cycles reach day 10–11) every ~3 h, plus a lighter 0–36 h refresh hourly
  if CI time allows. Record cycle + issue time in every output.
- **Elevation handling** (transparent, documented on about.html):
  - Sample base and summit separately at their own coordinates.
  - Temperature: adjust from NBM grid elevation to true point elevation with a
    lapse rate (start 6.5 °C/km; later derive from HRRR/RRFS column), capped.
  - Rain vs snow: compare snow-level percentiles to point elevation →
    P(snow at base), P(snow at summit). Show "rain at base / snow up top".
  - Snowfall at a point = NBM snowfall at that point; if snow level is above
    the point elevation, flag the amount as mixed/rain.
- **Day/night periods**: 6 AM–6 PM and 6 PM–6 AM local; report the 50th
  percentile with a 10–90 range for each period and for 24 h / 72 h / 7 d / 10 d.
- **Powder quality** (simple, documented heuristic, not a claim of accuracy):
  SLR median ≥ 15 → "Blower", 10–15 → "Medium", < 10 → "Dense"; add
  "wind-affected" when summit gusts > 30 mph during snowfall.
- Output: `data/points/<id>.json` (hourly series + period summaries) and
  `data/points/summary.json` (one row per area for Finder/home). Target
  < 150 KB per area.

### 5.3 NWS official layer (NDFD + alerts + discussion)
- `api.weather.gov` with our User-Agent. Cache `/points` → grid lookups in the
  catalog (static). Per run: `/gridpoints/{wfo}/{x},{y}` raw layers for base &
  summit (dedupe shared grid cells) — temperature, snowfallAmount, snowLevel,
  quantitativePrecipitation, windSpeed/Gust, skyCover, probabilityOfPrecipitation.
- Active alerts: one `/alerts/active?area=<western states>` call per run →
  point-in-polygon/zone match → **banner on the area page** (Winter Storm
  Warning, etc.).
- Area Forecast Discussion: latest AFD per WFO → issue time + link (+ optional
  collapsible text; NWS products are public domain).
- Present as an "NWS official" toggle/column next to NBM — never silently mix.

### 5.4 Model maps rework
- **Remove** `h500` and `t700` from HRRR and RRFS (config change). GFS keeps
  them; ECMWF will too.
- **Interactive tab (new architecture)** for surface fields — QPF windows,
  snowfall (10:1 / Kuchera toggle), snow level, 2 m temp, gust, later NBM
  snowfall percentiles:
  - Pipeline regrids each field/frame **once** for the west domain onto a
    **Web Mercator (EPSG:3857) grid** (~2–3 km) and writes a compact
    value-encoded PNG (8-bit index into a per-field value table, or 16-bit with
    scale/offset in the index JSON). Must be 3857, not lat/lon, or Leaflet
    overlays will be misplaced.
  - Browser decodes to a canvas, colorizes with the same palettes as
    `colors.js`, and shows it as a Leaflet overlay on the shaded-relief
    basemap: **smooth zoom/pan, hover/tap value readout, ski-area and station
    markers on top**, same play/scrub controls.
  - This replaces the six per-domain PNG sets for HRRR/RRFS (subregions become
    zoom presets). Expect total size to drop.
- **Synoptic charts tab**: keep the static PNG viewer for GFS (and ECMWF):
  500 mb heights/vorticity, 700 mb, QPF, etc. Add simple pan/zoom on the PNG.
- Snow-level maps: legend note "Snow level ≈ wet-bulb 0 °C height". Evaluate
  matching the NWS Western Region convention (0.5 °C wet-bulb) for consistency
  with NBM/NDFD snow level.

### 5.5 Multi-model point plumes
Reuse the model pipeline to sample HRRR, RRFS, GFS (and ECMWF, NBM) at every
ski-area summit/base: cumulative snowfall + QPF + snow level per model on one
chart ("Precipitation by model"). Later: ensemble members (GEFS, ECMWF ENS,
REFS) as a true plume — the University of Utah style product.

### 5.6 Sno-Parks & winter recreation points (new, Nov 8)
- **Point type `snopark`** in a recreation catalog (`data/rec_points.json`),
  sharing the ski-area machinery (alerts zone/county, avalanche zone,
  nearest SNOTEL/ASOS, NBM/NDFD cells, 3DEP elevation). NBM cell elevation =
  full 3DEP cell average (as for SNOTEL).
- **Sources (verify availability and license before use; prefer public
  domain, key-free):** state Sno-Park programs (e.g. Oregon, Washington, California
  Sno-Parks; Idaho Park N' Ski), USFS recreation-site data (EDW) for winter
  trailheads, and OpenStreetMap (ODbL) to fill gaps. Recreation.gov RIDB only
  after asking the owner (API key would be a GitHub Actions secret, never in
  code). Record the source of every point.
- **Fields:** name, state, managing agency, permit required, activities
  (snowmobile, XC ski, snowshoe, sled/tubing, dog sled), groomed (if known),
  lat/lon, elevation (3DEP), link.
- **Forecast view:** reuse the area page. Elevations: the trailhead, plus an
  optional clearly-labeled "high terrain" point (e.g. highest DEM elevation
  within ~5 km or a mapped route high point).
- **Recreation-relevant extras:** wind chill / apparent temperature, snow
  depth at the trailhead (SNODAS), new snow, NWS alerts (travel), avalanche
  danger shown prominently (snowmobilers are a high-risk group).
- **Integration:** Powder Finder gets a **Type** filter (Ski areas / Sno-Parks
  / All) with distinct map symbols; obs map gets a Sno-Parks layer.
- **Budget:** check the points job runtime and site size with the added
  points.

---

## 6. Visualization standards ("clean and sharp")

Create `docs/DESIGN.md` + shared `web/css/tokens.css` and `web/js/` chart helpers
so every page looks like one product.

- **Mobile-first** (375 px wide first, then desktop). Tap targets ≥ 40 px.
- **Typography**: system UI stack; tabular numerals for all numbers.
- **Color**: one snowfall palette used identically in maps, Finder markers,
  bars and legends; NAADS colors for avalanche; temperature palette with a clear
  32 °F break; color is never the only carrier of meaning (labels/values too).
- **Numbers first**: every chart has a headline sentence/number above it
  (e.g. "Next 72 h: **8–14 in** at summit, most likely 11 in").
- **Uncertainty everywhere**: bars = median, whiskers/bands = 10–90th.
- **Units**: in, °F, mph (point pages); kt on ASOS/model maps; ft for
  elevations; show local time with zone; relative times ("issued 2 h ago").
- **Chart set** (shared helpers, one charting library site-wide; Plotly is
  acceptable, switch only if mobile performance is poor):
  1. Day/night snowfall bars with range whiskers (10 days)
  2. **Snow level band (10–90) vs horizontal base/summit lines**
  3. Hourly meteogram: temp base & summit (32 °F line), wind + gust (summit),
     QPF bars + snow probability, sky cover strip
  4. Precipitation-by-model cumulative lines
  5. Recent obs: nearest SNOTEL depth/SWE 7 days, storm total
- **Freshness**: every module shows its source + issue time; stale data is
  visibly greyed.
- Accessibility: alt text on images, keyboard navigation for viewers, contrast
  AA.

### 6-B Chart readability & accessibility (applies to every chart; Nov 8)
- **Text size:** tick labels ≥ 13 px desktop / 12 px mobile; axis titles
  13–14 px, written horizontally at the top-left of each panel with units,
  e.g. "Snow (in)". No rotated axis titles.
- **Time axes:** weekday + date ("Mon 9"), local time zone stated once,
  faint vertical day separators, subtle night shading. Every stacked panel
  shares the same x-range and left margin so times line up.
- **One idea per panel, ≤ 3 series per panel.** Prefer direct labels at
  line ends over legends; if a legend is needed, put it above the chart.
- **Bars:** value labels ≥ 12 px placed so they never collide with
  whiskers; whiskers visibly thinner than bars.
- **Probabilities:** replace the multi-line "Chance of at least…" chart with
  a **heat table** (rows = thresholds, columns = days/windows) with the %
  printed in every cell, a color-blind-safe sequential palette and
  auto-contrast text. Same component in Powder Finder popups if useful.
- **Accumulation periods:** one period per axis. Next-36 h hourly chart and
  6-hourly extended chart are separate, or both shown as rate (in/hr) with
  the period stated.
- **Color:** color-blind-safe palettes (e.g. Okabe–Ito for categories);
  never rely on color alone — summit vs base use solid vs dashed lines too;
  WCAG AA contrast (4.5:1) for all text, including chart labels and the
  pale snowfall swatches.
- **Reference lines labeled in place:** 32 °F, base/summit elevations, zero.
- **Mobile:** each panel ≥ 200 px tall at 375 px width; tap tooltips with
  large targets; disable chart drag/zoom on touch so the page scrolls
  normally. Charts below the fold render lazily when scrolled into view.
- **Every chart has** a one-sentence summary above it (also used as its
  aria-label) and a **"View as table"** toggle.
- Implement once as a shared theme/helpers module (e.g.
  `web/js/charts/theme.js`); keep Plotly unless it truly can't meet these
  standards.
- **Acceptance:** Lighthouse accessibility ≥ 95 on every page; screenshots
  at 375 and 1280 px; a "5-second test" note per chart (what a skier reads
  first).

### 6-C Basemap reliability (Nov 8)
- Set `maxNativeZoom` per tile layer and allow overzoom so tiles scale up
  instead of disappearing (USGS shaded relief tops out well below street
  zooms).
- Watch `tileerror`; after repeated failures switch automatically to a
  fallback provider and update the attribution. Check each provider's
  usage terms before adding it.
- Log tile failure counts in a debug panel or console during testing.

---

## 7. Architecture notes

- New pipeline modules: `pipeline/catalog.py`, `pipeline/nbm/`,
  `pipeline/nws.py`, `pipeline/points.py` (shared sampling + period
  summaries), `pipeline/layers/` (3857 regrid + value PNG encoder).
  Same rules as CLAUDE.md: fetch separate from pure functions; offline tests
  with fakes; sources fail independently.
- CI: add an `nbm.yml` workflow (or a job in `models.yml`) publishing points +
  layers as a Release asset like the models; site build merges everything.
  Each job < 30 min; site < 900 MB (aim < 400 MB).
- Size budget: points ≈ 200 areas × ≤150 KB ≈ 30 MB; interactive layers
  should be smaller than today's per-domain PNGs.
- Schedules are best-effort on GitHub. If gaps persist, add an external
  trigger (free cron service calling `workflow_dispatch` with a fine-grained
  token) — owner decision.

---

## 8. Roadmap — milestones with acceptance criteria

Work top-down. Each milestone = its own commits with tests + a live run +
screenshots checked. Suggested session grouping in brackets.


### Roadmap order (Nov 8 b, replaces earlier "next" ordering)

Done: M0–M5, M3.5, M3.6, M9-prep (archive), dev6 fixes, dev7 (Expected
rename, day-10 temp/wind panels, Sno-Park research).

**Track 1 — Forecast pages (highest priority)**
1. **M4.5 Sno-Parks & winter recreation points** (approved sources: USFS
   EDW + OSM; scope ~450 Sno-Parks/snowplay/Nordic). [next session]
2. **M7 Precipitation by model at each point** — HRRR, RRFS, GFS (+ NBM)
   cumulative snow/QPF and snow level on one chart, from the existing
   model pipeline. Meteorologist-grade but readable (§6-B).
3. **Powder quality** indicator (SLR + wind, §5.2 heuristic), clearly
   labeled as a heuristic, on area pages and in the finder.
4. ✔ (S9) **"My mountains" home view** — mine.html + js/mine.js: one card per favorite (ski areas, Sno-Parks, SNOTEL): expected 24/72 h with NBM 10–90 %, chance of ≥ 6" (first 24/72-h windows), lowest snow level while precip is likely vs the base, alerts, avalanche danger; empty state explains ☆; remove from the card. Nav link "★ My mountains" on every page (short labels on phones). Lighthouse 100. Landing-page question open. Original text:: favorites dashboard (next 24/72 h
   expected + chance of ≥ 6", snow level, alerts) as the landing page for
   returning visitors.
5. **Point verification panel** (after ~4–6 weeks of archive data): "How
   did forecasts do here this season?" per site; feeds M9.

**Track 2 — Obs map (in parallel / alternating with Track 1)**
6. ✔ (S8) **Obs map mobile performance pass** — Lighthouse mobile (gzip, like Pages) 81 → 87: tiles and all data start at once (no wait for meta.json), compact data/map_points.json (ski areas + Sno-Parks) instead of full catalogs, Leaflet self-hosted (web/vendor, BSD-2), preconnect to USGS tiles, Plotly fetched on first interaction. Original text:: stations and overlays render
   before basemap tiles finish; preconnect to tile hosts; smaller first
   payload. Target Lighthouse mobile performance ≥ 85 (currently 47–71).
7. ✔ (S9) **Snow forecast overlays on the obs map** — pipeline/nbm/layers.py at the end of the points job: 9 layers (expected 24 h / 72 h / 7 d; P(≥4/6/12") 24 h and 72 h), first windows ending 12Z, full-suite cycles only; ~0.3 MB total (7 d 210 KB, others 6–28 KB), ~9 s extra in the points job (local). Picker groups Observed / Forecast with window + NBM run; hover values; obs map Lighthouse (gzip) 86. Original text:: NBM expected snowfall
   (24/72 h) and chance of ≥ 4/6/12" as zoomable layers with hover values
   (NOHRSC layer system). This is the consumer replacement for most
   model-map use.
8. **Storm-total tracker**: observed snow over a selectable storm window
   (NOHRSC snowfall + SNOTEL depth/SWE change), map + per-site totals.
9. **Obs time slider**: step back through the last 24–72 h of
   observations/NOHRSC analyses.
10. **More observation networks** (research licenses first, ask before
    building): MADIS category-3 public mesonets, state DOT RWIS,
    avalanche-center telemetry (contact centers).

**Track 3 — Later**
11. **M9 Verification & bias correction** (site-wide scores; MOS-lite).
12. **M8 ECMWF IFS/AIFS** (point sampling first; synoptic charts later).
13. **M6 Zoomable model layers + HRRR pressure-level file** — last.

### Milestones (detail and history)

**M0 — Housekeeping** [Session 1]
- Remove HRRR/RRFS `h500`, `t700`; snow-level legend note.
- Bump all Actions to current major versions (clear Node 20 warnings); pin
  `runs-on: ubuntu-24.04`.
- ✅ when: CI green with no deprecation warnings; models.html no longer lists
  upper-air fields for HRRR/RRFS.

**M1 — Ski-area catalog** [Session 1]
- `pipeline/catalog.py`, `config/ski_areas.yml` overrides, `data/ski_areas.json`.
- Ski-area layer on the main map (distinct marker, click → area page stub).
- ✅ when: ≥ 150 western areas with base+summit coords/elevations; top 60
  hand-verified; joins to avalanche zone, nearest SNOTEL/ASOS, NWS grid, NBM grid.

**M2 — NBM point pipeline** [Session 1–2]
- Inventory check, fetch-once-sample-all, percentiles, elevation handling,
  periods, powder quality; CI job.
- ✅ when: `data/points/<id>.json` + `summary.json` for all areas; unit tests for
  period aggregation, lapse adjustment, snow-level→P(snow); a sanity report
  comparing NBM 24 h snow median with NDFD for 10 areas.

**M3 — Ski-area page v1** [Session 2]
- Headline numbers, day/night bars, snow-level chart, hourly meteogram, recent
  obs, avalanche danger, favorites, share link. Mobile-first.
- ✅ when: Chrome screenshots at 375 px and 1280 px look clean for 3 areas
  (wet PNW, Sierra, dry interior); loads < 2 s on a cold cache.
- ✔ Done (S2): decisions 1–7 applied; screenshots at 375/1280 px (Crystal, Mammoth,
  Alta). Lighthouse mobile (local server, no gzip): Crystal 88, FCP 1.2 s, LCP 1.2 s
  (was 2.3 s), TBT 470 ms (Plotly parse after first paint), 446 KB (was 805 KB).

**M3.5 — Snowpack overlays, SNOTEL forecasts, speed** [Session 2]
- Obs map performance (canvas markers, cached declutter, lazy Plotly).
- NOHRSC overlays: SNODAS SWE, depth, 24 h SWE change; NOHRSC 24/48/72 h
  snowfall analysis — built on the §5.4 interactive-layer system.
- NBM + NDFD point forecasts at every SNOTEL site (NDFD via AWS GRIB2).
- ✅ when: map interactions feel instant; overlays zoom smoothly with hover
  values; any SNOTEL station opens a forecast view.
- ✔ Performance done (S2): canvas symbols; 4x-CPU benchmark per zoom step 300–385 ms
  of long tasks -> 64–83 ms, pans 57–67 ms -> 0 ms, DOM 6,146 -> 227 elements; clicks
  first frame < 40 ms, chart 160–190 ms; Lighthouse 46 -> 72 (TBT 1,270 -> 132 ms).
- ✔ NOHRSC overlays done (S2): §5.4 layer system (EPSG:3857 value PNGs, browser colorizer,
  hover/tap readout, legend, opacity, one at a time, valid time); NOHRSC 24/48/72 h
  snowfall (3 km cells) + SNODAS SWE, depth, 24 h SWE change (1.5 km). SNODAS SWE vs
  SNOTEL (211 sites ≥ 1 in): r 0.87, MAE 0.67 in. Ski-area pages show both at base/summit.
- ✔ SNOTEL forecasts done (S2): NBM at all 837 SNOTEL sites (area.html#snotel-…), NDFD (NWS
  official) for every ski area and SNOTEL site from AWS GRIB2 with an NBM ↔ NWS toggle;
  linked from the SNOTEL panel on the obs map.

**M3.6 — Chart readability, accessibility & basemap reliability** [Session 5]
- Fix bugs B1–B7 (Nov 8 live review, below); apply §6-B to every existing chart; §6-C basemaps.
- ✅ when: Lighthouse accessibility ≥ 95 on all pages; no blank basemap at
  any zoom; before/after screenshots for each chart.
- Bugs found in the Nov 8 live review:
  1. Basemap tiles go blank when zooming in on the obs map and Powder Finder
     (seen on Powder Finder with Shaded relief).
  2. Powder Finder "Ridge" column shows "– mph" for every area, even for windows
     inside the HRRR/RRFS range.
  3. Powder Finder snow level shows "–" while the same row says 32% chance of ≥ 8" —
     the "dry" rule uses the wrong window or field. Snow level should show whenever
     meaningful precip is likely in the selected window.
  4. Snow-level chart caption is stale ("first 48 h"; the band now runs to day 10–11),
     and the band and the "snow to the base" zone use nearly the same blue.
  5. Hourly chart mixes 1-h and 6-h amounts on one axis. Never mix accumulation periods.
  6. Ridge-top wind stops after ~24–30 h; show HRRR then RRFS with a labeled handoff, or explain.
  7. "hatched = extended outlook" is in the bar-chart caption but no hatching is visible.
- ✔ S5: B1 basemap.js (overzoom + fallback), B2/B3 Finder (ridge states; per-window wet snow level), B4-B7 in the
  chart rework. §6-B: `web/js/charts/theme.js` (SnowCharts) for every chart on the area page (day/night bars,
  heat table, snow level, temperature, wind + ridge HRRR→RRFS, snow rate, nearest SNOTEL) and the obs-map
  SNOTEL panel (depth, SWE, temperature); summaries, "View as table", lazy drawing, explicit heights (a resize
  used to squash charts to 200 px). Found and fixed: hourly PoP was empty for 01/07/13/19Z cycles, so the
  snow-level "likely" line never showed. Lighthouse a11y 100 on all six pages (was 95–100); performance area
  91→91–94, SNOTEL page 91→94–98, obs map 47→71 (header CLS 0.33→0.02), models 81→90, finder 97–98.
- S6 (dev6) Part A, fixes from the owner's live review of dev5 (each with a headless-browser check in
  `tools/browser_check.py`, opt-in pytest `SNOWWX_BROWSER=1`):
  1. Grey map with an overlay at high zoom: not tile errors (0 errors, base layer never removed) but the
     L.ImageOverlay element growing to 267,986 × 285,569 px at z14 (beyond GPU limits). Overlays now draw on a
     view-sized canvas (`ViewOverlay`); fallback only reacts to the active base layer; ResizeObserver →
     invalidateSize. Powder Finder could not be made to fail headless (no overlay; possible inner-scroll/sticky
     cause removed by fix 2) — owner to recheck.
  2. One scrollbar: area/finder/about use document scrolling (`body.doc-page`), footer at the end; obs map and
     models keep the app layout. Checked at 1280/375 px and browser zoom 80/150 %.
  3. Header search on every page (`pipeline/search.py` → data/search.json, `web/js/search.js`; shared ranking with
     the obs-map search; combobox a11y; "/" shortcut; icon on mobile).
  4. Snow-level wet/dry: per-hour chance of precip with fallbacks (6-h PoP → 12-h period PoP → NBM P(≥0.1" snow)).
  5. Ridge wind: the note explains, the wind-panel summary carries both numbers (whole panel + next 24 h).
  6. End labels: collision-free placement (theme `endLabels`, explicit y ranges).
  7. SNOTEL depth and SWE: separate panels with their own axes from 0.
  8. Chances vs ranges (Timberline 72 h "most likely 4 in, 13–15 % ≥ 4 in"): legitimate. Same window/cell
     (idx: both "35-59 hour acc"). NBM's deterministic amount is above NBM's median in 99 % of wet windows;
     P(≥ deterministic) ≈ 32 % (24 h) / 38 % (72 h). NBM's percentile and probability products disagree > 10
     points in only 0.1–0.4 % of checks (Timberline day 2 is one). about.html explains; wording is an owner decision.
  9. "1 ski areas" → singular; no-snow statement instead of an empty snow-rate chart.
  Follow-up: area pages reserve the viewport height (footer jump, CLS 0.098 → 0) and write the first chart's
  summary before Plotly loads (SNOTEL page LCP 4.8 → 2.1 s).
- 5-second test (what a skier reads first): day/night bars — the tallest bar and the number on it; heat table —
  the darkest cell (best odds) and its day; snow level — whether the solid line is under the Base line, and
  when; temperature — summit/base above or below the labelled 32 °F line; wind — the green ridge-top line's
  peak vs the summit wind; snow rate — when the tallest bar is; nearest SNOTEL — depth rising or falling this
  week; obs-map panel — depth trend, SWE, freezing or not.

**M4 — Powder Finder** [Session 2–3]
- Map + sortable/filterable table (state/region; 24 h / 72 h / 7 d; range;
  snow level; wind), favorites first.
- ✅ when: sort/filter work on mobile; markers use the shared snowfall palette.
- ✔ Done (S3): finder.html — 160 areas, 24 h/72 h/7 d/10 d (NBM) or 24/72 h (NWS), summit/base,
  state/region filters, sort by snow / observed 24 h / snow level, favorites first, Leaflet map
  (shared SNOWFALL palette) loaded after the list. Lighthouse mobile 99 (FCP 1.1 s, LCP 2.1 s,
  TBT 59–86 ms, CLS 0, 243 KB), accessibility 100.
- ✔ S4 (dev4) A: "Most likely ↔ Chance of" toggle. Chance mode = NBM's own exceedance probabilities
  (24/48/72 h windows ending 12Z, skier chips 4–24" / to 36" / to 48"), forecast-window select,
  summit/base, sorted by chance, shared PROB palette (table + map), NWS disabled with a note,
  ⓘ → about.html. Shows NBM's mean over the same window as "most likely". URL: m, pw, px, pd.
  Data: points/exceed_summary.json (lazy, ~220 KB). Area pages: "Chance of at least…" chart
  (24/48/72 h, lines per threshold). Lighthouse mobile 98 (FCP 1.1 s, LCP 2.3 s, TBT 78 ms, CLS 0).

**M4.5 — Sno-Parks & winter recreation points** [Session 5+]
- §5.6. ✅ when: western Sno-Parks cataloged with sources; each opens a
  forecast view; Powder Finder Type filter works on mobile.
- ✔ Done (S8, dev8): `python -m pipeline catalog --rec` → data/rec_points.json: 447 points (407 USFS EDW, 40 OSM)
  in 10 states (WA 103, OR 102, MT 71, CA 42, ID 39, UT 24, WY 24, CO 22, NM 12, AZ 8; 344 Sno-Parks, 54 winter
  trailheads, 30 snowplay, 19 Nordic). Trailhead + "high terrain" (highest 3DEP within 5 km, one 81×81 exportImage per
  site); full 3DEP cell averages (741 new cells). Cold build 38 min, cached rerun 3 min. Same record shape as ski areas
  (base = trailhead, summit = high terrain) → NBM/NDFD points, alerts, AFD, NOHRSC/SNODAS samples, archive, search.
  Area page "snopark" view: key facts first (avalanche danger, SNODAS trailhead depth, coldest 24 h wind chill,
  permit, activities (inferred marked), agency, source); wind chill line. Powder Finder Type filter (Ski areas /
  Sno-Parks / All, square symbols); obs-map Sno-Parks layer; about.html attribution. Points job: 1,832 cells (was
  1,090), local 4 m 44 s (network-bound; downloads unchanged); points output 25 → 44 MB, NDFD 9 → 14 MB, site 168 →
  197 MB; archive 20.8k → 36.9k NBM rows per cycle (~0.3 MB gz). Browser check `snoparks`.
- S7: source research done → docs/sources_recreation.md (USFS EDW public domain: 375 western winter sites;
  OSM ODbL: 182; WA/OR/CA/ID state lists have unstated or "All Rights Reserved" terms). Approved (S7): EDW + OSM, Sno-Parks + snowplay + Nordic; build next session.

**M5 — NWS official** [Session 3]
- NDFD base/summit, alerts banner, AFD link; NBM ↔ NWS toggle; about.html
  methods/attribution page.
- ✅ when: a test area under an active alert shows the banner; NDFD and NBM
  render side by side without mixing.
- ✔ Part 1 done (S3): active NWS alerts (one api.weather.gov call for 11 states, hourly with the
  obs build) matched by NWS zone/county codes and polygons → banner on area pages (expandable
  text), badge in Powder Finder, red ring + popup list on the obs map. Checked with a recorded
  sample (no winter alert touched a ski area on 7 Nov).
- ✔ Part 2 done (S4): `pipeline/afd.py` obs source (latest AFD for the 28 WFOs covering ski areas
  and SNOTEL points; 56 api.weather.gov calls, ~4 s, 184 KB) → area pages "Forecaster discussion"
  (issue time, weather.gov link, collapsible text loaded on open, paragraphs mentioning the area's
  name/region highlighted). about.html (methods, sources, attribution, disclaimer) in the nav; ⓘ
  tooltips link to it.
- ✔ S4 C: ridge-top (free-air) summit wind from HRRR (0–48 h) / RRFS (to 84 h), sampled during the
  model runs (no extra downloads beyond the u/v/HGT level messages), on area pages (meteogram +
  "next 24 h" note) and as Powder Finder's "Ridge" column; about.html explains why NBM 10 m wind runs
  lower on exposed summits. Live check 00Z 8 Nov: Timberline ridge 57–79 mph SW vs NBM summit wind
  ~37 / gust 53 mph. Lighthouse: finder 96–98, area page 85 → 90 (charts drawn one per task).

**M6 — Interactive model layers** [Session 3]
- 3857 value PNGs + client colorizer + hover readout for HRRR/RRFS surface
  fields; zoom presets replace subregion PNG sets; synoptic tab keeps GFS PNGs
  with pan/zoom.
- ✅ when: smooth zoom from west view to a single canyon; hover values match
  the source grid within quantization; total model storage ≤ today's.

**M7 — Precipitation by model at each area** [Session 4]
**M8 — ECMWF IFS/AIFS** (synoptic charts + point sampling; CC BY 4.0 credit) [Session 4]
**M9-prep — Forecast archive** [Session 5, small, time-sensitive]
- All daily leads (Decisions log, Nov 8). ✅ when: first monthly file appears in
  the `verification` release and docs/verification.md documents the format.
- ✅ Done (Nov 8): PR #6 merged; nbm/ndfd/snotel-202611.csv.gz are on the `verification` release.
- ✔ Code done (S5): `pipeline/archive.py` + `python -m pipeline archive`, run by update-site.yml after
  every build (continue-on-error). Monthly `nbm|ndfd|snotel-YYYYMM.csv.gz` + `state.json` on the
  `verification` prerelease; NBM points now carry per-window cell percentiles and the cell mean.
  Local dry run (01Z 8 Nov): 20,826 NBM rows (154 KB gz), 2,314 NDFD, 5,691 SNOTEL; rerun adds
  nothing. Starts collecting once merged to main.
- ✔ Local disk hygiene (S5): every run prunes data_cache files older than 2 days (keeps catalog/
  and openskimap/) and logs disk use (`pipeline/cache.py`, settings `cache:`).

**M9 — Verification & bias correction**: score NBM/NDFD/models vs SNOTEL 24 h
snow & temps by area/elevation; publish on about.html; later a per-site
bias correction (MOS-lite) [later]
**M10 — Alerts/notifications, webcams (links), ensembles plumes** [later]

---

## 9. Data licensing summary

| Source | Terms |
|---|---|
| NOAA/NWS (NBM, NDFD, HRRR, RRFS, GFS, api.weather.gov) | Public; credit NOAA/NWS |
| USDA NRCS AWDB (SNOTEL) | Public domain |
| Iowa Environmental Mesonet | Any lawful use incl. commercial |
| avalanche.org | Show unaltered, expire correctly, link to full forecast |
| ECMWF open data | CC BY 4.0 — "© ECMWF" on images and pages |
| OpenSkiMap / OpenStreetMap | ODbL — attribution; derived catalog shared under ODbL |
| USGS basemaps/3DEP | Public domain |
| MADIS | Only category 3 "full distribution" on public pages |
| Synoptic | Not used |

---

## 10. Known limitations & open questions

- Accessibility: map stations are drawn on a canvas, so the search box is the only keyboard
  route to an individual station or ski area (owner-accepted gap, S3).

- Kuchera/snow level from 5 pressure levels; Stull wet-bulb warm bias in dry air.
- NBM grid (2.5 km) under-resolves narrow ridges/valleys → elevation
  adjustment is approximate; verification (M9) will quantify.
- GitHub cron reliability for hourly obs.
- Open: external trigger service? custom domain (e.g. snow-wx.com)? app-like
  PWA (installable, offline favorites) after M4?

---

## 11. Monetization readiness (back burner — do not build unless asked)

Goal: be able to charge money, if the owner decides to, without legal,
hosting or brand problems. Decision point: **fall 2027**, using a
season of usage analytics and verification results.

### 11.1 Brand & naming
- **Rename "Powder Finder"** — OpenSnow announced a "Powder Finder Map"
  (2026–27 release). Pick a distinct name before any commercial launch.
- Check availability of the site name (trademark search, domain,
  social handles).

### 11.2 Hosting & infrastructure
- GitHub Pages is not allowed as hosting for an online business or
  commercial SaaS, and has a ~100 GB/month soft bandwidth limit → plan a
  move to a commercial-friendly static host (e.g. Cloudflare Pages,
  Netlify) with a custom domain. Keep the GitHub Actions pipeline.
- Repo visibility: GitHub Actions is free only for public repos. A
  private repo would exceed free Actions minutes at the current schedule
  (estimate the monthly cost before deciding). Public code is legal to
  keep but copyable — owner decision.
- Paid features like alerts need a small backend (accounts, scheduler,
  email/SMS/push) — estimate cost and complexity before committing.

### 11.3 Data & license audit (commercial use)
| Source | Status for commercial use |
|---|---|
| NOAA/NWS (NBM, NDFD, HRRR, RRFS, GFS, NOHRSC, api.weather.gov) | OK; attribute |
| USDA NRCS AWDB (SNOTEL), USGS (3DEP, basemaps) | Public domain |
| Iowa Environmental Mesonet | OK (any lawful use incl. commercial) |
| ECMWF open data | OK with CC BY 4.0 attribution |
| OpenStreetMap / OpenSkiMap / OSM Sno-Parks | ODbL: attribution; derived databases shared under ODbL |
| USFS EDW | Public domain |
| **avalanche.org API** | **Verify** commercial-use terms; contact if unclear |
| **OpenTopoMap tiles** | **Verify**: CC-BY-SA + fair-use policy; heavy commercial traffic may need self-hosted or paid tiles |
| State Sno-Park lists (WA/OR/CA/ID) | Not copied; ask permission if ever needed |

### 11.4 Legal & trust
- Terms of use, privacy policy, clear safety/avalanche disclaimers
  (already on site; review for a paid product).
- Consider liability insurance before charging.
- Accuracy claims only from our own published verification (M9).

### 11.5 Measurement (low effort, can be done earlier if the owner wants)
- Privacy-friendly analytics (no cookies/personal data) to learn which
  pages and sites are used.
- Optional feedback link.

### 11.6 Candidate business models (to evaluate, not build)
- **Freemium**: core forecasts/probabilities free; paid **alerts**
  ("notify me when Alta has ≥ 50% chance of ≥ 12""), synced favorites,
  ad-free.
- **B2B**: custom pages/data feeds for ski patrols, guide services,
  snowmobile clubs, small ski areas, avalanche centers.
- **Sponsorships**: local shops, avalanche education, regional brands.
- **Supporters**: voluntary memberships/donations.

### 11.7 Differentiators to emphasize (verify before marketing)
- Exceedance probabilities ("chance of ≥ X"), NBM + NWS side by side,
  snow level vs each mountain, avalanche + SNOTEL + NOHRSC in one place,
  Sno-Park/snowmobile coverage, public verification record, free core.
- Competitor reality check: OpenSnow has ranges, model comparisons,
  native apps with push alerts, human forecasters and PEAKS 2.0 — don't
  claim features they lack without checking.

## Sources
- OpenSnow 2026–27 winter release (PEAKS 2.0, Powder Finder Map): https://opensnow.com/news/post/2026-2027-winter-release
- OpenSnow PEAKS 2.0: https://opensnow.com/peaks
- NBM v4.1 new elements (snow level & SLR percentiles, 1 h snow percentiles): https://weather.gov/media/mdl/nbm/docs_v41/new_nbm_v4.1_wx_elements.pdf
- NBM documentation: https://blend.mdl.nws.noaa.gov/nbm-documentation
- NWS snow level definition (0.5 °C wet-bulb, Western US): https://ams.confex.com/ams/104ANNUAL/webprogram/Handout/Paper434400/Integrating%20Probabilistic%20Data%20into%20Operations%20for%20a%20Deterministic%20Forecast%20Process.pdf
- OpenSkiMap / ODbL: https://wiki.openstreetmap.org/wiki/OpenSkiMap
