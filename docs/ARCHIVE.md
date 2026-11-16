# Snow-Wx — Archive (history; not read by default)

> Completed work and older decisions moved out of `PLAN.md` to keep it lean. Read only when you need history.

---

## A. Decisions log, Nov 6–8 2026

| Date | Decision |
|---|---|
| Nov 6 | Public site for owner + friends; may monetize later → only sources whose terms allow public display & commercial use. |
| Nov 6 | No Synoptic. Obs from NRCS AWDB, IEM, avalanche.org. |
| Nov 6 | Stack: Python pipeline on GitHub Actions → static site. Dev in VS Code + Claude Code; env `C:/miniforge3/envs/snow-wx`. |
| Nov 7 | Model images stored as GitHub Release assets; site pulls newest per model; 900 MB guard. |
| Nov 7 | Snow level (model maps) = wet-bulb 0 °C height, capped at lowest 0 °C height; free-atmosphere freezing level dashed. |
| Nov 7 | 700 mb temperature in °C; surface °F / in / mph or kt (see §6). |
| Nov 7 | **Product focus: OpenSnow competitor centered on ski-area point forecasts (western US first).** |
| Nov 7 | **Remove upper-air fields (500 mb, 700 mb) from HRRR and RRFS. Keep them for GFS (and ECMWF later).** |
| Nov 7 | **Model maps must be zoomable** → interactive data layers for surface fields (§5.4). |
| Nov 7 | **NBM is the primary point-forecast engine; NDFD shown as the NWS official forecast alongside it.** |
| Nov 7 (S2) | Day/night = 12Z–00Z periods, labeled in local time. |
| Nov 7 (S2) | Snowfall: NBM snowfall percentiles 0–48 h; beyond 48 h QPF pct × SLR × P(snow), styled "extended outlook". |
| Nov 7 (S2) | Bars/headline/totals use NBM deterministic (mean) so bars sum to totals; percentiles only as 10–90% ranges; zero snow when QPF < 0.01". |
| Nov 7 (S2) | Point snow scaled by P(snow level below point elevation); "mostly rain"/"mixed" labels. |
| Nov 7 (S2) | NBM points 4×/day; Plotly kept but loaded after HTML headline; merge Snoqualmie summits, Alpental separate. |
| Nov 7 (S2) | NBM + NDFD forecasts for all SNOTEL sites; NDFD sampled from GRIB2 on AWS (api.weather.gov only for alerts/AFD/missing elements). |
| Nov 7 (S2) | NOHRSC overlays on obs map (SNODAS SWE, depth, 24 h SWE change; gridded snowfall 24/48/72 h); builds the interactive-layer system (§5.4). |
| Nov 7 (S2) | Obs map performance work (canvas rendering, lazy charts). |
| Nov 8 | dev4 verified on GitHub: Model maps #8 all green; RRFS job 3 m 50 s with ridge wind — no runtime concern. |
| Nov 8 | Forecast archive stores **all daily leads** (every 24 h window ending 12Z days 1–10 + every 72 h window; det/p10/p50/p90/P(≥4/8/12"); plus NDFD). Release assets only — never on the owner's PC or in git history. |
| Nov 8 | **Chart readability is a priority;** §6-B standards apply site-wide. |
| Nov 8 | **Basemaps must never go blank** — overzoom + fallback provider (§6-C). |
| Nov 8 | **Add Sno-Parks / winter recreation points** as a point type (§5.6, M4.5). |
| Nov 8 | Keep local disk small: auto-prune `data_cache` (> 2 days); report disk use in summaries. |
| Nov 8 | Priority: Obs map + per-site Forecast pages first; model maps last (models.html on low maintenance). Model pipeline keeps running — it feeds point products. |
| Nov 8 | Consumer snow-forecast map (NBM expected snowfall + chance-of) lives on the Obs map as overlays, not on models.html. |
| ~~Nov 8~~ | ~~Monetization on the back burner; decision point fall 2027.~~ **Superseded Nov 15 (below).** The fall-2027 *full launch* target survives; preparation starts now. |

---

## B. Completed milestones (as of Nov 8 2026)

M0 Housekeeping · M1 Ski-area catalog · M2 NBM point pipeline · M3 Ski-area page v1 · M3.5 Snowpack overlays/SNOTEL forecasts/speed · M3.6 Chart readability, accessibility & basemap reliability (bugs B1–B7 resolved) · M4 Powder Finder · M5 NWS official · M9-prep Forecast archive · dev6 fixes · dev7 (Expected rename, day-10 temp/wind panels, Sno-Park research).

Acceptance criteria for these live in git history and the original v0.6 plan (superseded).

---

## C. Original M-numbered roadmap notes

Track 1/2/3 ordering from Nov 8(b) was merged into PLAN.md §8 (sprint table + backlog).
