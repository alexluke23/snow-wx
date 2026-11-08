# Sno-Parks & winter recreation points: sources (M4.5 research, Nov 8 2026)

Goal (PLAN.md §5.6): western Sno-Parks and winter trailheads (snowmobile, XC ski, snowshoe,
sled/tubing) as a new point type `snopark`. Preference: public-domain, key-free sources;
OpenStreetMap to fill gaps; every point records its source. **Nothing is built until the owner
approves the sources below.**

## Summary

| Source | Coverage (western US) | Licence / terms | Access | Updates | Fields we get |
|---|---|---|---|---|---|
| **USFS EDW Recreation Sites** (`EDW_RecInfraRecreationSites_02`, layer 0) | 375 winter sites in the West: 313 SNOWPARK, 30 SNOWPLAY AREA, 18 SKI AREA NORDIC, 8 TRAILHEAD, 6 other. By Forest Service region: R6 OR/WA 191, R1 MT/N-ID 71, R4 UT/S-ID/NV/W-WY 40, R2 CO/WY 34, R5 CA 30, R3 AZ/NM 9 | US federal data, public domain (data.gov lists CC0 1.0) | ArcGIS REST query, no key, 2,000 records/request | Daily from the Forest Service recreation portal | name, site type, lat/lon, managing unit, fee charged, passes text (e.g. "Oregon State Sno-Park Permit required November 01 - April 30"), min/max elevation (58 % filled), USFS page URL (59 %), activities (only 8 % filled), season fields |
| **OpenStreetMap** (Overpass; names matching Sno-Park / Snow Park / Park N' Ski, parking with snowmobile=*, trailheads with ski=*) | 182 features: WA 72, OR 63, CA/NV 21, UT/CO/AZ/NM 22, ID/MT/WY 4 | ODbL: attribution, derived catalog shared under ODbL (as `data/ski_areas.json` already is) | Overpass API or a one-off extract, no key | Continuous (community) | name, lat/lon (parking area centre), operator, fee, website, access, sometimes piste tags; no elevation |
| Washington State Parks Winter Recreation Program ("Find Sno-Parks") | 126 Sno-Parks (many on USFS land, so partly in EDW) | Terms not stated; no data download found (finder pages + an interactive map) | Web pages only | Seasonal | name, area, permit type (non-motorized / groomed / snowmobile), Discover Pass, grooming notes |
| Oregon ODOT Sno-Park program (TripCheck "Oregon Sno-Parks") | ~100 Sno-Parks | Page footer "Copyright © ODOT. All Rights Reserved"; TripCheck Data API exists (needs a subscription key) but no Sno-Park endpoint was found | Interactive map / regional pages | Seasonal | name, region, activities supplied by land managers, permit |
| California State Parks OHMVR SNO-PARKs | 18 sites (all on USFS land, so mostly in EDW) | Terms not stated (state agency pages/brochure) | Web page + PDF brochure | Annual | name, corridor, activities (snowmobile / non-motorized), permit |
| Idaho Parks & Recreation Park N' Ski | 14 Park N' Ski areas + 4 state parks with groomed XC | Terms not stated; ArcGIS Experience map (an ArcGIS Online layer behind it, not checked) | Web map | Seasonal | name, trails, permit (Park N' Ski or Winter Access Pass) |
| Recreation.gov RIDB | Federal facilities (overlaps EDW) | Public, but **needs an API key** | REST + key | Daily | Not needed: EDW already has the USFS sites (owner: ask before using; key would be an Actions secret) |
| Montana / Wyoming / Utah / Colorado state snowmobile programs | Snowmobile trailheads (counts unknown) | Not researched in detail | Mostly web maps / PDFs | Seasonal | Candidates for a later pass if EDW + OSM leave gaps |

## Coverage per western state (expected after EDW + OSM, before de-duplication)

| State | EDW (USFS) | OSM | State program | Notes |
|---|---|---|---|---|
| WA | in R6 (191 with OR) | 72 | 126 Sno-Parks | Best covered; OSM adds state-managed lots not on USFS land |
| OR | in R6 | 63 | ~100 Sno-Parks | Good |
| CA | 30 (R5) | ~15 | 18 | All 18 OHMVR SNO-PARKs are on USFS land; verify names against the official list |
| ID | in R1/R4 | few | 14 Park N' Ski | Park N' Ski areas partly on state land: may need the IDPR list |
| MT | in R1 (71 with N-ID) | few | none | Mostly USFS snowmobile/XC trailheads |
| WY, CO | in R2 (34) and R4 | few | snowmobile programs | Sparse |
| UT, NV | in R4 (40) | ~10 | snowmobile program (UT) | Sparse |
| AZ, NM | 9 (R3) | few | none | Small; e.g. snowplay areas near Flagstaff |

## Proposed approach (needs approval)
1. **Backbone: USFS EDW** (public domain, key-free): all SNOWPARK / SNOWPLAY AREA / SKI AREA NORDIC sites plus winter TRAILHEADs in the 11 states. Keep `source: usfs-edw`, the USFS id and page URL.
2. **Gap fill: OSM** (ODbL), only features with no EDW site within ~400 m or with a different name; `source: osm`, OSM id. Filter out ski-resort "terrain parks".
3. **State lists: cross-check only.** Used by hand to check names and permit types; not copied into the catalog, since their terms are unstated, or "All Rights Reserved" for ODOT. Optionally we could ask WA State Parks, ODOT, CA OHMVR and IDPR for permission to use their lists; that's the owner's call.
4. **Fields per point:**
   - name, state, managing agency (EDW unit or OSM operator), source and id, link (USFS page, OSM website, or the state program page);
   - permit: EDW "passes" text, else the state's program name (WA/OR/CA/ID);
   - activities: EDW list when filled, else inferred from site type and name (nordic → XC ski; snowplay → sledding; "snowmobile" in name or tags → snowmobile), marked as inferred;
   - groomed: only when a source says so (rarely);
   - elevation: always our own 3DEP value, plus a "high terrain" point (highest DEM within ~5 km), clearly labelled.
5. **Joins:** reuse the catalog machinery: NWS zone/county (alerts), avalanche zone, nearest SNOTEL/ASOS, NBM/NDFD cell. The NBM cell elevation is the full 3DEP cell average (owner decision).
6. **Budget estimate:**
   - about 450 points after de-duplication;
   - about 400 new NBM cells, roughly 70 min of one-time 3DEP cell statistics (cached in data_cache/catalog);
   - points job about +40 % decode/sample time;
   - site about +11 MB (about 25 KB per point file).

## Sources
- USFS EDW Recreation Sites layer: https://apps.fs.usda.gov/arcx/rest/services/EDW/EDW_RecInfraRecreationSites_02/MapServer/0
- Data.gov listing (CC0 1.0): https://catalog.data.gov/dataset/recreation-sites-feature-layer
- Washington State Parks, Find Sno-Parks: https://parks.wa.gov/find-sno-parks
- ODOT Sno-Park program: https://www.oregon.gov/odot/maintenance/pages/sno-park-program.aspx ; TripCheck Sno-Parks: https://www.tripcheck.com/Pages/Sno-Parks ; TripCheck API: https://tripcheck.com/Pages/API
- California OHMVR SNO-PARKs: https://ohv.parks.ca.gov/?page_id=30701
- Idaho Park N' Ski: https://parksandrecreation.idaho.gov/park-activity/cross-country-xc-skiing/ ; map: https://experience.arcgis.com/experience/5905e736b8ab4910a8ae9eb36d470ccd
- OpenStreetMap Overpass API: https://overpass-api.de/ (ODbL: https://www.openstreetmap.org/copyright)
