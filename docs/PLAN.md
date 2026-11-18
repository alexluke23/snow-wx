# Snow-Wx — Development Plan (v1.1, Nov 15 2026)

> Lean plan read by Claude Code at the start of every session (soft size cap ~20 KB). Detail lives in `docs/specs/`, `docs/DESIGN.md`, `docs/BUSINESS.md` and `docs/ARCHIVE.md` (see "Where things live"). Tick milestones in §8 as they land.
> Conventions: **[verify]** = re-check at source before relying on it; **◇** = stretch, drop first if behind.

---

## Where things live (read only what the task needs)

| Need | File |
|---|---|
| Every session | **this file** (`docs/PLAN.md`) |
| Catalog, NBM points, NWS layer (§5.1–5.3) | `docs/specs/data-pipeline.md` |
| Model maps (§5.4) | `docs/specs/model-maps.md` |
| Multi-model, ECMWF (§5.5) | `docs/specs/multi-model.md` |
| Sno-Parks (§5.6) | `docs/specs/sno-parks.md` |
| Daily Snow summaries (§5.7) | `docs/specs/daily-summaries.md` |
| PWA / offline (§5.8) | `docs/specs/pwa.md` |
| Wind-exposure flag (§5.9) | `docs/specs/wind-exposure.md` |
| Hosting, SEO, prerendered pages (§5.10) | `docs/specs/hosting-seo.md` |
| Alerts backend (§5.11) | `docs/specs/alerts-backend.md` |
| Charts, colors, maps UI (§6) | `docs/DESIGN.md` |
| Business, pricing, legal, positioning (§9–10.1) | `docs/BUSINESS.md` — **not for coding sessions** |
| History, old decisions, done milestones | `docs/ARCHIVE.md` |
| Forecast archive and M9 verification (files, columns, loading) | `docs/verification.md` — read for archive/verification work |
| NBM GRIB layouts per cycle, selection rules | `docs/nbm_inventory.md` — read before touching NBM fetch/decode or `inventory.py` |
| NBM exceedance probabilities vs percentiles | `docs/nbm_prob_consistency_*.md` — read when changing "Chance of ≥ X" |
| NBM percentiles vs the GSL 1-D viewer | `docs/nbm_validation_gsl_*.md` — read when validating NBM decodes |
| Sno-Park / recreation sources and licences | `docs/sources_recreation.md` — read before adding or changing a recreation source |

When a task starts, read this file, then only the spec(s) for the active milestone.

---

## 0. TL;DR

A free, open-data snow forecasting site for the western US — point forecasts for every ski area and Sno-Park, with probabilities, snow level, observations, avalanche context and public verification — growing into a small sustainable business. **Free-first:** no paywall before Feb 2027 at the earliest; full paid launch targeted pre-season (Sep–Oct 2027).

**Priority now:** Foundations (W1 domain/hosting, W2 indexable pages, W3 daily summaries, W4 PWA, W5 analytics/monitoring) → M7/M8 multi-model → W6 alerts. Details in §8.2.

**Hard rules for all code**
1. Safety info (avalanche danger, NWS alerts, snow level/rain-at-base, data freshness) is never gated or hidden.
2. Never present a heuristic as an accuracy claim or an avalanche rating. Label heuristics.
3. Open, license-clean data only; keep attribution (§10.2) on pages and charts.
4. One accumulation period per chart axis; **never sum, scale or interpolate percentiles across windows** (ranges come from one native NBM window); uncertainty shown by default as **p25–p75 ("likely", the middle half of NBM's outcomes) for snowfall, snow level and snow ratio**; 10–90% only where explicitly noted (DESIGN §6); sources + issue times on every module.
5. Sources fail independently; fetch separate from pure functions; offline tests with fakes.
6. Stay within static-host limits (20,000 files/deploy, 25 MiB/file) — bulk data goes to R2.

---

## 1. Principles & audience

Trust first (show uncertainty, issue times, sources; publish misses); safety info always free; the free product is the
marketing; paid = convenience/personalization/compute, never public data; web/PWA first; license-clean open data;
automation over people; ~8–12 h/week **[assumption — owner to confirm]**. Audience: skiers/riders, backcountry users,
snowmobile/Nordic/snowshoe users (Sno-Parks), meteorologists, later B2B (lodging, guides, shops, clubs, avalanche
centers). Full text: `docs/ARCHIVE.md`.

---

## 2. Status (Nov 17 2026, through dev14)

- **Live:** https://alexluke23.github.io/snow-wx/ — repo `alexluke23/snow-wx` (custom domain: W1).
- **Done:** M0–M5, M3.5, M3.6, M4.5 Sno-Parks, M9-prep archive (running), "My mountains", NBM forecast
  overlays, dev10 basemap (relief + OSM reference layer), **dev11–dev13** (merged), **dev14** (PR open: "likely" p25–p75 wording site-wide, snow-ratio/snow-level panels from native percentile series, one powder-quality definition, W3 on Finder/My mountains, public status page, obs-map first-load defaults + drawn-set bug fix, W1 plan docs), dev11: snow charts on native
  NBM windows ("Snowfall by day" p25–p75 bars, accumulated = expected running total), NWS snowfall colors
  site-wide, 7/10-day summed ranges removed. Details: `docs/ARCHIVE.md`.
- **Product:** obs map (SNOTEL 836, ASOS 544, avalanche, NOHRSC + NBM overlays); ~607 forecast points (ski areas,
  Sno-Parks) + 837 SNOTEL sites, NBM to day 10–11, NDFD, alerts, AFDs; Powder Finder; model maps on `models.yml`.
- **Known issues:** NRCS AWDB (SNOTEL) outage **over**. Last good run before it ≈ 11:25 UTC Nov 16; first failing run seen 22:07 UTC Nov 16; still down
  02:21 UTC Nov 17. The forecast archive now holds 821 stations for 2026-11-17 12Z, so a fetch succeeded after 12Z Nov 17: recovery lies between
  02:21 UTC and ≈ 13:26 UTC Nov 17 (the earlier "00:45Z Nov 18" was only the first success I looked at). The Nov 16 12Z row was later backfilled (820
  stations). **M9 still excludes SNOTEL obs 2026-11-16 12Z through 2026-11-17 12Z** until the backfilled rows are checked. No Data-health issue opened because the
  monitor (merged 13:26 UTC Nov 17) most likely started after recovery; dev15 hardens the bootstrap anyway (§3). Handling: probe, last good copy ≤ 48 h flagged stale, auto-recovery.
  Obs map Lighthouse mobile 71–88 (bimodal; target: no worse than main, baseline ≈ 82, median of ≥ 3 interleaved runs); site ≈ 220 MB / 5.6 k files.

---

## 3. Current decisions

Full history (Nov 6–8) is in `docs/ARCHIVE.md`. Standing decisions from that history still apply: NBM primary + NDFD alongside; day/night 12Z–00Z; bars use NBM deterministic; point snow scaled by P(snow level below point); model images as release assets; surface-only fields on HRRR/RRFS; chart readability and never-blank basemaps; Sno-Parks as a point type; obs map + forecast pages before model maps.

**Nov 15 2026 decisions — accepted by owner Nov 15**

| Date | Decision |
|---|---|
| Nov 15 | **Business intent is active.** Free-first; no paywall before Feb 2027; optional Founding Supporter soft launch Feb 2027 (Gate 3); full paid launch Sep–Oct 2027. |
| Nov 15 | **Adopt:** Daily Snow summaries (W3), offline-first PWA (W4), multi-model incl. ECMWF (M7/M8). **Reshape** wind-loading (§5.9). **Reject** Open-Meteo API in production (`docs/BUSINESS.md` App. A). |
| Nov 15 | **Custom domain + Cloudflare Pages + R2 before public promotion** (W1); GitHub Pages stays a redirect/canonical stub (Pages isn't permitted for online businesses; PWA/SEO tie to the origin; file-count limits). |
| Nov 15 | **Path-based prerendered area URLs** (`/ski/<state>/<id>/`) so ~600 pages are indexable (W2); old `#id` links redirect. |
| Nov 15 | **Offline cache of the last forecast is free** (trust, PWA installs). |
| Nov 15 | **No numeric lee-aspect accumulation adjustment until verified** (M9); wind = informational flag, never an avalanche rating. |
| Nov 15 | **Alerts: email + web push first; SMS later, optional.** **Payments via a merchant of record** at first (confirm with a CPA). |
| Nov 15 | Models compared in **liquid-equivalent**, inches toggle via NBM SLR. |

**Nov 9–16 2026 (dev11) — accepted by owner**

| Date | Decision |
|---|---|
| Nov 9 | Snowfall bars are simple **range bars**: NBM p25–p75 as "low–high″", no expected tick, no 10–90% on that chart (10–90% stays on 24/48/72 h totals, snow level, SLR). |
| Nov 9 | **NWS snowfall color table site-wide**, one definition in `colors.js` (source: NOHRSC National Snowfall Analysis legend) for bars, tiles, Finder, overlays, legends. |
| Nov 9 | Accumulated snow = **NBM expected running total by day only**; no probabilistic checkpoint bars. |
| Nov 9 | **Native NBM windows only; never sum percentiles.** NBM has no 12 h snowfall percentiles → the chart is "Snowfall by day" (12Z–12Z, native 24 h p25/p75). |
| Nov 16 | **Drop the 7/10-day 10–90% ranges** (Finder, My mountains, area tiles): expected total only; keep native 24/48/72 h ranges. |
| Nov 16 | Partial first day keeps the **hatched grey expected bar**; legend/tooltip/aria: "partial day — expected amount, no range". |
| Nov 16 | SNOTEL 24 h depth change on the obs map: gains use NWS colors, losses stay brown, legend titled "Snow depth change" (compaction ≠ snowfall). |
| Nov 17 | **dev13 UX package (overnight, assumptions flagged in the session report):** NBM-native P(≥2″) row for 24/48 h only (never derived); one combined snow-ratio + powder-quality panel; linked Finder state/region menus with counts; obs-map defaults (reference layer, ski areas, Sno-Parks, avalanche, **NWS winter hazards** ON; SNOTEL/ASOS/NOHRSC OFF, remembered, URL `ly=` overrides, Reset button), red alert rings removed; hazards from NOAA/NWS WWA map service with a visible fallback to our alerts index; config `hazards.enabled`. |
| Nov 17 | **SNOTEL outage handling accepted:** previous good copy from the live site (option A, `SITE_ORIGIN`/`site.origin`, on the W1 cutover checklist); stale ≤ 48 h with original timestamps (never re-stamped), 24/72 h changes hidden when older than their window; data-health GitHub issues per source with limits from each source's real cadence (config `monitoring`), assigned to the owner, monitor can never fail the deploy. Independent "workflow did not run" check proposed in `docs/specs/data-pipeline.md` 5.2c (heartbeat service recommended). |
| Nov 17 | **Owner feedback (live review) → dev14:** the **default uncertainty range for snowfall, snow level and snow ratio is 25–75% ("likely", the middle half of NBM's outcomes)**; 10–90% is kept only where explicitly noted (Finder/W3 chance fields, M9 archive). Inline text says "likely X–Y in" with no "NBM 10–90%" label (source and issue time stay in run lines and captions). **One powder-quality definition** (config `powder_quality`: Dense < 10:1, Blower ≥ 15:1). Obs map first-load layers: relief + roads + ski areas + NWS winter hazards only; avalanche, Sno-Parks, SNOTEL, ASOS, NOHRSC off. W3 "Dry stretch" outranks "Wind-affected"; alert tag computed client-side from alerts/index.json. Obs-map Lighthouse target: no worse than main (≈ 82). |
| Nov 17 | **Monitor bootstrap (dev15):** a failing/stale/unavailable source is judged by the data's own age, last success and `outage_since`, not only the restarted failure counter; one decision log line per source. |
| Nov 16 | **Composite ranges are never shown:** where a 24/48/72 h total would add several 6 h percentile windows (fallback cycles), show the expected total only; points JSON marks totals `native: true/false`. Archive columns unchanged (they never carry composite ranges). Lighthouse target: median of ≥ 3 interleaved runs ≥ 85. |
| Nov 16 | Model-map snowfall colors stay as is for now (backlog §8.4). **Guard:** points JSON and the forecast archive keep their existing fields (p10/p50/p90, P(≥4/8/12″), 24/48/72 h). |

---

## 7. Architecture notes

- Pipeline modules: `catalog.py`, `nbm/`, `nws.py`, `points.py`, `layers/`,
  **new:** `summary.py` (§5.7), `pages.py` (§5.10), `alerts/` (§5.11 payload
  builder), `ecmwf.py` (M8). Rules from CLAUDE.md: fetch separate from pure
  functions; offline tests with fakes; sources fail independently.
- CI: the `points` entry in the `models.yml` matrix (there is no `nbm.yml`) and `models.yml`'s other entries
  publish points + layers as Release assets **and** (W1) sync to R2; the site build merges. Each job < 30 min; stay under host limits (§5.10).
- **Pipeline health:** a failed or stale run notifies the owner (email/push) and
  the public data-status page shows last-success time per source. Trust requires
  knowing when *we* are stale.
- Schedules are best-effort on GitHub; if gaps persist add an external `workflow_dispatch` trigger (owner decision).
- Public repo = free Actions minutes (private would cost; code is copyable, our moat is data ops, verification, brand).
- Size budget: points ≈ 600 areas × ≤ 150 KB ≈ 90 MB in R2 (not in the site bundle).

---

## 8. Roadmap

Done milestones: see `docs/ARCHIVE.md`.

### 8.2 The 12-week plan — Nov 16 2026 → Feb 15 2027

Assumes ~8–12 h/week; **◇ = drop first if behind.** Peak-traffic windows:
Thanksgiving (Nov 26), holidays (Dec 24–Jan 2), Presidents' Day weekend
(Feb 13–15). **Deploy freeze Dec 23–Jan 2** (fixes only).

| Sprint | Dates | Dev (Claude Code) | Owner / business |
|---|---|---|---|
| **S1 Foundations** | Nov 16–29 | **W1** domain + Cloudflare Pages + R2 + redirect stub (check file-count/size; parity test). **W5a** cookieless analytics + pipeline-failure alerts. Refresh §2 status. | Pick the name (check trademark/domain/handles; **rename "Powder Finder"**). Buy domain. Cloudflare account. Decide entity path with a CPA/attorney (`docs/BUSINESS.md` §10.1). |
| **S2 Indexable + summaries** | Nov 30–Dec 13 | **W2** prerendered area pages, sitemap, canonical, OG cards (top 60). **W3** Daily Snow summaries v1 + tests. | Terms/privacy/disclaimer review (**B2**). Newsletter provider chosen; signup form copy. **Gate 1 (Dec 13):** new domain live, analytics firing, indexed pages submitted. |
| **S3 PWA + first public push** | Dec 14–27 | **W4** PWA (manifest, SW, offline favorites, staleness, install coach, "My mountains" start page). **M4.5** Sno-Parks (if not done) on the new URL scheme. ◇ obs-map performance pass. | **First public share** (~Dec 18–20) before holiday storms: regional communities, avalanche-education contacts, friends. Start the email list. |
| **S4 Multi-model** | Dec 28–Jan 10 | **M7** HRRR/RRFS/GFS/NBM plumes + model-agreement badge. **M8-lite** ECMWF IFS point sampling + attribution. **Verification panel v0** (~7 weeks of archive). | Weekly "Storm Outlook" email (semi-automated, owner reviews 10 min). **Gate 2 (Jan 10):** read baseline KPIs (§9.7); confirm alerts scope. |
| **S5 Free alerts** | Jan 11–24 | **W6** alerts backend: magic-link accounts, free preset email alert, web push for installed PWAs. ◇ storm-total tracker. | Publish first **forecast report card** (verification) as content. Outreach to 3–5 local partners (shops, guides, clubs, Nordic/snowmobile). |
| **S6 Paid foundations** | Jan 25–Feb 7 | Pricing page; entitlements; MoR checkout; custom thresholds + unlimited favorites. ◇ **W7** wind-exposure flag (informational). | Founding-price copy, refund policy; confirm tax/entity setup; draft supporter FAQ. |
| **Wrap** | Feb 8–15 | Stabilize for Presidents' Day weekend; no risky deploys. | **Gate 3 (Feb 15):** go/no-go on a capped **Founding Supporter soft launch** (e.g., 200 seats) vs. waitlist-only until fall. |

**If behind, cut in this order:** W7 → storm-total tracker → obs-map perf pass →
M8-lite → W6 (shift alerts to the off-season). **Never cut:** W1, W2, W3, W4,
analytics, pipeline monitoring.

### 8.3 Milestone catalogue (acceptance criteria)

**W1 Domain & hosting** — custom domain on Cloudflare Pages + R2; ≤ 20,000 files, no file > 25 MiB; old URL redirects;
Lighthouse not worse; rollback plan. **W2 Indexable pages** — ≥ 160 server-rendered area pages (title/description/summary
without JS); sitemap; `#id` redirects; OG cards for top 60. **W3 Daily summaries** ✅ (dev14; apart from the "Low confidence" rule (needs M7) and `<meta description>` (W2)) — every point has a summary in
`points/<id>.json`; fixture-tested rules; shown on cards, Finder rows, meta descriptions. **W4 PWA** (built dev15 behind `pwa.enabled=false`; enable only after W1) — §5.8 tests pass on
real iPhone + Android; staleness banners; install event. **W5 Analytics/monitoring** (public status page + "Report a bust" done dev14; analytics not wired) — cookieless events (favorite,
install, signup, alert, avalanche-center click, "view as table"); feedback link; failure notifications; public status
page. **W6 Alerts** — double opt-in, one-click unsubscribe, test alert by email + push within one points run, rate
limits. **W7 ◇ Wind flag** — renders for 5 test cases, reviewed by an avalanche-literate person.

**M7 Precipitation by model** — ✅ when: per-area chart of HRRR/RRFS/GFS/NBM
(+ ECMWF when M8-lite lands) in liquid-equivalent with inches toggle; agreement
badge documented in about.html.

**M8 ECMWF** — point sampling first (✅ when ECMWF series validate against a
manual spot check for 3 areas; attribution live); synoptic charts later; AIFS/ENS
plumes in M10.

**M9 Verification & bias correction** — **check whether the rank-by-rank 12-h day/night ranges (points file `periods[].snow_lo/hi/q1/q3`) are over-wide against observed SNOTEL snowfall** (dev15 note); score NBM/NDFD/models vs SNOTEL 24 h snow &
temps by area/elevation; publish on about.html; later per-site bias correction
(MOS-lite). A "point verification panel" ("how did forecasts do here this
season?") ships first.

**M10 — Later:** ensemble plumes, webcams (links), SMS add-on, wind Phase B.

**M6 Interactive model layers** (+ HRRR pressure-level file) — last (Track 3).

### 8.4 Backlog (unscheduled, in priority order)
Track 1 leftovers: "My mountains" refinements; powder-quality surfaces (covered by
§5.7). Track 2 (obs map): mobile performance pass (stations/overlays render before
basemap tiles; preconnect; smaller first payload); **resort-reported snowfall observations** (5a: needs a licence decision; no scraping) and **webcams** (5b: links first; embeds only with permission); **storm-total tracker** (NOHRSC + SNOTEL, selectable window); obs time slider
(24–72 h); slope-angle/aspect layer (3DEP); more observation networks (research
licenses first — MADIS category 3, state DOT RWIS, avalanche-center telemetry via
the centers; **ask before building**). Models: **align model-map snowfall colors to the NWS table
(`colors.js`)**; self-hosted western-US PMTiles as an OpenFreeMap backup.

---

## 10. Data licensing summary (attribution is a code requirement)

| Source | Terms / status for commercial use |
|---|---|
| NOAA/NWS (NBM, NDFD, HRRR, RRFS, GFS, NOHRSC, api.weather.gov) | Public; credit NOAA/NWS |
| USDA NRCS AWDB (SNOTEL), USGS (3DEP, basemaps) | Public domain |
| Iowa Environmental Mesonet | Any lawful use incl. commercial |
| **ECMWF open data (IFS, AIFS)** | **CC BY 4.0 — commercial reuse OK with attribution** (full real-time catalogue open since Oct 1 2025; IFS 0.1° since Oct 20 2026) |
| **Open-Meteo API** | **Free API is non-commercial only; commercial use needs a paid plan. Not used in production** (prototype-only) |
| OpenSkiMap / OpenStreetMap / OSM Sno-Parks | ODbL: attribution; derived databases shared under ODbL |
| USFS EDW | Public domain |
| avalanche.org API | **Verify** commercial terms; contact (see `docs/BUSINESS.md` §10.1) |
| OpenFreeMap vector tiles (roads/towns layer) | No key/limits, commercial OK; credit OpenFreeMap/OpenMapTiles/OSM. Single volunteer-run service: PMTiles backup in §8.4 |
| State Sno-Park lists (WA/OR/CA/ID) | Not copied; ask permission if ever needed |
| MADIS | Only category 3 "full distribution" on public pages |
| Synoptic | Not used |

---

## 11. Known limitations & open questions

- Kuchera/snow level from 5 pressure levels (Stull wet-bulb warm bias in dry air); NBM's 2.5 km grid under-resolves
  narrow ridges (elevation adjustment approximate; M9 will quantify); raw model snowfall differs → compare liquid
  (§5.5); summary/agreement thresholds are heuristics until verified; GitHub cron is best-effort.
- **Owner decisions needed:** (1) name + domain (blocks W1); (2) entity/tax, CPA, merchant of record; (3) time budget
  (~8–12 h/week?); (4) capped Founding Supporter launch Feb 2027 if Gate 3 passes?; (5) hosting move now (recommended);
  (6) private vs public repo; (7) SMS never/only if asked/launch; (8) external cron trigger; (9) who contacts
  avalanche.org, and when.

---
