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
