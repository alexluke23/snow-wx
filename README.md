# Snow-Wx

Open weather, snowpack and avalanche information for the western US mountains,
built for skiers and snow-science folks.

**Phase 1 (this version):** one map showing
- **SNOTEL** (USDA NRCS): snow depth, SWE, 24/72-hr changes, % of median, temperature, with a 7-day chart per station
- **ASOS/AWOS** airports (via Iowa Environmental Mesonet): wind barbs, temperature, METAR
- **Avalanche danger** by forecast zone (avalanche.org), with expired ratings greyed out

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

After that the site refreshes every hour on its own. **Note:** GitHub pauses
scheduled workflows in public repos after 60 days with no commits. If that
happens, push any change or re-enable it in the Actions tab.

## Project layout

```
config/settings.yml        region, states, time windows, on/off switches
pipeline/                  Python: one module per data source
  snotel.py  asos.py  avalanche.py  common.py  __main__.py
web/                       the website (HTML/CSS/JS, no build step)
  js/colors.js             color scales and legends — tweak freely
tests/                     offline unit tests (fake API responses)
.github/workflows/         hourly build + deploy
CLAUDE.md                  context for Claude Code
```

## Data sources and terms

| Source | Use | Terms |
|---|---|---|
| USDA NRCS AWDB (SNOTEL) | snow, SWE, temp | Public domain |
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
