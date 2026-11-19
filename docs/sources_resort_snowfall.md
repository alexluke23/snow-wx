# Resort-reported snowfall: licensing brief (research only, Nov 18 2026)

> Purpose: decide whether Snow-Wx can show **resort-reported** new-snow totals (PLAN §8.4 "5a"). **Nothing here was scraped or integrated**: this is desk research from public documentation
> on Nov 18 2026 (WebSearch + page reads). Terms change: **[verify]** every line with the vendor before relying on it. This is not legal advice (PLAN §10 / BUSINESS §10.1: a lawyer reviews any contract).
> Rule that stands (CLAUDE.md): no scraping, ask before adding any source whose terms are unclear. Resort websites and OnTheSnow pages are not a free feed (an Apify "OnTheSnow scraper" exists; it is unlicensed access and we do not use it).

## The three candidates

| | **Mountain News (OnTheSnow) Partner API** | **The Weather Company (IBM) Snow and Ski Conditions API** | **OpenSnow API** |
|---|---|---|---|
| What it is | The resort-reported snow report feed: over 2,000 areas "file their snow conditions daily with Mountain News" ([data distribution](https://www.mountainnews.com/data-distribution/)); REST API with snow report and snowfall endpoints ([partner docs](https://partner.docs.onthesnow.com/)) | `/v3/wx/skiconditions`: "snow and ski conditions reported by ski resorts", **"sourced in partnership with OnTheSnow.com"** ([OpenAPI](https://developer.weather.com/docs/openapi/snow-and-ski-conditions-3-0)), i.e. the same resort data, resold | A **forecast** product (5-day, 12-h periods, hourly 24 h, snow summary), not a resort-observation feed ([API start](https://opensnow.com/api/start)) |
| Resort-reported snowfall fields | Yes: resort snowfall, base, trails, lifts; snowfall in **cm**, weather °C ([FAQ](https://partner.docs.onthesnow.com/faqs)); "check the last updated timestamp" because resorts do not always update | Yes: `snowFall24hours`, `snowFall48hours`, `snowFall72hours`, `snowDepthBase`, `snowDepthTop`, report time `conditionsValidTimeLocal`, expiry `expireTimeUtc` | No resort reports; its own forecasts only |
| Who can get it | "media outlets and large digital platforms" via the API, or a **self-service Snow Report Widget**; "Please contact us to inquire about a data partnership" ([contact](https://www.mountainnews.com/contact)); a key is issued after approval | API key; classified **"Restricted usage"**; production use needs a contract ([spec](https://developer.weather.com/docs/openapi/snow-and-ski-conditions-3-0)) | "select partners only"; request by e-mail (name, company, site, requirements) ([OpenSnow API](https://opensnow.com/api/start)) |
| Price | **Not published**; sales quote. Default quota 10 requests/s and 5,000/day, more "reach out to our sales team" ([FAQ](https://partner.docs.onthesnow.com/faqs)) | Published tiers: free trial 30 days (50k calls/day, "enterprise customers only"), **Standard $500/month for 1 M calls**, Enterprise custom ([packages](https://www.weathercompany.com/weather-data-apis/weather-data-apis-packages-pricing/)). The ski API is **not named** in the package features: confirm it is included | "custom quote ... according to the size and scope of your business"; not published ([OpenSnow API](https://opensnow.com/api/start)). A third-party listing puts a different vendor (CustomWeather) ski product at ~$225/month: unverified |
| Attribution | Not stated on the pages read (ask) | **Required**: every response carries `attribution` = "In Partnership with OnTheSnow.com" | **Required**: "Powered by OpenSnow" above the data and "View Forecast Details →" linking back below it ([terms §6](https://support.opensnow.com/api/api-terms)); the logo on every screen |
| Caching / redistribution | **Not stated** on the pages read (ask) | Depends on the "Data API Common Usage Guide" (not read) and the contract | Terms (Mar 24 2026): licence is "limited, non-exclusive, non-transferable, revocable ... solely for your internal business purposes or permitted applications"; **no resale/redistribution of raw data without consent; no training your own models; destroy cached data on termination**; 30 days' notice termination "with or without cause" ([terms](https://support.opensnow.com/api/api-terms)) |
| Fit for Snow-Wx | The primary source of the numbers; the question is only price/terms. Freshness: daily; many resorts report late | Same data via a paid, rate-limited, attribution-bound reseller; easier self-serve start, restricted usage class | Competitor: it sells forecasts; useful only as a possible partner, not as a source for observations |

## What we would show, and what we would not
Resort-reported 24/48/72 h new snow as a labelled **"reported by the resort"** observation next to our NOHRSC / SNOTEL / NBM numbers (never blended into a forecast, never used to score NBM until M9 knows the resort reporting bias), with the report time, an
"updated N h ago / stale" flag, and attribution as the vendor requires. Resort numbers are marketing-adjacent (measurement site, timing and rounding vary): label them that way (PLAN §0 rule 2).

## Likely cost (order of magnitude; all unverified until quoted)
- TWC Standard **$500/month** ($6,000/year) if the ski API is in that package; otherwise Enterprise custom. 160 ski areas refreshed hourly = ~115,000 calls/month, far inside 1 M, so cost is a flat plan, not per call.
- Mountain News: unknown; plausibly four to five figures per year for a "large digital platform", possibly a cheaper widget route. The widget (self-service) may allow an embed without an API contract: ask.
- OpenSnow: not a source of resort reports; no cost needed.
- Free-first stance (PLAN §1): no paywall before Feb 2027; a $500/month data line is only justified once supporter revenue or sponsorship exists, so this is a **post-Gate-3** decision.

## Questions to ask (copy into the e-mail)
**Mountain News / OnTheSnow** (https://www.mountainnews.com/contact):
1. We run a free, non-commercial-for-now snow-forecast website for the western US (about 160 ski areas, later a small paid tier). Which tier or agreement applies to us, and is there a self-serve or startup option?
2. What does it cost (setup, monthly, per-call), and does the price change if we later add paid features?
3. Which fields and update cadence do we get (24/48/72 h snowfall, base depth, open trails/lifts, report time), and for how many US ski areas and Sno-Park/Nordic centres?
4. May we **cache and store** the values (and for how long), show history, and keep a **forecast-verification archive** that compares our forecasts with resort-reported snowfall (internal analysis and a public accuracy page)?
5. What attribution is required (text, logo, link) and may we show the numbers in charts, tables, e-mail/push alerts and an offline-capable PWA?
6. May we redistribute derived values (e.g. "reported 8 in, NBM forecast 5 in") and are there restrictions on competing weather or snow-forecast products?
7. Which resorts opt out, and how are bad or stale reports flagged? Is there an SLA, and what happens on termination (must cached history be deleted)?
8. Can we get a trial key to test coverage of the 160 areas before committing?

**The Weather Company** (https://www.weathercompany.com/contact/contact-weather-data-intelligence/):
1. Is the Snow and Ski Conditions API included in Standard ($500/month / 1 M calls) or only Enterprise? What does "Restricted usage" mean for a public website and for a paid tier?
2. What are the caching/expiry rules for `skiconditions` (Common Usage Guide), may we store history for verification, and for how long?
3. Does the "In Partnership with OnTheSnow.com" attribution have required placement/size, and may it appear in alerts and a PWA?
4. Does the contract allow a non-commercial free site that later adds paid features, and what are termination and data-deletion obligations?

**OpenSnow** (only if a partnership is wanted; they do not supply resort observations): whether "Powered by OpenSnow" content could complement (not replace) NBM, and whether a public-verification page that cites their forecast is permitted. Low priority.

## Recommendation
Do **not** build until a written answer exists. Send the Mountain News questions first (primary source, may offer the widget route), ask TWC question 1 in parallel (the only published price). If neither fits the free-first budget, keep resort reports out and rely on NOHRSC, SNODAS and SNOTEL observations (already public domain). Record the decision in PLAN §3.

Sources (read Nov 18 2026): [Mountain News data distribution](https://www.mountainnews.com/data-distribution/) · [OnTheSnow partner docs](https://partner.docs.onthesnow.com/) · [partner FAQ](https://partner.docs.onthesnow.com/faqs) ·
[TWC Snow and Ski Conditions OpenAPI](https://developer.weather.com/docs/openapi/snow-and-ski-conditions-3-0) · [TWC packages and pricing](https://www.weathercompany.com/weather-data-apis/weather-data-apis-packages-pricing/) ·
[OpenSnow API](https://opensnow.com/api/start) · [OpenSnow API terms (Mar 24 2026)](https://support.opensnow.com/api/api-terms).
