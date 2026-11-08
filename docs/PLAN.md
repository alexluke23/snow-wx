# Snow-Wx — Product Plan & Development Framework (v0.4, Nov 7 2026)

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

## 2. Status (Nov 7 2026)

- **Live:** https://alexluke23.github.io/snow-wx/ — repo `alexluke23/snow-wx`.
- **Observations map:** SNOTEL (837), ASOS (545), avalanche danger (70 zones);
  search, shareable URL hash, declutter, smoothed depth charts.
- **Model maps:** HRRR, RRFS, GFS — 10 fields, 6 domains (GFS west only), loop
  viewer; `models.yml` CI every 3 h → Release assets (`model-maps`) → site.
  Site ≈ 240 MB. First CI run green.
- **Session 1 (dev2, Nov 7):** M0 done; M1 catalog (161 areas, 60 major,
  3DEP elevations); M2 NBM points (fixed NBM alternating-row decode bug;
  matches NBM bulletins); M3 area page v1 reviewed — consistent with NWS.
- **Not started:** NDFD, ECMWF, NOHRSC overlays, Powder Finder.
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

**M4 — Powder Finder** [Session 2–3]
- Map + sortable/filterable table (state/region; 24 h / 72 h / 7 d; range;
  snow level; wind), favorites first.
- ✅ when: sort/filter work on mobile; markers use the shared snowfall palette.

**M5 — NWS official** [Session 3]
- NDFD base/summit, alerts banner, AFD link; NBM ↔ NWS toggle; about.html
  methods/attribution page.
- ✅ when: a test area under an active alert shows the banner; NDFD and NBM
  render side by side without mixing.

**M6 — Interactive model layers** [Session 3]
- 3857 value PNGs + client colorizer + hover readout for HRRR/RRFS surface
  fields; zoom presets replace subregion PNG sets; synoptic tab keeps GFS PNGs
  with pan/zoom.
- ✅ when: smooth zoom from west view to a single canyon; hover values match
  the source grid within quantization; total model storage ≤ today's.

**M7 — Precipitation by model at each area** [Session 4]
**M8 — ECMWF IFS/AIFS** (synoptic charts + point sampling; CC BY 4.0 credit) [Session 4]
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

- Kuchera/snow level from 5 pressure levels; Stull wet-bulb warm bias in dry air.
- NBM grid (2.5 km) under-resolves narrow ridges/valleys → elevation
  adjustment is approximate; verification (M9) will quantify.
- GitHub cron reliability for hourly obs.
- Open: external trigger service? custom domain (e.g. snow-wx.com)? app-like
  PWA (installable, offline favorites) after M4?

## Sources
- OpenSnow 2026–27 winter release (PEAKS 2.0, Powder Finder Map): https://opensnow.com/news/post/2026-2027-winter-release
- OpenSnow PEAKS 2.0: https://opensnow.com/peaks
- NBM v4.1 new elements (snow level & SLR percentiles, 1 h snow percentiles): https://weather.gov/media/mdl/nbm/docs_v41/new_nbm_v4.1_wx_elements.pdf
- NBM documentation: https://blend.mdl.nws.noaa.gov/nbm-documentation
- NWS snow level definition (0.5 °C wet-bulb, Western US): https://ams.confex.com/ams/104ANNUAL/webprogram/Handout/Paper434400/Integrating%20Probabilistic%20Data%20into%20Operations%20for%20a%20Deterministic%20Forecast%20Process.pdf
- OpenSkiMap / ODbL: https://wiki.openstreetmap.org/wiki/OpenSkiMap
