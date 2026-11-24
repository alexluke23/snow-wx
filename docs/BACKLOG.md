---
status: current
owner: team
last_reviewed: 2026-11-23
read_when: picking the next piece of work, or closing one
---

# Backlog

One prioritised list: the Nov 23 code review (`docs/reviews/2026-11-code-review.md`, IDs C/H/M/L) plus the open items from the old PLAN §8.4 and the Nov 23 decisions. When an item lands, mark it ✅ with the merge request and date; when it's dropped, strike it through with the reason. Detail stays in the review and the specs; this file is the index.

**Owners** (`CONTRIBUTING.md`): **P** = pipeline (Dev A) · **I** = API + infra (Dev B) · **W** = web + mobile (Dev C).
**Blocks** = must land before: **MOVE** (platform Phases 1–2), **TRIM** (scope trim), **SCHED** (deploying the external scheduler, platform 0.3), **W1 / W2 / W4** (enabling that flag), **M9-UI** (verification panel).
**Effort:** S < ½ day · M ≤ 2 days · L > 2 days.

---

## 1. Merge-request order (from the review)

Do MR 1–4 before the Thanksgiving traffic; MR 6 before the scope trim; MR 7 and M15 before any container or R2 work.

| MR | Name | Items | Owner | Effort |
|---|---|---|---|---|
| 1 | Safety display | C2, H2, M12, N1 | W | S |
| 2 | Safety data on fetch failure | H3 | P + W | M |
| 3 | Archive cannot lose a month | C1, M13 | I | M |
| 4 | No silent empty deploy | H4 | I | S |
| 5 | 6-h window fix | H1, M3, M4 | P | S |
| 6 | Plume sampling without maps | H5 (+ record H6) | P | M–L |
| 7 | Pin the environment | H7 | I | S |
| 8 | Workflow hardening | M10, M11 | I | S |
| 9 | Ensemble gaps, GEFS, ECMWF partials | M6, M7, M8, M9, N2 | P + W | S |
| 10 | Summary and verification wording | M1, M2, M5 | P + W | S |
| PR B | Browser suite on frozen fixtures | M19 (+ `live_smoke.py`) | W | M |

Then: M15 (atomic outputs) before any R2 sync; M14 before the scheduler goes live; H8 before `pages.enabled`; M16 before `pwa.enabled`; M17 before the CSP is enforced at W1.

---

## 2. Code-review findings

| ID | Sev | Area | Owner | MR | Blocks | Item | Status |
|---|---|---|---|---|---|---|---|
| C1 | Critical | archive | I | 3 | MOVE | `gh release upload --clobber` can delete the only copy of a month | ○ |
| C2 | Critical | web, safety | W | 1 | — | "Extreme" avalanche label unreadable on the area page (contrast ≈ 1.1:1) | ○ |
| H1 | High | NBM | P | 5 | — | Off-by-one 6-h window lookup past f036 on 01/07/13/19Z: SLR, powder/snow-type and wind-affected labels wrong | ○ |
| H2 | High | safety | W | 1 | — | Expired avalanche ratings shown as current between builds | ○ |
| H3 | High | safety | P + W | 2 | MOVE | Failed alerts/avalanche fetch publishes pages with no banner, no center link, no notice | ○ |
| H4 | High | workflows | I | 4 | — | Failed release listing deploys a site with no products; monitor says "waiting" | ○ |
| H5 | High | pipeline | P | 6 | **TRIM**, MOVE | HRRR/RRFS/GFS plume lines and ridge winds exist only inside map rendering | ○ |
| H6 | High | verification | P | 6 | **TRIM** | Verification and the M11 baseline score only SNOTEL-site forecasts: keep computing them (decided Nov 23) | decided |
| H7 | High | deps | I | 7 | MOVE | No dependency pinned; notebook tools in the runtime environment | ○ |
| H8 | High (latent) | pages | W | — | W2 | Redirect loop once `pages.enabled` is on | ○ |
| M1 | Medium | summaries | P | 10 | — | "next 24 h" wording vs the actual window; p50 and range from different windows | ○ |
| M2 | Medium | verification | P | 10 | M9-UI | Lead buckets labelled one day late | ○ |
| M3 | Medium | NBM | P | 5 | — | Missing snow level gives P(snow) = 1.0 | ○ |
| M4 | Medium | NBM | P | 5 | — | Quality gate is global, not per field | ○ |
| M5 | Medium | web, rule 4 | W | 10 | — | Snow-ratio "likely" takeaway is a cross-hour envelope | ○ |
| M6 | Medium | plumes | W + P | 9 | — | Missing ECMWF steps bridged in plume lines and badge | ○ |
| M7 | Medium | GEFS | P | 9 | — | Failed CSNOW message counted as "no snow" | ○ |
| M8 | Medium | GEFS | P | 9 | MOVE | Truncated resume cache aborts every later attempt on that cycle | ○ |
| M9 | Medium | ECMWF | P | 9 | — | Partial cycles re-published every hour | ○ |
| M10 | Medium | security | I | 8 | SCHED | Shell injection via a `workflow_dispatch` input | ○ |
| M11 | Medium | security | I | 8 | — | Workflow-wide write permissions; actions pinned to tags, not SHAs | ○ |
| M12 | Medium | safety | W | 1 | — | Expired alerts shown; alert age never shown | ○ |
| M13 | Medium | ops | I | 3 | — | Archive outage alerts no one | ○ |
| M14 | Medium | scheduler | I | — | **SCHED** | Dispatches send no inputs (points slot runs the whole matrix; slots skipped while a run is active) | ○ |
| M15 | Medium | outputs | P | — | MOVE | Non-atomic writes; good files deleted before new ones exist (the review summary calls this "M17"; M15 is correct) | ○ |
| M16 | Medium (latent) | PWA | W | — | W4 | Safety data served stale-while-revalidate | ○ |
| M17 | Medium (latent) | CSP | W | — | W1 | Draft CSP `connect-src` misses the NOAA hazards host | ○ |
| M18 | Medium | NBM | P | — | — | One bad catalog record stops the whole points run | ○ |
| M19 | Medium | tests | W | PR B | — | Browser suite reads live build data | ○ |
| N1 | Medium | attribution | W | 1 | — | Area footer lacks avalanche.org and USDA NRCS credit; SNOTEL obs charts lack a source/time line; prerendered pages lack the ODbL credit (review §4, rule 3) | ○ |
| N2 | Medium | issue times | W | 9 | — | "Precipitation by model" shows no HRRR/RRFS/GFS run times (review §4, rule 4) | ○ |
| L1 | Low | docs | team | docs reorg | — | Committed docs lag decisions | ✅ docs/reorg-2026-11 |
| L2 | Low | pipeline | P | — | — | Coordinates rounded to 2 decimals in `write_json` | ○ |
| L3 | Low | performance | P | — | — | Summary rules YAML parsed per document | ○ |
| L4 | Low | XSS | W | — | TRIM | Unescaped `href` in Sno-Park facts (goes away with the trim) | ○ |
| L5 | Low | privacy | owner | — | W1 | Personal address as the feedback address (set by owner at W1) | ○ |
| L6 | Low | workflows | I | — | — | Stale workflow comments | ○ |

N1 and N2 are gaps the review reported in its hard-rule checklist without an ID.

---

## 3. Scope trim (Nov 23), after MR 6

Inventory with file:line detail: review §5.

| Item | Owner | Notes |
|---|---|---|
| Remove Models page + map frames | P + W | Keep `models/fetch.py`, run totals, `multimodel.py`, `ridge.py`; move `load_points` out of `models/`; replace the `models` status row with plume-sampling health |
| Remove Sno-Parks | P + W | Pages, `rec_points.json`, Finder type filter, obs-map layer, Sno-Park Finder; redirect old `#sp-*` links to the Finder; archive rows stay |
| Remove SNOTEL-site forecast pages and entry points | W | **Keep** `station_outputs` and the archive rows (H6) |
| Report before/after file count and size | P | Acceptance in PLAN §8.3 |

---

## 4. Product and platform work

| Item | State | Owner | Notes |
|---|---|---|---|
| NBM visualization pass (area page) | ○ | W | Split `web/js/area.js` (1,363 lines) into modules first (review §8) |
| Plume UI pass | ○ | W | After MR 9; gaps, run times, badge ≥ 3 models, AIFS out |
| Platform Phase 0 (GitLab, D1 inventory, CI tests) | ○ | I | `platform-transition.md` §10 |
| W1 on Workers Static Assets + R2 | ◐ | W + I | dev23 staging prep done; blocked on the domain (set by owner) |
| W2 prerendered pages + sitemap/robots | ⏸ | W | `pages.enabled=false`; ~160 ski-area pages; needs H8 |
| W4 PWA | ⏸ | W | `pwa.enabled=false`; needs W1 and M16; real-device tests open |
| W5 analytics | ◐ | W | Built, OFF until the provider is set by owner |
| W6 alerts backend | ⏸ | I | Offline skeleton + tests; target stack in `platform-transition.md` |
| W7 wind-exposure flag | ⏸ | P | Needs the reviewer checklist and H1 |
| M9 verification panel | ◐ | P + W | Daily CI scores live; needs M2; `verification_ui.enabled=false` |
| M11 SLR baseline | ◐ | P | First baseline ~Dec 19 |
| M12 R0 data lake + SNOTEL QC | ○ | P | `ml-postprocessing.md` §8 |
| `tools/live_smoke.py` in CI | ○ | W | PR B builds it; wire into GitLab CI after deploys |
| WX API v1 | ○ | I | `platform-transition.md` §6 |
| Mobile performance pass (obs map) | ◐ | W | Lighthouse mobile 71–91 (bimodal) |
| Webcams (links only) | ◐ | W | 60 areas; embeds stay out |
| Resort-reported snowfall | ○ | — | Licensing research only (`docs/reference/sources_resort_snowfall.md`); no build without a written licence |
| Obs time slider (24–72 h) | ○ | W | not started |
| Slope-angle / aspect layer (3DEP) | ○ | P + W | not started |
| More observation networks (MADIS cat. 3, RWIS, center telemetry) | ○ | — | research licences first; **ask before building** |
| PMTiles backup of the OSM reference layer | ○ | W | not started |
| "My mountains" refinements | ○ | W | never specified: drop unless listed |
| ~~Model-map snowfall colors → NWS table~~ | — | — | moot: model maps removed |
| ~~M6 interactive model layers~~ | — | — | cancelled Nov 23 |

---

## 5. Decisions needed

From the review (§9) and the Nov 23 plans. Record each answer in `docs/DECISIONS.md`.

1. Plume sources after the trim: keep HRRR/RRFS/GFS lines through a sample-only job (H5)? The agreement badge needs ≥ 3 models.
2. Archive durability until R2: a dated backup asset on GitHub, or move the archive to R2 in Phase 0?
3. Safety fallbacks on a failed alerts/avalanche fetch: last-good data (stale-flagged), "not available", or both? (Recommended: both.)
4. Rename `build/models/` (it will hold only ECMWF, GEFS and verification) to `products/` during the R2 move?
5. Feedback address: role address now, or at W1 (set by owner)?
6. Replace the `models` status row with per-model plume-sampling health?
7. ASOS stays on the obs map and as nearest obs (assumed)?
8. M12: approve the gates; who labels the QC gold set; internal SNOTEL forecast view for verification; point-only HRRR pressure-level fetch for SLR predictors (`ml-postprocessing.md` §10).
