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
- `C:/miniforge3/envs/snow-wx/python.exe -m http.server 8000 -d build` — preview at http://localhost:8000

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

## Conventions
- Keep fetch code separate from pure processing functions; test the pure parts.
- Write JSON via `common.write_json` (rounds floats, NaN -> null).
- US units on the site (in, °F, kt) for now.
- Use a polite User-Agent (config `http.user_agent`) and few requests per run.

## Data licensing rules (site may be monetized later)
- OK: NOAA/NWS (NODD on AWS, api.weather.gov), USDA NRCS AWDB, IEM (states
  any lawful use incl. commercial), ECMWF open data (CC-BY-4.0, attribute).
- Synoptic API: NOT available to this project.
- MADIS: only distribution category 3 ("Public – full distribution") may be shown.
- Avalanche.org: show ratings unaltered, grey out expired ratings, always link
  to the center's full forecast.
- Ask before adding any source whose terms are unclear.

## Roadmap (see project plan)
1. Observations map (done: SNOTEL, ASOS, avalanche danger)
2. Model map pipeline with Herbie: HRRR, RRFS (operational Nov 2026, replaced
   NAM), GFS, NBM, ECMWF IFS/AIFS — western domain + subregions, loop viewer
3. Point forecasts: NBM/NDFD meteograms, ensemble plumes, elevation bands
4. Snow-science products: SLR comparisons, snow level vs terrain, wind loading
5. Verification vs SNOTEL/ASOS, alerts, mobile polish

## TODO / session handoff (keep current; newest state wins)
Branch `dev` (not pushed). Plan: A1–A5 polish → HRRR end-to-end (fetch → plots →
viewer → CI) → RRFS → GFS → NBM points → ECMWF.
- [x] 0. Env bootstrap (DLL path, emoji-safe stdout), this TODO list
- [ ] A1 ASOS temp rounding · A2 %-median guard · A3 label declutter · A4 smoothed depth · A5 search + URL hash
- [ ] B6–B10 HRRR end-to-end, then RRFS, GFS
- [ ] C11 NBM points · C12 ECMWF
