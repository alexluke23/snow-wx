# Snow-Wx

Open weather, snowpack and avalanche information for the western US mountains,
built for skiers and snow-science folks.

**Phase 1:** one map showing
- **SNOTEL** (USDA NRCS): snow depth, SWE, 24/72-hr changes, % of median, temperature, with a 7-day chart per station
- **ASOS/AWOS** airports (via Iowa Environmental Mesonet): wind barbs, temperature, METAR
- **Avalanche danger** by forecast zone (avalanche.org), with expired ratings greyed out

Search any station by name or ID; the map view, variable and selected station
are kept in the page URL, so links can be shared.

**Phase 2: model maps** (`models.html`): HRRR forecast maps for the West and five
mountain regions (PNW/Cascades, Sierra, Northern Rockies, Wasatch/Uintas,
Colorado), looped by forecast hour: 500 mb heights & vorticity, 700 mb
temperature/wind, 1/6/24-hr and total precipitation, 10:1 vs Kuchera snowfall,
snow level vs terrain, 2-m temperature and wind gusts. RRFS and GFS are
configured and switch on in `config/models.yml`.

Everything runs free: GitHub Actions fetches the data every hour and publishes
the site to GitHub Pages. No API keys are needed.

---

## 1. Set up on your computer (Windows, one time)

Open a terminal in VS Code (**Terminal → New Terminal**) in this folder:

```powershell
conda env create -f environment.yml     # takes several minutes the first time
conda activate snow-wx
pytest -q                               # should say "passed"
```

In VS Code, press `Ctrl+Shift+P` → **Python: Select Interpreter** → choose **snow-wx**.

## 2. Run it locally

```powershell
conda activate snow-wx
python -m pipeline build                # copies the website to build/ and fetches live data
python -m http.server 8000 -d build     # then open http://localhost:8000
```

Press `Ctrl+C` in the terminal to stop the preview server. Fetch a single
source with logs: `python -m pipeline obs --only snotel -v`.

Ski areas and point forecasts:

```powershell
python -m pipeline catalog              # rebuild data/ski_areas.json (on demand; run `build` first)
python -m pipeline points               # NBM forecasts for every ski area -> build/data/points/
python -m pipeline.nbm.sanity           # NBM 24-h snow vs the NWS forecast for 10 areas
```

## 3. Put it on GitHub and publish

1. On github.com, click **+ → New repository**. Name it `snow-wx`, choose
   **Public**, and do **not** add a README (this folder already has one).
2. In the VS Code terminal, in this folder:
   ```powershell
   git init
   git add .
   git commit -m "Phase 1: observations map"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/snow-wx.git
   git push -u origin main
   ```
   A browser window will ask you to sign in to GitHub the first time.
3. On GitHub: repo **Settings → Pages → Build and deployment → Source: GitHub Actions**.
4. **Actions** tab → **Update site** → **Run workflow**. The first run takes
   a few minutes (it installs the environment, then caches it).
5. Your site: `https://YOUR_USERNAME.github.io/snow-wx/`
6. Edit `config/settings.yml` → `http.user_agent` to include your repo URL,
   then commit and push.

After that the site refreshes every hour on its own.

**Model maps** have their own workflow (**Model maps**, every 3 hours). The first
time, open **Actions → Model maps → Run workflow**. It creates a pre-release
called `model-maps` that holds the newest images for each model (one `.tar` per
model, replaced automatically; it is storage, not a software release), then
triggers **Update site**, which pulls those images into every deploy. If your
repository's *Settings → Actions → General → Workflow permissions* are
read-only, the workflow's own `permissions:` block still grants what it needs
unless an organization policy blocks it.

Run model maps locally (about a minute for this small example):

```powershell
C:/miniforge3/envs/snow-wx/python.exe -m pipeline models --model hrrr --fhours 0 6 12 --domains west wasatch
C:/miniforge3/envs/snow-wx/python.exe -m pipeline build
C:/miniforge3/envs/snow-wx/python.exe -m http.server 8000 -d build   # then open /models.html
``` **Note:** GitHub pauses
scheduled workflows in public repos after 60 days with no commits. If that
happens, push any change or re-enable it in the Actions tab.

## Project layout

```
config/settings.yml        region, states, time windows, on/off switches
config/models.yml          model maps: domains, models, forecast hours, fields
config/ski_areas.yml       ski-area catalog: filters, exclusions, name fixes, regions
data/ski_areas.json        the catalog (ODbL, derived from OpenStreetMap/OpenSkiMap)
docs/PLAN.md               product plan and milestones
pipeline/                  Python: one module per data source
  snotel.py  asos.py  avalanche.py  common.py  __main__.py
  models/                  model maps: fetch, derive, plot, run, catalog
  catalog.py               ski-area catalog (OpenSkiMap + USGS 3DEP + NWS + NBM grid)
  nbm/  points.py          NBM point forecasts (inventory, fetch, period math)
web/                       the website (HTML/CSS/JS, no build step)
  js/colors.js             color scales and legends — tweak freely
  models.html, js/models.js  model map loop viewer
tests/                     offline unit tests (fake API responses)
.github/workflows/         hourly build + deploy; 3-hourly model maps
CLAUDE.md                  context for Claude Code
```

## Data sources and terms

| Source | Use | Terms |
|---|---|---|
| USDA NRCS AWDB (SNOTEL) | snow, SWE, temp | Public domain |
| NOAA/NCEP HRRR, RRFS, GFS via NOAA Open Data Dissemination (AWS) | model maps | Public domain (US Government) |
| NOAA/NWS National Blend of Models (NBM) via NODD (AWS) | ski-area point forecasts | Public domain (US Government) |
| api.weather.gov | NWS grid lookup, forecast cross-check | Public domain; descriptive User-Agent |
| OpenSkiMap / OpenStreetMap | ski areas and lifts | ODbL: attribution; derived catalog shared under ODbL |
| USGS 3DEP (elevation.nationalmap.gov) | base/summit and grid-cell elevations | Public domain |
| Natural Earth | map outlines on model maps | Public domain |
| Iowa Environmental Mesonet | ASOS/AWOS currents | Free for any lawful use, incl. commercial |
| avalanche.org public API | danger by zone | Show unaltered, expire correctly, link to full forecast |
| USGS National Map | basemaps | Public domain |
| OpenTopoMap | basemap option | CC-BY-SA, attribution |

Sensor data are provisional and unquality-controlled beyond simple range
checks. This site is not a substitute for your local avalanche forecast.

## Troubleshooting

- **`conda` not recognized** in VS Code → close and reopen VS Code; make sure
  the terminal is PowerShell.
- **A layer is missing on the map** → the right panel's *Data status* shows
  which source failed and why. Sources fail independently.
- **Actions run failed** → open the run in the Actions tab and read the red step's log.
