<!-- First look, Nov 17 2026, produced by: python -m pipeline verify --dir <archive> --out <dir>. Preliminary: 4 observation days. -->
# Forecast verification (M9-prep)

Generated 2026-11-18T03:51Z. Pairs scored: **54692** (24-h windows ending 12Z, SNOTEL-site forecasts vs the observed depth change), over **4 days** (2026-11-12 to 2026-11-15).

Excluded: observations inside the SNOTEL outage window (2026-11-16T12:00Z to 2026-11-18T00:45Z); observations with fewer than 20 hourly reports in the 24 h (stale / carried / patchy); pairs missing either side. Counts: nbm: forecast_rows=259470, no_observation=183858, outage_window=41013, low_coverage=2237, missing_value=1347; ndfd: forecast_rows=56079, no_observation=28950, outage_window=11718, low_coverage=953, missing_value=571.

## By lead time

| source | lead_bucket | n | bias_in | mae_in | pod_1 | far_1 | pod_4 | far_4 |
|---|---|---|---|---|---|---|---|---|
| NBM expected | day 2 (24-48 h) | 9078 | 0.07 | 0.37 | 0.484 | 0.3 | 0.644 | 0.43 |
| NBM expected | day 3 (48-72 h) | 7752 | 0.04 | 0.41 | 0.412 | 0.32 | 0.55 | 0.472 |
| NBM expected | days 4-5 | 14324 | 0.07 | 0.51 | 0.399 | 0.405 | 0.517 | 0.514 |
| NBM expected | days 6+ | 7330 | -0.4 | 0.71 | 0.151 | 0.525 | 0.04 | 0.754 |
| NBM median | day 2 (24-48 h) | 9078 | 0.06 | 0.38 | 0.462 | 0.312 | 0.602 | 0.428 |
| NBM median | day 3 (48-72 h) | 7752 | 0.04 | 0.41 | 0.42 | 0.332 | 0.539 | 0.442 |
| NBM median | days 4-5 | 13693 | 0.03 | 0.52 | 0.365 | 0.352 | 0.487 | 0.523 |
| NBM median | days 6+ | 5374 | -0.53 | 0.75 | 0.084 | 0.509 | 0.029 | 0.812 |
| NWS (NDFD) | day 2 (24-48 h) | 8447 | -0.09 | 0.33 | 0.414 | 0.235 | 0.415 | 0.314 |
| NWS (NDFD) | day 3 (48-72 h) | 7130 | -0.15 | 0.35 | 0.323 | 0.248 | 0.36 | 0.279 |
| NWS (NDFD) | days 4-5 | 631 | -0.04 | 0.04 | 0.0 | – | – | – |

## What about 10 days of archive can and cannot support

- **Can:** a first look at bias and MAE for days 1-3, whether NBM's expected amount runs high against the observed depth change, and whether NBM beats NDFD on days 1-2.
- **Cannot:** seasonal skill or regional rankings (a handful of storms, many dry days: scores are dominated by zeros), rare-event skill (>= 4 in events are few: PODs are noisy), calibration of probabilities (Brier needs hundreds of events), or elevation effects within a state.
- **Observation limits:** depth change is a lower bound of snowfall (compaction), so positive forecast bias is expected; the SWE change is the better liquid check but the archive has no forecast liquid column.
- **Temperature is not scored:** the archive holds snow forecasts only and no SNOTEL temperatures. To score temperature, add forecast tmax/tmin (24 h, 12Z-12Z) and the observed tmax/tmin from SNOTEL TOBS to the archive columns first.
- **Ski-area points** are not scored here (no co-located observation); they would need the nearest-station proxy with its elevation difference.
