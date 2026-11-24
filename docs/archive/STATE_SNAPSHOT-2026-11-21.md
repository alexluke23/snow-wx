# Snow-Wx state snapshot (Nov 21 2026, through dev22; dev23 branch in progress)

For pasting into the owner's project notes. Details live in the files named in brackets. No secrets, no personal data.
Business planning is private and not part of this repo; do not create business docs here.

## Live now (after the dev22 merge)
- **Site:** GitHub Pages project site (`site.origin` in `config/settings.yml`); custom domain + Cloudflare is milestone W1 [docs/specs/hosting-seo.md].
- **Obs map:** SNOTEL (~836), ASOS (~544), avalanche danger (avalanche.org), NWS winter hazards, NOHRSC snowfall + NBM forecast overlays, reference layer (OpenFreeMap).
- **Forecast pages** for 160 ski areas, ~447 Sno-Parks and 837 SNOTEL sites: NBM to day 10-11 with "likely" (p25-p75) ranges (NBM only since dev22; the NWS point forecast is linked), snow level, snow ratio /
  powder quality (heuristic), hour-by-hour charts, chances of at least X, daily summary, alerts, AFD, webcam LINKS, storm totals.
- **Precipitation by model:** NBM, HRRR, RRFS, GFS, ECMWF HRES and the ECMWF AIFS line (experimental, NOT in the badge), with **model chips** to show/hide lines (dev21); agreement
  badge (a labelled heuristic, always over every model). **Ensemble view: ECMWF ENS | NOAA GEFS** (GEFS live from dev21).
- **Powder Finder, Sno-Park Finder, My mountains, model-map viewer, status page, Sources/Disclaimer/Privacy/Terms (drafts, noindex).**
- **Self-hosted:** Plotly, Leaflet, MapLibre. Browser contacts only USGS tiles, OpenFreeMap and the NOAA hazards layer besides the site itself.
- **Verification numbers are computed daily** (dev21) but the panel stays hidden until the owner switches it on (below).

## Scheduled workflows (UTC) [.github/workflows/]
| Workflow | Cadence | Does |
|---|---|---|
| `update-site.yml` | hourly at :17 (and on dispatch) | obs fetch, unpack newest product tars, build, deploy, forecast archive, monitor |
| `models.yml` | 55 1-22/3 (maps, NDFD, NOHRSC); 55 2,8,14,20 (NBM points) | model maps, NBM point forecasts, NDFD, NOHRSC -> release assets |
| `ecmwf.yml` | 50 8-13,20-23,0-1 (hourly attempts around the measured +7.75 h release) | ECMWF HRES + ENS (+ AIFS) with mirror failover, resume cache |
| `gefs.yml` (dev21) | 10 6,8,18,20 | NOAA GEFS plume (00Z/12Z; times from measured NOAA release times), resume cache |
| `verify.yml` (dev21) | 25 15 daily | scores the forecast archive against SNOTEL -> `models/verify/` |
| `tests.yml` | pull requests | pytest (offline) |

GitHub delivers few of these cron events (Nov 19-20: about 6 of 46 hourly `update-site` runs, 1 `ecmwf`, none for `gefs`/`verify`); manual dispatch always works. The external scheduler below is the fix.

## External scheduler: built, not deployed (dev23) [infra/scheduler/README.md]
A Cloudflare Worker (one cron trigger every 10 minutes, free plan) that dispatches the five workflows above on time: it lists each due workflow's latest 5 runs and dispatches (`ref: main`) only when none is queued/running or started since the slot, so it never double-dispatches. The workflows keep their own schedules as a backup. **Owner deploys it** (fine-grained token limited to this repo with Actions read/write, `wrangler secret put`, `wrangler deploy`; 6 steps in the README). Tests: `node --test` + `tests/test_scheduler.py` (also checks that its cron table equals the workflows' crons).

## Built but switched off (enable in this order at the custom-domain move)
1. **W1 domain + Cloudflare** first (owner: domain, account) [docs/w1_cutover_checklist.md, `tools/w1_rehearsal.py`].
2. `pages.enabled` (W2 indexable area pages, sitemap) [hosting-seo.md].
3. `og_images.enabled` (share cards; needs pages) + add `python -m pipeline og --out build` to the build step [hosting-seo.md "Share cards"].
4. `pwa.enabled` (offline PWA; only on the final origin) [docs/specs/pwa.md].
5. `analytics.enabled` after the owner picks a provider [launch-readiness.md 2c].
6. `verification_ui.enabled` **once the status page's "Forecast verification" row says enough data (projected about Nov 30)** [docs/verification.md].
7. Independent of the domain: `wind_exposure.enabled` (W7, needs a reviewer), `alerts_backend.enabled` (W6, needs e-mail provider/Cloudflare decisions).

## Key numbers
- **Site:** after dev23 the deployed site no longer contains `data/ndfd/` (nothing requests it): 6,851 -> 5,405 files, 319 -> 302 MB on a local build (limits 20,000 files, 25 MiB per file); GEFS adds 161 files / 1.8 MB, verification up to ~840 small files; share cards would add 162 files / 3.1 MB.
- **Lighthouse (mobile, local gzip server):** see docs/budgets_baseline.md §5; accessibility 100.
- **Tests:** 590 pytest passed + 9 skipped (~2.4 min, offline, green on Windows without a PATH change since dev23). Chrome browser suite: 38 checks in the full run (dev23 added `nondfd`, `rootbase`), ~6 min full / ~1.5 min `--quick`. WebKit + Firefox smoke: ~1 min (optional).
- **CI:** update-site median ~5 min; models ~4 min; ECMWF ~5-10 min (1.3 GB); GEFS ~5 min (376 MB); verification ~2 min [docs/budgets_baseline.md].
- **Forecast archive (dev23):** NBM files gain `slr_p25/p50/p75` (NBM's native snow-ratio percentiles at the window end hour) from the first build after the merge; the M11 baseline needs about 4 weeks of them (docs/specs/snow-ratio-ml.md 6.5). NDFD stays in the archive but is not shown (verification panel and deployed site are NBM only).
- **Verification today:** 4 observation days, 88,131 forecast/observation pairs at 790 SNOTEL sites; no site has reached 14 days + 30 pairs yet.

## Known issues
- Obs-map Lighthouse is bimodal (71-91) because of tile-server timing.
- SNOTEL outage of Nov 16-18 is excluded from verification; no seasonal accuracy claim yet.
- dev21's two workflows (`verify.yml`, `gefs.yml`) and dev20's AIFS/mirror preference have not yet run on a GitHub runner (they start after the merge).
- One outbound dead link comes from avalanche.org data (Shasta advisory URL); left unaltered by rule.
- Model-map snowfall colours still use the older table (deferred).

## Pending owner decisions (file with the details)
1. Site name and tagline: placeholders `site.name` / `site.tagline` in `config/settings.yml` (set by owner at W1).
2. Custom domain + Cloudflare account (W1) [docs/w1_cutover_checklist.md].
3. Analytics provider [docs/specs/launch-readiness.md 2c]; legal review of the draft pages [launch-readiness.md 2b].
4. `HEALTHCHECK_URL` secret for the monitor [docs/specs/data-pipeline.md 5.2c].
5. When to show verification (`verification_ui.enabled`), W6 alerts backend choices and a W7 wind-exposure reviewer.
