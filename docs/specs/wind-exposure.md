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
