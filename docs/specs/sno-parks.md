# Spec: Sno-Parks & winter recreation points (M4.5)

> Read when working on the recreation catalog and its forecast pages.
> Part of Snow-Wx docs v1.0 (Nov 15 2026). Index and priorities: `PLAN.md`.
> Section numbers (§) are kept from the original single plan so cross-references still work.

---

### 5.6 Sno-Parks & winter recreation points (M4.5)
- Point type `snopark` in `data/rec_points.json`, sharing the ski-area machinery
  (alerts zone, avalanche zone, nearest SNOTEL/ASOS, NBM/NDFD cells, 3DEP).
- **Approved sources:** USFS EDW (public domain) + OpenStreetMap (ODbL); scope
  ~450 Sno-Parks/snowplay/Nordic. **Do not copy** state Sno-Park lists (WA/OR/CA/ID)
  without permission. Record the source of every point.
- Fields: name, state, agency, permit required, activities (snowmobile, XC,
  snowshoe, sled, dog sled), groomed (if known), lat/lon, 3DEP elevation, link.
- Forecast view reuses the area page; trailhead elevation plus optional labeled
  "high terrain" point. Extras: wind chill/apparent temp, trailhead snow depth
  (SNODAS), new snow, travel alerts, **avalanche danger prominent** (snowmobilers
  are a high-risk group).
- Finder gets a **Type** filter (Ski areas / Sno-Parks / All); obs map gets a
  Sno-Parks layer. ~450 more pages for SEO — build **after** W2 so they launch
  on the new URL scheme (if M4.5 is already in flight, finish it, then migrate).

### dev16 audit (M4.5 complete)
- 447 points (USFS EDW 407, OSM 40), each with `source` / `source_id` and an attribution line on its page (USDA Forest Service public domain; OSM ODbL).
  Dedupe against EDW is in `rec.dedupe`; against ski areas the points are a separate type (a Sno-Park near a resort is legitimate), so adjacency is only flagged.
- **Owner review:** `python -m pipeline catalog --rec` also writes `data/rec_points_review.csv` (`rec.review_flags`): near_ski_area (< 1 km), osm_only,
  generic_name, elevation_mismatch (trailhead vs 2.5 km cell > 2,500 ft), no_nws_grid, duplicate_nearby. Nov 17 run: 68 points flagged (osm_only 40, duplicate_nearby 25, near_ski_area 9).
- Model: trailhead (base) + labelled "high terrain" (summit) pair, per this spec; NBM/NDFD at both coordinates, same elevation handling as ski areas.
- Budgets (Nov 17): 447 point files avg 57.6 KB, max 59.8 KB (< 150 KB), 26.4 MB; whole build 5,559 files, 217 MB, largest file 1.4 MB (limits 20,000 / 25 MiB).
  Enabled: no budget is exceeded, so no `sno_parks.enabled` flag.
- Finder Type filter checked at 375 px (`tools/browser_check.py --only spmobile`): buttons 40 px tall, no sideways scroll, state menu follows the type with counts.
