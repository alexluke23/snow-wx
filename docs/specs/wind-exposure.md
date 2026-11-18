# Spec: Wind-exposure flag (W7, stretch)

> Read when working on wind flags. Safety-sensitive: never present as an avalanche rating.
> Part of Snow-Wx docs v1.0 (Nov 15 2026). Index and priorities: `PLAN.md`.
> Section numbers (§) are kept from the original single plan so cross-references still work.

---

### 5.9 Wind-exposure flag (W7 ◇) — *reshaped from Gemini #3*
- **Phase A (informational):** when ridge-top wind ≥ ~25 mph sustained or gusts
  ≥ ~35 mph during/after snowfall **[thresholds to tune]**, show "Wind-affected
  snow likely" + wind direction + plain text such as "Wind-loading possible on
  leeward (E–NE) aspects; scouring on windward ridges". Always labeled **"Wind
  transport potential — not an avalanche rating"** and linked to the local
  avalanche center forecast.
- **Why not more:** model winds don't resolve terrain; an unverified numeric
  redistribution or "slab risk" badge could mislead and erodes trust.
- **Phase B (2027–28, after M9):** verify against observed snow-depth/wind
  changes; consider aspect-aware adjustments with 3DEP slope/aspect (public
  domain). OpenSnow shipped free slope/aspect overlays in 2026–27, so a
  slope-aspect map layer is also a parity item (Backlog).

---

### Build status (dev17) — BUILT BEHIND A FLAG, OFF
`pipeline/wind_exposure.py` (pure, tested in `tests/test_wind_exposure.py`), config `wind_exposure.enabled: false` (**never enable it from a dev session; the owner turns it on
only after the reviewer sign-off below**). While false: no point file carries a `wind_exposure` field, `area.js` `windExposure()` renders nothing, and nothing in the site mentions it.

**What it does (Phase A, informational).** For the *summit* point of an NBM point file, over the first 72 h: find snow episodes (consecutive native precipitation windows with
≥ 0.2 in of expected snow each, ≥ 0.5 in in total); inside the episode and the next 12 h count the hours with sustained wind ≥ 25 mph **or** gust ≥ 35 mph; with ≥ 2 such hours
write the flag for the first qualifying episode: "Wind-affected snow likely", the window, the forecast peak wind/gust, the vector-mean wind direction (16-point compass) and the
leeward side (direction + 180°), plus the fixed disclaimer **"Wind transport potential — not an avalanche rating."**, the caveat that model winds do not resolve terrain, and a link to
the zone's avalanche-center forecast (the zone link from `avalanche_ratings.json`, else avalanche.org). Thresholds are config (`wind_exposure.*`) and marked [to tune after M9].
It uses expected-amount series only; no percentile is read, summed or scaled, and **no number that could be read as slab or avalanche risk is ever produced** (the only numbers are the
forecast wind/gust and the snowfall that triggered the flag; a test asserts the field set and the forbidden vocabulary).

**The five spec cases** (the spec listed none; these are ASSUMED and are what "renders for 5 test cases" means in PLAN §8.3): (1) strong SW wind during a snowfall → flag, leeward NE;
(2) strong wind, no snow (or a trace) → no flag; (3) gusts ≥ 35 with sustained 18 → flag; (4) snowfall in light wind → no flag; (5) wind arriving ≤ 12 h after the snow stops → flag,
18 h after → no flag. Extra edge tests: missing wind data, missing direction, opposing directions (no dominant direction), one windy hour, the 72-h horizon, config thresholds,
disabled-by-default output, forbidden wording.

**Not in this build:** snow-redistribution numbers, aspect/slope (3DEP) adjustments, ridge-level (free-air) winds from `ridge.json`, Sno-Parks/SNOTEL points, an about.html section
(add `about.html#wind-exposure`, which the flag's "How this flag works" link targets, before enabling).

### Reviewer checklist (for an avalanche-literate person; sign off BEFORE the flag is enabled)
Reviewer: ____________  Date: ________  Affiliation / qualification: ____________________

1. **Wording.** Read every string in `pipeline/wind_exposure.py` (`TITLE`, `DISCLAIMER`, `CAVEAT`, `text()`) and the rendered note on 5 real areas. Does any phrase read as an avalanche rating,
   a safety assurance, or advice to travel/not travel? (The note must say wind-loading is *possible*, never that terrain is safe or unsafe.)  ☐ pass ☐ change: ________
2. **Disclaimer placement.** Is "Wind transport potential — not an avalanche rating." visible without expanding or scrolling past the flag, at 375 px and 1280 px?  ☐
3. **Avalanche center link.** Does the link go to the right center's own forecast for the area's zone (try 5 zones in different centers, incl. one with no rating)?  ☐
4. **Thresholds.** Are 25 mph sustained / 35 mph gust at the *summit point* (NBM 10 m wind) sensible triggers for "snow may be transported"? NBM winds are 10 m, not ridge-top: should
   the thresholds be lower or the flag use `ridge.json` free-air winds? Suggested values: ________ ☐
5. **Duration/horizon.** Is "≥ 2 windy hours, during the snow or within 12 h after, first 72 h" reasonable? Would you suppress, or reword, after the snow is old (> 24 h)?  ☐
6. **Direction logic.** Leeward = vector-mean direction + 180°. Is "leeward (NE-facing) slopes" adequate for a note this coarse, or should it list cross-loading too / drop the aspect entirely?  ☐
7. **False reassurance.** When the flag is NOT shown (light wind, or no model wind data), could its absence be read as "no wind loading"? Is a "no flag" statement needed or harmful?  ☐
8. **Sno-Parks / SNOTEL / base points.** Should the flag also appear for snowmobile/Nordic Sno-Park pages (different audience, lower terrain), or stay ski-area summit only?  ☐
9. **Heuristic labelling.** Is the "how this flag works" explanation (to be written in about.html) honest that this is an unverified heuristic and that M9 verification is pending?  ☐
10. **Go / no-go.** ☐ Enable as is  ☐ Enable after the changes above  ☐ Do not enable. Notes: ______________________________________________
