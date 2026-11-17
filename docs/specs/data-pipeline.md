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

### 5.2b SNOTEL observations and outages (`pipeline/snotel.py`)
Source: NRCS AWDB **REST** API (`wcc.sc.egov.usda.gov/awdbRestApi/services/v1`; the SOAP web service is being phased out).
Per run: a one-station health probe (10 s), then stations per state and hourly/daily data in chunks, under a hard time limit
(`snotel.max_seconds`) with a circuit breaker (`max_consecutive_chunk_failures`). A down service costs seconds per hourly run.
- **Last good copy:** the previous `snotel.geojson` + `snotel/*.json` in the output folder; stations whose latest observation is
  younger than `snotel.max_age_hours` (48) are kept with their ORIGINAL timestamps and `stale`/`age_h` flags; older ones are
  deleted. `meta.json` `sources.snotel` gets `stale`+`age_h`+`observed_through`, or `unavailable`+`last_observed`.
- **Recovery:** the first successful run replaces everything and clears the flags; no manual step.
- **UI:** `web/js/snotel-status.js` words it ("SNOTEL observations are X h old", "unavailable since <date>") on the obs map
  (banner, greyed markers), station panel and area-page "Recent observations". Old values are never shown as current.
- **Per-source history** (`meta.json`): `last_success_at`, `consecutive_failures`, `outage_since` (history needs the previous
  meta.json; on a fresh CI runner it restarts until the previous live copy is restored, see PLAN §2).
- NBM/NDFD forecasts at SNOTEL sites use the committed `data/snotel_points.json`, not AWDB.

### 5.3 NWS official layer (NDFD + alerts + discussion)
`api.weather.gov` with our User-Agent; `/points` lookups cached in the catalog.
Per run: gridpoints raw layers for base & summit (dedupe shared cells). One
`/alerts/active` call per run → zone match → banner on the area page. Latest AFD
per WFO (issue time + link; public domain). Always an "NWS official" toggle/
column beside NBM — never silently mixed. Credit NOAA/NWS; never imply NWS
endorsement or use NWS logos.
