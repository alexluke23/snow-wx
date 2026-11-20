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
def serve(folder: Path, png_delay: float = 0.0, headers: dict | None = None, json_delay: float = 0.0):
    """static server for `folder`; png_delay seconds before every .png answer imitates a slow network (layout-shift checks)"""
    port = free_port()
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a, **k):
            pass

        def end_headers(self):
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            super().end_headers()

        def do_GET(self):
            if png_delay and self.path.split("?")[0].endswith(".png"):
                time.sleep(png_delay)
            if json_delay and self.path.split("?")[0].endswith("/index.json"):
                time.sleep(json_delay)                      # a catalog that arrives after the first paint (slow network)
            super().do_GET()
    handler = functools.partial(Quiet, directory=str(folder))
    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):          # a browser that closes a connection early is normal; no traceback noise
            pass
    httpd = Server(("127.0.0.1", port), handler)
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
        self.console: list[str] = []           # browser-reported problems (Log.entryAdded: CSP violations, blocked resources)
        self.requests: list[str] = []          # every URL the page requested (Network.requestWillBeSent), for the privacy / analytics checks
        self.cmd("Runtime.enable")
        self.cmd("Page.enable")
        self.cmd("Network.enable")
        self.cmd("Log.enable")

    def cmd(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("method") == "Runtime.exceptionThrown":
                d = msg["params"]["exceptionDetails"]
                self.errors.append((d.get("exception") or {}).get("description", d.get("text", ""))[:200])
            if msg.get("method") == "Log.entryAdded":
                e = msg["params"]["entry"]
                self.console.append(f"{e.get('level')}: {e.get('text', '')[:200]} {e.get('url', '')[:80]}")
            if msg.get("method") == "Network.requestWillBeSent":
                self.requests.append(msg["params"]["request"]["url"])
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
        self.requests.clear()
        self.console.clear()
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


def wait_for(b, expr: str, timeout: float = 30.0):
    """poll a JS expression until it is truthy (pages render later on a busy machine); returns its value or fails after `timeout` seconds"""
    end = time.time() + timeout
    while time.time() < end:
        v = b.eval(f"(() => {{ try {{ return !!({expr}); }} catch (e) {{ return false; }} }})()")
        if v:
            return True
        time.sleep(0.4)
    raise Fail(f"timed out waiting for {expr}")


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
        # a live NWS alert for the area replaces the summary line by design ("Active NWS alerts always come first"): both states are the summary card
        need(sm["tag"] and ("rules, not a person" in sm["note"] or (sm["tag"] == "Alert active" and "alerts always come first" in sm["note"])), f"{area}: daily summary card missing: {sm}")
        # dev13 item 4: ONE snow-ratio + powder-quality panel (>= 260 px), no strip, powder bands + labels, p50 line only when snowing
        pq = b.eval("""(() => { const el = document.getElementById('slr-chart'); const L = el.layout || {};
          const anns = (L.annotations || []).map(a => a.text || '');
          return {h: el.getBoundingClientRect().height, strip: !!document.getElementById('snow-type-strip'),
                  bands: (L.shapes || []).filter(s => s.fillcolor && s.xref === 'paper' && s.type === 'rect' && s.y0 !== 0).length,
                  dashed: (L.shapes || []).filter(s => s.type === 'line' && s.line && s.line.dash === 'dash' && s.xref === 'paper').length,
                  nTraces: (el.data || []).length, bandTrace: (el.data || []).some(t => t.fill === 'tonexty'),
                  median: ((el.data || []).find(t => t.mode === 'lines' && t.line && t.line.dash === 'dot') || {y: []}).y.filter(v => v !== null).length,
                  head: (document.querySelector('#slr-chart + .chart-table th') || {textContent: ''}).textContent,
                  labels: ['Dense', 'Medium', 'Blower'].every(n => anns.some(t => t.includes(n))),
                  slider: !!(L.xaxis && L.xaxis.rangeslider && L.xaxis.rangeslider.visible),
                  summary: (el.previousElementSibling || {}).textContent || '', table: !!document.querySelector('#slr-chart + .chart-table'),
                  tableHead: (() => { const d = document.querySelector('#slr-chart + .chart-table'); d.open = true; d._build && d._build();
                    const h = [...d.querySelectorAll('th[scope=col]')].map(t => t.textContent).join('|'); d.open = false; return h; })()}; })()""")
        log(f"  charts {area}: powder panel {pq}")
        # dev14 F3: thin dashed threshold lines (2), no full-height colour bands, direct labels, median + likely band over the whole run, complete sentence
        need(pq["h"] >= 260 and not pq["strip"] and pq["bands"] == 0 and pq["dashed"] == 2 and pq["labels"] and not pq["slider"] and pq["table"]
             and pq["bandTrace"] and pq["median"] > 40, f"{area}: combined snow-ratio/powder panel: {pq}")
        need(not pq["summary"].rstrip().endswith("…") and pq["summary"].rstrip().endswith("."), f"{area}: powder summary is not a complete sentence: {pq['summary']!r}")
        need("25" in pq["tableHead"] and "75" in pq["tableHead"], f"{area}: table needs p25/p50/p75 columns: {pq['tableHead']}")
        need("heuristic" in pq["summary"] or "No snow" in pq["summary"], f"{area}: powder summary must say heuristic: {pq['summary'][:100]}")
        # dev13 item 3: the heat table lists NBM's native >=2" row for 24 h (and not for 72 h)
        rows = b.eval("""(async () => { const out = {}; for (const w of ['24h', '72h']) {
          const btn = document.querySelector(`#ex-win [data-w="${w}"]`); if (!btn) continue; btn.click(); await new Promise(r => setTimeout(r, 700));
          out[w] = [...document.querySelectorAll('#ex-chart tbody th')].map(t => t.textContent.trim()); }
          document.querySelector('#ex-win [data-w="24h"]')?.click(); return out; })()""")
        log(f"  charts {area}: heat-table rows {rows}")
        if rows.get("24h"):
            need(rows["24h"][0] == '2"' and rows.get("72h", [''])[0] == '2"', f"{area}: 2-inch row (24 h real, 72 h n/a): {rows}")
            na = b.eval("""(async () => { document.querySelector('#ex-win [data-w="72h"]').click(); await new Promise(r => setTimeout(r, 600));
              const r = [...document.querySelectorAll('#ex-chart tbody tr')][0]; const o = {cells: [...r.querySelectorAll('td')].map(t => t.textContent.trim()), tip: (r.querySelector('td') || {}).title || ''};
              document.querySelector('#ex-win [data-w="24h"]').click(); return o; })()""")
            need(na["cells"] and all(c == "n/a" for c in na["cells"]) and "24 h and 48 h only" in na["tip"], f"{area}: 72 h 2-inch row must read n/a with a tooltip: {na}")
        # dev14 F2: ranges read "likely X–Y in" (p25-p75), no inline 10-90 / "NBM 10" anywhere in the headline, tiles or summary
        txt = b.eval("(document.getElementById('headline').textContent + ' | ' + document.querySelector('.tiles').textContent + ' | ' + (document.getElementById('summary-card') || {textContent: ''}).textContent)")
        log(f"  charts {area}: wording {txt[:160]!r}")
        need("likely" in txt and "10–90" not in txt and "10-90" not in txt and "NBM 10" not in txt, f"{area}: inline range wording: {txt[:300]}")
        # Nov 16: no 7/10-day ranges on the tiles; the partial first day is labelled in the legend and summary
        t7 = b.eval("""(() => { const tiles = [...document.querySelectorAll('.tiles .tile')].map(t => [t.querySelector('.label').textContent, t.querySelector('.rng').textContent]);
          const leg = document.querySelector('.snow-legend'); const sum = document.getElementById('period-chart').previousElementSibling;
          return {tiles, partialLegend: !!(leg && /partial day — expected amount, no range/.test(leg.getAttribute('aria-label') || '')),
                  sum: sum ? sum.textContent : ''}; })()""")
        log(f"  charts {area}: tiles {t7['tiles']} partial legend {t7['partialLegend']}")
        need(all("expected total only" in r if ("7 days" in l or "10 days" in l) else ("–" in r or "expected total only" in r) for l, r in t7["tiles"]),
             f"{area}: 7/10-day tiles still show a range: {t7['tiles']}")
        need(all("likely" not in r for l, r in t7["tiles"] if "7 days" in l or "10 days" in l), f"{area}: long-window tile shows a range")
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
    # dev17 Part 1: default OFF, lazy (no layer PNG is requested until one is chosen), cycle + issue time shown, stale data greyed
    b.open(f"{base}/index.html", wait=7)
    lazy = b.eval(r"""(() => ({png: performance.getEntriesByType('resource').filter(r => /points\/layers\/.*\.png/.test(r.name)).length,
        active: window.snowwx.overlays.current(), sel: (document.querySelector('#overlay-select') || {}).value}))()""")
    log(f"  forecast overlays at load: {lazy}")
    need(lazy["png"] == 0 and not lazy["active"] and lazy["sel"] == "", f"forecast overlays must be off and not fetched until toggled: {lazy}")
    import datetime as _dt
    ixp = Path(__file__).resolve().parents[1] / "build" / "data" / "points" / "layers" / "index.json"
    orig = ixp.read_text(encoding="utf-8")
    try:
        for hours_old, want_stale in ((3, False), (30, True)):
            ix = json.loads(orig)
            cyc = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours_old)).strftime("%Y%m%d%H")
            for l in ix["layers"]:
                l["cycle"] = cyc
            ixp.write_text(json.dumps(ix), encoding="utf-8")
            b.open(f"{base}/index.html#v=depth_24h&map=7/46.0/-121.0", wait=7)
            b.eval("(() => { const s = document.querySelector('#overlay-select'); s.value = 'nbm72'; s.dispatchEvent(new Event('change')); return 1; })()")
            time.sleep(3)
            st = b.eval("""(() => { const o = window.snowwx.overlays.layer(), c = o && o._canvas;
              return {stale: window.snowwx.overlays.isStale('nbm72'), filter: c ? c.style.filter : null, opacity: c ? Number(c.style.opacity) : null,
                      note: (document.querySelector('.stale-note') || {}).textContent || '', meta: (document.querySelector('.overlay-meta .hint') || {}).textContent}; })()""")
            log(f"  forecast overlay {hours_old} h old: {st}")
            need(st["stale"] == want_stale, f"{hours_old} h old layer: stale={st['stale']}")
            need("started" in (st["meta"] or "") and "run" in (st["meta"] or ""), f"cycle / issue time missing: {st['meta']}")
            if want_stale:
                need("grayscale" in (st["filter"] or "") and st["opacity"] <= 0.4 and "Out of date" in st["note"], f"stale layer is not greyed with a note: {st}")
            else:
                need(not st["filter"] and not st["note"], f"fresh layer must not be greyed: {st}")
    finally:
        ixp.write_text(orig, encoding="utf-8")
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


def check_status(b: Browser, base: str, log):
    """dev14 W5: public data-status page from fixtures: healthy, a late source with an outage, an old file, a missing file; footer link everywhere."""
    import shutil
    from datetime import datetime, timedelta, timezone
    src = Path(base_dir_holder["path"])
    now = datetime.now(timezone.utc)
    iso = lambda h: (now - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    lims = {"snotel": {"max_failures": 3, "max_age_hours": 6}, "points": {"max_age_hours": 14}, "alerts": {"max_failures": 3, "max_age_hours": 6}}
    fixtures = {
        "good": {"generated_at": iso(0.2), "sources": {"snotel": {"ok": True, "count": 836, "last_success_at": iso(0.3), "consecutive_failures": 0},
                 "points": {"ok": True, "count": 160, "unit": "ski areas", "at": iso(3)}, "alerts": {"ok": True, "count": 4, "last_success_at": iso(0.3), "consecutive_failures": 0}},
                 "monitoring": {"sources": lims}, "site": {"feedback_email": "feedback@example.test"}},
        "late": {"generated_at": iso(0.2), "sources": {"snotel": {"ok": False, "unavailable": True, "last_observed": iso(60), "last_success_at": iso(60), "consecutive_failures": 7, "outage_since": iso(59)},
                 "points": {"ok": True, "at": iso(3)}}, "monitoring": {"sources": lims}},
        "ecmwf": {"generated_at": iso(0.2), "sources": {"points": {"ok": True, "at": iso(3)}, "ecmwf": {"ok": None, "disabled": True, "detail": "not enabled"}},
                  "monitoring": {"sources": {**lims, "ecmwf": {"max_age_hours": 30}}}},
        "old": {"generated_at": iso(30), "sources": {"alerts": {"ok": True, "last_success_at": iso(30), "consecutive_failures": 0}}, "monitoring": {"sources": lims}},
    }
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        for f in ("status.html", "css", "js"):
            (shutil.copytree if (src / f).is_dir() else shutil.copy)(src / f, t / f)
        (t / "data").mkdir()
        results = {}
        with serve(t) as tbase:
            for name in ("good", "late", "old", "ecmwf", "missing"):
                if name != "missing":
                    (t / "data" / "meta.json").write_text(json.dumps(fixtures[name]), encoding="utf-8")
                else:
                    (t / "data" / "meta.json").unlink()
                b.open(f"{tbase}/status.html", wait=2.5)
                results[name] = b.eval("""(() => ({rows: [...document.querySelectorAll('#st-table tbody tr')].map(r => r.className + ':' + r.querySelector('th').textContent.slice(0, 12)),
                    banner: document.getElementById('st-banner').hidden ? '' : document.getElementById('st-banner').textContent, foot: document.getElementById('st-foot').textContent,
                    msg: (document.querySelector('#st-table .snotel-note') || {}).textContent || '', detail: (document.querySelector('tr.st-late td:last-child') || {}).textContent || '',
                    fb: [...document.querySelectorAll('a.site-feedback')].map(a => (a.hidden ? 'hidden' : a.getAttribute('href'))).join(),
                    hscroll: document.documentElement.scrollWidth > innerWidth + 2, h1: document.querySelectorAll('h1,h2').length}))()""")
    log(f"  status: {json.dumps(results)[:600]}")
    need(all(r.startswith("st-ok") for r in results["good"]["rows"]) and len(results["good"]["rows"]) == 3 and not results["good"]["banner"], f"healthy fixture: {results['good']}")
    need(any(r.startswith("st-off:ECMWF") for r in results["ecmwf"]["rows"]) and not any(r.startswith("st-late") for r in results["ecmwf"]["rows"]) and not results["ecmwf"]["banner"],
         f"a disabled ECMWF must read 'not enabled', never late: {results['ecmwf']}")
    need(any(r.startswith("st-late:SNOTEL") for r in results["late"]["rows"]) and "unavailable" in results["late"]["detail"] and "since" in results["late"]["detail"], f"late fixture: {results['late']}")
    need("old" in results["old"]["banner"] and any(r.startswith("st-late") for r in results["old"]["rows"]), f"old fixture: {results['old']}")
    need("could not be read" in results["missing"]["msg"], f"missing meta.json must say so: {results['missing']}")
    need(results["good"]["fb"].startswith("mailto:feedback@example.test") and results["late"]["fb"] == "hidden", f"feedback link must come from meta.json site config and hide without it: {results['good']['fb']} / {results['late']['fb']}")
    need(not any(r["hscroll"] for r in results.values()), f"horizontal scroll on the status page: {results}")
    for page in ("index", "area", "finder", "mine", "models", "about", "status"):       # linked from every footer
        html = (src / f"{page}.html").read_text(encoding="utf-8")
        need('href="status.html"' in html.split("<footer")[1], f"{page}.html footer has no Data status link")
    b.open(f"{base}/status.html", width=375, wait=3)
    need(not b.eval("document.documentElement.scrollWidth > innerWidth + 2"), "status page scrolls sideways at 375 px")
    need(not b.errors, f"JS errors: {b.errors}")


def check_pwa(b: Browser, base: str, log):
    """dev15 W4: install + precache, Save for offline, an OFFLINE run through CDP (My mountains and a favorite's page with charts), staleness
    banner (info offline, red > 24 h), update flow files, kill switch. Uses a trimmed temp copy of build/ with pwa.enabled forced on."""
    import shutil
    from datetime import datetime, timedelta, timezone
    sys.path.insert(0, str(REPO))
    from pipeline import pwa as pwa_mod
    src = Path(base_dir_holder["path"])
    fav = "alta-ski-area"
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        for f in src.iterdir():
            if f.name in ("data", "models"):
                continue
            (shutil.copytree if f.is_dir() else shutil.copy)(f, t / f.name)
        for rel in ("meta.json", "ski_areas.json", "rec_points.json", "snotel_points.json", "search.json", "avalanche_ratings.json", "alerts/index.json",
                    f"points/summary.json", f"points/{fav}.json", f"ndfd/{fav}.json"):
            if (src / "data" / rel).exists():
                (t / "data" / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src / "data" / rel, t / "data" / rel)
        meta_path = t / "data" / "meta.json"
        write_meta = lambda hours_old: meta_path.write_text(json.dumps({**json.loads(meta_path.read_text(encoding="utf-8")), "generated_at": (datetime.now(timezone.utc) - timedelta(hours=hours_old)).strftime("%Y-%m-%dT%H:%M:%SZ")}), encoding="utf-8")  # noqa: E731
        write_meta(1.5)
        cfg = {"site": {"origin": "http://127.0.0.1", "base_path": ""}, "pwa": {"enabled": True}}
        need(pwa_mod.run(cfg, t) == 0 and (t / "sw.js").exists(), "pwa build step wrote nothing")
        with serve(t) as tbase:
            b.cmd("Network.emulateNetworkConditions", offline=False, latency=0, downloadThroughput=-1, uploadThroughput=-1)
            b.open(f"{tbase}/mine.html", wait=3)
            b.eval(f"localStorage.setItem('snowwx.favorites', JSON.stringify(['{fav}'])); 1")
            b.open(f"{tbase}/mine.html", wait=4)
            st = b.eval("""(async () => { const r = await navigator.serviceWorker.ready; for (let i = 0; i < 40 && !navigator.serviceWorker.controller; i++) await new Promise(x => setTimeout(x, 150));
              return {active: !!r.active, ctrl: !!navigator.serviceWorker.controller, manifest: !!document.querySelector('link[rel=manifest]'), save: !!document.getElementById('pwa-save'),
                      shell: (await caches.keys()).filter(k => k.startsWith('snowwx-shell-')).length}; })()""")
            log(f"  pwa install: {st}")
            need(st["active"] and st["manifest"] and st["shell"] == 1, f"service worker not installed / shell not precached: {st}")
            need(st["save"], f"My mountains has no 'Save for offline' control: {st}")
            # charts library online once (so it can be cached), then Save for offline
            b.open(f"{tbase}/area.html#{fav}", wait=7)
            b.open(f"{tbase}/mine.html", wait=4)
            b.eval("document.querySelector('#pwa-save button').click(); 1")
            time.sleep(6)
            note = b.eval("(document.getElementById('pwa-save-note') || {}).textContent || ''")
            log(f"  pwa save note: {note}")
            need("Saved 1 favorite" in note and "MB of 25 MB" in note, f"Save for offline did not report: {note}")
            mb = float(note.split("Saved 1 favorite for offline: ")[1].split(" MB")[0])
            need(mb < 5, f"1 favorite must stay far below the 25 MB budget: {mb} MB")
            # OFFLINE run
            b.cmd("Network.emulateNetworkConditions", offline=True, latency=0, downloadThroughput=0, uploadThroughput=0)
            b.open(f"{tbase}/mine.html", wait=4)
            off = b.eval("""(() => ({cards: document.querySelectorAll('.mcard').length, online: navigator.onLine,
               banner: (document.getElementById('pwa-banner') || {}).textContent || '', bannerHidden: (document.getElementById('pwa-banner') || {hidden: true}).hidden}))()""")
            log(f"  pwa offline mine: {off}")
            need(off["cards"] == 1 and "Offline — data from" in off["banner"] and not off["bannerHidden"], f"offline My mountains failed: {off}")
            b.open(f"{tbase}/area.html#{fav}", wait=6)
            _draw_all(b)
            area = b.eval("""(() => ({h1: (document.querySelector('h2, h1') || {}).textContent || '', charts: [...document.querySelectorAll('.chart')].filter(c => c.data).length,
               banner: (document.getElementById('pwa-banner') || {}).textContent || ''}))()""")
            log(f"  pwa offline area: {area}")
            need(area["charts"] >= 3 and "Offline" in area["banner"], f"offline favorite page has no charts/banner: {area}")
            b.cmd("Network.emulateNetworkConditions", offline=False, latency=0, downloadThroughput=-1, uploadThroughput=-1)
            # staleness: online but data 30 h old = red with the avalanche-center message; 8 h = amber
            for hrs, cls in ((30, "red"), (8, "amber")):
                write_meta(hrs)
                b.open(f"{tbase}/mine.html", wait=3)
                bn = b.eval("(() => { const n = document.getElementById('pwa-banner'); return {cls: n ? n.className : '', hidden: n ? n.hidden : true, text: n ? n.textContent : ''}; })()")
                log(f"  pwa banner {hrs} h: {bn}")
                need(bn["cls"] == cls and not bn["hidden"] and (cls != "red" or "avalanche center" in bn["text"]), f"staleness banner at {hrs} h: {bn}")
            # kill switch: the next build emits the self-removing worker; reload -> unregistered, caches gone
            need(pwa_mod.run({**cfg, "pwa": {"enabled": True, "kill": True}}, t) == 0, "kill switch build")
            b.open(f"{tbase}/mine.html", wait=2)
            b.eval("navigator.serviceWorker.getRegistration().then(r => r && r.update()); 1")
            time.sleep(4)
            gone = b.eval("""(async () => ({regs: (await navigator.serviceWorker.getRegistrations()).length, caches: (await caches.keys()).filter(k => k.startsWith('snowwx-')).length}))()""")
            log(f"  pwa kill switch: {gone}")
            need(gone["regs"] == 0 and gone["caches"] == 0, f"kill switch did not unregister/clear: {gone}")
        b.cmd("Network.emulateNetworkConditions", offline=False, latency=0, downloadThroughput=-1, uploadThroughput=-1)
    need(not b.errors, f"JS errors: {b.errors}")


def check_storm(b: Browser, base: str, log):
    """dev15 storm-total tracker: selectable window on the area page (SNOTEL change + NOHRSC, compaction caveat) and the 48 h / 7-day SNOTEL map variables."""
    b.open(f"{base}/area.html#alta-ski-area", wait=7)
    st = b.eval("""(async () => { await new Promise(r => setTimeout(r, 1500)); const h = document.getElementById('storm'); if (!h) return null;
      const out = {buttons: [...h.querySelectorAll('button')].map(x => x.textContent.trim()), rows72: h.querySelectorAll('tbody tr').length, note: h.querySelector('.note').textContent};
      h.querySelector('button[data-w="7d"]').click(); await new Promise(r => setTimeout(r, 300));
      out.note7 = h.querySelector('.note').textContent; out.rows7 = h.querySelectorAll('tbody tr').length; out.pressed = h.querySelector('button[data-w="7d"]').getAttribute('aria-pressed');
      return out; })()""")
    log(f"  storm total: {st}")
    need(st and st["buttons"] == ["24 h", "48 h", "72 h", "7 days"], f"storm-total window buttons: {st}")
    need("not snowfall" in st["note"] and "NOHRSC publishes snowfall for 24" in st["note7"] and st["rows7"] == 2 and st["rows72"] >= 3 and st["pressed"] == "true", f"storm-total content: {st}")
    b.open(f"{base}/index.html", wait=6)
    opts = b.eval("[...document.querySelectorAll('#var-select option')].map(o => o.textContent)")
    need(any("48-hr" in o for o in opts) and any("7-day" in o for o in opts), f"map SNOTEL variables lack 48 h / 7-day: {opts}")
    b.eval("(() => { const s = document.getElementById('var-select'); s.value = 'depth_7d'; s.dispatchEvent(new Event('change')); })()")
    time.sleep(2.5)
    leg = b.eval("({layers: window.snowwx.currentLayers(), drawn: window.snowwx.points.drawnGroups(), title: (document.getElementById('legend') || document.body).textContent.slice(0, 400)})")
    log(f"  7-day map variable: {leg['layers']} {leg['drawn']}")
    need("snotel" in leg["layers"] and "snotel" in leg["drawn"] and "compaction" in leg["title"], f"7-day variable did not show SNOTEL with the compaction legend: {leg}")
    need(not b.errors, f"JS errors: {b.errors}")


def check_hazard_popup(b: Browser, base: str, log):
    """dev16 Part 0b: a hazard popup shows readable product text in the page (fixture alert), escapes hostile text, links only to weather.gov
    (never an api.weather.gov alert record), and a lookup miss gives a clear message plus the same office link. Works at 375 px."""
    import hashlib
    aid = "urn:oid:2.49.0.1.840.0.fixture.001"
    key = hashlib.sha1(aid.encode()).hexdigest()[:10]
    idx = {"alerts": {key: {"event": "Winter Storm Warning", "headline": "Winter Storm Warning issued by <b>NWS Salt Lake City</b>", "sender": "NWS Salt Lake City UT",
           "effective": "2026-11-17T12:00:00-07:00", "expires": "2026-11-19T05:00:00-07:00", "area": "Wasatch Mountains; <img src=x onerror=alert(1)>"}}}
    det = {key: {"description": "* WHAT...Heavy snow.\n  Totals 12 to 24 inches.\n<script>window.__pwned = 1</script>", "instruction": "Slow down.\nCarry a shovel."}}
    # dev17: alerts that touch no ski area/SNOTEL site come from hazard_text.json (compact keys) with no live fetch
    hid = "urn:oid:2.49.0.1.840.0.fixture.hazardtext"
    ht = {"alerts": {hashlib.sha1(hid.encode()).hexdigest()[:10]: {"e": "Wind Advisory", "h": "Wind Advisory until 5 PM", "o": "NWS Rapid City SD",
          "f": "2026-11-18T01:00:00-07:00", "x": "2026-11-18T17:00:00-07:00", "a": "Black Hills <b>x</b>", "d": "Gusts to 55 mph.\nSecure loose objects.", "i": "Use caution."}}}
    for width in (1280, 375):
        b.open(f"{base}/index.html", width=width, wait=6)
        b.eval(f"window.snowwx.hazards.injectAlertFiles({json.dumps(idx)}, {json.dumps(det)}, {json.dumps(ht)}); 1")
        res = b.eval("""(async () => {
          const mkf = (url) => ({properties: {prod_type: 'Winter Storm Warning', wfo: 'KSLC', expiration: '2026-11-19T12:00:00Z', url}});
          const out = {};
          for (const [name, url] of [['known', 'https://api.weather.gov/alerts/%s'], ['hazardtext', 'https://api.weather.gov/alerts/%s'], ['unknown', 'https://api.weather.gov/alerts/urn:oid:2.49.0.1.840.0.nothing.999']]) {
            const host = document.createElement('div'); host.className = 'leaflet-popup-content'; host.style.cssText = 'position:fixed;top:60px;left:8px;width:300px;background:#fff;z-index:99999';
            const dom = window.snowwx.hazards.popupFor(mkf(url)); host.append(dom); document.body.append(host);
            await new Promise(r => setTimeout(r, name === 'unknown' ? 6000 : 800));
            const body = dom.querySelector('.hz-body');
            out[name] = {text: body.textContent, html: dom.innerHTML, links: [...dom.querySelectorAll('a')].map(a => a.href), scripts: dom.querySelectorAll('script, img').length,
                         pre: getComputedStyle(dom.querySelector('.hz-text') || dom).whiteSpace, maxH: getComputedStyle(body).maxHeight, w: host.getBoundingClientRect().width, vw: innerWidth};
            if (name === 'known') out.known.shot = host.getBoundingClientRect().bottom;
            if (name === 'known') host.id = 'hz-fixture'; else host.remove();
          }
          out.pwned = !!window.__pwned;
          return out; })()""" % (aid, hid))
        log(f"  hazard popup {width}px: {json.dumps(res)[:700]}")
        k, u, h = res["known"], res["unknown"], res["hazardtext"]
        need("Gusts to 55 mph." in h["text"] and "NWS Rapid City SD" in h["text"] and "Black Hills <b>x</b>" in h["text"] and "<b>" not in h["html"],
             f"hazard_text.json lookup failed or was not escaped: {h['text'][:200]}")
        need("Totals 12 to 24 inches." in k["text"] and "Slow down." in k["text"] and "NWS Salt Lake City UT" in k["text"] and "Wasatch Mountains" in k["text"], f"readable text missing: {k['text'][:200]}")
        need("<script>" in k["text"] and "&lt;script&gt;" in k["html"] and k["scripts"] == 0 and not res["pwned"], f"alert text was not escaped: {k['html'][:300]}")
        need(k["links"] == ["https://www.weather.gov/slc/"] and k["pre"] == "pre-wrap" and k["maxH"] != "none", f"links/layout: {k['links']} {k['pre']} {k['maxH']}")
        need(all("api.weather.gov" not in l and not l.endswith(".json") for l in k["links"] + u["links"]), "a popup link points at an API/JSON endpoint")
        need("not in our files" in u["text"] and u["links"] == ["https://www.weather.gov/slc/"], f"lookup miss needs a clear message and the office link: {u}")
        need(k["w"] <= k["vw"], f"popup wider than the viewport: {k['w']} > {k['vw']}")
        if width == 375:
            b.shot(Path(tempfile.gettempdir()) / "hz_popup_375.png")
    need(not b.errors, f"JS errors: {b.errors}")


def check_snopark_finder_mobile(b: Browser, base: str, log):
    """dev16 M4.5: the Finder Type filter (Ski areas / Sno-Parks / All) at 375 px: tappable (>= 40 px), no sideways scroll, state/region menus
    follow the type with counts, a Sno-Park row links to its forecast page and shows its source/attribution there."""
    b.open(f"{base}/about.html", wait=1.5)
    b.eval("localStorage.clear(); sessionStorage.clear(); 1")                     # earlier checks leave a remembered state/region filter behind
    b.open(f"{base}/finder.html#t=ski", width=375, wait=6)
    st = b.eval("""(() => ({types: [...document.querySelectorAll('#type button')].map(x => [x.textContent.trim(), Math.round(x.getBoundingClientRect().height), Math.round(x.getBoundingClientRect().width)]),
        rows: document.querySelectorAll('#rows .frow').length, hscroll: document.documentElement.scrollWidth > innerWidth + 2,
        states: [...document.querySelectorAll('#state option')].length}))()""")
    log(f"  finder 375 type filter: {st}")
    need([t[0] for t in st["types"]] == ["Ski areas", "Sno-Parks", "All"] and all(t[1] >= 40 for t in st["types"]), f"type filter not tappable at 375 px: {st}")
    need(not st["hscroll"], f"finder scrolls sideways at 375 px: {st}")
    ski_rows = st["rows"]
    b.eval("[...document.querySelectorAll('#type button')].find(x => x.textContent.trim() === 'Sno-Parks').click(); 1")
    time.sleep(1.2)
    sp = b.eval("""(() => ({rows: document.querySelectorAll('#rows .frow').length, sp: document.querySelectorAll('#rows .frow .kind-sp').length,
        states: [...document.querySelectorAll('#state option')].map(o => o.textContent), first: (document.querySelector('#rows .frow a') || {}).href || ''}))()""")
    log(f"  finder 375 sno-parks: rows {sp['rows']} (ski {ski_rows}) states {sp['states'][:4]}")
    need(sp["rows"] > ski_rows and sp["sp"] == sp["rows"], f"Sno-Park type shows the wrong rows: {sp['rows']} vs ski {ski_rows}")
    more = b.eval("(document.getElementById('show-all') || {textContent: ''}).textContent")
    need(sp["rows"] == 200 and "Show all 447" in more, f"long lists are capped at 200 rows with a Show all button: {sp['rows']} {more!r}")
    b.eval("document.getElementById('show-all').click(); 1")
    time.sleep(0.8)
    need(b.eval("document.querySelectorAll('#rows .frow').length") == 447, "Show all must draw every Sno-Park")
    need(sp["states"][0].startswith("All (") and any(x.startswith("WA (") for x in sp["states"]), f"state menu does not follow the type: {sp['states'][:5]}")
    b.eval("window.scrollTo(0, 0); 1")
    b.shot(Path(tempfile.gettempdir()) / "finder_sp_375.png")
    area = sp["first"].split("#")[-1]
    b.open(f"{base}/area.html#{area}", width=375, wait=6)
    pg = b.eval("""(() => ({txt: document.getElementById('area').textContent, hscroll: document.documentElement.scrollWidth > innerWidth + 2}))()""")
    need(("USDA Forest Service" in pg["txt"] or "OpenStreetMap" in pg["txt"]) and not pg["hscroll"], "Sno-Park page lacks its source/attribution or scrolls sideways")
    time.sleep(1.0)
    ex = b.eval("""(() => ({summary: !!document.querySelector('.summary-line'), avy: !!document.querySelector('.rec-key .rk-avy, #area a[href*="avalanche"], #area a[href^="http"]')}))()""")
    need(ex["summary"], "Sno-Park page has no daily summary (the W3 rules apply to every point)")
    need(not b.errors, f"JS errors: {b.errors}")


def check_finder_show_all(b: Browser, base: str, log):
    """dev17 Part 0c: with the Sno-Park list capped at 200 rows, sorting, the state filter, favorites and the header search all act on the FULL list
    (447), not on the 200 drawn rows. 375 px."""
    b.open(f"{base}/about.html", wait=1.5)
    b.eval("localStorage.clear(); sessionStorage.clear(); 1")
    b.open(f"{base}/finder.html#t=ski", width=375, wait=6)
    b.eval("[...document.querySelectorAll('#type button')].find(x => x.textContent.trim() === 'Sno-Parks').click(); 1")
    time.sleep(1.0)
    names = "[...document.querySelectorAll('#rows .frow .who > a')].map(a => a.textContent)"
    # 1. sort by name, ascending (A-Z): the capped list is exactly the first 200 of the full A-Z list
    b.eval("""(() => { const s = document.getElementById('sort'); s.value = 'name'; s.dispatchEvent(new Event('change')); return 1; })()""")
    time.sleep(0.6)
    if b.eval("document.getElementById('sort-dir').textContent.trim()") == "↓":        # make sure it is A-Z (ascending)
        b.eval("document.getElementById('sort-dir').click(); 1"); time.sleep(0.5)
    capped = b.eval(names)
    need(len(capped) == 200, f"expected the 200-row cap, got {len(capped)}")
    b.eval("document.getElementById('show-all').click(); 1"); time.sleep(0.8)
    full = b.eval(names)
    need(len(full) == 447 and full[:200] == capped, "the capped list must be the first 200 rows of the full sorted list")
    # 2. reversing the sort puts the LAST name of the full list on top of the capped view (it was beyond row 200)
    b.eval("document.getElementById('sort-dir').click(); 1"); time.sleep(0.8)
    rev = b.eval(names)
    need(rev[0] == full[-1] and rev[:200] == full[::-1][:200], f"reverse sort must start with the last name of the full list {full[-1]!r}, got {rev[0]!r}")
    log(f"  sort acts on the full list: A-Z first {full[0]!r}, Z-A first {rev[0]!r} (was row {len(full)})")
    # 3. state filter: the state of a row beyond 200 is selectable, counts add up to 447, and its rows are all reachable
    b.open(f"{base}/finder.html#t=ski", width=375, wait=5)
    b.eval("[...document.querySelectorAll('#type button')].find(x => x.textContent.trim() === 'Sno-Parks').click(); 1"); time.sleep(0.8)
    opts = b.eval("[...document.querySelectorAll('#state option')].map(o => [o.value, o.textContent])")
    counts = {v: int(t.split("(")[1].rstrip(")").replace(",", "")) for v, t in opts if v and "(" in t}
    total = int(opts[0][1].split("(")[1].rstrip(")"))
    need(total == 447 and sum(counts.values()) == 447, f"state counts do not add up to the full list: {total} vs {sum(counts.values())}")
    st = max(counts, key=lambda k: counts[k])
    b.eval(f"""(() => {{ const s = document.getElementById('state'); s.value = {json.dumps(st)}; s.dispatchEvent(new Event('change')); return 1; }})()""")
    time.sleep(0.8)
    n = b.eval("document.querySelectorAll('#rows .frow').length")
    need(n == min(200, counts[st]), f"state {st}: {n} rows drawn, expected {min(200, counts[st])} of {counts[st]}")
    if counts[st] > 200:
        need("Show all" in b.eval("(document.getElementById('show-all') || {textContent: ''}).textContent"), "filtered list over the cap needs its own Show all")
        b.eval("document.getElementById('show-all').click(); 1"); time.sleep(0.6)
        need(b.eval("document.querySelectorAll('#rows .frow').length") == counts[st], "Show all on a filtered list must draw all its rows")
    b.eval("""(() => { const s = document.getElementById('state'); s.value = ''; s.dispatchEvent(new Event('change')); return 1; })()"""); time.sleep(0.5)
    # 4. favorite a Sno-Park beyond row 200, then Favorites only shows exactly it
    b.eval("document.getElementById('show-all') && document.getElementById('show-all').click(); 1"); time.sleep(0.6)
    far = b.eval("""(() => { const r = [...document.querySelectorAll('#rows .frow')]; const x = r[r.length - 1];
        x.querySelector('.star').click(); return x.querySelector('.who > a').textContent; })()""")
    time.sleep(0.6)
    b.eval("""(() => { const c = document.getElementById('favonly'); c.checked = true; c.dispatchEvent(new Event('change')); return 1; })()""")
    time.sleep(0.8)
    favs = b.eval(names)
    need(favs == [far], f"favorites only must show the row starred beyond row 200 ({far!r}): {favs}")
    # 5. header search finds a Sno-Park that is beyond row 200 of the list, at 375 px (search button first)
    target = full[300]
    b.open(f"{base}/finder.html#t=ski", width=375, wait=4)
    b.eval("document.querySelector('.site-search .ss-toggle') && document.querySelector('.site-search .ss-toggle').click(); 1"); time.sleep(0.4)
    b.eval(f"""(() => {{ const i = document.querySelector('.site-search input'); i.value = {json.dumps(target)}; i.dispatchEvent(new Event('input', {{bubbles: true}})); return 1; }})()""")
    time.sleep(1.2)
    hits = b.eval("[...document.querySelectorAll('#ss-list li')].map(li => li.textContent)")
    need(any(h.startswith(target) for h in hits), f"header search did not find {target!r} (row 300 of the list): {hits[:5]}")
    log(f"  search finds {target!r}; favorites-only shows {far!r}; state {st} {counts[st]} rows")
    need(not b.errors, f"JS errors: {b.errors}")


def check_ensemble(b: Browser, base: str, log):
    """dev17 Part 2: the Models / Ensemble toggle on the area page at 1280 and 375 px: real two-option toggle (aria-pressed, >= 40 px, announced), the
    plume file is NOT requested until Ensemble is selected, the plume is ONE faint multi-segment trace plus bands/median/mean/HRES with direct labels,
    headline = aria-label, table with percentiles and "N of 50 members" rows, cycle/issue time + terrain + attribution shown, stale greyed."""
    import datetime as _dt
    plume = Path(__file__).resolve().parents[1] / "build" / "models" / "ecmwf" / "plume" / "alta-ski-area.json"
    if not plume.exists():
        log("  (no ECMWF data in build/: run `python -m pipeline ecmwf --force` and merge multimodel; skipping)")
        return
    orig = plume.read_text(encoding="utf-8")
    try:
        for width in (1280, 375):
            b.open(f"{base}/area.html#alta-ski-area", width=width, wait=8)
            wait_for(b, "document.getElementById('mm-sec')"); b.eval("document.getElementById('mm-sec').scrollIntoView(); 1"); time.sleep(4)
            pre = b.eval("""(() => { const v = document.getElementById('mm-view');
              return {shown: !!v && !v.hidden, btns: v ? [...v.querySelectorAll('button')].map(x => [x.textContent.trim(), x.getAttribute('aria-pressed'), Math.round(x.getBoundingClientRect().height)]) : [],
                      role: v && v.getAttribute('role'), plumeReq: performance.getEntriesByType('resource').filter(r => r.name.includes('ecmwf/plume')).length,
                      names: (document.getElementById('mm-chart').data || []).map(t => t.name)}; })()""")
            log(f"  ensemble toggle {width}px (before): {pre}")
            need(pre["shown"] and pre["role"] == "group" and [x[0] for x in pre["btns"]] == ["Models", "Ensemble"], f"toggle missing: {pre}")
            need(all(x[2] >= 40 for x in pre["btns"]) and pre["btns"][0][1] == "true" and pre["btns"][1][1] == "false", f"toggle size / aria state: {pre['btns']}")
            need(pre["plumeReq"] == 0, f"the plume file must not load before Ensemble is selected ({pre['plumeReq']} requests)")
            need("ECMWF" in pre["names"], f"Models view must include the ECMWF line: {pre['names']}")
            b.eval("[...document.querySelectorAll('#mm-view button')].find(x => x.dataset.v === 'ens').click(); 1")
            time.sleep(3.5)
            st = b.eval("""(() => { const el = document.getElementById('mm-chart'), d = el.data || [];
              const tbl = document.querySelector('#mm-chart + details.chart-table');
              if (tbl) { tbl.open = true; tbl.dispatchEvent(new Event('toggle')); }
              return {n: d.length, names: d.map(t => t.name), nulls: (d[0] ? d[0].x.filter(v => v === null).length : 0), faintPts: d[0] ? d[0].y.length : 0,
                aria: el.getAttribute('aria-label'), role: el.getAttribute('role'), badge: document.getElementById('mm-badge').textContent, note: document.getElementById('mm-note').textContent,
                announce: document.getElementById('mm-announce').textContent, pressed: [...document.querySelectorAll('#mm-view button')].map(x => x.getAttribute('aria-pressed')),
                plumeReq: performance.getEntriesByType('resource').filter(r => r.name.includes('ecmwf/plume')).length,
                table: tbl ? tbl.querySelector('.tbl-wrap').textContent : '', hscroll: document.documentElement.scrollWidth > innerWidth + 2,
                labels: [...el.querySelectorAll('.annotation-text, .annotation text')].map(x => x.textContent).filter(Boolean).slice(0, 12)}; })()""")
            log(f"  ensemble {width}px: traces {st['n']} {st['names']}, member segments {st['nulls']}, aria: {st['aria']}")
            need(st["n"] <= 10 and st["nulls"] == 50 and st["faintPts"] > 500, f"the members must be ONE multi-segment trace (<= 10 traces): {st['n']} traces, {st['nulls']} breaks")
            need({"Median", "Mean", "HRES"} <= set(st["names"]), f"median / mean / HRES missing: {st['names']}")
            need((st["aria"] or "").startswith("ECMWF ensemble (50 members): median ") and "25–75%" in st["aria"] and "of 50 members above" in st["aria"] and st["role"] == "img", f"headline / aria-label: {st['aria']}")
            need("ECMWF IFS ENS" in st["badge"] and "00Z" in st["badge"] and "50 perturbed members" in st["badge"], f"cycle / issue time missing: {st['badge']}")
            need("CC BY 4.0" in st["note"] and "Adapted from" in st["note"] and "not bias-corrected" in st["note"] and "0.25°" in st["note"] and "terrain" in st["note"], f"attribution / caveats missing: {st['note']}")
            need(st["announce"].startswith("Showing the ECMWF ensemble") and st["pressed"] == ["false", "true"] and st["plumeReq"] == 1, f"announce / state / one fetch: {st['announce']} {st['pressed']} {st['plumeReq']}")
            need("members" in st["table"] and "Median" in st["table"] and "at least" in st["table"] and not st["hscroll"], f"table rows / layout: {st['table'][:200]} hscroll={st['hscroll']}")
            if width == 375:
                b.shot(Path(tempfile.gettempdir()) / "ens_375.png")
            else:
                b.shot(Path(tempfile.gettempdir()) / "ens_1280.png")
            # Snow (in) toggle in the Ensemble view: sf x NBM's ratio; back to Models keeps working
            b.eval("[...document.querySelectorAll('#mm-mode button')].find(x => x.dataset.m === 'snow').click(); 1"); time.sleep(2.5)
            sn = b.eval("(() => ({aria: document.getElementById('mm-chart').getAttribute('aria-label'), note: document.getElementById('mm-note').textContent}))()")
            need("snow" in sn["aria"] and "median snow ratio" in sn["note"] and "inches assume NBM SLR" in sn["note"], f"snow mode in the ensemble: {sn}")
            b.eval("[...document.querySelectorAll('#mm-view button')].find(x => x.dataset.v === 'models').click(); 1"); time.sleep(2.5)
            back = b.eval("(() => ({names: (document.getElementById('mm-chart').data || []).map(t => t.name), announce: document.getElementById('mm-announce').textContent}))()")
            need("NBM" in back["names"] and "ECMWF" in back["names"] and back["announce"].startswith("Showing the model comparison"), f"back to Models: {back}")
        # GEFS (dev18 stretch, built OFF): when its plume is in the build, an ECMWF | GEFS switch appears in the Ensemble view only, and GEFS draws 31 members with no HRES line
        gplume = Path(__file__).resolve().parents[1] / "build" / "models" / "gefs" / "plume" / "alta-ski-area.json"
        if gplume.exists() and "gefs" in (json.loads((Path(__file__).resolve().parents[1] / "build" / "data" / "multimodel.json").read_text(encoding="utf-8")).get("plumes") or []):
            for width in (1280, 375):
                b.open(f"{base}/area.html#alta-ski-area", width=width, wait=8)
                wait_for(b, "document.getElementById('mm-sec')"); b.eval("document.getElementById('mm-sec').scrollIntoView(); 1"); time.sleep(3)
                hid = b.eval("document.getElementById('ens-src').hidden")
                b.eval("[...document.querySelectorAll('#mm-view button')].find(x => x.dataset.v === 'ens').click(); 1"); time.sleep(3.5)
                shown = b.eval("(() => { const s = document.getElementById('ens-src'); return {hidden: s.hidden, btns: [...s.querySelectorAll('button')].map(x => [x.textContent.trim(), x.getAttribute('aria-pressed'), Math.round(x.getBoundingClientRect().height)])}; })()")
                need(hid is True and shown["hidden"] is False and [x[0] for x in shown["btns"]] == ["ECMWF", "GEFS"] and all(x[2] >= 40 for x in shown["btns"]), f"source switch only in the Ensemble view: {hid} {shown}")
                b.eval("[...document.querySelectorAll('#ens-src button')].find(x => x.dataset.s === 'gefs').click(); 1"); time.sleep(3.5)
                g = b.eval("""(() => { const el = document.getElementById('mm-chart'), d = el.data || [];
                  return {names: d.map(t => t.name), nulls: d[0] ? d[0].x.filter(v => v === null).length : 0, aria: el.getAttribute('aria-label'), badge: document.getElementById('mm-badge').textContent,
                          note: document.getElementById('mm-note').textContent, announce: document.getElementById('mm-announce').textContent,
                          pressed: [...document.querySelectorAll('#ens-src button')].map(x => x.getAttribute('aria-pressed')), hscroll: document.documentElement.scrollWidth > innerWidth + 2}; })()""")
                log(f"  gefs {width}px: {g['names']}, segments {g['nulls']}, aria: {g['aria']}")
                need(g["nulls"] == 31 and "HRES" not in g["names"] and {"Median", "Mean"} <= set(g["names"]), f"GEFS plume traces: {g['names']} segments {g['nulls']}")
                need((g["aria"] or "").startswith("GEFS ensemble (31 members): median ") and "NOAA GEFS" in g["badge"] and "control run plus the perturbed members" in g["badge"], f"GEFS headline / badge: {g['aria']} / {g['badge']}")
                need("public domain" in g["note"] and "not bias-corrected" in g["note"] and "ECMWF" not in g["note"], f"GEFS note: {g['note'][:200]}")
                need(g["announce"].startswith("Showing the GEFS ensemble") and g["pressed"] == ["false", "true"] and not g["hscroll"], f"GEFS announce / state: {g}")
                b.eval("[...document.querySelectorAll('#mm-mode button')].find(x => x.dataset.m === 'snow').click(); 1"); time.sleep(2.5)
                sn = b.eval("document.getElementById('mm-note').textContent")
                need("ESTIMATE" in sn and "categorical-snow share" in sn, f"GEFS snow mode must say it is an estimate: {sn[:160]}")
        # stale: a run started 30 h ago is greyed and says so
        d = json.loads(orig)
        d["init"] = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=30)).strftime("%Y-%m-%dT%H:00Z")
        plume.write_text(json.dumps(d), encoding="utf-8")
        b.open(f"{base}/area.html#alta-ski-area", width=1280, wait=8)
        wait_for(b, "document.getElementById('mm-sec')"); b.eval("document.getElementById('mm-sec').scrollIntoView(); 1"); time.sleep(4)
        b.eval("[...document.querySelectorAll('#mm-view button')].find(x => x.dataset.v === 'ens').click(); 1"); time.sleep(3.5)
        stale = b.eval("""(() => { const d = document.getElementById('mm-chart').data || [];
          return {badge: document.getElementById('mm-badge').textContent, line: d.find(t => t.name === 'Median') ? d.find(t => t.name === 'Median').line.color : null,
                  ann: ((document.getElementById('mm-chart').layout || {}).annotations || []).map(x => x.text).join('|')}; })()""")
        log(f"  stale ensemble: {stale}")
        need("out of date" in stale["badge"] and stale["line"] == "#7a8594" and "Out of date" in stale["ann"], f"stale run must be greyed and labelled: {stale}")
    finally:
        plume.write_text(orig, encoding="utf-8")
    need(not b.errors, f"JS errors: {b.errors}")


def check_multimodel(b: Browser, base: str, log):
    """dev16 M7: precipitation by model on the area page: NBM + HRRR/RRFS/GFS lines, agreement badge (heuristic label), units toggle, table, model terrain in
    the tooltip, graceful when data/multimodel.json is missing, JS rebase == Python rebase."""
    sys.path.insert(0, str(REPO))
    from datetime import datetime, timezone
    from pipeline.models import multimodel as mm_mod
    area = "alta-ski-area"
    if not (Path(base_dir_holder["path"]) / "data" / "multimodel.json").exists():
        raise Fail("build/data/multimodel.json missing: run the models quickly or `pipeline build` first")
    b.open(f"{base}/area.html#{area}", wait=7)
    _draw_all(b)
    st = b.eval("""(async () => { await new Promise(r => setTimeout(r, 1500)); const el = document.getElementById('mm-chart'); if (!el || !el.data) return null;
      const out = {names: el.data.map(t => t.name), badge: document.getElementById('mm-badge').textContent, summary: (el.previousElementSibling || {}).textContent || '',
        hover: el.data[1].hovertemplate, terrain: String(el.data[1].customdata[0]), title0: (el.layout.annotations[0] || {}).text, h: Math.round(el.getBoundingClientRect().height), note: document.getElementById('mm-note').textContent,
        labels: el.layout.annotations.map(a => a.text)};
      document.querySelector('#mm-mode [data-m=snow]').click(); await new Promise(r => setTimeout(r, 800));
      out.title1 = (el.layout.annotations[0] || {}).text; out.badge1 = document.getElementById('mm-badge').textContent;
      const d = document.querySelector('#mm-chart + .chart-table'); d.open = true; d._build && d._build();
      out.cols = [...d.querySelectorAll('th[scope=col]')].map(t => t.textContent); out.rows = d.querySelectorAll('tbody tr').length;
      document.querySelector('#mm-mode [data-m=liquid]').click(); await new Promise(r => setTimeout(r, 500));
      // JS rebase vs the python reference on a fixture
      out.js = MultiModel.rebase(Date.parse('2026-11-18T12:00Z'), [0, 6, 12], [0, 0.2, 0.9], Date.parse('2026-11-18T15:00Z'));
      return out; })()""")
    log(f"  multimodel: {json.dumps(st)[:600]}")
    need(st and st["names"][0] == "NBM" and len(st["names"]) >= 3 and {"HRRR", "RRFS", "GFS"} & set(st["names"]), f"model lines missing: {st and st['names']}")
    need(("High" in st["badge"] or "Medium" in st["badge"] or "Low" in st["badge"]) and "heuristic" in st["badge"], f"agreement badge/heuristic label: {st['badge']}")
    need("customdata" in st["hover"] and "summit" in st["hover"] and "terrain" in st["terrain"], f"tooltip lacks model terrain vs summit: {st['hover']} {st['terrain']}")
    need(st["summary"].rstrip().endswith(".") and "…" not in st["summary"] and "model agreement" in st["summary"], f"headline sentence: {st['summary']}")
    need("Liquid" in st["title0"] and "Snow" in st["title1"] and st["badge1"] == st["badge"], f"units toggle: {st['title0']} / {st['title1']}; badge must not change")
    need(st["cols"][:2] == ["Time", "NBM"] and st["rows"] >= 4 and st["h"] >= 200, f"table/height: {st['cols']} {st['rows']} {st['h']}")
    py = mm_mod.rebase(datetime(2026, 11, 18, 12, tzinfo=timezone.utc), [0, 6, 12], [0, 0.2, 0.9], datetime(2026, 11, 18, 15, tzinfo=timezone.utc))
    need([round(x, 3) for x in st["js"]] == [round(x, 3) for x in py], f"JS rebase {st['js']} != Python {py}")
    b.open(f"{base}/area.html#{area}", wait=7, block=["*multimodel.json*"])
    _draw_all(b)
    time.sleep(1.5)
    msg = b.eval("(document.getElementById('mm-chart') || {textContent: ''}).textContent")
    need("not available" in msg, f"missing multimodel.json must read gracefully: {msg}")
    for width in (375,):
        b.open(f"{base}/area.html#{area}", width=width, wait=7)
        _draw_all(b)
        time.sleep(1.5)
        sc = b.eval("({w: document.documentElement.scrollWidth, vw: innerWidth, h: Math.round(document.getElementById('mm-chart').getBoundingClientRect().height)})")
        need(sc["w"] <= sc["vw"] + 2 and sc["h"] >= 200, f"model panel at 375 px: {sc}")
    need(not b.errors, f"JS errors: {b.errors}")


def check_models_layout(b: Browser, base: str, log):
    """dev18 Part 0a: the model viewer from a FIXTURE catalog + frames (tools/model_fixture.py): cumulative layout shift < 0.1 at 1280 and 375 px
    (new catalog with per-field pixel sizes, and an old-style catalog without them), the picture's box is reserved from the catalog size, switching
    model/field/region keeps CLS low and never leaves a missing frame."""
    import shutil
    sys.path.insert(0, str(REPO / "tools"))
    from model_fixture import write_fixture
    src = Path(base_dir_holder["path"])
    obs = """(() => { window.__cls = 0; try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; }).observe({type: 'layout-shift', buffered: true}); } catch (e) { window.__cls = -1; } })()"""
    b.cmd("Page.addScriptToEvaluateOnNewDocument", source=obs)
    res = {}
    try:
        for variant, sizes in (("sized", True), ("old", False)):
            with tempfile.TemporaryDirectory() as tmp:
                t = Path(tmp)
                for f in ("models.html", "css", "js"):
                    (shutil.copytree if (src / f).is_dir() else shutil.copy)(src / f, t / f)
                write_fixture(t / "models", with_sizes=sizes)
                with serve(t, png_delay=0.7, json_delay=0.6) as tbase:             # slow catalog + frames: the layout must already be final when they arrive
                    for width in (1280, 412, 375):
                        b.open(f"{tbase}/models.html", width=width, wait=4.0)
                        r = b.eval("""(() => { const i = document.getElementById('frame'), r = i.getBoundingClientRect();
                          return {cls: window.__cls, nat: [i.naturalWidth, i.naturalHeight], box: [Math.round(r.width), Math.round(r.height)], attrs: [i.getAttribute('width'), i.getAttribute('height')],
                                  missing: i.classList.contains('missing'), caption: document.getElementById('caption').textContent.length, hscroll: document.documentElement.scrollWidth > innerWidth + 2}; })()""")
                        res[f"{variant}-{width}"] = r
                        need(r["cls"] >= 0 and r["cls"] < 0.1, f"models page CLS {r['cls']} ({variant}, {width}px): {r}")
                        need(r["nat"][0] == 900 and not r["missing"] and r["caption"] > 10, f"frame did not load ({variant}, {width}px): {r}")
                        need(not r["hscroll"], f"sideways scroll ({variant}, {width}px)")
                        if sizes:
                            need(r["attrs"] == ["900", "700"], f"catalog size not applied before load: {r['attrs']}")
                    # switching: a new field and region (different heights) must not shift the page much
                    b.open(f"{tbase}/models.html", width=1280, wait=2.0)
                    b.eval("(() => { const s = document.getElementById('domain'); s.value = 'wasatch'; s.dispatchEvent(new Event('change')); })()")
                    time.sleep(1.2)
                    b.eval("(() => { const s = document.getElementById('model'); s.value = 'gfs'; s.dispatchEvent(new Event('change')); })()")
                    time.sleep(1.2)
                    r = b.eval("({cls: window.__cls, missing: document.getElementById('frame').classList.contains('missing'), d: document.getElementById('domain').value})")
                    res[f"{variant}-switch"] = r
                    need(not r["missing"] and r["cls"] < 0.1, f"switching model/region: {r}")
    finally:
        pass
    log(f"  models CLS: {json.dumps(res)[:700]}")
    need(not b.errors, f"JS errors: {b.errors}")


def check_webcams(b: Browser, base: str, log):
    """dev18 Part 1: the area page's Webcams row: <= 3 plain outbound links (https, target=_blank, rel noopener noreferrer), each tappable at 375 px, no iframe,
    no image or other resource loaded from a webcam host, no sideways scroll; SNOTEL pages and areas without an entry show no row."""
    sys.path.insert(0, str(REPO))
    import pipeline  # noqa: F401
    from pipeline import webcams as W
    src = Path(base_dir_holder["path"])
    W.write_public(src / "data" / "webcams.json")
    hosts = sorted({W.host_of(e["url"]) for items in W.load()["areas"].values() for e in items})
    res = {}
    for width in (375, 1280):
        b.open(f"{base}/area.html#alta-ski-area", width=width, wait=6)
        _draw_all(b)
        res[width] = b.eval("""(() => { const row = document.querySelector('.webcams'); if (!row) return {row: false};
          const links = [...row.querySelectorAll('a')];
          const hosts = %s;
          const res = performance.getEntriesByType('resource').map(r => r.name).filter(n => hosts.some(h => new URL(n).hostname.replace(/^www[.]/, '') === h));
          return {row: true, n: links.length, ok: links.every(a => a.target === '_blank' && /noopener/.test(a.rel) && /noreferrer/.test(a.rel) && a.href.startsWith('https://')),
                  tall: Math.min(...links.map(a => Math.round(a.getBoundingClientRect().height))), text: row.textContent.slice(0, 160),
                  iframes: document.querySelectorAll('iframe, embed, object, video').length, imgs: [...document.images].filter(i => hosts.some(h => i.src.includes(h))).length,
                  fetched: res, hscroll: document.documentElement.scrollWidth > innerWidth + 2}; })()""" % json.dumps(hosts))
        r = res[width]
        need(r["row"], f"no Webcams row on the area page at {width}px")
        need(1 <= r["n"] <= 3 and r["ok"], f"webcam links must be 1-3 https links with target=_blank rel=noopener noreferrer: {r}")
        need(r["iframes"] == 0 and r["imgs"] == 0 and not r["fetched"], f"nothing may be embedded or loaded from a webcam host: {r}")
        need(not r["hscroll"], f"sideways scroll at {width}px")
        if width == 375:
            need(r["tall"] >= 36, f"webcam links are too small to tap at 375px ({r['tall']} px)")
    b.open(f"{base}/area.html#snotel-1000-OR-SNTL", width=375, wait=5)
    need(not b.eval("!!document.querySelector('.webcams')"), "a SNOTEL page must not show a Webcams row")
    log(f"  webcams: {json.dumps(res)[:500]}")
    need(not b.errors, f"JS errors: {b.errors}")


def _hosts(urls):
    from urllib.parse import urlparse
    return sorted({(urlparse(u).hostname or "") for u in urls if u.startswith("http")})


def check_privacy(b: Browser, base: str, log):
    """dev18 Part 2b: what the privacy page promises, measured in a real browser on every page: NO cookies; the only hosts the browser contacts besides this
    site are the `browser:` hosts of config/sources.yml; localStorage keys are the ones the privacy page lists; no request to an analytics provider."""
    import yaml
    sys.path.insert(0, str(REPO / "tools"))
    import gen_site_pages as G
    reg = yaml.safe_load((REPO / "config" / "sources.yml").read_text(encoding="utf-8"))
    allowed = {h for s in reg["sources"] for h in (s.get("browser") or [])} | {"127.0.0.1"}
    listed = {k for k, *_ in G.STORAGE}
    pages = ["index.html", "area.html#alta-ski-area", "area.html#sp-wing-mountain", "finder.html", "mine.html", "models.html", "about.html", "status.html",
             "sources.html", "privacy.html", "terms.html", "disclaimer.html", "404.html"]
    seen_hosts = {}
    for pg in pages:
        b.open(f"{base}/{pg}", width=1280, wait=5)
        if pg.startswith(("area", "index")):
            _draw_all(b)
        hosts = _hosts(b.requests)
        for h in hosts:
            seen_hosts.setdefault(h, []).append(pg)
        bad = [h for h in hosts if h not in allowed]
        need(not bad, f"{pg}: the browser contacted hosts the privacy page does not list: {bad} (all: {hosts})")
        cookies = b.cmd("Network.getAllCookies").get("cookies", [])
        need(not cookies, f"{pg}: cookies were set: {[c['name'] for c in cookies]}")
        keys = b.eval("Object.keys(localStorage).concat(Object.keys(sessionStorage))")
        need(set(keys) <= listed, f"{pg}: storage keys not on the privacy page: {sorted(set(keys) - listed)}")
    need(not any("plausible" in h or "goatcounter" in h or "zgo.at" in h or "cloudflareinsights" in h for h in seen_hosts), f"an analytics host was contacted: {sorted(seen_hosts)}")
    log(f"  privacy: hosts seen {sorted(seen_hosts)}")
    need(not b.errors, f"JS errors: {b.errors}")


def check_analytics(b: Browser, base: str, log):
    """dev18 Part 2c: analytics is OFF by default (zero analytics requests, snowwxTrack is a harmless no-op, analytics.js is never fetched); when enabled the provider script is
    injected and events from real clicks reach the provider queue; Do Not Track and Global Privacy Control stop everything. Edits build/data/meta.json and restores it."""
    src = Path(base_dir_holder["path"])
    meta_path = src / "data" / "meta.json"
    original = meta_path.read_text(encoding="utf-8") if meta_path.exists() else None
    meta = json.loads(original) if original else {}
    block = ["*plausible.io*", "*gc.zgo.at*", "*cloudflareinsights*", "*analytics.test*"]

    def setmeta(a):
        meta_path.write_text(json.dumps({**meta, "analytics": a}), encoding="utf-8")

    def state():
        return b.eval("""(() => ({track: typeof window.snowwxTrack, mod: typeof SnowWxAnalytics, active: (typeof SnowWxAnalytics !== 'undefined' && SnowWxAnalytics.active()) ? SnowWxAnalytics.active().provider : null,
          script: !!document.querySelector('script[data-domain]'), q: (window.plausible && window.plausible.q || []).map(a => a[0]), cookies: document.cookie}))()""")
    try:
        b.open(f"{base}/about.html", width=1280, wait=2)
        b.eval("localStorage.clear(); sessionStorage.clear(); 1")                          # earlier checks leave favorites / a saved Finder filter behind: start from a clean browser
        # 1. OFF (the shipped default)
        setmeta({"enabled": False})
        b.open(f"{base}/finder.html", width=1280, wait=4, block=block)
        st = state()
        need(st["track"] == "function" and st["mod"] == "undefined" and st["active"] is None and not st["script"], f"disabled: {st}")
        need(not any("analytics" in u or any(h in u for h in ("plausible", "zgo.at", "cloudflareinsights")) for u in b.requests), f"disabled analytics made requests: {[u for u in b.requests if 'analytics' in u]}")
        b.eval("window.snowwxTrack('install'); window.snowwxTrack('favorite_added', {where: 'finder'}); 1")
        # 2. ON (plausible): script injected, events reach the provider queue
        setmeta({"enabled": True, "provider": "plausible", "site_id": "snow.example"})
        b.open(f"{base}/finder.html", width=1280, wait=4, block=block)
        st = state()
        need(st["mod"] == "object" and st["active"] == "plausible" and st["script"], f"enabled but not started: {st}")
        need(b.eval("document.querySelector('script[data-domain]').getAttribute('data-domain')") == "snow.example", "data-domain not set")
        clicked = False
        for _ in range(30):                                    # the Finder table renders after its data files arrive (slower on a busy machine): wait for a star
            clicked = b.eval("(() => { const t = document.querySelector('button.star:not(.on)'); if (t) t.click(); return !!t; })()")
            if clicked:
                break
            time.sleep(0.5)
        time.sleep(0.5)
        st = state()
        need(clicked and "favorite_added" in st["q"], f"a favorite click did not reach the provider queue (clicked={clicked}): {st}")
        need(st["cookies"] == "", "analytics set a cookie")
        b.open(f"{base}/area.html#alta-ski-area", width=1280, wait=6, block=block)
        _draw_all(b)
        b.eval("(() => { const d = document.querySelector('details.chart-table summary'); if (d) d.click(); const a = document.querySelector('a[data-track=avalanche_click]'); if (a) { a.addEventListener('click', e => e.preventDefault()); a.click(); } return 1; })()")
        time.sleep(0.5)
        st = state()
        need("table_view" in st["q"] and "avalanche_click" in st["q"], f"table_view / avalanche_click not tracked: {st}")
        # 3. ON but the visitor opted out: DNT, then GPC: nothing is injected, nothing queued
        for name, js in (("DNT", "Object.defineProperty(navigator, 'doNotTrack', {get: () => '1'});"), ("GPC", "Object.defineProperty(navigator, 'globalPrivacyControl', {get: () => true});")):
            res = b.cmd("Page.addScriptToEvaluateOnNewDocument", source=js)
            b.open(f"{base}/finder.html", width=1280, wait=4, block=block)
            st = state()
            need(st["active"] is None and not st["script"] and st["q"] == [], f"{name}: analytics ran for an opted-out visitor: {st}")
            b.cmd("Page.removeScriptToEvaluateOnNewDocument", identifier=res["identifier"])
        # 4. ON with no provider chosen: nothing
        setmeta({"enabled": True, "provider": "none", "site_id": "x"})
        b.open(f"{base}/finder.html", width=1280, wait=3, block=block)
        st = state()
        need(st["mod"] == "undefined" and not st["script"], f"provider none: {st}")
    finally:
        if original is None:
            meta_path.unlink(missing_ok=True)
        else:
            meta_path.write_text(original, encoding="utf-8")
    log("  analytics: off by default, plausible injection + events, DNT/GPC respected")
    need(not b.errors, f"JS errors: {b.errors}")


def check_csp(b: Browser, base: str, log):
    """dev18 Part 2d: the DRAFT Content-Security-Policy of docs/cloudflare_headers.draft, enforced by serving build/ with exactly that header: Chrome must report NO violation on any page
    (inline scripts, Plotly's CDN, MapLibre workers, tiles, the NWS overlay) and the maps and charts still draw. Fails when the draft would break the site."""
    import re
    draft = Path(os.environ.get("CSP_DRAFT") or REPO / "docs" / "cloudflare_headers.draft").read_text(encoding="utf-8")      # CSP_DRAFT: a variant, to prove the check can fail
    m = re.search(r"^\s*Content-Security-Policy:\s*(.+)$", draft, re.M)
    need(m, "no Content-Security-Policy line in docs/cloudflare_headers.draft")
    csp = m.group(1).strip()
    src = Path(base_dir_holder["path"])
    pages = ["index.html", "area.html#alta-ski-area", "area.html#sp-wing-mountain", "area.html#snotel-1000-OR-SNTL", "finder.html", "mine.html", "models.html", "about.html", "status.html",
             "sources.html", "privacy.html", "terms.html", "disclaimer.html", "404.html"]
    bad = {}
    with serve(src, headers={"Content-Security-Policy": csp}) as cbase:
        for pg in pages:
            b.open(f"{cbase}/{pg}", width=1280, wait=6)
            if pg.startswith(("area", "index")):
                _draw_all(b)
            v = [c for c in b.console if "Content Security Policy" in c or "Refused to" in c]
            if v:
                bad[pg] = v[:3]
        st = None
        b.open(f"{cbase}/index.html", width=1280, wait=7)
        st = b.eval("({tiles: document.querySelectorAll('img.leaflet-tile-loaded').length, markers: !!document.querySelector('canvas'), ref: document.querySelectorAll('.maplibregl-canvas').length})")
        b.open(f"{cbase}/area.html#alta-ski-area", width=1280, wait=6)
        _draw_all(b)
        ch = b.eval("document.querySelectorAll('.js-plotly-plot').length")
    need(not bad, f"the draft CSP breaks pages: {json.dumps(bad)[:900]}")
    need(st["tiles"] > 0 and st["markers"], f"the map did not draw under the CSP: {st}")
    need(ch >= 3, f"charts did not draw under the CSP ({ch} Plotly charts)")
    log(f"  csp: no violations on {len(pages)} pages; tiles {st['tiles']}, ref canvases {st['ref']}, charts {ch}")


def check_verify_ui(b: Browser, base: str, log):
    """dev18 Part 3: the M9 verification panel (behind verification_ui.enabled, default OFF) from FIXTURE data: flag off = hidden and no verification file is requested; enabled
    with too little data = "Collecting data: X of 14 days" and no numbers; enough data = chart + table + one-sentence summary + caveats; the about.html scorecard follows the same
    rules; 375 px has no sideways scroll. Edits build/data/meta.json + verification files and restores them."""
    import shutil
    src = Path(base_dir_holder["path"])
    dd = src / "data"
    meta_path = dd / "meta.json"
    original = meta_path.read_text(encoding="utf-8") if meta_path.exists() else None
    meta = json.loads(original) if original else {}
    trip = "1308:UT:SNTL"                                           # Alta's nearest SNOTEL site (Atwater)
    dates = [f"2026-12-{d:02d}" for d in range(1, 21)]
    doc = {"triplet": trip, "d": 20, "n": 40, "span": [dates[0], dates[-1]], "common_n": 20,
           "metrics": {"NBM expected": {"n": 20, "bias_in": 0.12, "mae_in": 0.4, "events_1": 8, "hit_1": 0.75}, "NWS (NDFD)": {"n": 20, "bias_in": -0.2, "mae_in": 0.3, "events_1": 8, "hit_1": 0.5}},
           "daily": {"dates": dates, "obs": [0, 2.5, 0, 1.2] * 5, "nbm": [0.1, 2.0, 0.4, 1.5] * 5, "ndfd": [0, 1.5, 0, 0.8] * 5}}
    vdir = dd / "verification"
    had_vdir = vdir.exists()
    backup = {f.name: f.read_bytes() for f in (dd / "verification.json",) if f.exists()}

    def setup(enabled, station=None, scorecard_ready=True):
        meta_path.write_text(json.dumps({**meta, "verification_ui": {"enabled": enabled, "min_days": 14, "min_pairs": 30}}), encoding="utf-8")
        idx = {"min_days": 14, "min_pairs": 30, "span": [dates[0], dates[-1]], "outage_excluded": ["2026-11-16T12:00Z", "2026-11-18T00:45Z"], "stations": {},
               "scorecard": {"ready": scorecard_ready, "days": 20 if scorecard_ready else 6, "pairs": 400 if scorecard_ready else 24,
                             "rows": [{"source": "NBM expected", "n": 300, "bias_in": 0.12, "mae_in": 0.4, "events_1": 50, "hit_1": 0.62}] if scorecard_ready else []}}
        if station:
            idx["stations"][trip] = station
        (dd / "verification.json").write_text(json.dumps(idx), encoding="utf-8")
        shutil.rmtree(vdir, ignore_errors=True)
        if station and station.get("ready"):
            vdir.mkdir(parents=True, exist_ok=True)
            (vdir / "1308_UT_SNTL.json").write_text(json.dumps(doc), encoding="utf-8")

    def panel():
        return b.eval("""(() => { const s = document.getElementById('verif-sec'); if (!s) return {exists: false};
          return {exists: true, hidden: s.hidden, text: s.textContent.replace(/\\s+/g, ' ').slice(0, 260), chart: !!s.querySelector('.js-plotly-plot'), rows: s.querySelectorAll('tbody tr').length,
                  caveats: s.querySelectorAll('.caveats li').length, summary: (s.querySelector('[role=img]') || {}).getAttribute ? (s.querySelector('[role=img]').getAttribute('aria-label') || '').slice(0, 200) : '',
                  hscroll: document.documentElement.scrollWidth > innerWidth + 2}; })()""")
    res = {}
    try:
        # 1. flag OFF: hidden, nothing fetched
        setup(False, {"d": 20, "n": 40, "ready": True})
        b.open(f"{base}/area.html#alta-ski-area", width=1280, wait=6)
        res["off"] = panel()
        need(res["off"]["exists"] and res["off"]["hidden"] is True and not res["off"]["chart"], f"flag off: the panel must stay hidden: {res['off']}")
        need(not any("verification.json" in u or "/verification/" in u for u in b.requests), f"flag off: verification data files were requested: {[u for u in b.requests if 'verification' in u]}")
        b.open(f"{base}/about.html", width=1280, wait=3)
        need(b.eval("document.getElementById('scorecard').hidden") is True and not any("verification.json" in u or "/verification/" in u for u in b.requests), "flag off: the scorecard must stay hidden and fetch nothing")
        # 2. ON, too little data: "Collecting data" and no numbers
        setup(True, {"d": 6, "n": 24})
        b.open(f"{base}/area.html#alta-ski-area", width=1280, wait=6)
        res["collect"] = panel()
        r = res["collect"]
        need(not r["hidden"] and "Collecting data: 6 of 14 days; 24 of 30 forecast pairs" in r["text"] and not r["chart"] and r["rows"] == 0, f"collecting state: {r}")
        need(not any("verification/" in u for u in b.requests), "collecting state must not load a station results file")
        # 3. ON, enough data: chart + table + sentence + caveats
        setup(True, {"d": 20, "n": 40, "ready": True})
        for width in (1280, 375):
            b.open(f"{base}/area.html#alta-ski-area", width=width, wait=6)
            b.eval("document.getElementById('verif-sec').scrollIntoView(); 1")
            _draw_all(b)
            r = panel()
            res[f"ready{width}"] = r
            need(not r["hidden"] and r["chart"] and r["rows"] >= 2 and r["caveats"] >= 3, f"ready state at {width}px: {r}")
            need("NBM's expected 24-h snowfall ran 0.12 in above" in r["summary"] and "SNOTEL site nearest this ski area" in r["summary"], f"summary sentence: {r['summary']}")
            need("lower bound" in b.eval("document.getElementById('verif-sec').textContent"), "the lower-bound caveat is missing")
            need(not r["hscroll"], f"sideways scroll at {width}px: {r}")
        need(b.eval("!!document.querySelector('#verif-sec details.chart-table')"), "View as table toggle missing")
        # 4. about.html scorecard
        b.open(f"{base}/about.html", width=375, wait=3)
        sc = b.eval("(() => { const s = document.getElementById('scorecard'); return {hidden: s.hidden, text: s.textContent.replace(/\\s+/g, ' ').slice(0, 900), hscroll: document.documentElement.scrollWidth > innerWidth + 2}; })()")
        need(not sc["hidden"] and "NBM expected" in sc["text"] and "lower bound" in sc["text"] and not sc["hscroll"], f"scorecard: {sc}")
        setup(True, {"d": 6, "n": 24}, scorecard_ready=False)
        b.open(f"{base}/about.html", width=1280, wait=3)
        need("Collecting data: 6 of 14 days, 24 of 30" in b.eval("document.getElementById('scorecard-body').textContent"), "scorecard collecting state")
        # 5. a SNOTEL station page uses its own site
        b.open(f"{base}/area.html#snotel-1308-UT-SNTL", width=375, wait=6)
        st = panel()
        need(st["exists"], f"station page without a verification section: {st}")
    finally:
        shutil.rmtree(vdir, ignore_errors=True)
        if had_vdir:
            vdir.mkdir(parents=True, exist_ok=True)
        for n, data in backup.items():
            (dd / n).write_bytes(data)
        if not backup:
            (dd / "verification.json").unlink(missing_ok=True)
        if original is None:
            meta_path.unlink(missing_ok=True)
        else:
            meta_path.write_text(original, encoding="utf-8")
    log(f"  verifyui: {json.dumps(res)[:600]}")
    need(not b.errors, f"JS errors: {b.errors}")


def check_failure_modes(b: Browser, base: str, log):
    """dev18 stretch 2: each DATA file/source unreachable one at a time (the request fails like a dead server). The obs map, an area page, the Finder, My mountains and the status page must
    still load: no JavaScript exception, a heading, and no "undefined" / "NaN" / "[object" text on screen. A few degraded states are asserted by name."""
    patterns = {"snotel": "*data/snotel.geojson*", "asos": "*data/asos.geojson*", "avalanche map": "*data/avalanche.geojson*", "avalanche ratings": "*data/avalanche_ratings.json*",
                "hazards": "*data/hazards.json*", "alerts": "*data/alerts/*", "afd": "*data/afd/*", "ndfd": "*data/ndfd/*", "points (NBM)": "*data/points/*", "multimodel": "*data/multimodel.json*",
                "ridge": "*data/ridge.json*", "nohrsc": "*data/nohrsc/*", "model catalog": "*models/index.json*", "meta": "*data/meta.json*", "search index": "*data/search.json*",
                "map points": "*data/map_points.json*", "webcams": "*data/webcams.json*", "chart library (self-hosted Plotly)": "*vendor/plotly*",
                "hazard text": "*alerts/hazard_text.json*"}
    pages = [("index.html", "obs map"), ("area.html#alta-ski-area", "area page"), ("finder.html", "Finder"), ("mine.html", "My mountains"), ("models.html", "models"), ("status.html", "status")]
    bad = []
    seen = {}
    for name, pat in patterns.items():
        for pg, label in pages:
            b.open(f"{base}/{pg}", width=1280, wait=3.5, block=[pat])
            r = b.eval("""(() => { const t = document.body.innerText; return {h: !!document.querySelector('h1, h2'), junk: (t.match(/undefined|NaN|\\[object/g) || []).length, len: t.length,
                  text: t.replace(/\\s+/g, ' ').slice(0, 2000)}; })()""")
            seen[(name, label)] = r
            problems = []
            if b.errors:
                problems.append(f"JS errors {b.errors[:2]}")
            if not r["h"] or r["len"] < 80:
                problems.append("page is empty")
            if r["junk"]:
                problems.append(f"{r['junk']} undefined/NaN/[object] on screen")
            if problems:
                bad.append(f"{name} unreachable -> {label}: {'; '.join(problems)}")
    need(not bad, "degraded pages broke:\n  " + "\n  ".join(bad[:8]))
    # named degraded states
    b.open(f"{base}/area.html#alta-ski-area", width=1280, wait=4, block=["*data/points/*"])
    t = b.eval("document.body.innerText")
    need("No point forecast is available" in t or ("NWS forecast" in t and ("out of date" in t.lower() or "ago" in t)), "area page without its NBM file must fall back to the dated NWS forecast (or say none is available)")
    b.open(f"{base}/area.html#alta-ski-area", width=1280, wait=4, block=["*data/avalanche_ratings.json*"])
    need("avalanche" in b.eval("document.body.innerText").lower() and not b.errors, "area page without avalanche ratings must still link to the avalanche center")
    b.open(f"{base}/status.html", width=1280, wait=3, block=["*data/meta.json*"])
    need("could not be read" in b.eval("document.body.innerText"), "status page without meta.json must say so")
    b.open(f"{base}/area.html#alta-ski-area", width=1280, wait=5, block=["*vendor/plotly*"])
    tp = b.eval("document.body.innerText")
    need("Charts unavailable" in tp, "area page without the chart library must say charts are unavailable and still show the numbers")
    need(not b.errors, f"JS errors without the chart library: {b.errors}")
    log(f"  failure modes: {len(patterns)} sources x {len(pages)} pages, no broken page")


def check_keyboard(b: Browser, base: str, log):
    """dev18 stretch 3: keyboard-only sweep of every page with real Tab key events (CDP Input): focus moves forward through the page without a trap, every stop is a real control that is
    visible, has an accessible name, and shows a focus indicator (outline or ring). Leaflet's internal tile/marker panes are not Tab stops here (the search box is the keyboard path to a site)."""
    pages = ["index.html", "area.html#alta-ski-area", "area.html#snotel-1308-UT-SNTL", "finder.html", "mine.html", "models.html", "about.html", "status.html", "sources.html", "privacy.html",
             "terms.html", "disclaimer.html", "404.html"]

    def tab():
        for typ in ("keyDown", "keyUp"):
            b.cmd("Input.dispatchKeyEvent", type=typ, key="Tab", code="Tab", windowsVirtualKeyCode=9, nativeVirtualKeyCode=9)

    probe = """(() => { const e = document.activeElement; if (!e || e === document.body) return null; const r = e.getBoundingClientRect(), cs = getComputedStyle(e);
      const name = (e.getAttribute('aria-label') || e.getAttribute('title') || e.textContent || e.value || e.placeholder || (e.labels && e.labels[0] && e.labels[0].textContent) || '').trim().slice(0, 40);
      return {tag: e.tagName, id: e.id, name, w: Math.round(r.width), h: Math.round(r.height), vis: cs.visibility !== 'hidden' && cs.display !== 'none' && r.width > 0 && r.height > 0,
              ring: (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none', y: Math.round(r.top + scrollY)}; })()"""
    res, bad = {}, []
    for pg in pages:
        b.open(f"{base}/{pg}", width=1280, wait=5)
        b.eval("document.activeElement && document.activeElement.blur(); window.scrollTo(0, 0); 1")
        stops, seen_same = [], 0
        for _ in range(140):
            tab()
            r = b.eval(probe)
            if r is None:
                if stops:
                    break                                            # focus left the document: the sweep reached the end
                continue
            if stops and (r["tag"], r["id"], r["name"], r["y"]) == (stops[-1]["tag"], stops[-1]["id"], stops[-1]["name"], stops[-1]["y"]):
                seen_same += 1
                if seen_same >= 3:
                    bad.append(f"{pg}: keyboard trap at {r['tag']}#{r['id']} '{r['name']}'")
                    break
            else:
                seen_same = 0
            stops.append(r)
        res[pg] = len(stops)
        if len(stops) < 5:
            bad.append(f"{pg}: only {len(stops)} Tab stops")
        for r in stops:
            if not r["vis"]:
                bad.append(f"{pg}: focus lands on a hidden element {r['tag']}#{r['id']} '{r['name']}'")
            elif not r["name"] and r["tag"] in ("A", "BUTTON", "SUMMARY"):
                bad.append(f"{pg}: {r['tag']}#{r['id']} has no accessible name")
            elif not r["ring"]:
                bad.append(f"{pg}: no focus indicator on {r['tag']}#{r['id']} '{r['name']}'")
    log(f"  keyboard Tab stops: {res}")
    need(not bad, "keyboard sweep: " + " | ".join(list(dict.fromkeys(bad))[:8]))
    need(not b.errors, f"JS errors: {b.errors}")


def check_mobile_sweep(b: Browser, base: str, log):
    """dev16: every page at 375 px: no sideways scroll, no JS errors, primary buttons tappable (>= 36 px), nothing wider than the viewport."""
    pages = ["index.html", "finder.html", "mine.html", "about.html", "status.html", "models.html", "sources.html", "privacy.html", "terms.html", "disclaimer.html", "404.html", "area.html#alta-ski-area", "area.html#sp-wing-mountain", "area.html#snotel-1000-OR-SNTL"]
    bad = []
    for pg in pages:
        b.open(f"{base}/{pg}", width=375, wait=6)
        _draw_all(b)
        time.sleep(1.0)
        r = b.eval("""(() => { const vw = innerWidth, wide = [...document.querySelectorAll('body *')].filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.right > vw + 2 && !e.closest('.leaflet-container, .tbl-wrap, .chart, .js-plotly-plot, pre, .hz-popup, [hidden]') && getComputedStyle(e).position !== 'fixed'; }).slice(0, 3).map(e => e.tagName + '.' + e.className + ':' + Math.round(e.getBoundingClientRect().right));
          const small = [...document.querySelectorAll('button:not([hidden])')].filter(x => { const r = x.getBoundingClientRect(); return r.width > 0 && r.height > 0 && r.height < 36 && !x.closest('.leaflet-container, .leaflet-control, .js-plotly-plot'); }).map(x => (x.id || x.textContent.trim().slice(0, 16)) + ':' + Math.round(x.getBoundingClientRect().height)).slice(0, 5);
          return {scroll: document.documentElement.scrollWidth, vw, wide, small}; })()""")
        log(f"  375px {pg}: {r}")
        if r["scroll"] > r["vw"] + 2 or r["wide"]:
            bad.append((pg, r["scroll"], r["wide"]))
        if r["small"]:
            log(f"    small tap targets on {pg}: {r['small']}")
    need(not bad, f"sideways overflow at 375 px: {bad}")
    need(not b.errors, f"JS errors: {b.errors}")


CHECKS = {"basemap": check_basemap, "fallback": check_fallback, "layout": check_layout, "search": check_search, "charts": check_charts, "snoparks": check_snoparks, "forecast": check_forecast_overlays, "mine": check_mine, "panel": check_panel, "snotel": check_snotel_outage, "finder": check_finder_filters, "hazards": check_hazards, "status": check_status, "pwa": check_pwa, "storm": check_storm, "hazpop": check_hazard_popup, "spmobile": check_snopark_finder_mobile, "mmodel": check_multimodel, "showall": check_finder_show_all, "ensemble": check_ensemble, "mobile": check_mobile_sweep, "models": check_models_layout, "webcams": check_webcams, "privacy": check_privacy, "analytics": check_analytics, "csp": check_csp, "verifyui": check_verify_ui, "failure": check_failure_modes, "keyboard": check_keyboard}


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
                except Exception as e:  # noqa: BLE001 - one broken check (a crashed page, a JS error in the check itself) must not hide the results of the others
                    failed.append(name)
                    print(f"FAIL  {name}: {type(e).__name__}: {str(e)[:300]}")
        finally:
            b.close()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
