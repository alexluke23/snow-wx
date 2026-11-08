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
                         ("zoom 14", "window.snowwx.map.setZoom(14)"), ("zoom 8", "window.snowwx.map.setZoom(8)"),
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
    pages = {"area": "area.html#alta-ski-area", "finder": "finder.html", "about": "about.html"}
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


CHECKS = {"basemap": check_basemap, "fallback": check_fallback, "layout": check_layout, "search": check_search}


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
