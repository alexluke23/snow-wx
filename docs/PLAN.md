# Snow-Wx — Development Plan (v1.1, Nov 15 2026)

> Lean plan read by Claude Code at the start of every session. Detail lives in `docs/specs/`, `docs/DESIGN.md`, `docs/BUSINESS.md` and `docs/ARCHIVE.md` (see "Where things live"). Tick milestones in §8 as they land.
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

When a task starts, read this file, then only the spec(s) for the active milestone.

---

## 0. TL;DR

A free, open-data snow forecasting site for the western US — point forecasts for every ski area and Sno-Park, with probabilities, snow level, observations, avalanche context and public verification — growing into a small sustainable business. **Free-first:** no paywall before Feb 2027 at the earliest; full paid launch targeted pre-season (Sep–Oct 2027).

**Priority now:** Foundations (W1 domain/hosting, W2 indexable pages, W3 daily summaries, W4 PWA, W5 analytics/monitoring) → M7/M8 multi-model → W6 alerts. Details in §8.2.

**Hard rules for all code**
1. Safety info (avalanche danger, NWS alerts, snow level/rain-at-base, data freshness) is never gated or hidden.
2. Never present a heuristic as an accuracy claim or an avalanche rating. Label heuristics.
3. Open, license-clean data only; keep attribution (§10.2) on pages and charts.
4. One accumulation period per chart axis; uncertainty (10–90%) shown by default; sources + issue times on every module.
5. Sources fail independently; fetch separate from pure functions; offline tests with fakes.
6. Stay within static-host limits (20,000 files/deploy, 25 MiB/file) — bulk data goes to R2.

---

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

## 2. Status (last recorded Nov 8 2026 — Claude Code: refresh at next session)

- **Live:** https://alexluke23.github.io/snow-wx/ — repo `alexluke23/snow-wx`
  (moving to a custom domain, W1).
- **Done:** M0–M5, M3.5, M3.6 (chart readability/accessibility/basemap
  reliability — bugs B1–B7 resolved), M9-prep (forecast archive running),
  dev6 fixes, dev7 (Expected rename, day-10 temp/wind panels, Sno-Park research).
- **Product today:** observations map (SNOTEL 837, ASOS 545, avalanche 70 zones,
  NOHRSC overlays); 161-area catalog (60 major, hand-checked); NBM point
  forecasts to day 10–11 with percentiles, snow level, SLR; NDFD; NWS alerts +
  AFD links; Powder Finder with "Chance of ≥ X"; ridge-top wind; about.html;
  model maps (HRRR, RRFS, GFS) on `models.yml` every 3 h.
- **Forecast archive:** all daily leads stored as GitHub release assets
  (~30–40 MB/month) since ~Nov 8 → ~7 weeks of data by late Dec for the first
  verification panel.
- **Approved, not built:** M4.5 Sno-Parks (USFS EDW + OSM, ~450 points).
- **Known issues:** obs map Lighthouse mobile performance 47–71 (target ≥ 85);
  site ≈ 240 MB (Nov 7) — recheck against hosting limits (§5.10); GitHub's
  scheduled runs are best-effort.

---

## 3. Current decisions

Full history (Nov 6–8) is in `docs/ARCHIVE.md`. Standing decisions from that history still apply: NBM primary + NDFD alongside; day/night 12Z–00Z; bars use NBM deterministic; point snow scaled by P(snow level below point); model images as release assets; surface-only fields on HRRR/RRFS; chart readability and never-blank basemaps; Sno-Parks as a point type; obs map + forecast pages before model maps.

**Nov 15 2026 decisions — accepted by owner Nov 15**

| Date | Decision |
|---|---|
| Nov 15 | **Business intent is active.** Free-first. No paywall before Feb 2027; optional Founding Supporter soft launch Feb 2027 (Gate 3); full paid launch Sep–Oct 2027. |
| Nov 15 | **Adopt** from the Gemini review: Daily Snow summaries (W3), offline-first PWA (W4), multi-model comparison incl. ECMWF (M7/M8). **Reshape** wind-loading (§5.9). **Reject** Open-Meteo API for production (rationale: `docs/BUSINESS.md` Appendix A). |
| Nov 15 | **Move to a custom domain + Cloudflare Pages (site) + R2 (frequently-updated data) before any public promotion** (W1). GitHub Pages stays as a redirect/canonical stub. Reason: GitHub Pages is not permitted for online businesses/SaaS, installed PWAs and SEO are tied to the origin, and Pages file-count limits may bite the model-map frames. |
| Nov 15 | **Path-based, prerendered area URLs** (`/ski/<state>/<id>/`), not hash routing, so ~600 pages are indexable (W2). Old `#id` links redirect. |
| Nov 15 | **Offline cache of the last-fetched forecast is free.** (Gemini proposed paywalling it.) It builds trust, drives PWA installs, and iOS push needs the install anyway. |
| Nov 15 | **No numeric "lee-aspect accumulation adjustment" until verified** (M9). Wind is shown as an informational flag, never as an avalanche rating. |
| Nov 15 | **Alerts: email + web push first; SMS is an optional later add-on** (carrier fees + registration + TCPA overhead; its advantage is working on weak signal). |
| Nov 15 | **Payments via a merchant of record at first** (Stripe Managed Payments / Paddle / Lemon Squeezy class) to offload sales-tax registration; revisit when volume justifies Stripe + Stripe Tax. Confirm with a CPA. |
| Nov 15 | Models compared primarily in **liquid-equivalent (SWE/QPF)**, with an inches toggle using the NBM SLR — apples-to-apples across models. |

---

## 7. Architecture notes

- Pipeline modules: `catalog.py`, `nbm/`, `nws.py`, `points.py`, `layers/`,
  **new:** `summary.py` (§5.7), `pages.py` (§5.10), `alerts/` (§5.11 payload
  builder), `ecmwf.py` (M8). Rules from CLAUDE.md: fetch separate from pure
  functions; offline tests with fakes; sources fail independently.
- CI: `nbm.yml` / `models.yml` publish points + layers as Release assets **and**
  sync to R2; site build merges. Each job < 30 min; stay under host limits (§5.10).
- **Pipeline health:** a failed or stale run notifies the owner (email/push) and
  the public data-status page shows last-success time per source. Trust requires
  knowing when *we* are stale.
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

**M4.5 Sno-Parks** — ✅ when: western Sno-Parks cataloged with a source per point;
each opens a forecast view; Finder Type filter works on mobile.

**M7 Precipitation by model** — ✅ when: per-area chart of HRRR/RRFS/GFS/NBM
(+ ECMWF when M8-lite lands) in liquid-equivalent with inches toggle; agreement
badge documented in about.html.

**M8 ECMWF** — point sampling first (✅ when ECMWF series validate against a
manual spot check for 3 areas; attribution live); synoptic charts later; AIFS/ENS
plumes in M10.

**M9 Verification & bias correction** — score NBM/NDFD/models vs SNOTEL 24 h snow &
temps by area/elevation; publish on about.html; later per-site bias correction
(MOS-lite). A "point verification panel" ("how did forecasts do here this
season?") ships first.

**M10 — Later:** ensemble plumes, webcams (links), SMS add-on, wind Phase B.

**M6 Interactive model layers** (+ HRRR pressure-level file) — last (Track 3).

### 8.4 Backlog (unscheduled, in priority order)
Track 1 leftovers: "My mountains" refinements; powder-quality surfaces (covered by
§5.7). Track 2 (obs map): mobile performance pass (stations/overlays render before
basemap tiles; preconnect; smaller first payload); **snow forecast overlays**
(NBM expected snowfall 24/72 h and chance of ≥ 4/6/12" as zoomable layers);
**storm-total tracker** (NOHRSC + SNOTEL, selectable window); obs time slider
(24–72 h); slope-angle/aspect layer (3DEP); more observation networks (research
licenses first — MADIS category 3, state DOT RWIS, avalanche-center telemetry via
the centers; **ask before building**).

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
| OpenTopoMap tiles | **Verify** (CC-BY-SA + fair-use) |
| State Sno-Park lists (WA/OR/CA/ID) | Not copied; ask permission if ever needed |
| MADIS | Only category 3 "full distribution" on public pages |
| Synoptic | Not used |

---

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

---
