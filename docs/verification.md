# Forecast archive (M9 prep)

Snow-Wx keeps every NBM and NWS (NDFD) snowfall forecast it publishes, plus the SNOTEL
observations needed to score them, so verification (PLAN.md M9) can start with a
history instead of from zero.

- **Where:** assets of the GitHub prerelease **`verification`** of `alexluke23/snow-wx`.
  Never in git history and never on a local PC.
- **Written by:** the `Forecast archive` step of `.github/workflows/update-site.yml`
  (`python -m pipeline archive --data build/data`, code in `pipeline/archive.py`).
  It runs after every site build: hourly, and after each new points/NDFD upload.
  It never blocks the deploy (`continue-on-error`).
- **Starts:** with the first site build on `main` that contains this code.

## Files

| Asset | Content | One row per |
|---|---|---|
| `nbm-YYYYMM.csv.gz` | NBM snowfall forecasts; month = NBM cycle | cycle × point × elevation × window |
| `ndfd-YYYYMM.csv.gz` | NWS official (NDFD) snowfall forecasts; month = NDFD issue time | issue × point × elevation × window |
| `snotel-YYYYMM.csv.gz` | SNOTEL observed depth/SWE at 12Z and the 24-h changes; month = date | 12Z time × station |
| `state.json` | NBM cycles and NDFD issue times already archived (the last 400 of each) | — |

All files are gzipped UTF-8 CSV with a header row and `\n` line ends. Empty cells mean
missing. Numbers are inches; probabilities are whole percent. All times are UTC, written
`YYYY-MM-DDTHH:MMZ`.

## Forecast columns (`nbm-*`, `ndfd-*`)

| Column | Meaning |
|---|---|
| `cycle` | NBM cycle, or NDFD issue time, as `YYYYMMDDHH` UTC |
| `point` | Forecast point id: a ski-area id (`alta-ski-area`, as in `data/ski_areas.json`) or `snotel-<triplet with dashes>` (`snotel-1000-OR-SNTL`) |
| `elev` | `summit` or `base` (ski areas); `point` (SNOTEL sites) |
| `elev_ft` | Elevation of the point (ft): the lift terminal or SNOTEL site |
| `cell_elev_ft` | Mean terrain elevation of the 2.5 km NBM/NDFD grid cell (ft; 3DEP) |
| `hours` | Window length: `24` or `72` |
| `end` | Window end; always 12Z (about 4–5 AM local in the West). Window start = `end − hours` |
| `lead_h` | Hours from `cycle` to `end` |
| `det` | **NBM:** deterministic ("most likely") snowfall as shown on the site, i.e. the 12-h period amounts × the chance the snow level is below the point (elevation-adjusted). **NDFD:** NDFD snowfall for the grid cell, raw as issued (no elevation adjustment) |
| `det_cell` | NBM deterministic snowfall for the grid cell, not elevation-adjusted (sum of the 6-h amounts). NBM only |
| `p10`, `p50`, `p90` | NBM's own snowfall percentiles for the window and grid cell. NBM only |
| `p_ge4`, `p_ge8`, `p_ge12` | NBM's own chance (%) of at least 4, 8 and 12 inches in the window, for the grid cell. NBM only |

**Windows.** NBM rows cover every 24-h window and every 72-h window that ends at 12Z and
is covered by the forecast, so days 1–10 of each cycle.

NBM's percentile and probability fields come only with the 01/07/13/19Z cycles. They are
blank for rows from other cycles. If a period is missing, `det` is blank for the windows
that contain it.

NDFD snowfall runs only 72 h, so NDFD rows are mostly the day-1 and day-2 24-h windows. A
72-h row appears only when NDFD covers the whole window. NDFD windows never start before
the issue time.

**Key.** `cycle, point, elev, hours, end` is unique.

**Volume.** One NBM cycle is about 20,800 rows: 160 ski areas × 2 elevations plus 837
SNOTEL sites, × (10 + 8) windows.
- Roughly 4 cycles a day gives about 2.5 M rows a month.
- In dry weather that is about 18 MB gzipped a month (measured: 154 KB per cycle on 8 Nov
  2026). Expect 30–40 MB in a snowy month.
- NDFD is a few MB a month; SNOTEL is under 1 MB.

## SNOTEL columns (`snotel-*`)

| Column | Meaning |
|---|---|
| `end` | The 12Z hour, UTC. Stations report in local standard time, so this is 04:00 PST or 05:00 MST |
| `triplet` | Station triplet, e.g. `1000:OR:SNTL` |
| `depth_in` | Snow depth at `end` (in; whole inches as reported) |
| `depth_med3_in` | Snow depth smoothed with a centred 3-hour median (the site's chart line; tames sensor noise) |
| `swe_in` | Snow water equivalent at `end` (in) |
| `d_depth_24h`, `d_depth_med3_24h`, `d_swe_24h` | Change since the same hour the day before; blank if either value is missing |
| `hours_present` | Hourly depth reports present in the 24 h ending at `end` (0–24) |

**Key.** `end, triplet`. A later run overwrites a row if AWDB revised the data; each run
re-merges the last 7 days.

Depth change is not snowfall: settling, melt and wind affect it. M9 will treat it as a
lower bound and use the SWE change for liquid.

## Rules
- Idempotent: running twice on the same build adds nothing and uploads nothing.
- New rows replace rows with the same key. Monthly files are always downloaded and
  merged before they are replaced. If a download fails, nothing is uploaded.
- Only the current and previous UTC month are written.
- Gzip is written with a fixed timestamp, so identical content gives identical bytes.

## Loading (pandas)

```python
import pandas as pd

# after: gh release download verification -p "nbm-202611.csv.gz"
nbm = pd.read_csv("nbm-202611.csv.gz", parse_dates=["end"], dtype={"cycle": str})
obs = pd.read_csv("snotel-202611.csv.gz", parse_dates=["end"])

# 24-h NBM forecasts at SNOTEL sites vs the observed 24-h depth change
f = nbm[(nbm.hours == 24) & nbm.point.str.startswith("snotel-")].copy()
f["triplet"] = f.point.str.removeprefix("snotel-").str.replace("-", ":", regex=False)
both = f.merge(obs, on=["triplet", "end"])
print(both.groupby(pd.cut(both.lead_h, [0, 24, 48, 96, 168, 264]))[["det", "d_depth_med3_24h"]].mean())
```
