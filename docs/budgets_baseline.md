# Budgets baseline (Nov 20 2026, dev21 update of the dev18-dev20 baseline; for the W1 Cloudflare move)

Numbers measured on the current GitHub Pages setup, so the Cloudflare Pages + R2 move has something to compare against. Sources: the local build (`build/`, one full `pipeline build` of Nov 18 plus the dev18 pages), the public GitHub Actions API (40 most recent completed runs per workflow, read Nov 19 2026 01:55 UTC),
dev14's production-size measurement (`docs/specs/hosting-seo.md`), local Lighthouse runs (below). Re-measure with the commands in the last section.

## 0a. dev21 additions (Nov 20 2026)
| Item | Number |
|---|---|
| GEFS plume (LIVE after merge, `gefs.yml`, 2 attempts per 00Z/12Z cycle) | real run 00Z Nov 20: **376 MB, 275 s**, 3,723 requests, 1 retry, 0 missing; +161 site files (160 plumes avg 8.4 KB + index.json), 1.8 MB raw; resume cache ~280 KB per cycle (2 kept); a re-run of a finished cycle: 0 MB, 2.4 s |
| Verification job (`verify.yml`, daily) | archive download today ~16 MB (NBM 14.8, NDFD 1.3, SNOTEL 0.1; closed months from the Actions cache later), scoring 7.6 s locally; output today 3 files / 28 KB; at most ~840 files (one per SNOTEL site that meets the minima, ~2-3 KB each) once the minima are met |
| Site file count after both | ~5.7 k + 161 (GEFS) + up to ~840 (verification) = ~6.7 k of 20,000 |
| Browser suite | full run 34 jobs (32 checks; `failure` in 3 shards): **377 s**, 34/34; `--quick` 98 s |
| Cross-browser smoke (`tools/xbrowser_smoke.py`, optional) | WebKit + Firefox, 6 pages x 2 widths each: **56 s** |
| pytest | 530 passed + 9 skipped, ~2.3 min |
| Lighthouse (dev21, mobile, gzip server, frozen inputs) | accessibility 100 on all 11 pages; performance: obs map 90/86/81, Alta 87/88/86, area page WITH an active alert 91/90/77 (median 90) and **CLS 0.000** (was 0.084), Finder 97, Sno-Park Finder 90, SNOTEL page 90, about/mine/models/sources/status 100 |

## 0. dev20 additions (Nov 19-20 2026)
| Item | Number |
|---|---|
| Share cards (`pipeline og`, OFF) | 162 PNG (160 ski areas + Sno-Park + site), 3.1 MB total, avg 18.8 KB, max 22.3 KB, rendered in 10.9 s locally; +162 files against the 20,000 limit |
| ECMWF AIFS line (ON after merge) | +17.3 MB download and +17 s per ECMWF run (41 steps, 160 areas); +1 file (~40 KB) inside the existing ecmwf tar |
| ECMWF on a real runner (dev19 code, Nov 20 04:00Z) | fetch step 510 s, AWS regional mirror, 26 retries, no failover, 1,275 MB; release asset 2.5 MB |
| ECMWF full uncached local run, dev20 code (12Z Nov 19) | 669 s incl. AIFS 22 s; AWS regional, 34 retries, 1,275 MB; ecCodes decodes now serialized (thread safety): <= ~58 s of the total (14 ms per message x ~4,100) |
| ECMWF resume cache | ~1.1 MB per cycle, newest 2 cycles kept, hard cap 300 MB; one Actions cache entry per run (~2 MB), evicted by GitHub after 7 days unused |
| GEFS end to end (OFF in dev20; live from dev21) | 376 MB, 249 s, 31 members, 0 retries (00Z Nov 20) |
| Browser suite | full 29 checks: ~32 min serial (dev19) -> 4.8-6.0 min (4 workers; 6 min with Lighthouse running alongside); `--quick` (8 checks) 97 s |
| pytest | 494 passed + 9 skipped, ~2 min |
| Lighthouse accessibility | 100 on all 15 page states (incl. the area page with an AIFS line) |

## 1. Platform limits that matter
| Limit | Value | Where we are |
|---|---|---|
| Files per deployment (Pages / Cloudflare Pages) | 20,000 | ~5.7 k (production build); +161 GEFS plumes (dev21), up to +~840 verification site files, +~610 if the W2 pages go live |
| Largest single file | 25 MiB | 1.45 MB (`data/points/exceed_summary.json`) |
| Total site size | none stated | ~220 MB (points 66, models 123, NDFD 21, SNOTEL 7) |
| GitHub Actions minutes | free on a public repo | see §4 |
| R2 operations (if data moves) | Class A 1 M/month free **[verify]** | hourly sync of ~3.8 k objects would be ~2.8 M/month: needs hash-skip (spec) |

## 2. Page weights (raw / gzip, KB) — `build/`, Nov 19 2026
| Page | HTML | | Page | HTML |
|---|---|---|---|---|
| index.html (obs map) | 5.0 / 1.8 | | about.html | 30.5 / 11.0 |
| area.html | 3.1 / 1.3 | | status.html | 4.4 / 1.9 |
| finder.html | 6.4 / 2.1 | | sources.html | 13.0 / 4.3 |
| mine.html | 3.2 / 1.3 | | privacy.html | 9.8 / 3.6 |
| models.html | 4.2 / 1.7 | | terms / disclaimer / 404 | 5.3 / 2.2, 5.3 / 2.2, 3.1 / 1.3 |

Shared assets: our JS 23 files = 305 KB raw / 110 KB gzip (largest: `area.js`); `style.css` 39 KB / 10 KB; Leaflet 144 KB / 42 KB; MapLibre GL (reference layer, lazy) 784 KB / 207 KB; Plotly 2.35.2 basic, **self-hosted since dev19** (`vendor/plotly-2.35.2/plotly-basic.min.js` 1,071 KB raw / 355 KB gzip, loaded only on chart pages, started when the browser is idle after `load` so it does not delay the headline paint; same bytes as before, now from our origin, so no third-party request).

## 3. Data sizes and file counts
| Folder | Files | Raw size | Notes |
|---|---|---|---|
| `data/points/` | 1,457 | 65 MB (avg 43 KB, max 1.4 MB; ~8 KB gzip per file) | NBM point forecasts, 607 areas + 837 SNOTEL sites |
| `data/ndfd/` | 1,446 | 17-21 MB (avg 12 KB, ~2 KB gzip) | |
| `data/snotel/` | 837 | 5.8-7 MB (avg 7 KB, ~1 KB gzip) | |
| `models/` (HRRR, RRFS, GFS frames) | ~1,700 (production) | ~123 MB | PNG frames; the local build holds a small subset |
| `models/ecmwf/` | 162 | 2.5 MB raw (plume files avg 14.9 KB raw / 3.7 KB gzip; 0.6 MB gzip in total) | live since dev18; `index.json` now carries `fetch` (mirror, retries, switches, status counts) and `steps_missing` |
| `data_cache/ecmwf/<cycle>/` (runner only, not published) | 41 | 1.1 MB per cycle | resume cache (sampled values per step), restored/saved by `actions/cache` in `ecmwf.yml`; a re-run of a finished cycle downloads 0 MB (3.9 s) |
| `data/*.json` shared | 13 | 2.1 MB | `multimodel.json` 123 KB / 18 KB gz, `search.json` 175 KB / 31 KB, `map_points.json` 177 KB / 28 KB, `ski_areas.json` 172 KB / 36 KB, `webcams.json` 17 KB / 2 KB, `meta.json` 2 KB |
| NBM forecast overlays (9 layers) | ~18 | 1.72 MB | +8.8 s CI |
| `vendor/` | 17 | 2.2 MB (+1.07 MB, +4 files in dev19) | Leaflet, MapLibre, plugin, **Plotly 2.35.2 + licence files**; on a site of ~5.7 k files and ~220 MB that is +4 files and +1 MB |

## 4. CI runtimes (GitHub Actions, ubuntu-24.04; read from the API)
| Workflow | Runs read | Median | p90 | Max | Notes |
|---|---|---|---|---|---|
| `update-site.yml` (hourly build + deploy) | 40 (24 ok) | 5.2 min | 8.7 min | 12.6 min | `build` job 3.1-3.3 min typical ("Build site and fetch data" 140 s), 8.8 min when SNOTEL is slow or restores; deploy 0.2-0.4 min; monitor 0.1-0.3 min |
| `models.yml` (model maps, NBM points, NDFD, NOHRSC) | 40 (all ok) | 3.6 min | 4.5 min | 4.7 min | jobs run in parallel; slowest = RRFS render 202-216 s, HRRR 150-157 s, GFS 52-131 s, points 95-139 s, NDFD 24 s, NOHRSC ~30 s; most runs exit early when nothing is new |
| `tests.yml` (pull requests: pytest) | 6 | 0.5 min | 0.6 min | 0.6 min | 421 tests offline at the time of the read; 467 passed + 9 skipped locally after dev19 (102 s on a laptop, includes the real-HTTP-server fetch tests) |
| `ecmwf.yml` (dev18; resilient since dev19) | measured locally | ~5-8 min | | | 300 s / 1,214 MB (00Z) and 336 s / 1,205 MB (12Z) on a laptop on the AWS mirror (dev18); **dev19, Nov 19 12Z run: the AWS regional mirror tripped the breaker, the run failed over to Google: 456 s / 1,275 MB, 18 retries, 0 steps missing**; an immediate re-run reads the per-step cache: 3.9 s, 0 MB. Expect 5-10 min on a runner when a mirror throttles; timeout 30 |

Per-run network volume of the model jobs (from the model-maps assets, PLAN §2 history): HRRR tar ~98 MB, RRFS ~83 MB, GFS ~23 MB; ECMWF ~1.2 GB downloaded (0.6 MB published).

## 5. Lighthouse (local, gzip server like Pages, mobile profile; dev18 branch, Nov 19 2026; dev19 rows added below the table)
Accessibility is **100 on every one of the 15 page states** (target >= 95). Performance (single run per page unless stated; the obs map and area page are medians of 3 interleaved runs against main):

| Page state | Perf | A11y | CLS | LCP s | TBT ms |
|---|---|---|---|---|---|
| obs map (index) | 89 (main 88) | 100 | 0.016 (main 0.027) | 3.2 | 182 |
| area page, ski area | 89 (main 89) | 100 | 0.014 | 2.0 | 402 |
| area page, SNOTEL / Sno-Park | 93 / 91 | 100 | 0.014 | 1.9 / 2.0 | 274 / 348 |
| Powder Finder / Sno-Parks | 96 / 87 | 100 | 0.000 | 2.1 | 172 / 468 |
| My mountains | 100 | 100 | 0.008 | 1.1 | 0 |
| model maps | **100** (was 90) | 100 | **0.01** (was 0.21) | 1.2 | 0 |
| status, about, sources, privacy, terms, disclaimer, 404 | 100 | 100 | 0.00-0.04 | 1.1-1.4 | 0-13 |

**dev19 re-measurement (6 interleaved runs each against main's web files with the same data; main loads Plotly from cdn.plot.ly, dev19 from our own host):**

| Page | dev19 | main | Notes |
|---|---|---|---|
| obs map (index) | 88.0 (CLS 0.021, LCP 3.25 s, TBT 200 ms) | 88.5 (0.016, 3.16 s, 188 ms) | same within run-to-run noise |
| area page, ski area | **88.0** (CLS 0.014, LCP 2.02 s, TBT 416 ms) | 88.0 (0.014, 2.01 s, 421 ms) | the FIRST self-hosted version scored **75** (LCP 4.2 s): the early same-origin Plotly request is part of Lighthouse's simulated LCP graph (the CDN request on another origin was not), so the download now starts when the browser is idle after `load`; real users see the same headline paint, charts follow |
| Sno-Park Finder (5 runs) | **93** (TBT 276 ms) | 86 (TBT 506 ms; same data) | 447 DOM Sno-Park markers (divIcon + tooltip + popup) replaced by squares drawn on the map canvas; "Show all" and the 200-row cap are unchanged |

The model-maps CLS (0.21 with a catalog whose frames are missing, the worst case; 0.20 reproduced with a slow catalog at 412 px) came from the player row re-wrapping when the hour label arrived; fixed with a reserved row (`browser_check --only models` now delays the catalog and fails on the old CSS). Remaining ceiling for the obs map is tile-server timing (bimodal 71-91, see PLAN §2).

## 6. How to re-measure
- Sizes and counts: `python <scratch>/sizes.py build` (the script is a few lines of `Path.rglob` + `gzip.compress`; see this file's tables for the quantities) or `du -sh build; find build -type f | wc -l`.
- CI runtimes: the public REST API (`/repos/alexluke23/snow-wx/actions/workflows/<file>/runs`, then `/actions/runs/<id>/jobs`); no token needed for a public repo.
- Lighthouse: `PATH=/c/miniforge3/envs/tools:$PATH npx -y lighthouse@12.6.1 URL --only-categories=performance,accessibility` against a gzip server of `build/` (the plain `http.server` understates mobile scores); median of ≥ 3 interleaved runs.
- After the move: repeat the same four on the Cloudflare origin; the parity script in `docs/specs/hosting-seo.md` covers byte-equality.
