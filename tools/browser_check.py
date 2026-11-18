"""Headless-browser regression checks for the site (real Chrome via the DevTools protocol).

    python tools/browser_check.py [--build build] [--only basemap,layout,...] [-v]

Serves the built site from a local port, drives headless Chrome and asserts:
  basemap   obs map: toggling a snow overlay while zooming 6 -> 14 -> 8 keeps the base map
            (tiles loaded, no provider switch, no JS errors) and the overlay element is never
            larger than the view (fix 1: an L.ImageOverlay grew to ~270,000 px at z14 and
            real GPUs dropped the layers -> grey map).
  fallback  tile errors from a non-base layer never switch the base map; a blocked base
            provider does switch (and says so).
  layout    one scrollbar: on area/finder/about pages the document scrolls and the footer
            sits at the end; on the obs map and models pages the viewport layout stays (fix 2).
  search    header search on every page: "/" focuses, results are an accessible listbox,
            Enter opens the forecast page; collapsed to an icon at 375 px (fix 3).
Needs Chrome/Chromium and the `websocket-client` package. Exit code 1 on any failure.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import functools
import http.server
import json
import os
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CANDIDATES = [os.environ.get("CHROME_PATH", ""), r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe", "google-chrome", "google-chrome-stable",
              "chromium", "chromium-browser"]


def find_chrome() -> str | None:
    for c in CANDIDATES:
        if c and (Path(c).exists() or shutil.which(c)):
            return c if Path(c).exists() else shutil.which(c)
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def serve(folder: Path):
    port = free_port()
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):
            pass
    handler = functools.partial(Quiet, directory=str(folder))
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", port), handler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()


class Browser:
    """Minimal CDP client: one headless Chrome, one page."""

    def __init__(self, chrome: str):
        import websocket
        self.port = free_port()
        self.proc = subprocess.Popen([chrome, "--headless=new", f"--remote-debugging-port={self.port}",
                                      f"--user-data-dir={tempfile.mkdtemp()}", "--no-first-run", "--hide-scrollbars",
                                      "--no-sandbox", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        tabs = None
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json"))
                break
            except Exception:
                time.sleep(0.1)
        page = next(t for t in tabs if t["type"] == "page")
        self.ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=120)
        self.n = 0
        self.errors: list[str] = []
        self.cmd("Runtime.enable")
        self.cmd("Page.enable")
        self.cmd("Network.enable")

    def cmd(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("method") == "Runtime.exceptionThrown":
                d = msg["params"]["exceptionDetails"]
                self.errors.append((d.get("exception") or {}).get("description", d.get("text", ""))[:200])
            if msg.get("id") == self.n:
                return msg.get("result", {})

    def eval(self, js):
        r = self.cmd("Runtime.evaluate", expression=js, returnByValue=True, awaitPromise=True)
        if "exceptionDetails" in r:
            raise RuntimeError(f"JS error: {json.dumps(r['exceptionDetails'])[:300]}")
        return r.get("result", {}).get("value")

    def open(self, url, width=1280, height=800, wait=6.0, block=None, zoom=1.0):
        # browser zoom z: the page sees a CSS viewport of width/z px at z device pixels per CSS px
        self.cmd("Emulation.setDeviceMetricsOverride", width=int(width / zoom), height=int(height / zoom),
                 deviceScaleFactor=zoom, mobile=width < 500)
        self.cmd("Network.setBlockedURLs", urls=block or [])
        self.cmd("Network.setCacheDisabled", cacheDisabled=bool(block))   # blocked URLs must not come from cache
        self.cmd("Page.navigate", url="about:blank")      # a hash-only change would not reload the page
        time.sleep(0.3)
        self.errors.clear()
        self.cmd("Page.navigate", url=url)
        time.sleep(wait)

    def shot(self, path):
        Path(path).write_bytes(base64.b64decode(self.cmd("Page.captureScreenshot", format="png")["data"]))

    def close(self):
        with contextlib.suppress(Exception):
            self.ws.close()
        self.proc.kill()


# ---------------------------------------------------------------- checks

class Fail(AssertionError):
    pass


def need(cond, msg):
    if not cond:
        raise Fail(msg)


STATE = """(() => { const m = window.snowwx.map, pane = m.getPane('tilePane');
  const tiles = [...pane.querySelectorAll('img.leaflet-tile-loaded')].filter(t => t.naturalWidth > 0);
  const ov = window.snowwx.overlays && window.snowwx.overlays.layer && window.snowwx.overlays.layer();
  const sz = m.getSize();
  return {zoom: m.getZoom(), loaded: tiles.length, base: window.snowwx.basemap.current(),
          note: (document.querySelector('.basemap-note') || {}).textContent || '',
          view: [sz.x, sz.y], overlay: ov && ov.elementSize ? ov.elementSize() : null}; })()"""


def check_basemap(b: Browser, base: str, log):
    b.open(f"{base}/index.html#v=depth_24h&map=6/40.6/-111.6", wait=7)
    start = b.eval(STATE)
    need(start["loaded"] > 0, f"no base tiles at start: {start}")
    for cycle in range(2):
        for step, js in (("overlay on", "(() => { const s = document.querySelector('#overlay-select'); s.value = 'depth'; s.dispatchEvent(new Event('change')); return 1; })()"),
                         ("zoom 14", "window.snowwx.map.setZoom(14)"), ("zoom 9", "window.snowwx.map.setZoom(9)"),
                         ("overlay off", "(() => { const s = document.querySelector('#overlay-select'); s.value = ''; s.dispatchEvent(new Event('change')); return 1; })()"),
                         ("zoom 6", "window.snowwx.map.setZoom(6)")):
            b.eval(js)
            time.sleep(3)
            st = b.eval(STATE)
            log(f"  basemap c{cycle} {step:11s} z{st['zoom']} tiles={st['loaded']} base={st['base']} overlay={st['overlay']}")
            need(st["loaded"] > 0, f"{step}: base map has no loaded tiles ({st})")
            need(st["base"] == start["base"] and not st["note"], f"{step}: base map switched to {st['base']} ({st['note']})")
            if st["overlay"]:
                need(st["overlay"][0] <= st["view"][0] + 2 and st["overlay"][1] <= st["view"][1] + 2,
                     f"{step}: overlay element {st['overlay']} larger than the view {st['view']}")
    # reference layer (roads, towns, peaks; basemap-ref.js): loads after first paint, draws on a GL canvas,
    # credits OpenFreeMap/OSM, hides on Topo and comes back with the relief (owner pick S10)
    for _ in range(20):
        ref = b.eval("JSON.stringify({s: window.snowwx.reference.state, gl: !!document.querySelector('.leaflet-reference-pane canvas'),"
                     " attr: document.querySelector('.leaflet-control-attribution').textContent.includes('OpenFreeMap')})")
        ref = json.loads(ref)
        if ref["s"] in ("idle", "failed"):
            break
        time.sleep(1)
    log(f"  reference layer: {ref}")
    need(ref["s"] == "idle" and ref["gl"] and ref["attr"], f"reference layer not drawn: {ref}")
    sw = json.loads(b.eval("JSON.stringify((() => { const m = window.snowwx.map, g = window.snowwx.reference.group,"
                           " i = () => document.querySelectorAll('.leaflet-control-layers-base input');"
                           " i()[1].click(); const topo = m.hasLayer(g); i()[0].click(); return {topo, relief: m.hasLayer(g)}; })())"))
    log(f"  reference with Topo/relief: {sw}")
    need(not sw["topo"] and sw["relief"], f"reference layer should hide on Topo and return on the relief: {sw}")
    need(not b.errors, f"JS errors: {b.errors}")


def check_fallback(b: Browser, base: str, log):
    # 1) errors from a non-base tile layer must not switch the base map
    b.open(f"{base}/index.html#v=depth_24h&map=8/40.6/-111.6", wait=7)
    b.eval("window.__bad = L.tileLayer('http://127.0.0.1:9/{z}/{x}/{y}.png', {maxZoom: 17}).addTo(window.snowwx.map); 1")
    for z in (9, 10, 11, 10):
        b.eval(f"window.snowwx.map.setZoom({z})")
        time.sleep(2)
    st = b.eval(STATE)
    errs = b.eval("window.__bad._tiles ? Object.keys(window.__bad._tiles).length : 0")
    log(f"  fallback: overlay-layer tiles tried={errs}, base={st['base']} note={st['note']!r}")
    need(st["base"] == "Shaded relief (USGS)" and not st["note"], f"a non-base layer's errors switched the base map: {st}")
    # 2) a failing base provider does switch
    # a view this session has not loaded yet: blocked tiles must not come from the memory cache
    b.open(f"{base}/index.html#v=depth_24h&map=10/46.85/-121.76", wait=9, block=["*USGSShadedReliefOnly*"])
    st = b.eval(STATE)
    log(f"  fallback: blocked shaded relief -> base={st['base']} tiles={st['loaded']} note={st['note']!r}")
    need(st["base"] != "Shaded relief (USGS)" and st["loaded"] > 0 and st["note"], f"no fallback when the base provider fails: {st}")


LAYOUT = """(() => { const d = document.scrollingElement, f = document.querySelector('footer');
  const inner = [...document.querySelectorAll('main, main *')].filter(e => {
      const cs = getComputedStyle(e); return /(auto|scroll)/.test(cs.overflowY) && e.scrollHeight > e.clientHeight + 2
        && !e.closest('.tbl-wrap, .leaflet-container, .search-results, .site-search') && e.clientHeight > 120; })
    .map(e => (e.id || e.className || e.tagName).toString().slice(0, 40));
  const fr = f ? f.getBoundingClientRect() : null;
  return {docScroll: d.scrollHeight > d.clientHeight + 2, docH: d.scrollHeight, viewH: innerHeight, inner,
          footerBottom: fr ? Math.round(fr.bottom + scrollY) : null}; })()"""


def check_layout(b: Browser, base: str, log):
    pages = {"area": "area.html#alta-ski-area", "finder": "finder.html", "about": "about.html", "mine": "mine.html"}
    apps = {"obs map": "index.html", "models": "models.html"}
    for width, height, zoom in ((1280, 800, 1.0), (375, 740, 1.0), (1280, 800, 0.8), (1280, 800, 1.5)):
        for name, path in pages.items():
            b.open(f"{base}/{path}", width=width, height=height, wait=5, zoom=zoom)
            st = b.eval(LAYOUT)
            log(f"  layout {name:7s} {width}px x{zoom}: doc scrolls={st['docScroll']} inner={st['inner']} footer@{st['footerBottom']} doc={st['docH']}")
            need(not st["inner"], f"{name} {width}px x{zoom}: inner scroll containers {st['inner']}")
            need(st["footerBottom"] is None or st["footerBottom"] >= st["docH"] - 4, f"{name}: footer not at the end ({st})")
        for name, path in apps.items():
            b.open(f"{base}/{path}", width=width, height=height, wait=4, zoom=zoom)
            st = b.eval(LAYOUT)
            log(f"  layout {name:7s} {width}px x{zoom}: doc scrolls={st['docScroll']}")
            if width >= 800:
                need(not st["docScroll"], f"{name} {width}px: the app page scrolls as a document ({st})")


def _type(b: Browser, text: str):
    for ch in text:
        b.cmd("Input.dispatchKeyEvent", type="keyDown", key=ch, text=ch)
        b.cmd("Input.dispatchKeyEvent", type="keyUp", key=ch)
    time.sleep(0.8)


def _key(b: Browser, key: str, code: int):
    b.cmd("Input.dispatchKeyEvent", type="rawKeyDown", key=key, windowsVirtualKeyCode=code)
    b.cmd("Input.dispatchKeyEvent", type="keyUp", key=key, windowsVirtualKeyCode=code)
    time.sleep(0.4)


def check_search(b: Browser, base: str, log):
    # desktop: header search on a document page, keyboard only ("/" to focus, type, ArrowDown, Enter)
    for page in ("finder.html", "about.html", "models.html"):
        b.open(f"{base}/{page}", wait=4)
        _key(b, "/", 191)
        need(b.eval("document.activeElement && document.activeElement.id") == "ss-input", f"{page}: '/' does not focus the search")
        _type(b, "snowbird")
        st = b.eval("""(() => { const i = document.querySelector('#ss-input'), l = document.querySelector('#ss-list');
          return {exp: i.getAttribute('aria-expanded'), act: i.getAttribute('aria-activedescendant'),
                  opts: [...l.querySelectorAll('[role=option]')].map(o => o.textContent.trim().slice(0, 40))}; })()""")
        log(f"  search {page}: {st}")
        need(st["exp"] == "true" and st["opts"] and st["act"], f"{page}: no accessible result list ({st})")
        _key(b, "ArrowDown", 40)
        _key(b, "Enter", 13)
        time.sleep(1.5)
        url = b.eval("location.href")
        log(f"  search {page}: -> {url}")
        need("area.html#" in url, f"{page}: Enter did not open a forecast page ({url})")
    # mobile: collapsed to an icon; the button opens it; SNOTEL ids match
    b.open(f"{base}/area.html#alta-ski-area", width=375, height=740, wait=4)
    vis = b.eval("(() => { const r = e => { const x = document.querySelector(e).getBoundingClientRect(); return x.width > 0 && x.height > 0; }; return [r('.ss-toggle'), r('#ss-input')]; })()")
    need(vis == [True, False], f"mobile: expected icon only, got toggle/input visible = {vis}")
    b.eval("document.querySelector('.ss-toggle').click()")
    time.sleep(0.5)
    need(b.eval("document.activeElement.id") == "ss-input", "mobile: the search button does not open/focus the box")
    _type(b, "766")
    first = b.eval("(document.querySelector('#ss-list [role=option]') || {}).textContent || ''")
    log(f"  search mobile '766': {first.strip()[:60]}")
    need("Snowbird" in first, f"mobile: SNOTEL id 766 should find Snowbird, got {first!r}")
    _key(b, "Enter", 13)
    time.sleep(1.5)
    need(b.eval("location.hash") == "#snotel-766-UT-SNTL", f"mobile: wrong page {b.eval('location.hash')}")
    # obs map panel search shares the ranking (and still flies the map)
    b.open(f"{base}/index.html", wait=6)
    b.eval("document.querySelector('#search').focus()")
    _type(b, "kslc")
    first = b.eval("(document.querySelector('#search-results li') || {}).textContent || ''")
    log(f"  obs panel search 'kslc': {first.strip()[:60]}")
    need("salt lake" in first.lower(), f"obs-map panel search broken: {first!r}")
    need(not b.errors, f"JS errors: {b.errors}")


def _draw_all(b: Browser):
    """Scroll every chart into view so the lazy charts draw."""
    b.eval("""(async () => { for (const el of document.querySelectorAll('.chart, .heat-box')) {
        el.scrollIntoView(); await new Promise(r => setTimeout(r, 700)); } return 1; })()""")
    time.sleep(1.5)


def check_panel(b: Browser, base: str, log):
    """S10 1b: on the obs map, the SNOTEL panel's lazily drawn charts never overlap Data status."""
    for w, h in ((1280, 800), (375, 740)):
        b.open(f"{base}/index.html#v=depth_24h&map=9/45.33/-121.7&s=651:OR:SNTL", width=w, height=h, wait=9)
        st = b.eval("""(() => { const a = document.getElementById('station').getBoundingClientRect(),
            c = document.getElementById('status').closest('section') || document.getElementById('status');
            const z = c.getBoundingClientRect(); return {stationBottom: Math.round(a.bottom), statusTop: Math.round(z.top),
            charts: document.querySelectorAll('#chart .js-plotly-plot').length}; })()""")
        log(f"  panel {w}px: {st}")
        need(st["charts"] == 3 and st["statusTop"] >= st["stationBottom"] - 1, f"panel overlap at {w}px: {st}")
    # S10 1a: no ridge-top wind on the forecast page
    b.open(f"{base}/area.html#timberline-lodge-ski-area", wait=5)
    _draw_all(b)
    names = b.eval("(document.getElementById('w-chart').data || []).map(t => t.name)")
    log(f"  wind chart traces: {names}")
    need(names and not any("Ridge" in (n or "") for n in names) and not b.eval("!!document.getElementById('ridge-note')"),
         f"ridge-top wind still on the forecast page: {names}")


def check_charts(b: Browser, base: str, log):
    for area in ("alta-ski-area", "timberline-lodge-ski-area"):
        b.open(f"{base}/area.html#{area}", wait=5)
        _draw_all(b)
        st = b.eval("""(async () => {
          const d = await (await fetch('data/points/%s.json')).json();
          const per = d.points.summit.periods, wetPeriods = per.filter(p => (p.pop ?? 0) >= 0.2).length;
          const sl = document.getElementById('sl-chart');
          const wetLine = sl && sl.data ? sl.data[3].y.filter(v => v !== null).length : -1;
          const sum = (sl.previousElementSibling || {}).textContent || '';
          return {wetPeriods, wetLine, sum}; })()""" % area)
        log(f"  charts {area}: snow level wet periods={st['wetPeriods']} wet line points={st['wetLine']} | {st['sum'][:90]}")
        if st["wetPeriods"]:
            need(st["wetLine"] > 0, f"{area}: {st['wetPeriods']} wet periods but the snow-level line is dry everywhere")
            need("Little precipitation" not in st["sum"], f"{area}: summary says little precipitation: {st['sum']}")
        # S11: "Snowfall by day" = one bar per 12Z-12Z day from NBM's native 24-h p25/p75 (never summed),
        # labelled "low–high", no expected tick, NWS-colour legend under the chart
        st = b.eval("""(async () => {
          const d = await (await fetch('data/points/%s.json')).json();
          const days = d.points.summit.days || [];
          const el = document.getElementById('period-chart');
          const tr = el && el.data ? el.data : [];
          const ticks = tr.filter(t => t.marker && t.marker.symbol === 'line-ew').length;
          const bars = tr[0] ? tr[0].x.length : 0;
          const bad = days.filter(x => x.snow_p25 !== null && x.range_window === null).length;
          const legend = !!el.parentElement.querySelector('.snow-legend');
          const labels = [...el.querySelectorAll('.annotation-text')].map(a => a.textContent).filter(t => /″/.test(t));
          return {days: days.length, bars, ticks, bad, legend, labels: labels.slice(0, 11)}; })()""" % area)
        log(f"  charts {area}: snowfall by day {st}")
        need(st["days"] >= 8 and st["bars"] == st["days"] and st["ticks"] == 0 and st["legend"] and st["bad"] == 0,
             f"{area}: daily snowfall chart wrong: {st}")
        need(len(st["labels"]) == st["days"], f"{area}: every day needs a low–high label: {st['labels']}")
        # dev13 B1 (W3): the rules-based summary is at the top of the forecast card, hedged and labelled
        sm = b.eval("(() => ({tag: (document.querySelector('.summary-tag') || {}).textContent || '', text: (document.querySelector('.summary-line') || {}).textContent || '',"
                    " note: (document.querySelector('.summary-note') || {}).textContent || ''}))()")
        log(f"  charts {area}: summary {sm['tag']!r}")
        need(sm["tag"] and "rules, not a person" in sm["note"], f"{area}: daily summary card missing: {sm}")
        # dev13 item 4: ONE snow-ratio + powder-quality panel (>= 260 px), no strip, powder bands + labels, p50 line only when snowing
        pq = b.eval("""(() => { const el = document.getElementById('slr-chart'); const L = el.layout || {};
          const anns = (L.annotations || []).map(a => a.text || '');
          return {h: el.getBoundingClientRect().height, strip: !!document.getElementById('snow-type-strip'),
                  bands: (L.shapes || []).filter(s => s.fillcolor && s.xref === 'paper').length,
                  labels: ['Dense', 'Medium', 'Blower'].every(n => anns.some(t => t.includes(n))),
                  slider: !!(L.xaxis && L.xaxis.rangeslider && L.xaxis.rangeslider.visible),
                  summary: (el.previousElementSibling || {}).textContent || '', table: !!document.querySelector('#slr-chart + .chart-table')}; })()""")
        log(f"  charts {area}: powder panel {pq}")
        need(pq["h"] >= 260 and not pq["strip"] and pq["bands"] == 3 and pq["labels"] and not pq["slider"] and pq["table"],
             f"{area}: combined snow-ratio/powder panel: {pq}")
        need("heuristic" in pq["summary"] or "No snow" in pq["summary"], f"{area}: powder summary must say heuristic: {pq['summary'][:100]}")
        # dev13 item 3: the heat table lists NBM's native >=2" row for 24 h (and not for 72 h)
        rows = b.eval("""(async () => { const out = {}; for (const w of ['24h', '72h']) {
          const btn = document.querySelector(`#ex-win [data-w="${w}"]`); if (!btn) continue; btn.click(); await new Promise(r => setTimeout(r, 700));
          out[w] = [...document.querySelectorAll('#ex-chart tbody th')].map(t => t.textContent.trim()); }
          document.querySelector('#ex-win [data-w="24h"]')?.click(); return out; })()""")
        log(f"  charts {area}: heat-table rows {rows}")
        if rows.get("24h"):
            need(rows["24h"][0] == '2"' and '2"' not in rows.get("72h", []), f"{area}: 2-inch row: {rows}")
        # Nov 16: no 7/10-day ranges on the tiles; the partial first day is labelled in the legend and summary
        t7 = b.eval("""(() => { const tiles = [...document.querySelectorAll('.tiles .tile')].map(t => [t.querySelector('.label').textContent, t.querySelector('.rng').textContent]);
          const leg = document.querySelector('.snow-legend'); const sum = document.getElementById('period-chart').previousElementSibling;
          return {tiles, partialLegend: !!(leg && /partial day — expected amount, no range/.test(leg.getAttribute('aria-label') || '')),
                  sum: sum ? sum.textContent : ''}; })()""")
        log(f"  charts {area}: tiles {t7['tiles']} partial legend {t7['partialLegend']}")
        need(all("expected total only" in r if ("7 days" in l or "10 days" in l) else ("–" in r or "expected total only" in r) for l, r in t7["tiles"]),
             f"{area}: 7/10-day tiles still show a range: {t7['tiles']}")
        need(all("10–90" not in r for l, r in t7["tiles"] if "7 days" in l or "10 days" in l), f"{area}: long-window tile shows a 10–90 range")
        # S11 step 4: accumulated = expected running total by day, no probability bars; ends at the 10-day total
        acc = b.eval("""(async () => {
          const d = await (await fetch('data/points/%s.json')).json();
          const el = document.getElementById('acc-chart'); const t = el && el.data ? el.data : [];
          const T = d.points.summit.totals; const tot = (T['10d'] || T['7d'] || T['72h'] || {}).snow_in;
          const y = t[0] ? t[0].y : [];
          return {traces: t.length, shapes: (el.layout.shapes || []).length, last: y[y.length - 1], tot,
                  mono: y.every((v, i) => i === 0 || v >= y[i - 1] - 0.05)}; })()""" % area)
        log(f"  charts {area}: accumulated {acc}")
        need(acc["traces"] == 1 and acc["shapes"] == 0 and acc["mono"] and abs((acc["last"] or 0) - (acc["tot"] or 0)) <= 0.11,
             f"{area}: accumulated snow chart: {acc}")
        nws = b.eval("""(async () => { const btn = document.querySelector('[data-src=nws]'); if (!btn) return null;
          btn.click(); await new Promise(r => setTimeout(r, 2500));
          const sec = document.getElementById('period-chart').parentElement;
          const out = {toggles: sec.querySelectorAll('.chart-table').length, legends: sec.querySelectorAll('.snow-legend').length};
          document.querySelector('[data-src=nbm]').click(); await new Promise(r => setTimeout(r, 1500));
          out.back = sec.querySelectorAll('.chart-table').length; return out; })()""")
        log(f"  charts {area}: NBM -> NWS -> NBM table toggles/legends {nws}")
        need(nws is None or (nws["toggles"] == 1 and nws["legends"] == 1 and nws["back"] == 1), f"{area}: duplicate toggles/legends: {nws}")
        # fix 6: end labels (right of the plot) never overlap; fix 7: SNOTEL panels start at 0
        st = b.eval("""(() => {
          const overlaps = [];
          for (const id of ['t-chart', 'w-chart']) {
            const el = document.getElementById(id); if (!el) continue;
            const plotR = el.querySelector('.nsewdrag') ? el.querySelector('.nsewdrag').getBoundingClientRect().right : 0;
            const boxes = [...el.querySelectorAll('.annotation')].map(a => a.getBoundingClientRect())
              .filter(r => r.left >= plotR - 2 && r.width > 0);
            for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
              const a = boxes[i], c = boxes[j];
              if (a.left < c.right && c.left < a.right && a.top < c.bottom - 1 && c.top < a.bottom - 1) overlaps.push(id);
            }
          }
          const r0 = (id) => { const el = document.getElementById(id); return el && el.layout ? el.layout.yaxis.range[0] : null; };
          return {overlaps, depth0: r0('obs-chart'), swe0: r0('obs-swe')}; })()""")
        log(f"  charts {area}: end-label overlaps={st['overlaps']} depth axis from {st['depth0']} SWE axis from {st['swe0']}")
        need(not st["overlaps"], f"{area}: overlapping end labels in {st['overlaps']}")
        need(st["depth0"] == 0 and st["swe0"] == 0, f"{area}: SNOTEL depth/SWE axes must start at 0 ({st})")
        need(not b.errors, f"{area}: JS errors {b.errors}")


def check_snoparks(b: Browser, base: str, log):
    """M4.5: a Sno-Park page, the Finder Type filter, the obs-map layer and search."""
    rec = json.loads((Path(REPO / "data" / "rec_points.json")).read_text(encoding="utf-8"))["areas"]
    sp = next((a for a in rec if a["source"] == "usfs-edw" and a.get("avalanche")), rec[0])
    b.open(f"{base}/area.html#{sp['id']}", wait=6)
    _draw_all(b)
    st = b.eval("""(() => ({ seg: [...document.querySelectorAll('#elev-seg button')].map(x => x.textContent.trim()),
        facts: !!document.querySelector('.rec-key'), avy: !!document.querySelector('.rec-key .rk-avy'),
        depth: (document.getElementById('rk-depth') || {}).textContent, wc: (document.getElementById('rk-wc') || {}).textContent,
        temp: document.getElementById('t-chart') && document.getElementById('t-chart').data ? document.getElementById('t-chart').data.map(t => t.name) : [] }))()""")
    log(f"  snopark page {sp['id']}: {st}")
    need(st["seg"] and st["seg"][0].startswith("Trailhead") and any(x.startswith("High terrain") for x in st["seg"]), f"labels: {st['seg']}")
    need(st["facts"] and st["avy"] and st["wc"] not in (None, "", "–"), f"key facts missing: {st}")
    need("Wind chill" in st["temp"], f"no wind chill line: {st['temp']}")
    need(not b.errors, f"JS errors: {b.errors}")
    for t, expect_sp in (("snopark", True), ("ski", False)):
        b.open(f"{base}/finder.html#t={t}&m=amount&w=72h&e=summit", wait=6)
        st = b.eval("""(() => ({ rows: document.querySelectorAll('#rows .frow').length, sp: document.querySelectorAll('#rows .frow .kind-sp').length,
            elev: [...document.querySelectorAll('#elev button')].map(x => x.textContent.trim()),
            ridge: document.querySelectorAll('[data-label="Ridge"]').length + (document.querySelector('.fhead').textContent.includes('Ridge') ? 1 : 0) }))()""")
        log(f"  finder t={t}: {st}")
        need(st["ridge"] == 0, f"Powder Finder still shows ridge-top wind (owner S10): {st}")
        need(st["rows"] > 0 and ((st["sp"] == st["rows"]) if expect_sp else (st["sp"] == 0)), f"finder t={t}: {st}")
    need(st["elev"] == ["Summit", "Base"], f"finder elevation labels {st['elev']}")
    b.open(f"{base}/index.html", wait=7)
    ref = b.eval("window.snowwx.reference.state")
    if ref == "failed":                    # headless Chrome can lose WebGL after many page loads in one session: one retry
        b.open(f"{base}/index.html", wait=9)
        ref = b.eval("window.snowwx.reference.state")
    log("  obs map reference layer without interaction: " + str(ref) + " " + str(b.eval("window.snowwx.reference.error || ''")))
    need(ref in ("ready", "idle"), f"roads/towns layer did not load on its own: {ref}")
    n = b.eval("(() => { const g = window.snowwx.map && document.querySelector('.leaflet-control-layers'); return [...document.querySelectorAll('.leaflet-control-layers-overlays label')].map(l => l.textContent.trim()).join('|'); })()")
    log(f"  obs map layers: {n}")
    need("Sno-Parks" in n, f"no Sno-Parks layer in the layer control: {n}")
    b.eval("document.querySelector('#search').focus()")
    _type(b, sp["name"][:8].lower())
    first = b.eval("[...document.querySelectorAll('#search-results li')].map(x => x.textContent).join(' | ')")
    log(f"  obs search '{sp['name'][:8]}': {first[:120]}")
    need(sp["name"].split()[0].lower() in first.lower(), f"search does not find {sp['name']}: {first[:200]}")
    need(not b.errors, f"JS errors: {b.errors}")


def check_forecast_overlays(b: Browser, base: str, log):
    """Track 2 item 7: NBM forecast layers in a "Forecast" group, view-sized, with hover values."""
    b.open(f"{base}/index.html#v=depth_24h&map=7/46.0/-121.0", wait=7)
    groups = b.eval("[...document.querySelectorAll('#overlay-select optgroup')].map(g => g.label + ':' + g.children.length)")
    log(f"  overlay groups: {groups}")
    need(any(g.startswith("Forecast:") and int(g.split(":")[1]) >= 6 for g in groups), f"no Forecast group: {groups}")
    for lid in ("nbm72", "nbmp24_4"):
        b.eval(f"(() => {{ const s = document.querySelector('#overlay-select'); s.value = '{lid}'; s.dispatchEvent(new Event('change')); return 1; }})()")
        time.sleep(3)
        st = b.eval("""(() => { const m = window.snowwx.map; m.fire('mousemove', {latlng: L.latLng(46.85, -121.76)});
          const o = window.snowwx.overlays.layer(), sz = m.getSize();
          return {size: o ? o.elementSize() : null, view: [sz.x, sz.y], read: document.querySelector('#overlay-readout').textContent,
                  meta: (document.querySelector('.overlay-meta .hint') || {}).textContent}; })()""")
        log(f"  {lid}: {st}")
        need(st["size"] and st["size"][0] <= st["view"][0] + 2, f"{lid}: overlay not drawn view-sized ({st})")
        need(any(ch.isdigit() for ch in st["read"]) and "run" in (st["meta"] or ""), f"{lid}: no value / no run info ({st})")
        # dry grid cells stay clear (owner S9): alpha 0 where the value is below the threshold
        clear = b.eval("""(() => { const m = window.snowwx.map, o = window.snowwx.overlays.layer(), c = o._canvas;
          const ctx = c.getContext('2d'), dpr = c.width / m.getSize().x; let n = 0, clear = 0;
          for (let x = 5; x < m.getSize().x; x += 40) for (let y = 5; y < m.getSize().y; y += 40) {
            const ll = m.containerPointToLatLng([x, y]);
            const a = ctx.getImageData(Math.floor(x * dpr), Math.floor(y * dpr), 1, 1).data[3]; n++; if (a === 0) clear++; }
          return [clear, n]; })()""")
        log(f"  {lid}: clear pixels {clear[0]}/{clear[1]}")
        need(clear[0] > 0, f"{lid}: no transparent (dry) pixels at all")
    # S11: snowfall overlays use the shared NWS snowfall colours + legend (one definition in colors.js)
    leg = b.eval("""(() => { const s = document.querySelector('#overlay-select'); s.value = 'nbm72'; s.dispatchEvent(new Event('change'));
      const l = document.querySelector('#overlays .snow-legend');
      return {legend: !!l, first: l ? l.querySelector('.sw').textContent : null, nws: SNOWFALL.colors[7] === '#fffe95' && SNOWFALL.bins[6] === 6}; })()""")
    log(f"  snowfall overlay legend: {leg}")
    need(leg["legend"] and leg["first"] == "0.1" and leg["nws"], f"snowfall overlay legend / NWS colours: {leg}")
    need(not b.errors, f"JS errors: {b.errors}")


def check_mine(b: Browser, base: str, log):
    """Track 1 item 4: "My mountains" empty state, favorite cards, removing a favorite."""
    b.open(f"{base}/mine.html", wait=4)
    st = b.eval("(() => ({empty: !!document.querySelector('.mine-empty'), text: (document.querySelector('.mine-empty h3') || {}).textContent}))()")
    log(f"  mine empty: {st}")
    need(st["empty"] and "No favorites" in (st["text"] or ""), f"no empty state: {st}")
    b.eval("localStorage.setItem('snowwx.favorites', JSON.stringify(['alta-ski-area','sp-dutchman-flat-snowpark','snotel-917-MT-SNTL'])); location.reload(); 1")
    time.sleep(5)
    st = b.eval("""(() => ({cards: document.querySelectorAll('.mcard[data-id]').length,
        vals: [...document.querySelectorAll('.mcard[data-id]')].map(c => c.querySelectorAll('.mgrid b').length + '/' + c.querySelectorAll('.pchip').length)}))()""")
    log(f"  mine cards: {st}")
    need(st["cards"] == 3 and all(v.startswith("2/") for v in st["vals"]), f"cards: {st}")
    b.eval("document.querySelector('.mcard .unfav').click(); 1")
    time.sleep(2)
    n = b.eval("JSON.parse(localStorage.getItem('snowwx.favorites')).length + ':' + document.querySelectorAll('.mcard[data-id]').length")
    log(f"  after removing one: {n}")
    need(n == "2:2", f"remove failed: {n}")
    # landing banner (owner S9): favorites + direct visit -> banner; "Always" -> redirect; off again on mine.html
    b.open(f"{base}/index.html", wait=6)
    st = b.eval("(() => ({banner: !!document.querySelector('.home-banner'), url: location.pathname}))()")
    log(f"  map with favorites, direct visit: {st}")
    need(st["banner"], f"no My mountains banner: {st}")
    b.open(f"{base}/index.html#map=8/40.6/-111.6", wait=5)
    need(not b.eval("!!document.querySelector('.home-banner')"), "banner shown on a shared link")
    b.open(f"{base}/index.html", wait=6)
    b.eval("document.querySelector('.home-banner [data-act=always]').click(); 1")
    time.sleep(3)
    need(b.eval("location.pathname").endswith("mine.html"), "Always did not open My mountains")
    b.open(f"{base}/index.html", wait=4)
    url = b.eval("location.pathname")
    log(f"  direct visit with 'always': {url}")
    need(url.endswith("mine.html"), f"no redirect with the preference set ({url})")
    b.eval("(() => { const c = document.getElementById('home-pref'); c.checked = false; c.dispatchEvent(new Event('change')); return 1; })()")
    b.open(f"{base}/index.html", wait=6)
    need(b.eval("location.pathname").endswith("index.html") and b.eval("!!document.querySelector('.home-banner')"),
         "turning the preference off did not restore the map + banner")
    b.eval("localStorage.removeItem('snowwx.favorites'); localStorage.removeItem('snowwx.home'); 1")
    need(not b.errors, f"JS errors: {b.errors}")


base_dir_holder: dict = {}


def check_snotel_outage(b: Browser, base: str, log):
    """fix-snotel: stale SNOTEL is labelled with its age and greyed; unavailable shows "unavailable since";
    neither breaks the map or the area page. Edits build/data temporarily and restores it."""
    data = Path(base_dir_holder["path"]) / "data"
    meta_p, gj_p = data / "meta.json", data / "snotel.geojson"
    saved = {p: p.read_bytes() for p in (meta_p, gj_p) if p.exists()}
    try:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        gj = json.loads(gj_p.read_text(encoding="utf-8"))
        meta["sources"]["snotel"] = {"ok": False, "error": "x", "stale": True, "age_h": 13.2, "observed_through": "2026-11-16T11:00Z",
                                     "count": len(gj["features"]), "consecutive_failures": 2, "outage_since": "2026-11-16T12:17:00Z"}
        for f in gj["features"]:
            f["properties"]["stale"] = True; f["properties"]["age_h"] = 13.2
        meta_p.write_text(json.dumps(meta), encoding="utf-8"); gj_p.write_text(json.dumps(gj), encoding="utf-8")
        b.open(f"{base}/index.html#v=depth_24h&map=6/41/-111", wait=7)
        st = b.eval("({note: document.getElementById('snotel-note').textContent, hidden: document.getElementById('snotel-note').hidden, ready: window.snowwx.ready,"
                    " status: document.getElementById('status').textContent})")
        log(f"  stale: {st}")
        need(not st["hidden"] and "13 h old" in st["note"] and st["ready"] and "stale" in st["status"], f"stale SNOTEL not labelled: {st}")
        need(not b.errors, f"JS errors (stale): {b.errors}")
        b.open(f"{base}/area.html#alta-ski-area", wait=6)
        txt = b.eval("document.getElementById('obs')?.textContent || ''")
        need("13 h old" in txt, f"area page does not label stale SNOTEL: {txt[:140]}")
        meta["sources"]["snotel"] = {"ok": False, "error": "x", "unavailable": True, "last_observed": "2026-11-16T11:00Z"}
        meta_p.write_text(json.dumps(meta), encoding="utf-8"); gj_p.unlink()
        (data / "snotel").rename(data / "snotel_bak")           # what the pipeline does when the data are too old
        b.open(f"{base}/index.html#v=depth_24h&map=6/41/-111", wait=7)
        st = b.eval("({note: document.getElementById('snotel-note').textContent, ready: window.snowwx.ready})")
        log(f"  unavailable: {st}")
        need("unavailable since" in st["note"] and st["ready"], f"unavailable SNOTEL not labelled: {st}")
        need(not b.errors, f"JS errors (unavailable): {b.errors}")
        b.open(f"{base}/area.html#alta-ski-area", wait=6)
        txt = b.eval("document.getElementById('obs')?.textContent || ''")
        log(f"  area page obs: {txt[:100]}")
        need("unavailable" in txt, f"area page does not say SNOTEL is unavailable: {txt[:120]}")
    finally:
        if (data / "snotel_bak").exists():
            (data / "snotel_bak").rename(data / "snotel")
        for p, raw in saved.items():
            p.write_bytes(raw)


def check_finder_filters(b: Browser, base: str, log):
    """dev13 item 1: linked state/region menus with counts, deterministic sort, bounds fit, hash restore."""
    b.open(f"{base}/finder.html#t=ski&m=amount&w=72h&e=summit&sort=name", wait=8)
    MENU = """(() => { const o = (id) => [...document.getElementById(id).options].map(x => [x.value, x.textContent, x.disabled]);
      const rows = [...document.querySelectorAll('#rows .frow .who a')].map(a => a.textContent);
      return {state: o('state'), region: o('region'), rows, hash: location.hash}; })()"""
    st0 = b.eval(MENU)
    n_all = len(st0["rows"])
    log(f"  finder: {n_all} rows; states {len(st0['state'])} regions {len(st0['region'])}; first state options {st0['state'][:3]}")
    need(n_all > 100 and st0["state"][0][1].startswith("All (") and st0["region"][0][1].startswith("All ("), f"menus: {st0['state'][:2]}")
    # choose a state: the region list narrows, counts add up, empty regions are disabled
    b.eval("(() => { const s = document.getElementById('state'); s.value = 'UT'; s.dispatchEvent(new Event('change')); })()")
    time.sleep(1.2)
    st1 = b.eval(MENU)
    ut_total = int(st1["state"][0][1].split("(")[1].rstrip(")"))
    regs = [(v, int(t.rsplit("(", 1)[1].rstrip(")")), d) for v, t, d in st1["region"][1:]]
    log(f"  finder UT: rows {len(st1['rows'])}, regions with places {[r for r in regs if r[1]][:5]}")
    need(len(st1["rows"]) == sum(c for _, c, _ in regs) and len(st1["rows"]) < n_all, f"UT rows {len(st1['rows'])} vs region counts {regs}")
    need(all(d for v, c, d in regs if c == 0 and v != ""), "empty regions must be disabled")
    need("st=UT" in st1["hash"], f"hash: {st1['hash']}")
    # sort stable: same relative order of the places that stay, on sort=name; ties by name
    names_all = st0["rows"]
    need(st1["rows"] == [n for n in names_all if n in set(st1["rows"])], "selecting a state must not reorder the list")
    # region -> the state list narrows to states that have it; Tahoe-like overlaps show both states
    b.eval("(() => { const s = document.getElementById('state'); s.value = ''; s.dispatchEvent(new Event('change')); })()")
    time.sleep(0.8)
    multi = b.eval("""(() => { const r = [...document.getElementById('region').options].map(o => o.value).filter(Boolean);
      for (const name of r) { const s = document.getElementById('region'); s.value = name; s.dispatchEvent(new Event('change'));
        const st = [...document.getElementById('state').options].filter(o => o.value && !o.disabled).map(o => o.value);
        if (st.length > 1) return {region: name, states: st, rows: document.querySelectorAll('#rows .frow').length}; } return null; })()""")
    log(f"  finder multi-state region: {multi}")
    need(multi is None or len(multi["states"]) > 1, f"overlap region: {multi}")
    # regions north to south
    order = b.eval("""(() => [...document.getElementById('region').options].map(o => o.value).filter(Boolean))()""")
    log(f"  finder region order (first 6): {order[:6]}")
    # sort direction: reverse keeps the same set, reverses the order; the hash carries it
    b.eval("(() => { const r = document.getElementById('region'); r.value = ''; r.dispatchEvent(new Event('change')); })()")
    time.sleep(0.6)
    a1 = b.eval("[...document.querySelectorAll('#rows .frow .who a')].map(a => a.textContent)")
    b.eval("document.getElementById('sort-dir').click()")
    time.sleep(0.8)
    a2 = b.eval("({rows: [...document.querySelectorAll('#rows .frow .who a')].map(a => a.textContent), hash: location.hash})")
    need(a2["rows"] == a1[::-1] and "dir=desc" in a2["hash"], f"sort direction toggle: {a2['hash']}")
    # hash restores state, region and sort
    b.open(f"{base}/finder.html#t=ski&m=amount&w=72h&e=summit&sort=name&dir=desc&st=CO", wait=8)
    rs = b.eval("({state: document.getElementById('state').value, rows: [...document.querySelectorAll('#rows .frow .who a')].map(a => a.textContent), dir: document.getElementById('sort-dir').textContent})")
    log(f"  finder hash restore: state {rs['state']} dir {rs['dir']} rows {len(rs['rows'])}")
    need(rs["state"] == "CO" and rs["dir"] == "↓" and rs["rows"] == sorted(rs["rows"], reverse=True), "hash did not restore state/direction")
    # the map fits the filtered places (Colorado only)
    bounds = b.eval("""(async () => { await new Promise(r => setTimeout(r, 2500));
      const m = window.snowwx && window.snowwx.map; if (!m) return null; const c = m.getCenter(); return {lat: c.lat, lon: c.lng, z: m.getZoom()}; })()""")
    log(f"  finder map after state=CO: {bounds}")
    need(bounds is None or (36 < bounds["lat"] < 42 and -110 < bounds["lon"] < -104 and bounds["z"] >= 6), f"map did not fit Colorado: {bounds}")
    need(not b.errors, f"JS errors: {b.errors}")


def check_hazards(b: Browser, base: str, log):
    """dev13 item 2: layer defaults, memory, hash override, reset, NWS hazards layer + never-blank fallback."""
    LAYERS = """(() => Object.fromEntries([...document.querySelectorAll('.leaflet-control-layers-overlays label')]
      .map(l => [l.textContent.trim(), l.querySelector('input').checked])))()"""
    b.open(f"{base}/about.html", wait=2)
    b.eval("localStorage.removeItem('snowwx.layers'); localStorage.removeItem('snowwx.layers.v'); 1")
    b.open(f"{base}/index.html#map=6/42/-112", wait=10)
    d = b.eval(LAYERS)
    log(f"  defaults: {d}")
    on = {k for k, v in d.items() if v}
    need(on == {"Roads, towns & peaks", "Ski areas", "NWS winter hazards"}, f"first-load layer defaults wrong (owner Nov 17): {d}")
    # nothing may be DRAWN from an unchecked layer: items of the canvas groups, and the Leaflet layers, must equal the checked set
    drawn = b.eval("""(() => { const p = window.snowwx.points, items = p._items(), g = {};
        for (const it of items) g[it.group] = (g[it.group] || 0) + 1;
        return {groups: g, layers: window.snowwx.currentLayers(), minor: items.filter(i => i.group === 'ski' && i.area && !i.area.major).length,
                major: items.filter(i => i.group === 'ski' && i.area && i.area.major).length}; })()""")
    log(f"  drawn: {drawn}")
    need(set(drawn["groups"]) <= {"ski"} and drawn["groups"].get("ski", 0) > 0, f"canvas draws unchecked groups (ASOS/SNOTEL/Sno-Park): {drawn}")
    need(set(drawn["layers"]) == {"ref", "ski", "haz"}, f"Leaflet layer set differs from the checked set: {drawn}")
    need(drawn["minor"] == 0 and drawn["major"] > 0, f"low zoom must show only major ski areas: {drawn}")
    # a saved choice from before the defaults changed is ignored once (version key), then remembered again
    b.open(f"{base}/about.html", wait=2)
    b.eval("localStorage.setItem('snowwx.layers', JSON.stringify(['ref','ski','sp','avy','haz'])); localStorage.removeItem('snowwx.layers.v'); 1")
    b.open(f"{base}/index.html#map=6/42/-112", wait=9)
    need({k for k, v in b.eval(LAYERS).items() if v} == {"Roads, towns & peaks", "Ski areas", "NWS winter hazards"}, "old saved layers must not override the new defaults")
    b.eval("localStorage.removeItem('snowwx.layers'); localStorage.removeItem('snowwx.layers.v'); 1")
    b.open(f"{base}/index.html#map=6/42/-112", wait=9)
    hz = b.eval("(() => ({status: window.snowwx.hazards.state.status, count: window.snowwx.hazards.state.count, panel: document.getElementById('hazards').textContent.trim(),"
                " hidden: document.getElementById('hazards').hidden}))()")
    log(f"  hazards: {hz['status']} {hz['count']} | {hz['panel'][:110]!r}")
    need(not hz["hidden"] and hz["status"] in ("ok", "fallback") and len(hz["panel"]) > 40, f"hazards panel is blank: {hz}")
    # memory: turn SNOTEL on, reload: still on; hash carries it
    b.eval("document.querySelectorAll('.leaflet-control-layers-overlays label input')[5].click(); 1")
    time.sleep(0.8)
    st = b.eval("({ls: localStorage.getItem('snowwx.layers'), hash: location.hash})")
    need("snotel" in (st["ls"] or "") and "ly=" in st["hash"], f"layer choice not remembered: {st}")
    b.open(f"{base}/index.html#map=6/42/-112", wait=9)
    need(b.eval(LAYERS).get("SNOTEL") is True, "SNOTEL choice not restored from localStorage")
    # explicit hash beats memory
    b.open(f"{base}/index.html#map=6/42/-112&ly=ref,ski", wait=8)
    d2 = b.eval(LAYERS)
    need(d2.get("Ski areas") is True and d2.get("SNOTEL") is False and d2.get("NWS winter hazards") is False, f"hash override: {d2}")
    # reset to defaults
    b.eval("document.getElementById('reset-layers').click(); 1")
    time.sleep(1.0)
    d3 = b.eval(LAYERS)
    st = b.eval("({ls: localStorage.getItem('snowwx.layers'), hash: location.hash})")
    need(d3.get("NWS winter hazards") is True and d3.get("SNOTEL") is False and st["ls"] is None and "ly=" not in st["hash"], f"reset: {d3} {st}")
    # never a silent blank: service blocked -> our alerts index fallback notice
    b.open(f"{base}/index.html#map=6/42/-112", wait=8, block=["*mapservices.weather.noaa.gov*"])
    fb = b.eval("(async () => { await new Promise(r => setTimeout(r, 2500)); return {status: window.snowwx.hazards.state.status, panel: document.getElementById('hazards').textContent.trim()}; })()")
    log(f"  blocked service: {fb['status']} | {fb['panel'][:120]!r}")
    need(fb["status"] == "fallback" and "not showing" in fb["panel"], f"no visible fallback when the NWS service fails: {fb}")
    need(not b.errors, f"JS errors: {b.errors}")


CHECKS = {"basemap": check_basemap, "fallback": check_fallback, "layout": check_layout, "search": check_search, "charts": check_charts, "snoparks": check_snoparks, "forecast": check_forecast_overlays, "mine": check_mine, "panel": check_panel, "snotel": check_snotel_outage, "finder": check_finder_filters, "hazards": check_hazards}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", default=str(REPO / "build"))
    ap.add_argument("--only", default=",".join(CHECKS))
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    chrome = find_chrome()
    if not chrome:
        print("Chrome not found (set CHROME_PATH)")
        return 2
    log = print if args.verbose else (lambda *a: None)
    failed = []
    base_dir_holder["path"] = args.build
    with serve(Path(args.build)) as base:
        b = Browser(chrome)
        try:
            for name in [x for x in args.only.split(",") if x]:
                try:
                    CHECKS[name](b, base, log)
                    print(f"ok    {name}")
                except Fail as e:
                    failed.append(name)
                    print(f"FAIL  {name}: {e}")
        finally:
            b.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
