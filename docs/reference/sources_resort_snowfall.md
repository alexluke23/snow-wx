---
status: reference
owner: pipeline
last_reviewed: 2026-11-23
read_when: reference for its topic only
---

# Resort-reported snowfall: licence terms (research only, Nov 18 2026)

> Purpose: record whether Snow-Wx can show **resort-reported** new-snow totals (PLAN §8.4). **Nothing here was scraped or integrated**: desk research from public documentation
> on Nov 18 2026. Terms change: **[verify]** every line with the vendor before relying on it. Not legal advice.
> Rule that stands (CLAUDE.md): no scraping, ask before adding any source whose terms are unclear. Resort websites and OnTheSnow pages are not a free feed (third-party scrapers exist; they are
> unlicensed access and we do not use them). Contracts, costs and vendor contact are owner tasks and are tracked privately.

## Candidate feeds and their published terms

| | **Mountain News (OnTheSnow) Partner API** | **The Weather Company (IBM) Snow and Ski Conditions API** | **OpenSnow API** |
|---|---|---|---|
| What it is | The resort-reported snow report feed: over 2,000 areas "file their snow conditions daily with Mountain News" ([data distribution](https://www.mountainnews.com/data-distribution/)); REST API with snow report and snowfall endpoints ([partner docs](https://partner.docs.onthesnow.com/)) | `/v3/wx/skiconditions`: "snow and ski conditions reported by ski resorts", sourced in partnership with OnTheSnow ([spec](https://developer.weather.com/docs/openapi/snow-and-ski-conditions-3-0)) | Forecast content, not a resort-observation feed ([API start](https://opensnow.com/api/start)) |
| Resort-reported snowfall fields | Yes: resort snowfall, base, trails, lifts; snowfall in **cm**, weather °C ([FAQ](https://partner.docs.onthesnow.com/faqs)); "check the last updated timestamp" because resorts do not always update | Yes: `snowFall24hours`, `snowFall48hours`, `snowFall72hours`, `snowDepthBase`, `snowDepthTop`, report time `conditionsValidTimeLocal`, expiry `expireTimeUtc` | No resort reports |
| Access | Key issued after approval of a data partnership | API key; classified **"Restricted usage"**; production use needs a contract | Select partners only |
| Attribution | Not stated on the pages read | **Required**: every response carries `attribution` = "In Partnership with OnTheSnow.com" | **Required**: "Powered by OpenSnow" above the data and a "View Forecast Details →" link back below it ([terms §6](https://support.opensnow.com/api/api-terms)) |
| Caching / redistribution | **Not stated** on the pages read | Depends on the "Data API Common Usage Guide" (not read) and the contract | Terms (Mar 24 2026): limited, non-exclusive, revocable licence; **no redistribution of raw data without consent; no training own models; cached data destroyed on termination** |

## What we would show, and what we would not
Resort-reported 24/48/72 h new snow as a labelled **"reported by the resort"** observation next to our NOHRSC / SNOTEL / NBM numbers (never blended into a forecast, never used to score NBM until M9
knows the resort reporting bias), with the report time, an "updated N h ago / stale" flag, and attribution as the licence requires. Measurement site, timing and rounding vary by resort: label them that
way (PLAN §0 rule 2).

## Technical requirements a licence must allow before any build
Caching and storing values (for how long), keeping history for the verification archive, showing the numbers in charts, tables, alerts and an offline-capable PWA, and the exact attribution placement.

## Status
Do **not** build until a written licence exists. Without one, keep resort reports out and rely on NOHRSC, SNODAS and SNOTEL observations (already public domain).

Sources (read Nov 18 2026): [Mountain News data distribution](https://www.mountainnews.com/data-distribution/) · [OnTheSnow partner docs](https://partner.docs.onthesnow.com/) · [partner FAQ](https://partner.docs.onthesnow.com/faqs) ·
[TWC Snow and Ski Conditions OpenAPI](https://developer.weather.com/docs/openapi/snow-and-ski-conditions-3-0) · [OpenSnow API](https://opensnow.com/api/start) · [OpenSnow API terms (Mar 24 2026)](https://support.opensnow.com/api/api-terms).
