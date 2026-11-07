# snow-wx — notes for Claude Code

Public website of open weather, snowpack and avalanche data for western US
mountains, built for skiers and snow-science users. Owner is a meteorologist
comfortable with Python. Free hosting: GitHub Actions (hourly) builds static
JSON/PNG + HTML and deploys to GitHub Pages. No servers, no API keys.

## Commands
Use the project's conda env Python for every Python command (no `conda activate`
needed), e.g.
- `C:/miniforge3/envs/snow-wx/python.exe -m pytest -q` — unit tests (offline; uses tests/fakes.py FakeSession)
- `C:/miniforge3/envs/snow-wx/python.exe -m pipeline build` — copy web/ to build/ and fetch fresh data into build/data
- `C:/miniforge3/envs/snow-wx/python.exe -m pipeline obs --only snotel -v` — fetch one source, verbose
- `C:/miniforge3/envs/snow-wx/python.exe -m pipeline models --model hrrr --fhours 0 6 12 --domains west wasatch --keep-grib`
  — quick model-map run into build/models (drop the limits for a full run; `build` then merges the catalog)
- `C:/miniforge3/envs/snow-wx/python.exe -m http.server 8000 -d build` — preview at http://localhost:8000
  (models viewer: http://localhost:8000/models.html)
- SNOTEL fetch takes 3–8 min (AWDB is slow). For front-end-only changes copy `web/*` over `build/`
  instead of re-running `build`. Headless Chrome screenshots work for checking pages
  (`chrome --headless=new --screenshot=out.png --window-size=1400,900 --virtual-time-budget=15000 URL`);
  the obs map accepts `#v=<var>&map=<z>/<lat>/<lon>&s=<station>`, the viewer `#m=&f=&d=&h=`.

Windows note: calling the env's python.exe directly (without `conda activate`) leaves
`envs/snow-wx/Library/bin` off PATH, so ecCodes can't find `eccodes.dll` and
cfgrib/Herbie fail to import. `pipeline/__init__.py` prepends that folder to PATH
on Windows, and `pipeline/__main__.py` makes stdout tolerate emoji (Herbie prints them).
Ad-hoc scripts that import eccodes/herbie should `import pipeline` first.

## Layout
- `config/settings.yml` — region, states, windows, toggles. Prefer config over code.
- `pipeline/` — one module per source, each with `run(cfg, session, outdir) -> dict`
  registered in `pipeline/__main__.py:SOURCES`. Sources fail independently.
- `web/` — static site (Leaflet + Plotly from CDN, plain JS, no build step).
  `web/js/colors.js` holds color scales/legends.
- `tests/` — pytest; extend `tests/fakes.py` with canned responses for new sources.
- `config/models.yml` + `pipeline/models/` — model maps (see below); `web/models.html`
  + `web/js/models.js` — loop viewer.
- `.github/workflows/update-site.yml` (hourly obs + deploy) and `models.yml` (model maps).

## Conventions
- Keep fetch code separate from pure processing functions; test the pure parts.
- Write JSON via `common.write_json` (rounds floats, NaN -> null).
- US units on the site (in, °F, kt) for now. Exception (owner decision): 700 mb
  temperature is in °C (upper-air convention).
- Use a polite User-Agent (config `http.user_agent`) and few requests per run.

## Data licensing rules (site may be monetized later)
- OK: NOAA/NWS (NODD on AWS, api.weather.gov), USDA NRCS AWDB, IEM (states
  any lawful use incl. commercial), ECMWF open data (CC-BY-4.0, attribute).
- Synoptic API: NOT available to this project.
- MADIS: only distribution category 3 ("Public – full distribution") may be shown.
- Avalanche.org: show ratings unaltered, grey out expired ratings, always link
  to the center's full forecast.
- Ask before adding any source whose terms are unclear.

## Model maps (Phase 2)
- Flow: `fetch.py` (Herbie, `priority=["aws"]` = NODD only; one byte-range download per
  product and forecast hour; ecCodes decode cropped to the maps' lat/lon bounds) →
  `run.derive_frame` (in fhour order; QPF windows by differencing run-total APCP;
  snowfall accumulated per step) → `.npz` per frame → process pool `plot.render_task`.
- `plot.Canvas` is built once per (grid, domain) per worker: figure, basemap, and a
  precomputed pixel→grid bilinear sampling map. Shading = `map_coordinates` + `imshow`
  in the map projection; per-image artists are removed after each save. Fixed pixel
  size per domain; PNGs quantized to 128 colors.
- Output: `<out>/<model>/<YYYYMMDDHH>/<field>/<domain>/fNNN.png` + `<out>/<model>/index.json`;
  `build` merges all into `build/models/index.json` (catalog the viewer reads).
- CI: `models.yml` (cron 55 1-22/3) renders each model in a matrix job, tars
  `<model>/` to `<model>-<cycle>.tar` on the `model-maps` prerelease (race-safe create,
  deletes only that model's older assets), then dispatches `update-site.yml`, which
  downloads the newest tar per model before every build. `--published` makes runs
  with nothing new exit 0 without output.
- Adding a model: add it to `config/models.yml` (products, moisture `dpt|rh`,
  vorticity `native|compute`, levels, cycles, fhours, domains, fields), run a quick
  local render and look at every PNG, then add it to the matrix in `models.yml`.
- Known limitations / future work:
  - Kuchera Tmax and the wet-bulb-zero height use only 1000/925/850/700/500 mb (+2 m),
    so a shallow warm nose can be missed and WBZ is interpolated across ~5000-ft gaps.
    Future: pull TMP/DPT from the HRRR prs file at 25-mb spacing.
  - WBZ uses Stull (2011) Tw (fit near 1000 hPa; biased slightly warm aloft in dry
    air). WBZ is capped at the model's lowest 0 °C height (physically Tw <= T); the
    cap fixed WBZ > freezing level in NM precip on 2026-11-07.
  - Snow level shading is drawn only where WBZ is above ground; elsewhere one flat
    "at/below ground" color. Freezing-level contours use HGT:highest tropospheric
    freezing level (HRRR's lowest 0C isotherm follows valley cold pools).
  - Snowfall uses CPOFP (frozen %) at the end of each step for the whole step.
  - WBZ cross-check vs RRFS native `HGT:lowest level of the wet bulb zero`
    (gh/lowestLevelWetBulb0), RRFS 12Z 7 Nov 2026, f000–f048, western crop:
    precipitating points: computed − native median about −190 ft (per-hour −155 to −200,
    IQR about −390 to −10 ft); terrain > 5000 ft: median −180 ft but varies by time of
    day (IQR about ±600 ft); all above-ground points: about +300 ft (dry air aloft, Stull
    runs warm). At/below-ground classification agrees on 92–99.7% of points.
    The 0 °C cap barely changes RRFS (it has 925 mb heights).

## Roadmap (see project plan)
1. Observations map (done: SNOTEL, ASOS, avalanche danger)
2. Model map pipeline with Herbie: HRRR, RRFS (operational Nov 2026, replaced
   NAM), GFS, NBM, ECMWF IFS/AIFS — western domain + subregions, loop viewer
   (done on `dev`: HRRR, RRFS, GFS + viewer + CI; ECMWF and NBM maps not yet)
3. Point forecasts: NBM/NDFD meteograms, ensemble plumes, elevation bands
4. Snow-science products: SLR comparisons, snow level vs terrain, wind loading
5. Verification vs SNOTEL/ASOS, alerts, mobile polish

## TODO / session handoff (keep current; newest state wins)
Branch `dev` (not pushed). Plan: A1–A5 polish → HRRR end-to-end (fetch → plots →
viewer → CI) → RRFS → GFS → NBM points → ECMWF.
Git note: the global `user.name` in ~/.gitconfig contains pasted command text, so
commits on `dev` were made with `git -c user.name="Alex Lukinbeal" commit ...`
(the global config was left alone; owner to fix).
- [x] 0. Env bootstrap (DLL path, emoji-safe stdout), this TODO list
- [x] A1 ASOS temp rounding · A2 %-median guard · A3 label declutter · A4 smoothed depth · A5 search + URL hash
- [x] B6+B7 HRRR fetch/derive/plots (`pipeline/models/`, `config/models.yml`, tests/test_models.py)
- [x] B8 full HRRR run: 1361 images, 59 MB, 216 s locally · B9 web/models.html viewer
- [x] B10 CI: `.github/workflows/models.yml` + release-asset hand-off in `update-site.yml`.
      NOT yet exercised on GitHub (schedules only run on the default branch): after
      merging to main, run Actions → Model maps → Run workflow and check the
      `model-maps` release + site.
- [x] RRFS enabled (config + CI matrix); WBZ cross-check done (see Model maps notes)
- [x] GFS enabled (moisture rh, native ABSV, west only) + CI matrix [hrrr, rrfs, gfs].
      Local full runs (home internet; CI on AWS should be faster): HRRR 1361 img/59 MB/216 s,
      RRFS 1349 img/100 MB/240 s, GFS 369 img, ~27 s/frame locally (download-bound:
      0.25° global messages can't be spatially subset by byte range).
- [ ] C11 NBM points (not started). Findings: NBM `core` CONUS 2.5 km files (~200 MB,
      `blend.tHHz.core.fFFF.co.grib2`, Herbie `nbm`, product `co`) already hold ASNOW
      percentiles (`ASNOW:surface:18-24 hour acc@(fcst,dt=6 hour),missing=0:10% level`,
      also 50%/90%, and 1-h windows), 6-h APCP and SNOWLR percentiles — no `qmd` file
      needed. Plan: `config/points.yml` (SNOTEL triplets + ski areas with lat/lon/elev),
      reuse fetch.download_frame/decode with an NBM var catalog, nearest-grid-point
      extraction (precompute indices once), 6-hourly to 168 h, write
      `data/nbm/<id>.json`, meteogram in the station panel (p10/p50/p90 band).
- [ ] C12 ECMWF open data IFS 0p1 / AIFS 0p25 (not started): Herbie `ifs`/`aifs`,
      IDX_STYLE eccodes; attribution "© ECMWF, CC BY 4.0" on images + page.
