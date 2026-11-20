# Snow-Wx state snapshot (Nov 19 2026, through dev20)

For pasting into the owner's project notes. Details live in the files named in brackets. No secrets, no personal data.

## Live now
- **Site:** GitHub Pages project site (`site.origin` in `config/settings.yml`); custom domain + Cloudflare is milestone W1 [docs/specs/hosting-seo.md].
- **Obs map:** SNOTEL (~836), ASOS (~544), avalanche danger (avalanche.org), NWS winter hazards, NOHRSC snowfall + NBM forecast overlays, reference layer (OpenFreeMap).
- **Forecast pages** for 160 ski areas, ~447 Sno-Parks and 837 SNOTEL sites: NBM to day 10-11 with "likely" (p25-p75) ranges, NWS (NDFD) view, snow level, snow ratio /
  powder quality (heuristic), hour-by-hour charts, chances of at least X, W3 daily summary, alerts, AFD, webcam LINKS, storm totals.
- **Precipitation by model:** NBM, HRRR, RRFS, GFS, ECMWF HRES + ECMWF ensemble plume; agreement badge (a labelled heuristic). **ECMWF AIFS (AI) line: switched on in dev20,
  appears after the merge, experimental, NOT in the badge.**
- **Powder Finder, Sno-Park Finder, My mountains, model-map viewer, status page, Sources/Disclaimer/Privacy/Terms (drafts, noindex).**
- **Self-hosted:** Plotly, Leaflet, MapLibre. Browser contacts only USGS tiles, OpenFreeMap and the NOAA hazards layer besides the site itself.

## Scheduled workflows (UTC) [.github/workflows/]
| Workflow | Cadence | Does |
|---|---|---|
| `update-site.yml` | hourly at :17 (and on dispatch) | obs fetch, unpack newest model/points/ECMWF tars, build, deploy, monitor |
| `models.yml` | 55 1-22/3 (maps, NDFD, NOHRSC); 55 2,8,14,20 (NBM points) | model maps, NBM point forecasts, NDFD, NOHRSC -> release assets |
| `ecmwf.yml` | 40 9,11,21,23 | ECMWF HRES + ENS (+ AIFS) with mirror failover, resume cache, -> release asset |
| `tests.yml` | pull requests | pytest (offline) |

## Built but switched off (enable in this order at the custom-domain move)
1. **W1 domain + Cloudflare** first (owner: domain, account) [docs/w1_cutover_checklist.md, `tools/w1_rehearsal.py` 15/15].
2. `pages.enabled` (W2 indexable area pages, sitemap) [hosting-seo.md].
3. `og_images.enabled` (share cards; needs pages) + add `python -m pipeline og --out build` to the build step [hosting-seo.md "Share cards"].
4. `pwa.enabled` (offline PWA; only on the final origin) [docs/specs/pwa.md].
5. `analytics.enabled` after the owner picks a provider [launch-readiness.md 2c].
6. `verification_ui.enabled` when the archive has enough days [docs/verification.md].
7. Independent of the domain: `gefs.enabled` (needs the owner to add `docs/workflow_snippets/gefs.yml` as a workflow), `wind_exposure.enabled` (W7, needs a reviewer),
   `alerts_backend.enabled` (W6, needs e-mail provider/Cloudflare decisions) [wind-exposure.md, alerts-backend.md].

## Key numbers
- **Site:** ~5.7 k files, ~220 MB (limits 20,000 files, 25 MiB per file; largest file 1.45 MB). Share cards would add 162 files / 3.1 MB.
- **Lighthouse (mobile, local gzip server):** obs map 88, area page 88, Powder Finder 96, Sno-Park Finder 93, other pages 100; accessibility 100 on every page.
- **Tests:** 494 pytest passed + 9 skipped (~2 min, offline). Browser suite: 29 checks in 4 parallel isolated workers with frozen inputs, ~5 min full / ~1.5 min `--quick`.
- **CI:** update-site median ~5 min; models ~4 min; ECMWF ~5-10 min (1.3 GB download; AIFS adds 17 MB / 17 s) [docs/budgets_baseline.md].

## Known issues
- Obs-map Lighthouse is bimodal (71-91) because of tile-server timing.
- SNOTEL outage of Nov 16-18 is excluded from verification; no seasonal accuracy claim yet.
- The ECMWF job has never been seen succeeding on a real GitHub runner after the dev19/dev20 resilience work (it works from the owner's PC; AWS throttles, Google works and is now remembered).
- One outbound dead link comes from avalanche.org data (Shasta advisory URL); left unaltered by rule.
- Model-map snowfall colours still use the older table (deferred).

## Pending owner decisions (file with the details)
1. Merge dev20 (compare link in the session report).
2. Brand name and tagline: placeholders `site.name` / `site.tagline` in `config/settings.yml`.
3. Custom domain + Cloudflare account (W1) [docs/w1_cutover_checklist.md].
4. Analytics provider [docs/specs/launch-readiness.md 2c].
5. Legal review of the draft Disclaimer / Privacy / Terms [launch-readiness.md 2b].
6. `HEALTHCHECK_URL` secret for the monitor [docs/specs/data-pipeline.md 5.2c].
7. Whether to add the GEFS workflow [docs/workflow_snippets/gefs.yml].
8. W6 alerts backend choices and a W7 wind-exposure reviewer [docs/specs/alerts-backend.md, wind-exposure.md].
