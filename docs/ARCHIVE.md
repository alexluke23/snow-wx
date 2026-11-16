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
