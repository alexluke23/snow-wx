---
status: current
owner: team
last_reviewed: 2026-11-23
read_when: you need to know what is live, what is switched off, or what is known to be broken
---

# Snow-Wx status (Nov 23 2026)

State of `main` at commit `bf8f8ac` (dev23 + the models-page hotfix, PR #35). Update this file when a merge changes what is live; move the previous dev-round detail to `docs/archive/ARCHIVE.md`. The Nov 21 snapshot it replaces is `docs/archive/STATE_SNAPSHOT-2026-11-21.md`.

> **Scope trim pending (decided Nov 23):** model maps, Sno-Parks and SNOTEL-site forecast *pages* are still live until the trim lands (`docs/BACKLOG.md` §3). Items below marked *(to be removed)* go then.

## Live now
- **Site:** GitHub Pages project site (`site.origin` in `config/settings.yml`). Moving to a custom domain (set by owner) on Cloudflare Workers Static Assets + R2 at W1 (`docs/specs/platform-transition.md`).
- **Obs map:** SNOTEL (~836), ASOS (~544), avalanche danger (avalanche.org), NWS winter hazards, NOHRSC snowfall + NBM forecast overlays, reference layer (OpenFreeMap).
- **Forecast pages:** 160 ski areas — NBM to day 10–11 with "likely" (p25–p75) ranges (NBM only since dev22), snow level, snow ratio / powder quality (labelled heuristic), hour-by-hour charts, chances of at least X, daily summary, alerts, AFD, webcam links, storm totals. Also ~447 Sno-Parks *(to be removed)* and 837 SNOTEL sites *(pages to be removed; forecasts kept for verification)*.
- **Precipitation by model:** NBM, HRRR, RRFS, GFS, ECMWF HRES, ECMWF AIFS (experimental, not in the badge), model chips; agreement badge (labelled heuristic, every model). **Ensemble view:** ECMWF ENS | NOAA GEFS.
- **Other pages:** Powder Finder (name to be replaced, set by owner), Sno-Park Finder *(to be removed)*, My mountains, model-map viewer *(to be removed)*, status page, Sources / Disclaimer / Privacy / Terms (drafts, `noindex`).
- **Self-hosted:** Plotly, Leaflet, MapLibre. The browser contacts only USGS tiles, OpenFreeMap and the NOAA hazards layer besides the site itself.
- **Verification:** scores computed daily (`verify.yml`); the panel stays hidden until `verification_ui.enabled` is switched on.

## Scheduled workflows (UTC) [`.github/workflows/`]
| Workflow | Cadence | Does |
|---|---|---|
| `update-site.yml` | hourly at :17 (and on dispatch) | obs fetch, unpack newest product tars, build, deploy, forecast archive, monitor |
| `models.yml` | 55 1-22/3 (maps *(to be removed)*, NDFD, NOHRSC); 55 2,8,14,20 (NBM points) | model maps + plume sampling, NBM point forecasts, NDFD, NOHRSC → release assets |
| `ecmwf.yml` | 50 8-13,20-23,0-1 | ECMWF HRES + ENS + AIFS, mirror failover, resume cache |
| `gefs.yml` | 10 6,8,18,20 | NOAA GEFS plume, resume cache |
| `verify.yml` | 25 15 daily | scores the forecast archive against SNOTEL → `models/verify/` |
| `tests.yml` | pull requests | pytest (offline) |

GitHub delivers few of these cron events (Nov 19–20: about 6 of 46 hourly `update-site` runs, 1 `ecmwf`, none for `gefs`/`verify`); manual dispatch always works. The external scheduler (`infra/scheduler/`) is built, not deployed; fix review M14 and M10 before deploying it.

## Feature flags (`config/settings.yml`)
- **On:** `snotel`, `asos`, `avalanche`, `forecast_overlays`, `gefs`, `ecmwf`, `aifs` (`in_badge: false`), `hazards`, `verification.ci_enabled`.
- **Off:** `r2`, `og_images`, `pages`, `pwa`, `analytics`, `alerts_backend`, `wind_exposure`, `verification_ui`.

**Enable order at the domain move:**
1. W1 domain + Cloudflare (`docs/ops/w1_cutover_checklist.md`, `tools/w1_rehearsal.py`).
2. `pages.enabled` (after H8).
3. `og_images.enabled`, plus `python -m pipeline og --out build` in the build step.
4. `pwa.enabled` (after M16; only on the final origin).
5. `analytics.enabled` (provider set by owner).
6. `verification_ui.enabled` once the status page says there is enough data (after M2).

Independent of the domain: `wind_exposure.enabled` (W7, needs a reviewer and H1) and `alerts_backend.enabled` (W6).

## Key numbers
- **Site (local build after dev23):** 5,405 files / 302 MB (limits 20,000 files, 25 MiB per file). The trim removes the model frames, Sno-Park and SNOTEL pages.
- **Tests:** pytest **606 passed, 9 skipped** (~2.5 min, offline; the 9 skips are browser tests gated on `SNOWWX_BROWSER=1`). Browser suite **32/38** on Nov 23 (`charts`, `ensemble`, `mmodel` read live data: PR B). No linters or type checkers configured.
- **Lighthouse (mobile, local gzip server):** area 89, Finder 98, About 100; obs map 71–91 (bimodal, tile timing); accessibility 100 (`docs/ops/budgets_baseline.md` §5).
- **CI:** update-site median ~5 min; models ~4 min; ECMWF ~5–10 min (1.3 GB); GEFS ~5 min (376 MB); verification ~2 min.
- **Forecast archive:** NBM files carry `slr_p25/p50/p75` since dev23; the M11 baseline needs about 4 weeks (first ~Dec 19). NDFD stays in the archive, not on the site.

## Known issues
- **Code review (Nov 23):** 2 critical, 8 high, 19 medium and 6 low findings (`docs/BACKLOG.md`). Most urgent:
  - C1: the archive can lose a month.
  - C2, H2, H3, M12: safety display and safety data when a fetch fails.
  - H4: a silent empty deploy.
  - H1: wrong SLR, powder and wind labels past f036 on the production cycles.
  - H5/H6: the scope trim would break the plumes and verification if done naively.
- Obs-map Lighthouse is bimodal (71–91) because of tile-server timing.
- The SNOTEL outage of Nov 16–18 is excluded from verification (`verification.snotel_outage`); no seasonal accuracy claim yet.
- One outbound dead link comes from avalanche.org data (Shasta advisory URL); left unaltered by rule.

## Waiting on the owner (set by owner)
Site name and tagline (`site.name` / `site.tagline`); custom domain + Cloudflare account; analytics provider; legal review of the draft pages; `HEALTHCHECK_URL` secret; when to show verification; W6 choices; a W7 reviewer. Owner decisions are tracked privately.
