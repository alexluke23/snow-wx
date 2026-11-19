# Launch-readiness package (dev18 Part 2; public share Dec 18–20)

Status: built and tested on branch dev18. Everything here is OFF or DRAFT where an owner decision or a lawyer is needed. Pages carry `noindex` until the owner signs the legal drafts.

## 2a Sources and credits
- `config/sources.yml` is the one register (18 entries: NOAA/NWS, NOHRSC, NRCS SNOTEL, IEM, USGS, avalanche.org, OSM/OpenSkiMap, OpenFreeMap, ECMWF, USFS and state parks, Plotly, Leaflet/MapLibre, Python libraries, analytics providers, hosting, resort websites, webcam links).
  Fields: licence, licence URL, the credit text the licence asks for, `hosts` (every host code/config talks to) and `browser` (hosts the VISITOR'S browser contacts, with when).
- `tools/gen_site_pages.py` writes `web/sources.html` from it (committed; `tests/test_sources.py` fails when the page is stale). The ODbL notice for the derived catalogs and the ECMWF "adapted" statement are on the page.
- `tests/test_sources.py::test_every_external_host_in_code_and_config_has_a_source_entry` scans `pipeline/`, `web/` and `config/` for `https://host` and fails for any host without an entry (or an `ignore_hosts` reason).
- Open: **avalanche.org commercial terms** (`verify: true`, PLAN §10, owner decision #9).

## 2b Disclaimer, privacy, terms (plain-language DRAFTS)
- `web/disclaimer.html`, `web/privacy.html`, `web/terms.html`: DRAFT banner, `noindex`, "not legal advice", bracketed `[OWNER / LAWYER: …]` placeholders. The disclaimer says the site is not for avalanche or life-safety decisions and links avalanche.org, the NWS and 911.
- Footer on every page: Data status · Sources · Disclaimer · Privacy · Terms.
- **Privacy audit (measured with a real browser on 13 pages, `tools/browser_check.py --only privacy`):** no cookies are set anywhere; storage keys are exactly those listed on the privacy page; the only hosts contacted besides our own are
  `basemap.nationalmap.gov` (USGS tiles), `tiles.openfreemap.org` (reference layer), `mapservices.weather.noaa.gov` (NWS winter-hazard overlay, **found by the audit and now disclosed**), `cdn.plot.ly` (Plotly) and, rarely, `api.weather.gov` (hazard popup text, last resort). No fonts, trackers or embeds.
- **Requests that should be removed or self-hosted (recommendations, none done):**
  1. **`cdn.plot.ly` → self-host Plotly** (MIT, vendored like Leaflet): removes a third-party request on every chart page, a CSP exception and a CDN dependency. ~1 MB, well inside limits.
  2. **`api.weather.gov` live fetch → drop it** by widening `alerts/hazard_text.json` to the offices outside the 11 configured states (the 4–18 % of popups that still need the live call); then the privacy page has one fewer host.
  3. USGS tiles, OpenFreeMap and the NOAA overlay are inherent to the maps; the long-term answer is self-hosted PMTiles (PLAN §8.4), not before launch.
- Owner/lawyer to-do: legal name, governing law, contact, region-specific rights, final dates; decide whether `noindex` comes off at launch.

## 2c Cookieless analytics (W5), OFF
- `config/settings.yml` `analytics: {enabled: false, provider: none, site_id: "", script_url: ""}`. The owner chooses the provider; nothing in code picks one.
- `web/js/analytics.js` is fetched ONLY when `data/meta.json` says enabled (`site-config.js` loads it): with the shipped config the site makes **zero** analytics requests (checked in a real browser: `--only analytics`).
- Honours Do Not Track and Global Privacy Control (nothing injected for opted-out visitors); no cookies, no storage, no fingerprinting calls (tests grep the file); events carry only a name from a fixed list and a `where`/`kind` label from a fixed vocabulary.
- Events (PLAN W5): `favorite_added` (area, Finder), `install` (PWA `appinstalled`), `avalanche_click` (`data-track` on the avalanche-center links), `table_view` (the "View as table" toggle), `signup` and `alert_created` (API only: no UI exists yet).
- Providers supported (adapters in `analytics.js`; prices and terms **[verify]** before choosing):

| | Plausible | GoatCounter | Cloudflare Web Analytics |
|---|---|---|---|
| Cookies / personal data | none | none | none |
| Custom events | yes (`plausible(name, {props})`) | yes (`count({event:true})`) | **no** (page views and web vitals only) |
| Cost | paid hosted plan or self-host (AGPL) | free for non-commercial use, small fee otherwise; self-host (EUPL) | free |
| Fit | simplest events + dashboards | tiny, open, hosted or self-hosted | zero setup on Cloudflare Pages (W1), no events |

- To enable: set `analytics.enabled: true`, `provider`, `site_id` (see comments in settings.yml); add the provider's script host to `browser:` in `config/sources.yml`, to the privacy page (regenerate) and to the CSP `script-src`/`connect-src` — `tests/test_analytics.py::test_enabling_a_provider_requires_it_to_be_disclosed` fails until the privacy page and sources register name it.

## 2d Link check, 404, robots/sitemap, `_headers`
- `python -m pipeline linkcheck --build build [--outbound] [--data]` (`pipeline/linkcheck.py`): internal links and `#id`s of the generated pages, `<base>`-aware 404, title/description sanity, robots/sitemap/canonical sanity when those files exist (they are produced by `pipeline pages`, behind `pages.enabled`), and every distinct outbound URL (HEAD, one streamed GET when HEAD is refused, one request per URL, 1 s per host); `--data` adds the links stored in data files (resort sites, permit pages, avalanche-center forecasts, webcams). Offline tests with fakes: `tests/test_linkcheck.py`.
- `web/404.html` (generated, `noindex`, `<base href>` filled from `site.base_path` at build time).
- **`docs/cloudflare_headers.draft`** (NOT in web/): CSP, nosniff, referrer and permissions policies, cache rules, with a note per header on what it could break. `tools/browser_check.py --only csp` serves the build with exactly that CSP and fails on any violation on 14 pages: today there is none (no inline scripts, no eval; Plotly needs `style-src 'unsafe-inline'`; MapLibre needs `worker-src blob:`).
