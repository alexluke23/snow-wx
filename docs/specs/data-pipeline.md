# Spec: Catalog, NBM point forecasts, NWS layer

> Read when working on `pipeline/catalog.py`, `pipeline/nbm/`, `pipeline/nws.py`, `pipeline/points.py`.
> Part of Snow-Wx docs v1.0 (Nov 15 2026). Index and priorities: `PLAN.md`.
> Section numbers (§) are kept from the original single plan so cross-references still work.

---

### 5.1 Ski-area catalog (`data/ski_areas.json`)
One record per area: `id` (slug), `name`, `state`, `region`, `base {lat, lon,
elev_ft}`, `summit {…}`, optional `mid`, `tz`, `url`, `avalanche_zone_id`,
`nearest {snotel[], asos[]}` (distance + elevation difference), `nws {wfo,
grid_x, grid_y}` for base & summit, `nbm_grid {i, j, elev_ft}` for base & summit.

- **Seed** from OpenSkiMap (OSM, **ODbL**: attribute "© OpenStreetMap
  contributors / OpenSkiMap"; publish our derived catalog under ODbL). Filter:
  western states, downhill, has lifts, operating.
- **Curate** base/summit from lowest/highest lift terminals; elevations from
  USGS 3DEP — never trust a single source. Hand-check the top ~60.
- Joins computed once in `pipeline/catalog.py`; versioned in git
  (`config/ski_areas.yml` overrides). No resort logos; no scraping of resort
  snow reports.

### 5.2 NBM point forecasts (primary engine)
- Source: NBM GRIB2 on AWS (`noaa-nbm-grib2-pds`, `core` + `qmd`), byte-range
  via Herbie. **Download each field once per cycle and sample all points.**
- Elements (verify in the `.idx` inventory): snowfall 1 h/6/12/24 h with
  percentiles 10/25/50/75/90; QPF + PQPF; PoP; **snow level percentiles**;
  **SLR percentiles**; temperature/dewpoint/apparent; wind speed/dir/gust;
  sky cover; precip type probabilities; ice (FRAM) if present.
- Cadence: cycles reaching day 10–11 every ~3 h plus lighter 0–36 h refresh if
  CI time allows. Record cycle + issue time in every output.
- **Elevation handling** (documented on about.html): sample base and summit at
  their own coordinates; lapse-rate adjust temperature (6.5 °C/km start);
  P(snow at base/summit) from snow-level percentiles; flag mixed/rain.
- **Periods:** 6 AM–6 PM / 6 PM–6 AM local; p50 with 10–90 range per period and
  for 24 h / 72 h / 7 d / 10 d.
- **Powder quality** (documented heuristic, not an accuracy claim): SLR median ≥ 15
  "Blower", 10–15 "Medium", < 10 "Dense"; add "wind-affected" when summit gusts
  > 30 mph during snowfall.
- Output: `data/points/<id>.json` (hourly + period summaries) and
  `data/points/summary.json`. Target < 150 KB per area.

### 5.3 NWS official layer (NDFD + alerts + discussion)
`api.weather.gov` with our User-Agent; `/points` lookups cached in the catalog.
Per run: gridpoints raw layers for base & summit (dedupe shared cells). One
`/alerts/active` call per run → zone match → banner on the area page. Latest AFD
per WFO (issue time + link; public domain). Always an "NWS official" toggle/
column beside NBM — never silently mixed. Credit NOAA/NWS; never imply NWS
endorsement or use NWS logos.
