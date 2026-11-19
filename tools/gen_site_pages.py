"""Generate the launch-readiness pages (dev18 Part 2) into web/: sources.html (from config/sources.yml), privacy.html, terms.html, disclaimer.html, 404.html.
The output is committed; tests/test_sources.py regenerates in memory and fails when a committed page is stale.

    python tools/gen_site_pages.py            # write web/*.html
    python tools/gen_site_pages.py --check    # exit 1 when a page is stale (what the test does)

The disclaimer, privacy and terms pages are plain-language DRAFTS for the owner and a lawyer (not legal advice); they carry a DRAFT banner and
`noindex` until the owner signs them off. The privacy page is generated from facts the code can verify: the third-party requests come from
config/sources.yml (`browser:`), the storage keys from STORAGE below (tests scan web/js for every key), and a browser check asserts "no cookies".
"""
from __future__ import annotations

import html
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
WEB = REPO / "web"
E = html.escape

# What the site keeps in YOUR browser (localStorage / sessionStorage). Every key literal in web/js must be listed here (tests/test_sources.py).
STORAGE = [
    ("snowwx.favorites", "localStorage", "Your favorite ski areas and SNOTEL sites (\"My mountains\")", "until you remove them or clear site data"),
    ("snowwx.home", "localStorage", "Whether you chose \"My mountains\" as your start page", "until you change it"),
    ("snowwx.home.dismissed", "sessionStorage", "That you closed the start-page prompt in this tab", "until you close the tab"),
    ("snowwx.layers", "localStorage", "Which map layers you switched on", "until you reset or clear site data"),
    ("snowwx.layers.v", "localStorage", "The version of the default map layers (so a new default is not forced on you twice)", "until you clear site data"),
    ("snowwx.finder", "localStorage", "Your Powder Finder choices (sort, filters, units)", "until you clear site data"),
    ("snowwx.pwa.coach", "localStorage", "That the \"install this app\" hint was shown (only if the offline app mode is switched on, which it is not yet)", "until you clear site data"),
]

NAV = """    <nav class="site-nav">
      <a href="mine.html"><span class="nav-long">★ My mountains</span><span class="nav-short">★ Mine</span></a>
      <a href="index.html"><span class="nav-long">Obs map</span><span class="nav-short">Map</span></a>
      <a href="finder.html"><span class="nav-long">Powder Finder</span><span class="nav-short">Finder</span></a>
      <a href="models.html"><span class="nav-long">Model maps</span><span class="nav-short">Models</span></a>
      <a href="about.html">About</a>
    </nav>"""
SEARCH = """    <form class="site-search" role="search" autocomplete="off">
      <button type="button" class="ss-toggle" aria-label="Search ski areas and SNOTEL sites" aria-expanded="false" aria-controls="ss-input">
        <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24"><circle cx="10.5" cy="10.5" r="6.5" fill="none" stroke="currentColor" stroke-width="2.2"/><path d="M15.5 15.5 21 21" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"/></svg>
      </button>
      <div class="ss-box">
        <label class="sr" for="ss-input">Search ski areas and SNOTEL sites</label>
        <input id="ss-input" type="search" placeholder="Search ski areas, SNOTEL…" role="combobox" aria-autocomplete="list"
          aria-expanded="false" aria-controls="ss-list" spellcheck="false" enterkeyhint="go">
        <ul id="ss-list" class="search-results" role="listbox" aria-label="Search results" hidden></ul>
      </div>
    </form>"""
LEGAL_LINKS = ('<a href="sources.html">Sources</a> · <a href="disclaimer.html">Disclaimer</a> · <a href="privacy.html">Privacy</a> · <a href="terms.html">Terms</a>')
FOOTER = ("""  <footer>Forecasts: NOAA/NWS. Snowpack: USDA NRCS, NOAA/NWS NOHRSC. Ski areas © OpenStreetMap contributors,
    OpenSkiMap (ODbL). Not a substitute for the NWS forecast or your local avalanche center. · <a href="status.html">Data status</a> · """ + LEGAL_LINKS + """ <span data-mailto-wrap hidden>· <a class="site-feedback" data-mailto data-subject="Snow-Wx feedback" hidden>Send feedback</a></span>
  </footer>""")


def page(title: str, description: str, body: str, *, draft: bool = False, active: str = "", robots: str = "", scripts: str = "", base: bool = False) -> str:
    banner = ('\n    <p class="draft-banner" role="note"><b>DRAFT</b> for the owner and a lawyer to review. It is written in plain language, it is not legal advice, and it is '
              'not final: nothing here is binding until the owner publishes a final version.</p>') if draft else ""
    meta_robots = f'\n  <meta name="robots" content="{robots}">' if robots else ""
    base_tag = '\n  <base href="__BASE_HREF__">' if base else ""      # 404.html is served from ANY path: `pipeline build` fills in config site.base_path + "/"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Snow-Wx · {E(title)}</title>
  <meta name="description" content="{E(description)}">{meta_robots}{base_tag}
  <link rel="icon" href="data:,">
  <link rel="stylesheet" href="css/style.css">
</head>
<body class="about-page doc-page">
  <header>
    <h1>Snow-Wx <span>Western US</span></h1>
{NAV}
{SEARCH}
  </header>

  <main class="about">{banner}
{body}
  </main>
{FOOTER}
  <script src="js/site-config.js"></script>
  <script src="js/search.js" defer></script>{scripts}
</body>
</html>
"""


def load_sources() -> dict:
    return yaml.safe_load((REPO / "config" / "sources.yml").read_text(encoding="utf-8"))


KINDS = [("data", "Weather, snow and avalanche data"), ("basemap", "Map tiles and elevation"), ("software", "Software"), ("hosting", "Hosting"), ("links", "Links to other sites")]


def sources_page(src: dict | None = None) -> str:
    src = src or load_sources()
    parts = ["""    <h2>Data sources and credits</h2>
    <p class="lead">Every number on Snow-Wx comes from a public source. This page lists each one, the licence it comes under and the credit it asks for. We are not
      affiliated with any of them, and none of them endorses this site.</p>"""]
    for kind, heading in KINDS:
        rows = [s for s in src["sources"] if s["kind"] == kind]
        if not rows:
            continue
        parts.append(f'    <section id="{kind}"><h3>{E(heading)}</h3>')
        for s in rows:
            ver = ' <span class="hint">(terms being confirmed before launch)</span>' if s.get("verify") else ""
            credit = f'<p class="credit"><b>Credit:</b> {E(s["credit"])}</p>' if s.get("credit") else ""
            parts.append(f"""      <div class="src" id="src-{E(s['id'])}"><h4>{E(s['name'])}{ver}</h4>
        <p>{E(s['role'])}.</p>
        <p><b>Licence:</b> {E(s['licence'])} · <a href="{E(s['licence_url'])}" target="_blank" rel="noopener">terms</a></p>
        {credit}</div>""")
        parts.append("    </section>")
    parts.append("""    <section id="our-data"><h3>Data we publish</h3>
      <p>The ski-area and Sno-Park catalogs (<code>data/ski_areas.json</code>, <code>data/rec_points.json</code>) are derived from OpenStreetMap and OpenSkiMap and are
        therefore made available under the <a href="https://opendatacommons.org/licenses/odbl/1-0/" target="_blank" rel="noopener">Open Database Licence (ODbL)</a>:
        you may use and adapt them if you credit "© OpenStreetMap contributors" and share derived databases under the same licence. Forecast numbers shown on pages are
        derived from NOAA/NWS and ECMWF data (see above) and carry no additional claim.</p>
      <p>ECMWF data are <b>adapted</b>: we read point values from ECMWF's gridded files, accumulate precipitation, and compute percentiles across ensemble members.
        ECMWF has not endorsed these adaptations.</p>
    </section>
    <p class="hint">Missing a credit, or see one that is wrong? Use the feedback link in the footer and we will fix it.</p>""")
    return page("Sources and credits", "Every data source, licence and credit used by Snow-Wx: NOAA/NWS, NRCS SNOTEL, USGS, ECMWF open data, OpenStreetMap and more.", "\n".join(parts))


def disclaimer_page() -> str:
    body = """    <h2 id="disclaimer">Disclaimer</h2>
    <p class="lead"><strong>Snow-Wx is not for avalanche, travel or life-safety decisions.</strong> It shows weather-model guidance and observations. Mountain weather and snow
      conditions can change quickly and models are often wrong at a single point on a mountain.</p>
    <section><h3>Avalanche safety</h3>
      <ul>
        <li>Avalanche danger shown here is the rating published by your local avalanche center, copied unaltered and greyed out when it has expired. We never make our own rating.
          Read the center's <b>full forecast</b> every time, and go to <a href="https://avalanche.org/" target="_blank" rel="noopener">avalanche.org</a> to find your center.</li>
        <li>Backcountry travel needs training, the right equipment and a partner who knows how to use it. A forecast on this site does not replace any of that.</li>
        <li>Labels such as "wind-affected snow likely", "powder quality" and "model agreement" are <b>heuristics</b> we wrote. They are not accuracy claims and not avalanche ratings.</li>
      </ul></section>
    <section><h3>Weather</h3>
      <ul>
        <li>This is not an official forecast. For warnings and official forecasts use the <a href="https://www.weather.gov/" target="_blank" rel="noopener">National Weather Service</a>.</li>
        <li>Point forecasts come from coarse model grids (about 2.5 km for NBM, 28 km for ECMWF). We adjust for height in a simple way; a ridge, a bowl or a road can differ a lot.</li>
        <li>Snow depth, temperature and wind observations are automatic and provisional. They can be wrong, missing or out of date; the page says when they are.</li>
        <li>Data can arrive late or stop. The <a href="status.html">Data status</a> page shows what is current.</li>
      </ul></section>
    <section><h3>Roads, parking and permits</h3>
      <p>Road, parking, Sno-Park permit and webcam information is linked from the agencies and resorts that publish it. Check their sites before you travel. Links to other sites are
        outside our control.</p></section>
    <section><h3>No warranty</h3>
      <p>The site is provided "as is", without any promise that it is accurate, complete or available. Use it at your own risk. In an emergency call 911.</p></section>
    <p class="hint">See also: <a href="terms.html">Terms</a> · <a href="privacy.html">Privacy</a> · <a href="about.html">About and methods</a>.</p>"""
    return page("Disclaimer", "Snow-Wx is not for avalanche or life-safety decisions: what the site is, what it is not, and where to find your avalanche center and the National Weather Service.",
                body, draft=True, robots="noindex")


def terms_page() -> str:
    body = """    <h2>Terms of use</h2>
    <p class="lead">These are the plain-language rules for using Snow-Wx. [OWNER / LAWYER: replace the bracketed items before publishing.]</p>
    <section><h3>1. What this is</h3>
      <p>Snow-Wx ([OWNER: legal name or trading name]) shows open weather, snowpack and avalanche data for western US mountains. It is free to use. Read the
        <a href="disclaimer.html">Disclaimer</a>: the site is <b>not for avalanche or life-safety decisions</b>.</p></section>
    <section><h3>2. Using the site</h3>
      <ul>
        <li>You may use the site for personal and non-commercial purposes and link to it.</li>
        <li>Please do not overload it: no scraping of pages at high rates, no attempts to break or probe it. The underlying public data are available from their original sources
          (see <a href="sources.html">Sources</a>).</li>
        <li>You may not use the site, or anything on it, to suggest that a government agency, an avalanche center or a data provider endorses you or us.</li>
      </ul></section>
    <section><h3>3. Content and licences</h3>
      <p>The code is open source ([OWNER: licence, once chosen]). Data from NOAA/NWS, USDA NRCS and USGS are public domain; OpenStreetMap-derived catalogs are under the ODbL; ECMWF open
        data are under CC BY 4.0; others as listed on the <a href="sources.html">Sources</a> page. Credits must stay with any copy you make.</p></section>
    <section><h3>4. No warranty, limits on liability</h3>
      <p>The site and its data are provided "as is" and "as available". To the extent the law allows, we are not liable for loss or injury arising from use of, or inability to use, the
        site. [LAWYER: wording and jurisdiction-specific limits.]</p></section>
    <section><h3>5. Your feedback</h3>
      <p>If you send feedback or a "bust" report by e-mail, you allow us to use it to improve the site. We will not publish your name or address without asking.</p></section>
    <section><h3>6. Changes, accounts and alerts</h3>
      <p>We may change the site or these terms. There are no accounts or paid features today. If e-mail alerts or paid features are added, these terms will be updated first and we
        will say so on the site. [OWNER: effective date.]</p></section>
    <section><h3>7. Law and contact</h3>
      <p>[LAWYER: governing law and place of disputes.] Contact: use the feedback link in the footer.</p></section>
    <p class="hint">See also: <a href="disclaimer.html">Disclaimer</a> · <a href="privacy.html">Privacy</a>.</p>"""
    return page("Terms of use", "Plain-language draft terms of use for Snow-Wx (draft for owner and lawyer review).", body, draft=True, robots="noindex")


def privacy_page(src: dict | None = None) -> str:
    src = src or load_sources()
    third = [(h, s["name"], s.get("browser_when", "")) for s in src["sources"] for h in (s.get("browser") or [])]
    third_rows = "\n".join(f"        <tr><th scope=\"row\">{E(h)}</th><td>{E(name)}</td><td>{E(when)}</td></tr>" for h, name, when in third)
    store_rows = "\n".join(f"        <tr><th scope=\"row\"><code>{E(k)}</code></th><td>{E(kind)}</td><td>{E(what)}</td><td>{E(keep)}</td></tr>" for k, kind, what, keep in STORAGE)
    body = f"""    <h2>Privacy</h2>
    <p class="lead"><strong>Snow-Wx sets no cookies, has no accounts, and runs no analytics or advertising today.</strong> This page lists exactly what the site does with your browser,
      so you can check it. It describes the site as it is built now and will be updated before anything changes.</p>
    <nav class="toc" aria-label="On this page"><a href="#ours">What we keep</a> · <a href="#browser">What stays in your browser</a> · <a href="#third">Other companies your browser contacts</a> ·
      <a href="#links">Links to other sites</a> · <a href="#later">If this changes</a></nav>
    <section id="ours"><h3>What we keep about you</h3>
      <ul>
        <li><b>Nothing</b> that identifies you. The site is a set of static files: there is no login, no form and no database that holds visitors.</li>
        <li>The site is served from GitHub Pages (planned: Cloudflare). Like any web host, the host sees your IP address and the pages you request and keeps ordinary server logs under its own privacy
          policy. We do not receive or use those logs. [OWNER: update when the host changes.]</li>
        <li>If you click "Send feedback" or "Report a bust", your e-mail program opens with a message to the feedback address. Nothing is sent until you send it; if you do, we receive your e-mail address and what you wrote.</li>
      </ul></section>
    <section id="browser"><h3>What stays in your browser</h3>
      <p><b>No cookies.</b> The site stores a few settings in your browser's own storage, on your device only. They are never sent to us. Clear them any time with your browser's "clear site data".</p>
      <div class="tbl-wrap"><table class="st-tbl"><caption class="sr">What Snow-Wx stores in your browser</caption>
        <thead><tr><th scope="col">Key</th><th scope="col">Where</th><th scope="col">What it holds</th><th scope="col">How long</th></tr></thead>
        <tbody>
{store_rows}
        </tbody></table></div>
      <p class="hint">When the optional offline app mode is switched on (not yet), your browser also keeps a copy of the pages and your favorites' forecasts in its cache storage so they work without a connection.</p></section>
    <section id="third"><h3>Other companies your browser contacts</h3>
      <p>To draw maps and charts, <b>your browser itself asks the services below for files</b>. Each one therefore sees your IP address, your browser type and what you ask for (for map tiles,
        roughly the area you are looking at). We do not control their logs; see their privacy policies. Nothing else is requested from other sites when a page loads.</p>
      <div class="tbl-wrap"><table class="st-tbl"><caption class="sr">Third-party requests your browser makes</caption>
        <thead><tr><th scope="col">Host</th><th scope="col">Service</th><th scope="col">When</th></tr></thead>
        <tbody>
{third_rows}
        </tbody></table></div>
      <p class="hint">No external fonts, trackers, advertising, social-media buttons or embedded videos are used. Webcams are links only: no webcam picture is loaded here.</p></section>
    <section id="links"><h3>Links to other sites</h3>
      <p>Links to the National Weather Service, avalanche centers, resorts, road-condition sites and others open their own websites, which have their own privacy practices. We add no tracking to those links
        and they open with <code>rel="noopener noreferrer"</code>, so the destination is not told which page you came from.</p></section>
    <section id="later"><h3>If this changes</h3>
      <ul>
        <li><b>Analytics:</b> if we add visitor counts they will be cookieless, with no personal data, no fingerprinting, and they will honour "Do Not Track" and Global Privacy Control. Until then none is loaded
          (the code is switched off and makes no request).</li>
        <li><b>E-mail alerts</b> (planned) would need your e-mail address; we would ask you to confirm it, send you a one-click unsubscribe link and delete it when you unsubscribe. This page will say so before launch.</li>
        <li>Children: the site is not directed at children and collects no personal data from anyone.</li>
        <li>[OWNER / LAWYER: add your contact details, region-specific rights (for example California and EU/UK) and the date of the final version.]</li>
      </ul></section>
    <p class="hint">See also: <a href="sources.html">Sources</a> · <a href="disclaimer.html">Disclaimer</a> · <a href="terms.html">Terms</a>.</p>"""
    return page("Privacy", "What Snow-Wx stores in your browser and which other services your browser contacts: no cookies, no accounts, no analytics (draft for owner and lawyer review).",
                body, draft=True, robots="noindex")


def not_found_page() -> str:
    body = """    <h2>Page not found</h2>
    <p class="lead">That page does not exist (or has moved). Try one of these:</p>
    <ul>
      <li><a href="index.html">Obs map</a>: snow depth, forecasts and avalanche danger on a map</li>
      <li><a href="finder.html">Powder Finder</a>: rank ski areas by expected snow</li>
      <li><a href="mine.html">My mountains</a>: your favorites</li>
      <li><a href="about.html">About and methods</a> · <a href="status.html">Data status</a></li>
    </ul>
    <p>Looking for a ski area? Use the search box at the top of the page.</p>"""
    return page("Page not found", "This Snow-Wx page was not found.", body, robots="noindex", base=True)


def pages() -> dict[str, str]:
    return {"sources.html": sources_page(), "disclaimer.html": disclaimer_page(), "terms.html": terms_page(), "privacy.html": privacy_page(), "404.html": not_found_page()}


def main(argv: list[str]) -> int:
    check = "--check" in argv
    stale = []
    for name, content in pages().items():
        path = WEB / name
        if check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                stale.append(name)
        else:
            path.write_text(content, encoding="utf-8", newline="\n")
            print("wrote", path.relative_to(REPO))
    if stale:
        print("stale:", ", ".join(stale))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
