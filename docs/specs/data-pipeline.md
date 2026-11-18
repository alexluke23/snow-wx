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
- **Powder quality** (documented heuristic, not an accuracy claim): ONE definition, `config/settings.yml` `powder_quality`
  (`dense_below: 10`, `blower_at: 15`; mirrored by `web/js/colors.js` `POWDER_Q`, a test keeps them equal): SLR median ≥ 15
  "Blower", 10–15 "Medium", < 10 "Dense"; add "wind-affected" when summit gusts ≥ 30 mph during snowfall. The same three
  classes drive the SLR/powder panel, the Finder and My mountains "Type", the W3 rules and about.html.
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
- **Previous copy on CI (owner Nov 17: option A):** `pipeline restore` downloads the live site's `meta.json`, `snotel.geojson`
  and the young station files (`SITE_ORIGIN` / `site.origin`) before every build; no secrets, no extra assets. Timestamps are
  preserved, so a stale copy can never be re-stamped fresh (test: five failed runs, `obs_time`/files unchanged, age grows).
  While stale, the 24 h / 72 h changes are hidden once the data are older than that window.
- NBM/NDFD forecasts at SNOTEL sites use the committed `data/snotel_points.json`, not AWDB.

### 5.2c Data-health monitoring (`pipeline/monitor.py`, W5a slice)
- `meta.json` per source: `last_success_at`, `consecutive_failures`, `outage_since`. Limits per source in config
  `monitoring.sources`, from the source's real cadence: hourly obs sources = 3 consecutive failures or 6 h; points (job every
  6 h, ~1.7 h model lag) 14 h; NDFD and model maps (job every 3 h) 10 h; NOHRSC 30 h.
- The `monitor` job in `update-site.yml` runs after the deploy (`needs: [build, deploy]`, `if: always()`, `continue-on-error`),
  reads the LIVE meta.json and opens/updates/closes ONE issue per unhealthy source ("Data health: <source>", label
  `data-health`, assigned to `monitoring.assignee` so GitHub e-mails them). Uses only the workflow's `GITHUB_TOKEN`
  (`issues: write`); no secrets. It cannot fail the deploy: separate job after deploy, `continue-on-error`, script always exits 0.
- **Bootstrap rules (dev15):** `consecutive_failures` restarts on a fresh runner and is absent in old-format meta.json, so a failing source
  (`ok:false`, `stale` or `unavailable`) is also judged by the data's own clock (`observed_through` / `last_observed`), `last_success_at`
  and `outage_since` (first seen failing): breach when that age exceeds `max_age_hours`; a failing source with no clock at all breaches at the failure limit.
  Stale and unavailable count as at least one failure. Every run prints one line per source (`snotel: state=stale failures=1/3 age=9.0h(data time)/6h
  -> BREACH ... | action: open issue`) so the Actions log explains the decision. Tests: `tests/test_monitor_bootstrap.py` (replayed meta states, real-outage path).
- Delivery: GitHub e-mails the assignee (Settings → Notifications → e-mail on); the GitHub mobile app gives push.
- **Test input:** `update-site.yml` has a manual `simulate_failure=<source>` input (workflow_dispatch only; sets
  `SIMULATE_FAILURE`): the source fails as if its service were down (SNOTEL goes through the real stale/unavailable path), so
  the status text, banner and the monitor's issue can be verified live; the next normal run recovers.
- **Heartbeat (built, inactive until configured):** the `monitor` job's last step pings the URL in the repository secret
  `HEALTHCHECK_URL` only when the build AND deploy succeeded; no secret = skipped; `continue-on-error`. Setup: create a free
  Healthchecks.io account → new check "snow-wx hourly", period 1 h, grace 3 h, e-mail alert → copy its ping URL → repo
  Settings → Secrets and variables → Actions → New repository secret `HEALTHCHECK_URL`.
- **Known gap (the heartbeat above covers it once configured): a check inside the hourly workflow cannot notice that the workflow did not run at all**
  (GitHub's schedules are best-effort and can pause for hours). Independent options for W5a, in order of recommendation:
  1. **Dead-man's-switch heartbeat (Healthchecks.io free tier, or similar):** the hourly job `curl`s a ping URL at the end;
     the service e-mails the owner when no ping arrives within a grace period (e.g. 3 h). Independent of GitHub, so it also
     catches a paused scheduler. Needs one secret (`HEALTHCHECK_URL`) and an account; the ping step is `continue-on-error`.
  2. **Cloudflare Worker cron (after W1):** a scheduled Worker fetches the live `meta.json`, e-mails/pushes when `generated_at`
     is older than ~3 h, and can call `workflow_dispatch` to restart the pipeline (this is also the "external cron trigger"
     of PLAN §11, decision 8). Needs a fine-grained token secret.
  3. **Second GitHub scheduled workflow (`watchdog.yml`, every 6 h, offset):** cheap and secret-free, but it shares GitHub's
     scheduler, so it only protects against a failure of one workflow, not of the scheduler.

### 5.3 NWS official layer (NDFD + alerts + discussion)
`api.weather.gov` with our User-Agent; `/points` lookups cached in the catalog.
Per run: gridpoints raw layers for base & summit (dedupe shared cells). One
`/alerts/active` call per run → zone match → banner on the area page. Latest AFD
per WFO (issue time + link; public domain). Always an "NWS official" toggle/
column beside NBM — never silently mixed. Credit NOAA/NWS; never imply NWS
endorsement or use NWS logos.

### NBM forecast overlays on the obs map: audit (dev17)
Built earlier (`pipeline/nbm/layers.py`, `web/js/overlays.js`, "Forecast" group). dev17 checked it against the brief and added the missing pieces.
- **Which layers exist (from the real `.idx` files, 07Z cycle Nov 18):** expected snowfall 24 h and 72 h (native ASNOW deterministic windows ending 12Z), chance of ≥ 4 / 6 / 12 in for 24 h and 72 h (native ASNOW exceedance messages at 0.1016 / 0.1524 / 0.3048 m), and a 7-day expected total. No other thresholds or windows were synthesized; the layer is omitted when its message is not in the file (build log line "not in fNNN"). The 7-day layer adds NBM's seven native 24 h EXPECTED amounts (a total of expected values; no percentile is added), and the legend text says so. Only the 01/07/13/19Z cycles have these fields (other cycles: "skipped").
- **Format/size:** value-encoded EPSG:3857 PNGs on a 2.5 km grid (1025 × 1091), drawn on a view-sized canvas; 9 layers = **1.72 MB** in total (nbm24 167 KB, nbm72 333 KB, nbm7d 441 KB, probabilities 49-233 KB); decoded only when a layer is picked (the browser check asserts 0 PNG requests at load). **Added CI time: 8.8 s** per points run (3 `.idx` lookups + range reads), measured.
- **Colours:** amounts use `colors.js` SNOWFALL (NWS table) with the shared legend; chances use `PROB`, a single-hue sequential blue ramp whose lightness now falls monotonically (the old purple/magenta top steps were equal in lightness; dE ≥ 7.8 between steps under simulated deuteranopia / protanopia / tritanopia, DESIGN §6-B).
- **State shown:** default OFF; legend; cycle, valid window, "run started <local time>" and the grid-cell caveat; **stale data greyed**: a layer whose model cycle started more than `forecast_overlays.stale_hours` (14) ago is drawn grey at ≤ 40 % opacity with an "Out of date" note (browser check: 3 h old = normal, 30 h old = grey + note).
- **Switch:** config `forecast_overlays.enabled` (written to `data/meta.json`); false removes the whole Forecast group. It stays true: obs-map Lighthouse (6 interleaved runs, gzip server, same data) dev17 median 89 vs main 88; accessibility 100.
