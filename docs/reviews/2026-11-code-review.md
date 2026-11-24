# Snow-Wx code review, November 2026

Written for: the three developers taking over Snow-Wx (pipeline / API + infra / web + mobile).
Review date: Nov 23 2026. Commit reviewed: `bf8f8ac` (main after PR #35, the models-page hotfix).
Read-only review. Nothing was changed except this file. Every finding below was checked in the code by the reviewer. The plan used is the PLAN v1.4 and `platform-transition.md` v1.1 shared with the review; **neither is committed yet** (the repo's `docs/PLAN.md` is still v1.1, see F-L1).

Severity: **Critical** = wrong forecast shown, safety-rule violation, secret leak or data loss. **High** = likely failure in production or during the migration. **Medium** = edge-case correctness or a real maintainability cost. **Low** = nits.

---

## 1. Summary

The codebase is in good shape for a project of its size. It has 606 offline tests that pass. Percentile handling is careful (no composite range reaches the UI), there are no secrets in the code or the git history, and fetch code is mostly kept apart from pure functions. The weak spots are where data is **published or replaced**, how **safety data behaves when a fetch fails**, and a few **timing and window bugs**.

Top 5 risks:
1. **Forecast archive can be lost** (C1): `gh release upload --clobber` deletes the only copy of a month before the new one is uploaded.
2. **Safety info can vanish or look current when it is not** (C2, H2, H3):
   - the "Extreme" avalanche label is unreadable;
   - expired ratings stay coloured between builds;
   - a failed alerts or avalanche fetch ships a page with no alerts and no avalanche link, and nothing says data is missing.
3. **The scope trim can silently break plumes and verification** (H5, H6):
   - HRRR/RRFS/GFS plume lines are produced inside the map-rendering loop;
   - M9 verification and the M11 baseline score only the SNOTEL-site NBM forecasts that the trim plans to drop.
4. **Wrong snow-ratio, powder-quality and wind-affected labels past f036** on the production 01/07/13/19Z cycles (H1): an off-by-one 6-h window lookup.
5. **Deploys can ship without forecast products, silently** (H4): a failed release listing deploys a site with no points, ECMWF, GEFS or verification. The monitor then reports "waiting" instead of an alarm.

**Ready for the platform move?** Not yet. Do these first:
- the C1/H3/H4 publish fixes;
- the H5/H6 decoupling (before the scope trim);
- pinned dependencies (H7);
- atomic writes (M17).

None of these is large. The pipeline already runs as plain `python -m pipeline <cmd>` commands, which is the right shape for one container image.

---

## 2. Repo map

| Path / entry point | Purpose |
|---|---|
| `pipeline/__main__.py` | CLI. Sub-commands: `build` (obs sources `alerts afd avalanche hazards snotel asos` + site copy + merges), `points`, `models`, `ecmwf`, `gefs`, `ndfd`, `nohrsc`, `catalog`, `archive`, `archive-check`, `verify`, `verify-ci`, `restore`, `pages`, `pwa`, `og`, `stub`, `linkcheck`, `webcams`, `r2-plan`. `product_status()` writes per-source health to `data/meta.json`. |
| `pipeline/nbm/` | NBM GRIB inventory (`inventory.py`), fetch, decode and point forecasts (`run.py`), obs-map overlay layers (`layers.py`), NDFD sanity (`sanity.py`). |
| `pipeline/points.py`, `summary.py` | Pure forecast maths (lapse rate, P(snow), SLR, powder class) and Daily Snow summary rules. |
| `pipeline/ecmwf.py`, `ecmwf_attempts.py`, `gefs.py`, `fetch_resilient.py` | ECMWF HRES/ENS/AIFS and GEFS point sampling for plumes. Resilient byte-range fetcher. |
| `pipeline/models/` | HRRR/RRFS/GFS map rendering (`run.py`, `plot.py`, `derive.py`, `catalog.py`) **and** the plume/ridge point samplers (`multimodel.py`, `ridge.py`), which run inside the map loop. |
| `pipeline/snotel.py`, `asos.py`, `alerts.py`, `afd.py`, `avalanche.py`, `hazards.py`, `nohrsc.py`, `restore.py` | Observations, NWS alerts/AFDs, avalanche.org ratings, NWS hazards list, NOHRSC/SNODAS layers, last-good SNOTEL restore. |
| `pipeline/archive.py`, `archive_check.py`, `verify.py` | Forecast archive (CSV assets on the `verification` release), integrity check, M9 scorer. |
| `pipeline/catalog.py`, `rec.py`, `search.py`, `webcams.py` | Ski-area catalog builder (OpenSkiMap + 3DEP), Sno-Park builder, search index, webcam links. |
| `pipeline/pages.py`, `pwa.py`/`pwa_sw.js`, `og.py`, `stub.py`, `linkcheck.py`, `r2_plan.py` | Built-but-off W1/W2/W4 pieces: prerendered pages, PWA, share cards, redirect stub, link checker, R2 plan. |
| `pipeline/monitor.py` | Opens and closes GitHub issues from the live `meta.json`. |
| `pipeline/alerts_backend.py`, `wind_exposure.py` | W6 / W7 skeletons (OFF). |
| `.github/workflows/update-site.yml` | Hourly `:17`: unpack release tars → `restore` → `build` → size guard → `archive` → `rm data/ndfd` → Pages deploy → `monitor`. |
| `.github/workflows/models.yml` | `55 1-22/3` and `55 2,8,14,20`: matrix `hrrr rrfs gfs points nohrsc ndfd` → `<product>-<cycle>.tar` on `model-maps` → dispatch update-site. |
| `.github/workflows/ecmwf.yml`, `gefs.yml`, `verify.yml`, `tests.yml` | ECMWF hourly attempts `50 8-13,20-23,0-1`; GEFS `10 6,8,18,20`; verification `25 15`; pytest on PRs. |
| `infra/scheduler/` | Cloudflare Worker (built, not deployed) that dispatches the five workflows on time. |
| `web/index.html` + `js/app.js` | Obs map (SNOTEL, ASOS, avalanche, hazards, NOHRSC + NBM overlays). |
| `web/area.html` + `js/area.js` | Ski-area / Sno-Park / SNOTEL-site forecast page. Uses `multimodel.js`, `ensemble.js`, `verification-ui.js`, `charts/*`, `freshness.js`, `summary-ui.js`. |
| `web/finder.html`, `mine.html`, `models.html`, `status.html`, `about.html`, `sources.html` + legal drafts | Powder Finder, My mountains, model-map viewer, data status, methods, sources register. |
| `tests/`, `tools/browser_check.py` (+ `browser_fixtures.py`, `model_fixture.py`) | 606 offline pytest tests; 38 headless-Chrome checks. |
| `config/settings.yml`, `models.yml`, `sources.yml`, `ski_areas.yml`, `webcams.yml`; `data/*.json` | Flags and limits; committed catalogs (ski areas, SNOTEL points, Sno-Parks). |

**Config flags** (`config/settings.yml`):
- **On:** `snotel`, `asos`, `avalanche`, `forecast_overlays`, `gefs`, `ecmwf`, `aifs` (`in_badge: false`), `hazards`, `verification.ci_enabled`.
- **Off:** `r2`, `og_images`, `pages`, `pwa`, `analytics`, `alerts_backend`, `wind_exposure`, `verification_ui`.

---

## 3. Findings

Sorted by severity. Effort: S < ½ day, M ≤ 2 days, L > 2 days.

| ID | Sev | Area | File:line | Problem | Evidence | Suggested fix | Effort |
|---|---|---|---|---|---|---|---|
| C1 | **Critical** | archive | `pipeline/archive.py:297`, `:384-389` | Replacing a monthly archive file can destroy it. `upload()` runs `gh release upload … --clobber`. gh's clobber deletes the existing asset of that name, then uploads. If the upload fails (5xx, timeout, runner killed), the asset is gone. The next run sees `name not in names`, sets `existing = {}`, and rebuilds the month from a single build. The release is the **only copy** (docs/verification.md: "never on a local PC"). | `existing = read_csv_gz(...) if name in names else {}`; `self._gh("release", "upload", self.tag, str(path), "--clobber")` | Upload under a temporary name, then delete the old asset and rename the new one. Or keep a second copy: a dated backup asset now, R2 with object versioning after the move. Add a test where the upload fails after the delete. | M |
| C2 | **Critical** | web, safety | `web/css/style.css:162`; `web/js/area.js:1059` | The **"Extreme" avalanche danger label is unreadable** on every ski-area page: text `#111` on background `#231F20` (contrast ≈ 1.1:1). The obs map and My mountains set a readable text colour; the area page doesn't. | `.danger-chip {… color: #111; }`; area.js sets only `style="background:${esc(p.color)}"`; compare `mine.js:85` `color:${textOn(r.color)}`, `colors.js:101` `DANGER_TEXT` | Add `color:${DANGER_TEXT[p.danger_level] ?? textOn(p.color)}` on the area chip. Add a browser assertion for contrast on all 5 levels. | S |
| H1 | High | pipeline, NBM | `pipeline/nbm/run.py:361`, `:416` | **Off-by-one 6-h window lookup on the 01/07/13/19Z cycles** (the production cycles). Windows end at f005, f011, … f041, f047 (valid 00/06/12/18Z). `h + (-h % 6)` rounds to multiples of 6, and those hours don't exist past f036: the 13Z cycle of Nov 21 has hours `38, 41, 44, 47…`.<br>Effects past f036:<br>• `raw_snow_at()` is always 0.<br>• `slr_in()` falls back to the window's **maximum** SNOWLR, so the period SLR runs high and the powder/"snow type" labels on days 2–10 are biased toward lighter snow.<br>• `snowy_gusts` is empty, so "wind-affected" is never set and the summary's wind rule is silent.<br>• Up to f036, `dry` (line 418) never fires.<br>Snow amounts and percentiles are not affected. | line 354 already uses the correct form: `v(h + (-(init.hour + h) % 6), "pop6")` | Use `h + (-(init.hour + h) % 6)` at both places. Add a test on an 01Z/13Z fixture that checks `slr` and `snow_type` past f036. | S |
| H2 | High | pipeline + web, safety | `pipeline/avalanche.py:77`; `web/js/area.js:1059`, `mine.js:85`, `app.js:286,298` | **Expired avalanche ratings can be shown as current.** `expired` is computed once, at build time. Between builds the browser trusts the flag. GitHub delivered about 6 of 46 hourly runs (PLAN §2), so many-hour gaps are normal, and a rating that expires in a gap keeps its full colour. | `expired = level in DANGER and end is not None and end < now`; `end_date` is already in the ratings index (`avalanche.py:100`) | In the browser, compute `expired = Date.parse(r.end_date) < Date.now()` (or OR it with the flag) wherever the flag is read. Add a test with a frozen clock. | S |
| H3 | High | pipeline + web, safety | `pipeline/avalanche.py:110-113`, `alerts.py:218-221`, `afd.py:97`; `restore.py:37-82`; `web/js/area.js:1058`, `:1189-1190` | **A failed alerts or avalanche fetch publishes pages with that safety info missing, silently.** Each source correctly "fails before writing", but on a fresh runner (and later in an ephemeral container) there is no last-good file. `restore` brings back SNOTEL only. Then:<br>• the area page shows **no alert banner and no notice** (`… : ""`);<br>• the avalanche block shows the zone name **without the link to the center** (`if (!p) return <p>${esc(a.zone)}</p>`).<br>An active Winter Storm Warning looks like "no alerts". | `raise RuntimeError("no avalanche zones in region")`; `restore` docstring: "meta.json, snotel.geojson and the young station files" | (1) Restore last-good `alerts/`, `avalanche*.json`, `afd/` from the live origin (later R2), flagged stale. (2) On fetch failure show "NWS alerts could not be loaded, check weather.gov" plus a link, and always link the avalanche center (or avalanche.org) with "rating not available". | M |
| H4 | High | workflows | `.github/workflows/update-site.yml:54`; `pipeline/__main__.py:110-111` (and the same pattern for ecmwf/gefs/verify); `pipeline/monitor.py:66-72` | **A failed release listing deploys a site with no forecast products, and nothing alarms.**<br>• `names=$(gh release view model-maps … 2>/dev/null \|\| true)` turns an API error into "nothing published". Pages replaces the whole site, so points (NBM), ECMWF, GEFS and verification are gone for at least an hour.<br>• The status functions then return `waiting: True` ("waiting for the first run").<br>• The monitor never alarms on `waiting`. | `except (OSError, ValueError, KeyError, TypeError): return {"ok": None, "waiting": True, …}`; `if e.get("disabled") or e.get("waiting"): … no alarm` | Retry the listing; fail the build (keep the previous deploy) if it stays empty. In `product_status`, keep `last_success_at` (as `with_history` does for obs) so a product that delivered before can never go back to "waiting". | S |
| H5 | High | pipeline, scope trim | `pipeline/models/run.py:238-250`, `:280-292`, `:324-335`, `:262`; `pipeline/__main__.py:274-283` | **The HRRR/RRFS/GFS plume lines and ridge winds exist only as a side effect of map rendering.**<br>• `PrecipSampler` and the ridge `Sampler` are fed inside the render loop.<br>• `precip.json` and `ridge.json` are written only if at least one PNG rendered (`if not ok: return 1`).<br>• Rendering needs a Natural Earth download (`ensure_basemap_data()`).<br>• The merges run in the same `try` as `write_catalog`.<br>So deleting map rendering for the Nov 23 scope trim, or any matplotlib/cartopy failure today, removes three of the plume models and drops the agreement badge to "needs at least three models". `ecmwf.py:588` and `gefs.py:178` also import `models.multimodel.load_points`. | see lines; `area.js:595` badge needs ≥ 3 models | **Before the trim:** add a sample-only path (fetch → decode → `derive_frame` totals → samplers, no plotting) as its own job. Write `precip.json`/`ridge.json` independently of images. Move `load_points` to a neutral module. Then delete `plot.py` and the map parts. | M–L |
| H6 | High | scope trim, verification | `pipeline/verify.py:50`; `tools/slr_baseline.py:66`; `pipeline/nbm/run.py:744-758`, `:772-773` | **M9 verification and the M11 baseline score only the NBM forecasts made at SNOTEL sites** (`snotel-<triplet>` points; ski areas have no co-located observation). The Nov 23 plan ("stop SNOTEL-site forecast pages… ~1,444 → ~160 points") would leave verification with nothing to score from the next cycle on. | `forecasts["point"].astype(str).str.startswith("snotel-")` | Keep computing and archiving the SNOTEL-site point forecasts (`station_outputs`). Remove only their pages, search entries and links. Decide §11 item 13 with this in mind. | S (decision) |
| H7 | High | migration, deps | `environment.yml:8-28` | **No dependency is pinned** (no versions, no lock file), and notebook tools (`jupyterlab`, `ipykernel`) are in the production environment. Every CI run resolves fresh versions. The test run already warns of a binary mismatch: `numpy.ndarray size changed, may indicate binary incompatibility`. A Docker image built from this file is not reproducible. | `- numpy`, `- eccodes`, `- herbie-data` … no versions | Generate a lock (`conda-lock` or `micromamba env export --explicit`) per platform. Split `environment.dev.yml` (notebooks) from the runtime environment. Build the container from the lock. | S |
| H8 | High (latent) | pages (W2) | `pipeline/pages.py:101`, `:121-124`, `:150-153` | **Redirect loop once `pages.enabled` is turned on.** The prerendered page links to `area.html#<id>`, and `id-redirect.js` (injected into `area.html`) sends every mapped id back to the prerendered page. The interactive page, with alerts, avalanche, snow level and charts, becomes unreachable. Rated High only because W2 is OFF. It blocks W2. | `<a href="{bp}/area.html#{e(a['id'])}">…`; `if(m[id])location.replace(m[id])` | Link to a non-redirecting form (e.g. `area.html?i=1#id`) and skip the redirect for it. Add a browser check that follows the link. | S |
| M1 | Medium | summaries | `pipeline/summary.py:59-63`, `:127`, `:138`, `:148-159` | The summary says "next 24 h / next 72 h", but uses the **first exceedance window ending 12Z**. That window can start up to ~23 h after the cycle (for example f017–f041 on a 19Z run). `storm_cycle` also takes p50 from one window and the range from the totals window (a different window). | `"the median forecast for the next 24 h is …"`; `_first_window` returns `ex["start"][0]` | Word it by the actual window ("from Tue 5 AM to Wed 5 AM"), and take p50 and the range from the same native window. | S |
| M2 | Medium | verification | `pipeline/verify.py:28`, `:78` | Lead buckets use the lead to the window **end**. Every 24-h window starts at or after the cycle, so `lead_h ≥ 24`: "day 1 (0-24 h)" is always empty and every bucket is labelled one day late. This matters when the panel ships. | `LEADS = [(0, 24, "day 1 (0-24 h)"), …]` applied to `lead_h` = cycle → end | Bucket by `lead_h - hours` (window start), or relabel. | S |
| M3 | Medium | NBM | `pipeline/nbm/run.py:385-386` | A 6-h window with **no snow-level data** gets P(snow) = 1.0. The base point then receives the full cell snowfall during rain, while the hourly chart (line 419, `or 0.0`) shows 0 for the same hours. Up to 20 % missing messages still publishes. | `pw = sum(pw) / len(pw) if pw else 1.0` | Treat it as a gap (`None`), or fall back to the deterministic snow level. | S |
| M4 | Medium | NBM | `pipeline/nbm/run.py:825` | The quality gate is global. If one field disappears entirely (for example `snow6` renamed, about 5 % of messages), the run publishes "new" data with no snowfall windows. Every page then shows no snow. | `if quality["share"] > MAX_MISSING_SHARE …` (`by_field` is already computed) | Also fail when any required field is missing in more than about 20 % of its hours. | S |
| M5 | Medium | web, rule 4 | `web/js/area.js:470` | The snow-ratio "likely X–Y:1" takeaway is the **minimum p25 and maximum p75 across all wet hours**. That is an envelope over many hours labelled with the single-window word "likely". | `Math.min(...idx.map((i) => p25[i] ?? p50[i]))` … `Math.max(...p75…)` | Show the median range only, or the p25–p75 at the hour of the extreme median. Don't call an envelope "likely". | S |
| M6 | Medium | web, plumes | `web/js/multimodel.js:81` (and `pipeline/models/multimodel.py:138-146`) | Null points are filtered out before drawing and before badge interpolation, so **a missing ECMWF step is bridged by a straight line and by `interpAt`**. That breaks the dev19 rule "a missing step is a GAP, never interpolated". | `.filter(([x, y]) => x >= t0 && y !== null)` | Keep the nulls (`connectgaps: false`), make `interpAt` return null across a gap, and match the Python reference. | S |
| M7 | Medium | GEFS | `pipeline/gefs.py:240` | A failed CSNOW message counts as **"no snow"** for that member and 6-h bucket, which permanently lowers its running snow total. | `… if r[1] is not None else 0.0` | Mark it missing (NaN) and count it in `missing`. | S |
| M8 | Medium | GEFS, idempotency | `pipeline/gefs.py:150-161` | The resume cache is written in place (`np.savez_compressed` to the final name), and loading catches only `OSError, ValueError, KeyError`. A run killed mid-write leaves a truncated `.npz`. `zipfile.BadZipFile` then aborts **every later attempt** on that cycle (the cache is saved with `if: always()`). | `with np.load(...)` … `except (OSError, ValueError, KeyError): return None` | Write to a temporary file and `os.replace` it (as `ecmwf.py:415-417` does). Catch `Exception` on load and delete the bad file. | S |
| M9 | Medium | ECMWF | `pipeline/ecmwf.py:610`, `:752` | A cycle published **with gaps** is never treated as "already published": its tag is `partial_tag(tag_full)`, but the check compares with `tag_full`. Every hourly attempt re-runs, can emit `new=true` with the same partial tag, and re-uploads and redeploys (up to 6 times per cycle). `generated_at` keeps moving, so the monitor sees an old partial cycle as fresh. | `if published == tag_full:` … `tag = partial_tag(tag_full) if steps_missing else tag_full` | When `published == partial_tag(tag_full)` and no new step was fetched, emit `new=false`. | S |
| M10 | Medium | workflows, security | `.github/workflows/models.yml:87` | **Shell injection.** A `workflow_dispatch` input is pasted into bash: `want="${{ github.event.inputs.models }}"`. The planned scheduler token has Actions write only, but anyone holding it could inject commands that run with this workflow's `contents: write` + `actions: write` token. | line 87 | Pass the input through `env:` and validate it against `^[a-z0-9 ]*$`. Same for the boolean `force` inputs. | S |
| M11 | Medium | workflows, security | `.github/workflows/update-site.yml:3-6`, `:36`; `models.yml:81`, `ecmwf.yml:39`, `gefs.yml:37`, `verify.yml:38`; all `uses:` lines | Permissions are workflow-wide: the build job gets `pages`/`id-token: write`, and every pipeline step and `pytest` run with a write-capable `GH_TOKEN`. Actions are pinned to tags, not SHAs (`mamba-org/setup-micromamba@v3` is third-party). | `permissions: contents: write, pages: write, id-token: write` | Set permissions per job. Set `GH_TOKEN` only on the `gh` steps. Use `persist-credentials: false` on checkout. Pin SHAs (at least for micromamba). | S |
| M12 | Medium | web, safety | `web/js/area.js:1085-1100`; `web/area.html:32` | `alertBanner` shows every ref in the index without checking `ends`, so a stale index (between builds) shows expired warnings as active. `#updated` on the area page is never filled (no reference in `area.js`), so the page never says how old the alert data is. | `refs.filter((r) => r.relevant !== false)` (no time filter) | Filter `Date.parse(r.ends) > Date.now()`. Show "Alerts checked <time>" from `alerts/index.json` `generated_at`, and flag it when it is older than about 2 h. | S |
| M13 | Medium | ops | `.github/workflows/update-site.yml:98`; `config/settings.yml:191-206` | The forecast-archive step is `continue-on-error`, and `monitoring.sources` has no `archive` entry. An archive outage of days (an M9/M11 data gap) alerts no one. | `continue-on-error: true`; no `archive:` key | Write an `archive` status (last cycle archived, rows added) into `meta.json` and monitor it (for example max 14 h). | S |
| M14 | Medium | scheduler | `infra/scheduler/src/due.js:86-87`; `src/tick.js:43`; `.github/workflows/models.yml:88` | Dispatches send no inputs. In a dispatched run `github.event.schedule` is empty, so the NBM-points slot (`55 2,8,14,20`) runs the **whole matrix**. That slot is also skipped while an earlier models run is still active, and its window then closes. | `body: JSON.stringify({ ref: env.GH_REF })`; `if (active) return {… "skip"}` | Give each slot its inputs (`{models: "points"}`). For queued-safe workflows, dispatch even while a run is active (the concurrency group queues it). | S |
| M15 | Medium | migration | `pipeline/common.py:75`; `pipeline/ecmwf.py:724-729`; `pipeline/gefs.py:268-274`; `pipeline/models/run.py:244`; `pipeline/nbm/run.py:834-847` | **Outputs are not atomic, and good files are deleted before the new ones exist.** `write_json` opens the final path. Plume, point and `precip.json` files are deleted before the new set is written. This is safe today only because CI tars a fresh directory on success. With a persistent volume or a direct R2 sync, a killed job publishes a truncated or mixed cycle. | `with open(path, "w", …)`; stale files `unlink()` before writes | Write to a staging prefix, then swap the `latest` pointer (or `os.replace` per file). Upload `index.json` last. Keep the delete-after-success order. | M |
| M16 | Medium (latent) | PWA | `pipeline/pwa_sw.js:18`, `:57-62`, `:86` | Once `pwa.enabled` is on, alerts, avalanche ratings and favourites' points are **stale-while-revalidate**: an online visit renders the previous visit's copy first. With H2, old ratings would look current. | `SMALL_DATA = [… "data/alerts/index.json", "data/avalanche_ratings.json" …]` → `swr()` | Use network-first (with a timeout) for safety data; use the cache only offline, labelled with its age. | S |
| M17 | Medium (latent) | CSP | `docs/cloudflare_headers.draft:26`; `web/js/hazards.js:96` | The draft CSP's `connect-src` lacks `https://mapservices.weather.noaa.gov`, but the hazards layer `fetch()`es it. Once enforced at W1, the default-on NWS hazards layer always drops to its fallback. | `connect-src 'self' https://tiles.openfreemap.org` | Add the host to `connect-src`, and make the `csp` browser check wait for the hazards layer. | S |
| M18 | Medium | NBM, robustness | `pipeline/nbm/run.py:602-652`, `:769-771`, `:795-796` | There is no per-record guard. One catalog record (ski area, Sno-Park or SNOTEL point) without `nbm_grid`, `region` or `elev_ft` raises a `KeyError` before any fetch and stops the whole points run. `rec_points.json` is merged without validation. No current record was found to be broken. | `cells = sorted({(a["nbm_grid"][k]["i"], …`; `"region": a["region"]` | Validate at load, skip bad records with a warning, and wrap the per-area body. | S |
| M19 | Medium | tests | `tools/browser_check.py:470-591` (`charts`), `:1202-1314` (`ensemble`), `:1318-1406` (`mmodel`), plus `forecast`, `mine`, `storm`, `pwa`, `mmchips`, `alertcls`, `slrchart`, `lean`, `rootbase`; `tests/test_models_catalog.py:85-95` | The browser suite still reads **live point, multimodel and ensemble data** from `build/`. Only alerts and third-party hosts are frozen (`browser_fixtures.py:54-67`). A dry forecast fails `charts`, `ensemble` and `mmodel` today (32/38 green on Nov 23). `slrchart` claims a "Grand Targhee fixture" but reads the live file. The new catalog contract test also reads `build/`. | `prepare_site` copies `build/` then freezes alerts only | Planned in PR B: commit snowy and dry Alta fixtures and make every check use them. Mark build-reading pytest tests with an explicit marker. | M |
| L1 | Low | docs | `docs/PLAN.md:1`; `README.md:14,57,74-84,117,130` | Committed docs lag the decisions:<br>• `docs/PLAN.md` is v1.1 (v1.4 and `platform-transition.md` exist only outside the repo);<br>• README still documents `models.html`, NDFD as the "NWS official point forecasts", and GitHub Pages setup;<br>• CLAUDE.md's dev22 bullet still says "(branch)". | header lines | Commit PLAN v1.4 and `platform-transition.md`. Rewrite README for the trimmed product. | S |
| L2 | Low | pipeline | `pipeline/common.py:71`; `pipeline/nbm/run.py:602-645` | `write_json` defaults to 2 decimals, so lat/lon in `summary.json` and the embedded `area`/`station` records lose precision (about 1 km). | `def write_json(path, obj, ndigits=2)` | Pass `ndigits=5` for documents carrying coordinates. | S |
| L3 | Low | performance | `pipeline/summary.py:97` | `load_rules()` (two YAML parses) runs for every one of about 1,300 documents per points run. | `rules = rules or load_rules()` | Load once in `build_outputs` and pass it in. | S |
| L4 | Low | web, XSS (Sno-Parks) | `web/js/area.js:1174-1175` | `href="${safeUrl(…)}"` is not escaped; `safeUrl` only checks the `https?://` prefix, so a USFS/OSM URL containing `"` could inject attributes. It goes away with the Sno-Park removal. | `safeUrl = (u) => (/^https?:\/\//i.test(u \|\| "") ? u : "#")` | `esc(safeUrl(…))`, as at line 1240. | S |
| L5 | Low | privacy | `config/settings.yml:71`; git author metadata | The owner's personal Gmail is published as the site's feedback address. One commit's author name contains a pasted `git config … user.email …` command. | `feedback_email: "…@gmail.com"`; `git shortlog -sn` | Use a role address on the new domain ("set by owner at W1"). The author string is history; it leaves with the GitHub repo. | S |
| L6 | Low | workflows | `.github/workflows/ecmwf.yml:65`, `gefs.yml:10`, `verify.yml:11` | Stale comments ("four daily attempts", ECMWF "at :40"). | comments | Update when the workflows move. | S |

**Checked and found correct** (no finding):
- No composite percentile range reaches the UI. Totals set `native` only for one native window (`nbm/run.py:556`), and every consumer checks it: `area.js:67,162`, `finder.js:135-136`, `mine.js:24`, `summary.py:76,133`. 7/10-day totals show the expected amount only.
- The rank-summed 12-h `snow_q1/q3` (the documented exception) has no web consumer.
- `alternativeRowScanning` is handled in both decode paths.
- AIFS is kept out of the agreement badge (`multimodel.py:127`; `multimodel.js:60,111`).
- Units are correct: AIFS kg m⁻² ÷ 25.4 (`ecmwf.py:495`); IFS metres → 0.1 mm / inches (`ecmwf.py:159,224`).
- Archive columns match `docs/verification.md`; the dev23 SLR columns are append-only.
- Fetched text is escaped: alert text, AFDs, search results, webcams and hazard popups (`textContent`).
- Heuristic labels are present on the agreement badge, powder quality, the daily summary, the wind flag and the verification panel.

---

## 4. Hard-rule compliance checklist

| Rule (PLAN §0) | Result | Evidence |
|---|---|---|
| 1. Safety info never gated or hidden | **FAIL** | C2 (Extreme label unreadable), H2 (expired rating shown as current between builds), H3 (failed alerts/avalanche fetch → no banner, no center link, no notice), M12 (expired alerts shown, alert age never shown). Nothing is paywalled; all failures are display/robustness. Latent: H8 (W2 redirect loop), M16 (PWA serves old safety data first). |
| 2. Heuristics labelled, never accuracy or avalanche ratings | **PASS** (one weakness) | Badge "a heuristic" (`area.js` mm-badge), powder quality "documented heuristic", summary "rules, not a person", W7 disclaimer, verification panel "not an accuracy rating". Weakness: H1 makes the powder/snow-type and wind labels wrong past f036 (labelled, but wrong). |
| 3. License-clean data with attribution | **PASS with gaps** | ECMWF "Contains ECMWF open data … CC BY 4.0 … adapted" on the plume panels; NOAA/NWS on charts; OpenSkiMap/OSM ODbL on the maps. Gaps: the area-page footer (`area.html:40-41`) credits neither avalanche.org nor USDA NRCS; the SNOTEL observation charts (`area.js:1025-1033`) have no source/time line; prerendered pages (`pages.py:102`) have no ODbL credit. |
| 4. No percentiles summed, scaled or interpolated across windows; p25–p75 default; sources + issue times on every module | **PARTIAL** | Percentile arithmetic: pass (see "checked and found correct"). Fails: M5 (snow-ratio "likely" is a cross-hour envelope), M6 (plume lines/badge interpolate across ECMWF gaps). Issue times: "Precipitation by model" names HRRR/RRFS/GFS but shows no run time for them (`area.js:607`; `multimodel.py` keeps runs up to 24 h older than the newest); the SNOTEL obs charts have none. |
| 5. Sources fail independently; fetch separate from pure functions; offline tests | **PASS with gaps** | `SOURCES` registry in `__main__.py:26`; 606 tests pass offline (no network found in tests). Gaps: M18 (one bad record stops the whole points run), H5 (plume sampling depends on map rendering), M19 (browser suite reads live build data). |
| 6. Static-host limits; bulk data to R2 | **PASS** | Local build 5,405 files / 302 MB after dev23 (limit 20,000 / 25 MiB per file); size guard in `update-site.yml`; `r2-plan` prepared. |
| Browser contacts only USGS, OpenFreeMap, NOAA hazards | **PASS** | Hosts in `config/sources.yml` `browser:`, enforced by the `privacy` browser check. Analytics hosts load only when `analytics.enabled` (off). |

---

## 5. Scope-trim inventory

REMOVE = only used by the removed feature. KEEP = also feeds plumes, SNOTEL obs, verification or the archive. UNSURE = needs a team decision. **Shared-code hazards are marked ⚠.**

### 5.1 Model maps

| Item | Mark | Why |
|---|---|---|
| `web/models.html`, `web/js/models.js` | REMOVE | Viewer only. |
| Nav links in every page (`404/about/area/disclaimer/finder/index/mine/models/privacy/sources/status/terms.html` ~line 18-21) + generator `tools/gen_site_pages.py:38` | REMOVE | Add a redirect `models.html → /` (platform §5.3). |
| CSS `web/css/style.css:22-23, 29-58, 138-139, 551-552` (viewer, `#prev/#play/#next`) | REMOVE | Keep `#chart` (~131: obs map). |
| `pipeline/models/plot.py` (all), `catalog.py` (all), map parts of `run.py` (`FIELD_ARRAYS` 37-42, map branches of `derive_frame` 99-164, process pool/`render_task` 264-317, `build_index`/`frame_sizes`/`png_size` 347-403, run-dir cleanup 229-231/336-338) | REMOVE **after** H5 | ⚠ The same loop feeds the plume and ridge samplers. |
| `pipeline/models/fetch.py`, `derive_frame` run totals (`state.totals`, run.py:83-97), `config.py` `var_catalog`/`needed_vars` | **KEEP** ⚠ | Needed to download/decode APCP and orography for the HRRR/RRFS/GFS plume lines; APCP is only downloaded because QPF fields are configured (`fetch.py:81-82`). |
| `pipeline/models/derive.py` (Kuchera, WBZ, vorticity, smoothing) | REMOVE (check) | Map-only fields; confirm nothing in the samplers uses them. |
| `pipeline/models/multimodel.py`, `ridge.py` | **KEEP** | Plume lines and ridge wind. Move `load_points` out of `models/`: `ecmwf.py:588` and `gefs.py:178` import it ⚠. |
| `config/models.yml` image/domains/field_domains/per-model fields/`budget` | UNSURE | `budget.max_site_mb` is read by the update-site size guard (`update-site.yml:86`); keep a sampling-only config block. |
| `.github/workflows/models.yml` matrix entries `hrrr rrfs gfs` | REPLACE | Keep them as **sample-only** jobs (H5); `points`, `nohrsc`, `ndfd` entries stay. |
| `pipeline/__main__.py:185-196` (`models` status row), `:275-277` (`write_catalog`), `models` CLI 288-304/452-464; `config/settings.yml:202` `monitoring.sources.models`; `web/js/status.js:8-9`, `web/js/app.js:669` | REMOVE / REPLACE | Replace with a per-model "plume sampling" health row (newest HRRR/RRFS/GFS `precip.json` age). |
| `pipeline/stub.py:23` (`OLD_PAGES` has models.html), `docs/cloudflare_headers.draft:38-39` (`/models/*`), `pipeline/pwa.py:41-42` (precaches every html/js) | UPDATE | Redirect entry stays in the stub; headers for `/models/*` must stay (plumes and verify live there). |
| `build/models/` folder | **KEEP** ⚠ | Also holds `ecmwf/`, `gefs/`, `aifs` data, `verify/` (`verification-ui.js:10`). Rename later (e.g. `products/`). |
| Tests/tools: `tests/test_models.py` (render parts), `test_models_fixture.py`, `test_models_catalog.py`, `tools/model_fixture.py`, `tools/mapbench.py`, browser checks `models` (`browser_check.py:1486-1560`) and the models page in `failure*` and `privacy` page lists | REMOVE | Keep `test_models.py` parts that cover `derive_frame` totals and the samplers. |
| Docs: `docs/specs/model-maps.md`, CLAUDE.md "Model maps" section, README §Phase 2 | RETIRE | Already marked retired in the plan. |

### 5.2 Sno-Parks

| Item | Mark | Why |
|---|---|---|
| `pipeline/rec.py`, `data/rec_points.json`, `data/rec_points_review.csv`, `tests/test_rec.py`, `docs/sources_recreation.md`, `config/sources.yml` Sno-Park entries | REMOVE | Builder, data and research for Sno-Parks only. |
| `pipeline/nbm/run.py:769-771` (merge), `:639-641` (`kind`, `type_label`, base lat/lon) | REMOVE | Points run works without the file. |
| `pipeline/common.py:91-100` `forecast_areas()` | UPDATE ⚠ | Also used by `afd.py:32` and `alerts.py:178` for ski areas: drop only the rec branch. |
| `pipeline/search.py:24-28, 59-62`; `pages.py:9,44-47`; `og.py:290,313`; `stub.py:50`; `version.py:18-23`; `webcams.py:101`; `linkcheck.py:206,211`; `nohrsc.py:230`; `__main__.py:163-165, 261, 324, 491, 571-574` | REMOVE branches | Sno-Park branches in shared modules. |
| `web/js/app.js:62,79,94,115,248-268,500-516,571-572,596-599,751-753,760`; `area.js:816-820,1042-1045,1147-1177 (recFacts),1211,1214,1231-1232,1252,1266-1279`; `finder.js:38-41,80,152-153,214-215,262-277,289-296`; `finder.html:42,75`; `mine.js:2,34,55-59,90`; `mine.html:7`; `analytics.js:17`; `style.css:384-397`; `pwa_sw.js:19` | REMOVE | Page, filter, layer and card code. Add a redirect for old `#sp-*` links to the Finder. |
| Page text: `area.html:41`, `about.html:45,254,300-307,413-415`, `sources.html:68,79-82,129`, `disclaimer.html:55`, `status.js:7` | REMOVE | |
| Browser checks `snoparks`, `spmobile`, and `sp-wing-mountain` in the `privacy`/`csp` page lists; `tests/fixtures/browser/alerts/index.json` Sno-Park refs | REMOVE / UPDATE | |
| Archive rows already written for Sno-Parks | KEEP | Additive rule. |
| Plumes | n/a | `multimodel.load_points` and `ridge.load_summits` read `ski_areas.json` only: Sno-Park removal does not touch the plumes. |

### 5.3 SNOTEL-site forecast pages

| Item | Mark | Why |
|---|---|---|
| `pipeline/nbm/run.py:744-758` `station_outputs`, `:772-773` load of `data/snotel_points.json`, cell set `:796`; `pipeline/archive.py:110-120` station rows | **KEEP** ⚠ | H6: verification (`verify.py:50`) and the M11 baseline (`slr_baseline.py:66`) score only these points. |
| `pipeline/common.py:116,126` (`stale_point_files` handles `snotel-*`) | KEEP | Cleanup of the kept station files. |
| `web/js/area.js:694,1113-1137,1157-1158,1189-1190 (alerts.points),1211,1214,1232,1234-1237,1356`; `app.js:397` ("Forecast for this site (NBM / NWS)" link); `mine.js:54-56,66-70,84,90`; `search.py:29-34` (`k=snotel` entries); header label "Search ski areas and SNOTEL sites" | REMOVE (pages and entry points only) | Users can't reach station forecast pages any more. |
| `pipeline/pwa_sw.js:19` (`snotel_points.json`), `pipeline/alerts.py:186` (alerts per SNOTEL point), `web/privacy.html:54` | UPDATE | Keep what verification needs. |
| SNOTEL observations: `web/js/area.js:992-1034` (nearest station), `app.js:338-445` (obs map), `pipeline/snotel.py`, `restore.py`, archive `snotel-*.csv.gz` | **KEEP** | Obs, storm totals, M9 ground truth. |
| `web/js/area.js:694` (`proxy` test in the verification panel) | UPDATE | It distinguishes station pages; it changes when they go. |

---

## 6. GitHub-coupling inventory

Phases refer to `platform-transition.md` §10.

| Coupling | Where | Replace with | Phase |
|---|---|---|---|
| Release-asset publishing of products (`<product>-<cycle>.tar` on `model-maps`) | `models.yml`, `ecmwf.yml:89-114`, `gefs.yml`, `verify.yml` upload steps; `docs/workflow_snippets/ecmwf.yml:7-20` | Jobs write straight to R2 (staging then prod). | 1 (dual write) → 2 |
| Unpacking release tars into `build/` | `update-site.yml:52-67` (+ H4) | R2 *is* the latest state; the site reads `data.<domain>`. | 1–2 |
| "Already published" tag from `gh release view` | `ecmwf.yml:58-62`, `models.yml`, `gefs.yml`, `verify.yml` (`--published`) | `runs` table in D1 (last published tag per product). | 2 |
| `GITHUB_OUTPUT` (`new=`, `cycle=`) | `pipeline/__main__.py:301,330,336,345,353`; `models/run.py:181-218,343`; `ecmwf.py:577-581`; `gefs.py:167-171`; `nbm/run.py:776`; `ndfd.py:338`; `nohrsc.py:176-180`; `verify.py:326` | A JSON result on stdout/exit code that the Workflow step reads (keep the `--github-output` flag as an adapter). | 2 |
| Forecast archive on the `verification` release via `gh` | `pipeline/archive.py:266-297` (`ReleaseStore`), `archive_check.py:4,154-159`, `__main__.py:548`, `config/settings.yml:222-223`, `verify.yml:75` | `R2Store` with versioning (fixes C1), later Parquet. | 1 (R2 copy now) → 2 |
| Actions cache for resume caches | `ecmwf.yml:64-87`, `gefs.yml:60-81`; `REPO_ROOT/"data_cache"` in `ecmwf.py:591`, `gefs.py:228`, `__main__.py:479`, `cache.py:74`, `models/run.py:176-178` | R2 prefix `cache/<product>/<cycle>/` (or a container volume); make the cache root configurable. | 2 |
| `gh` issues for data health; `GITHUB_RUN_ID/SERVER_URL/REPOSITORY` | `pipeline/monitor.py:141-145, 155-167, 216-225` | D1 `source_health` + email/push to the on-call developer. | 2 |
| GitHub REST API dispatch | `infra/scheduler/src/tick.js:5,26,38`, `wrangler.toml:15` | Becomes the Cron → Workflows entry point. | 0 (deploy against GitHub) → 2 |
| GitHub Pages origin and base path | `config/settings.yml:61` (`origin` github.io), `:67` (`base_path "/snow-wx"`); `pipeline/restore.py:26-28,45,111`; `monitor.py:216`; `stub.py`; `pwa.py:34`; `pwa_sw.js:13`; `pages.py:29`; `linkcheck.py:114-128`; `__main__.py:246-249,508`; `config/sources.yml:20`; `tools/w1_rehearsal.py:26` | Config values only (no hard-coded `/snow-wx/` in `web/`); flip at W1. `restore` and `monitor` must read the new origin (or R2). | 1 |
| Pages deploy actions | `update-site.yml` `configure-pages`, `upload-pages-artifact`, `deploy-pages` | Workers Builds / Workers Static Assets. | 1 |
| Workflow-YAML tests | `tests/test_dev21_workflows.py:17`, `test_ecmwf_workflow.py:26`, `test_ndfd_not_deployed.py:13,63-71`, `test_scheduler.py:20,38,78` | Re-point to the GitLab CI / Workflows definitions or retire with the workflows. | 2–3 |
| GitHub links / user agent | `config/settings.yml:48` (UA), `config/sources.yml:158,175,192,200`, `web/sources.html:101-125`, `tools/nbm_inventory.py:29`, `tools/browser_fixtures.py:136` | New repo URL / contact URL. | 0–3 |
| Hosting wording | `web/privacy.html:45`, `tools/gen_site_pages.py:199`, `web/js/status.js:41`, `web/status.html:49`, `web/js/freshness.js:8` | Update text at W1. | 1 |

**Blocks for "one Docker container writing to R2":**
- unpinned environment (H7);
- `--out` defaults to `build/…`, and cache paths are fixed under `REPO_ROOT` (`data_cache`);
- the catalogs are read from the repo (`data/ski_areas.json` via `REPO_ROOT` in `multimodel.py:29-33`, `ridge.py:90-93`, `common.py:91-100`, `nohrsc.py:227`), which is fine inside an image but must be the same version as the site;
- non-atomic writes (M15);
- the published-tag lookup (D1);
- plume sampling coupled to map rendering (H5).

**Blocks for D1:**
- there is no schema yet;
- catalog, latest summary and run health exist only as JSON files (`data/ski_areas.json`, `points/summary.json`, `meta.json`);
- `product_status()` is the natural writer for `source_health`.

**Idempotency per job:**

| Job | Retry-safe? | Kill-safe? |
|---|---|---|
| `points`, `ecmwf`, `verify-ci` | Yes, the published tag check makes them retry-safe (ECMWF partial runs: M9). | Only because CI tars a fresh folder (M15). |
| `gefs` | Yes. | No (M8). |
| `models` | Yes. | A partial render with one good image is published as complete (`run.py:324`). |
| `archive` | Yes (idempotent). | No (C1). |
| `build` / obs | Yes. | Yes on a fresh runner, but loses safety data on a fetch failure (H3). |

---

## 7. Test report

- **pytest** (offline, Windows, conda env `snow-wx`): **606 passed, 9 skipped, 1 warning in 157 s**. The 9 skips are `tests/test_browser.py`, gated on `SNOWWX_BROWSER=1`. The warning is the numpy binary-compatibility message (H7).
- **Network:** no test touches the network. `test_fetch_resilient.py` uses 127.0.0.1 servers. `tests/test_fetch_resilient.py:151` has an assertion that always passes (`… or True`).
- **Reads local state:**
  - `tests/test_models_catalog.py:85-95` reads `build/` (skips without a build).
  - `tools/browser_check.py` reads live build data in 13 checks (M19).
- **Browser suite:** not re-run for this review. Last full run Nov 23: 32/38 (`charts`, `ensemble`, `mmodel` fail on a dry forecast; `failure1-3` were the models bug, now fixed).
- **Linters / type checks:** none configured (no ruff, flake8, mypy or eslint config). Not run.
- **Secret scan:**
  - Ran `git log -p --all` (165 commits) for `ghp_`, `github_pat_`, `AKIA`, private keys, Slack, Healthchecks, `sk-` and Google key patterns, plus literal `token/secret/password = "…"`. **Nothing found** except the fake test token `ghp_SECRETSECRETSECRET` in `infra/scheduler/test/due.test.js:134`.
  - No deleted `.env`, key or credential files in history.
  - Secrets (`HEALTHCHECK_URL`, the planned `GH_DISPATCH_TOKEN`) are referenced only as secrets.
- **Covered well:**
  - native windows and composite ranges (`test_points.py`);
  - archive columns and old/new formats (`test_archive*.py`);
  - SNOTEL outage exclusion (`test_verify.py`, `test_snotel_outage.py`);
  - agreement badge (`test_agreement_js.py`);
  - ECMWF freshness (`test_freshness_js.py`);
  - models catalog (`test_models_catalog.py`);
  - daily summaries (`test_summary.py`);
  - scheduler decisions (`node --test`, 19).
- **Gaps** (each maps to a finding):
  - 6-h windows on 01/07/13/19Z cycles past f036 (H1);
  - expiry computed at view time (H2);
  - safety display when alerts/avalanche data fail (H3);
  - the empty release listing (H4);
  - archive upload failure after delete (C1);
  - partial-render publish threshold (`run.py:324`);
  - per-field quality gate (M4);
  - GEFS truncated cache (M8);
  - ECMWF partial republish (M9);
  - plume gaps (M6);
  - danger-chip contrast (C2);
  - verification lead buckets (M2).
- **Flakiness:** `charts` and `storm` have fixed in-page waits (`browser_check.py:531,537,566,569,1038,1040`). `charts` also contains dead NWS-toggle code (565-572).

---

## 8. Recommended order of work: the first 10 fixes as reviewable merge requests

Each MR is sized so a reviewer can check it in under 30 minutes. Do MR 1–4 before the Thanksgiving traffic; do MR 6 before starting the scope trim.

1. **MR "safety display"** (web, S): C2 chip text colour on the area page, H2 browser-side expiry from `end_date`, M12 alert `ends` filter + "alerts checked" time. Browser assertions for all three.
2. **MR "safety data on fetch failure"** (pipeline + web, M): H3: restore last-good alerts, avalanche and AFD from the live origin (stale-flagged); "not available" message + always-on center link.
3. **MR "archive cannot lose a month"** (pipeline, M): C1: upload-temp → delete → rename in `ReleaseStore`, and a dated backup copy. Test with a store that fails after the delete. Add an `archive` monitor source (M13).
4. **MR "no silent empty deploy"** (workflow + pipeline, S): H4: retry the release listing, fail if empty; `last_success_at` for products so "waiting" can't come back.
5. **MR "6-h window fix"** (pipeline, S): H1 plus M3 (P(snow) gap) and M4 (per-field gate), with an 01Z/13Z fixture test.
6. **MR "plume sampling without maps"** (pipeline, M–L): H5: sample-only job, `precip.json`/`ridge.json` independent of PNGs, move `load_points`; record H6 (keep SNOTEL-site forecasts) as the decision for the trim.
7. **MR "pin the environment"** (infra, S): H7: lock file per platform, split dev tools, CI uses the lock.
8. **MR "workflow hardening"** (workflow, S): M10 input via `env` + validation, M11 per-job permissions, `GH_TOKEN` per step, SHA pins.
9. **MR "ensemble gaps and GEFS"** (pipeline + web, S): M6 keep gaps in plume lines/badge, M7 CSNOW missing ≠ 0, M8 atomic GEFS cache, M9 ECMWF partial tag.
10. **MR "summary and verification wording"** (pipeline, S): M1 window wording, M2 lead buckets, M5 SLR envelope wording.

Then: PR B (M19, frozen fixtures), M15 (atomic outputs) before any R2 sync, H8 before enabling W2, M16/M17 before enabling PWA/CSP at W1.

**Suggested code ownership** (matches `platform-transition.md` §4.4):
- **Pipeline** (Dev A): `pipeline/` except `pages.py`/`pwa*`/`og.py`, plus `config/models.yml` and `data/`.
- **API + infra** (Dev B): `infra/`, `.github/` → `.gitlab-ci.yml`, `pipeline/monitor.py`, `archive*.py`, `r2_plan.py`, D1/R2.
- **Web + mobile** (Dev C): `web/`, `pipeline/pages.py`, `pwa.py`, `pwa_sw.js`, `og.py`, `tools/browser_*.py`.

`web/js/area.js` (1,363 lines, 51 commits) and `pipeline/nbm/run.py` (863 lines) are the hotspots. Split `area.js` by module (safety header, snow charts, plumes, observations) before adding the NBM and plume UI work.

---

## 9. Open questions for the team

1. **SNOTEL scope (§11 item 13):** confirm "observations only" means *no pages*, but NBM forecasts at SNOTEL sites are still computed and archived (H6). Otherwise M9/M11 stop.
2. **Plume sources after the trim:** keep HRRR/RRFS/GFS lines (needs the sample-only job, H5) or drop them? The agreement badge needs ≥ 3 models.
3. **Archive durability now:** is a dated backup asset on GitHub acceptable until R2, or should the archive move to R2 in Phase 0?
4. **Safety fallbacks:** on a failed alerts/avalanche fetch, show last-good data (stale-flagged) or show "not available" only? (Recommended: both.)
5. **`build/models/` naming:** it will hold only ECMWF, GEFS and verification. Rename to `products/` during the R2 move?
6. **Feedback address:** personal Gmail until W1, or a role address now?
7. **Commit PLAN v1.4 and `platform-transition.md`** to the repo so future sessions read the same plan?
8. **`models` status row:** replace it with per-model plume-sampling health (newest `precip.json` per model)?
