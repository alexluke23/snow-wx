---
status: current
owner: team
last_reviewed: 2026-11-23
read_when: you need the reason or date behind a rule, or want to add a decision
---

# Decision log

Newest first. One row per decision; when a later decision replaces one, the old row stays and is marked *Superseded*. Add new rows at the top of the table and mirror the ones that change current work in `docs/PLAN.md` §3. For a decision that needs context and trade-offs, write an ADR in `docs/adr/` and link it from the row.

## Standing decisions from Nov 6–8 2026

Full history (Nov 6–8) is in `docs/archive/ARCHIVE.md`. Standing decisions from that history still apply: NBM is the only forecast source shown (NDFD alongside is superseded, dev22); day/night 12Z–00Z; bars use NBM deterministic; point snow scaled by P(snow level below point); ~~model images as release assets~~ (model maps removed Nov 23); surface-only fields on HRRR/RRFS; chart readability and never-blank basemaps; ~~Sno-Parks as a point type~~ (removed Nov 23); obs map + forecast pages first.

## Log

| Date | Decision |
|---|---|
| Nov 23 | **Docs reorganised:** `docs/INDEX.md` map; PLAN ≤ ~20 KB; decisions here; work items in `docs/BACKLOG.md`; history in `docs/archive/`; retired specs in `docs/specs/retired/`. |
| Nov 23 | **M12 ML post-processing** opened as a research program (QPF, snowfall, SLR; SNOTEL QC); no site change before its R3 gate (`docs/specs/ml-postprocessing.md`). M11 becomes its SLR part. |
| Nov 23 | **Platform move** to GitLab.com + Cloudflare (Workers Static Assets, R2, D1, Containers + Workflows, WX API Worker); team of 3 developers; repo goes private on GitLab (`docs/specs/platform-transition.md`). Supersedes the Nov 15 "Cloudflare Pages" row. |
| Nov 23 | **Clarification (code review H6):** SNOTEL-site forecast *pages* go, but NBM forecasts at SNOTEL sites are **still computed and archived** (verification and M11/M12 score only these). |
| Nov 23 | **SNOTEL = observations on the site** (obs map, nearest obs, storm totals, verification ground truth). |
| Nov 23 | **Ski areas only:** Sno-Parks removed (M4.5 retired); old links redirect to the Finder; archive rows already written stay. |
| Nov 23 | **UI focus = NBM visualizations + model plumes.** |
| Nov 23 | **Model maps removed; M6 and synoptic charts cancelled.** Model fetch/sample code that feeds the plumes (HRRR/RRFS/GFS sampling, ECMWF, GEFS) stays and is decoupled from rendering first (review H5). |
| Nov 23 | **Models-page hotfix + test independence:** the map-model catalog lists only real map models; the browser suite must not read live points/multimodel/ensemble/catalog data (frozen snowy + dry fixtures, PR B); a live smoke script is built first, wiring it to automation is a later decision. |
| Nov 21 | **dev22 (owner feedback round):** the site is **NBM only**: the "NWS official" (NDFD) toggle, its state/URL/storage keys and wording are gone (NWS alerts, hazards, AFDs, avalanche links and NOAA/NWS attribution stay; the NDFD fetch and the archive's NDFD rows are untouched and the browser no longer requests `data/ndfd/`). Chart modules are lean (title, one takeaway, chart, legend, View as table, one source/issue-time line, "How it works" link to About "Reading the charts"). The snow-ratio chart is drawn only where precipitation is likely, one closed band per run, hatched dry strips. Model-run freshness is judged against when the NEXT run is due: latest / late / out of date (`web/js/freshness.js`; lags measured: ECMWF ENS +7.75 h, HRES +7.57 h, GEFS +5.65 h). `ecmwf.yml` now attempts hourly around the measured release (GitHub drops most cron events here). |
| Nov 21 | **dev23 (owner brief):** hide NDFD scores in the verification panel (NBM only on the surface; the archive keeps NDFD); stop deploying `data/ndfd/` (one workflow step; fetch and archive unchanged); build the external scheduler as code only (the owner deploys it); archive NBM SLR p25/p50/p75 additively (native hourly value at the window end hour, never derived across windows). |
| Nov 20 | **dev21 (owner brief):** two more owner-authorized workflows, `verify.yml` and `gefs.yml` (model on `ecmwf.yml`, publish product tars that update-site already unpacks; no edit to existing workflows); GEFS on; model chips change the drawing only (badge and table use every model); the verification panel stays OFF until the owner flips it. |
| Nov 19 | **dev18 (owner-authorized):** ECMWF goes live via its own workflow `.github/workflows/ecmwf.yml` (`ecmwf.enabled: true`); badge shows "Little precipitation expected" when every model is < 0.20 in (never "High"); webcams are links only; legal pages are DRAFTS (`noindex`); analytics and the verification UI are built but OFF (owner picks the provider / flips the flag). |
| Nov 19 | **dev19 (owner brief):** ECMWF goes through a resilient fetcher with mirror failover; a step that cannot be fetched is a GAP (all members + HRES, never interpolated), a run needs >= 90 % of the steps and the first 120 h, else it exits 0 with `new=false`. Plotly is self-hosted (privacy: no CDN request). Hazard popups never call api.weather.gov from the browser. Webcam links that cannot be verified are removed, not guessed. |
| Nov 19 | **dev20 (owner brief):** the site name is config-driven (`site.name`/`site.tagline` placeholders; set by owner at W1); share cards only with `pages` AND `og_images` on; AIFS shown as an experimental line, kept OUT of the agreement badge unless `aifs.in_badge`; the browser suite never depends on live data (frozen fixtures). |
| Nov 17 | **SNOTEL outage handling accepted** (stale ≤ 48 h flagged, per-source data-health issues, never fails the deploy): details in `docs/archive/ARCHIVE.md`. |
| Nov 17 | **Owner feedback → dev14:** default uncertainty range for snowfall, snow level and snow ratio = **25–75% ("likely")**; 10–90% only where noted; ONE powder-quality definition (config `powder_quality`); obs-map first-load layers: relief, roads, ski areas, NWS winter hazards. Full text: `docs/archive/ARCHIVE.md`. |
| Nov 17–18 | **dev15–dev17 (merged):** monitor judges a source by the data's own age; hazard popups show NWS text in-page; M7 precipitation by model (agreement badge = documented heuristic); M9 scorer excludes the SNOTEL outage; ECMWF, W7 wind flag and W6 alerts built OFF (details: `docs/archive/ARCHIVE.md`). |
| Nov 16 | **Drop the 7/10-day 10–90% ranges** (Finder, My mountains, area tiles): expected total only; keep native 24/48/72 h ranges. |
| Nov 16 | Partial first day keeps the **hatched grey expected bar**; legend/tooltip/aria: "partial day — expected amount, no range". |
| Nov 16 | SNOTEL 24 h depth change on the obs map: gains use NWS colors, losses stay brown, legend titled "Snow depth change" (compaction ≠ snowfall). |
| Nov 16 | **Composite ranges are never shown:** where a 24/48/72 h total would add several 6 h percentile windows (fallback cycles), show the expected total only; points JSON marks totals `native: true/false`. Archive columns unchanged (they never carry composite ranges). Lighthouse target: median of ≥ 3 interleaved runs ≥ 85. |
| Nov 16 | Model-map snowfall colors stay as is for now (backlog §8.4). **Guard:** points JSON and the forecast archive keep their existing fields (p10/p50/p90, P(≥4/8/12″), 24/48/72 h). *(Moot Nov 23: model maps removed.)* |
| Nov 15 | **Adopt:** Daily Snow summaries (W3), offline-first PWA (W4), multi-model incl. ECMWF (M7/M8). **Reshape** wind-loading (§5.9). **Open-Meteo API not used in production** (free tier is non-commercial only, §10). |
| Nov 15 | **Custom domain + Cloudflare Pages + R2** (W1; domain set by owner at W1); GitHub Pages stays a redirect/canonical stub (PWA/SEO tie to the origin; file-count limits). *(Superseded Nov 23: Workers Static Assets + R2, `docs/specs/platform-transition.md`.)* |
| Nov 15 | **Path-based prerendered area URLs** (`/ski/<state>/<id>/`) so ~600 pages are indexable (W2); old `#id` links redirect. *(Nov 23: ~160 ski-area pages; Sno-Parks removed.)* |
| Nov 15 | **Offline cache of the last forecast is always available** (trust; iOS push needs the install). |
| Nov 15 | **No numeric lee-aspect accumulation adjustment until verified** (M9); wind = informational flag, never an avalanche rating. |
| Nov 15 | **Alerts: email + web push first; SMS later, optional.** |
| Nov 15 | Models compared in **liquid-equivalent**, inches toggle via NBM SLR. |
| Nov 9 | Snowfall bars are simple **range bars**: NBM p25–p75 as "low–high″", no expected tick, no 10–90% on that chart (10–90% stays on 24/48/72 h totals, snow level, SLR). |
| Nov 9 | **NWS snowfall color table site-wide**, one definition in `colors.js` (source: NOHRSC National Snowfall Analysis legend) for bars, tiles, Finder, overlays, legends. |
| Nov 9 | Accumulated snow = **NBM expected running total by day only**; no probabilistic checkpoint bars. |
| Nov 9 | **Native NBM windows only; never sum percentiles.** NBM has no 12 h snowfall percentiles → the chart is "Snowfall by day" (12Z–12Z, native 24 h p25/p75). |

## Older history

Nov 6–8 decisions and everything trimmed from PLAN before Nov 23: `docs/archive/ARCHIVE.md`.
