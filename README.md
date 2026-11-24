# Snow-Wx

Open snow forecasts and observations for western US ski areas, built for skiers, riders and snow-science folks.

- **Ski-area forecasts** for about 160 areas: NOAA's National Blend of Models (NBM) to day 10–11 with "likely" ranges,
  chances of at least X inches, snow level against base and summit, snow ratio / powder quality (a labelled heuristic),
  hour-by-hour charts and a plain-language daily summary.
- **Model plumes:** precipitation by model (NBM, HRRR, RRFS, GFS, ECMWF HRES, the experimental ECMWF AIFS line) with a
  model-agreement badge (a labelled heuristic), plus ECMWF ENS and NOAA GEFS ensemble plumes.
- **Observations map:** SNOTEL snow depth, SWE and changes; ASOS/AWOS airports; avalanche danger by zone (avalanche.org,
  expired ratings greyed out); NWS winter hazards; NOHRSC snowfall and NBM forecast overlays.
- **Safety first:** avalanche danger, NWS alerts, snow level and data freshness are always shown and never gated.
  This site is not a substitute for your local avalanche forecast.

> **Nov 2026:** the model-map viewer and the Sno-Park pages are being removed (decision of Nov 23), and the project is
> moving from GitHub Actions + GitHub Pages to GitLab + Cloudflare (`docs/specs/platform-transition.md`).
> New here? [`docs/ONBOARDING.md`](docs/ONBOARDING.md). Doc map: [`docs/INDEX.md`](docs/INDEX.md). Plan: [`docs/PLAN.md`](docs/PLAN.md);
> timeline and action items: [`docs/ROADMAP.md`](docs/ROADMAP.md). AI agents: [`AGENTS.md`](AGENTS.md).

---

## 1. Set up (Windows, one time)

In VS Code open a terminal (**Terminal → New Terminal**) in this folder:

```powershell
conda env create -f environment.yml     # takes several minutes the first time
conda activate snow-wx
pytest -q                               # about 606 passed, 9 skipped (browser tests)
```

Then `Ctrl+Shift+P` → **Python: Select Interpreter** → **snow-wx**.
Without `conda activate`, call the env's Python directly, e.g. `C:/miniforge3/envs/snow-wx/python.exe -m pytest -q`
(see `CLAUDE.md` for the Windows ecCodes PATH note).

## 2. Run it locally

```powershell
python -m pipeline build                # copies web/ to build/ and fetches live observations
python -m pipeline points               # NBM forecasts for every ski area -> build/data/points/
python -m http.server 8000 -d build     # then open http://localhost:8000
```

`Ctrl+C` stops the preview. Fetch one source with logs: `python -m pipeline obs --only snotel -v` (SNOTEL takes 3–8 minutes).

Other commands:

```powershell
python -m pipeline catalog              # rebuild data/ski_areas.json (on demand; run `build` first)
python -m pipeline nohrsc               # NOHRSC snowfall + SNODAS overlay layers -> build/data/nohrsc/
python -m pipeline.nbm.sanity           # NBM 24-h snow vs the NWS forecast for 10 areas
python -m pipeline archive-check        # integrity of the forecast archive
```

## 3. Tests

```powershell
pytest -q                                                   # offline unit tests (fake HTTP sessions)
$env:PYTHONIOENCODING="utf-8"; python tools/browser_check.py --quick   # headless-Chrome checks (copy web/* to build/ first)
cd infra/scheduler; node --test                             # external scheduler
```

## 4. How it runs today

GitHub Actions workflows (`.github/workflows/`) fetch the data and publish the site to GitHub Pages:
`update-site.yml` (hourly build + deploy + forecast archive + monitor), `models.yml` (NBM points, model sampling, NOHRSC, NDFD),
`ecmwf.yml`, `gefs.yml`, `verify.yml` and `tests.yml`. GitHub delivers few scheduled runs on this repository; a manual
**Run workflow** always works. Current state, flags and known issues: [`docs/STATUS.md`](docs/STATUS.md).

## Project layout

```
config/          settings.yml (region, windows, feature flags), models.yml, sources.yml, summary_rules.yml, ski_areas.yml
data/            committed catalogs: ski_areas.json (ODbL), snotel_points.json
docs/            INDEX.md (start here), PLAN.md, STATUS.md, DECISIONS.md, BACKLOG.md, DESIGN.md, specs/, ops/, reference/, reviews/, archive/
infra/scheduler/ Cloudflare Worker that dispatches the workflows on time (built, not deployed)
pipeline/        Python: one module per data source; NBM (nbm/), plumes (ecmwf.py, gefs.py, models/multimodel.py), archive, verify
web/             the website (HTML/CSS/JS, no build step; Plotly, Leaflet, MapLibre self-hosted in web/vendor/)
tests/           offline unit tests
tools/           browser checks, fixtures, NBM inventories, rehearsals
AGENTS.md        protocol for AI agents (imported by CLAUDE.md); .claude/ holds project skills and review subagents
CLAUDE.md        context for Claude Code; CONTRIBUTING.md for the team workflow
```

## Data sources and terms

| Source | Use | Terms |
|---|---|---|
| NOAA/NWS National Blend of Models (NBM) via NODD (AWS) | ski-area point forecasts | Public domain (US Government) |
| NOAA/NCEP HRRR, RRFS, GFS, GEFS via NODD (AWS) | model plumes | Public domain (US Government) |
| ECMWF open data (IFS HRES, ENS, AIFS) | model plumes | CC BY 4.0; credit ECMWF |
| NOAA/NWS NDFD via NODD (AWS) | archived for verification only (not shown) | Public domain (US Government) |
| api.weather.gov | alerts, forecast discussions, grid lookup | Public domain; descriptive User-Agent |
| USDA NRCS AWDB (SNOTEL) | snow, SWE, temperature | Public domain |
| Iowa Environmental Mesonet | ASOS/AWOS currents | Free for any lawful use, incl. commercial |
| avalanche.org public API | danger by zone | Show unaltered, expire correctly, link to the full forecast |
| NOAA/NWS NOHRSC National Snowfall Analysis v2.1 | observed snowfall overlay | Public domain; credit NOAA/NWS NOHRSC |
| NOHRSC SNODAS via NSIDC (G02158) | SWE, depth, 24-h SWE change overlay | NOAA data, free; cite NSIDC G02158 |
| OpenSkiMap / OpenStreetMap | ski areas and lifts | ODbL: attribution; derived catalog shared under ODbL |
| USGS 3DEP, USGS National Map | elevations, basemaps | Public domain |
| OpenFreeMap | roads/towns reference layer | Free; credit OpenFreeMap / OpenMapTiles / OSM |

Full licensing table: `docs/PLAN.md` §10. Sensor data are provisional and quality-controlled only by simple checks.

## Troubleshooting

- **`conda` not recognized** in VS Code → close and reopen VS Code; make sure the terminal is PowerShell.
- **A layer is missing on the map** → the *Data status* panel (and `status.html`) shows which source failed and why. Sources fail independently.
- **A workflow run failed** → open it in the Actions tab and read the red step's log.
