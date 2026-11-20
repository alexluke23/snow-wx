"""Cross-browser smoke tests (dev21 Part 3): WebKit (Safari's engine) and Firefox via Playwright. OPTIONAL suite, not part of tools/browser_check.py --quick.

Setup (once, outside the project env so the pipeline env stays unchanged):
    conda create -n pw -c conda-forge python=3.12
    C:/miniforge3/envs/pw/python.exe -m pip install playwright==1.49.1
    C:/miniforge3/envs/pw/python.exe -m playwright install webkit firefox
Run (copy web/* over build/ first, like browser_check):
    C:/miniforge3/envs/pw/python.exe tools/xbrowser_smoke.py [--build build] [--engines webkit firefox] [--shots DIR] [-v]

Pages: the obs map, an area page (Alta), the Finder, the models page, the status page and about.html, at 375 and 1280 px. Each must load with no page error and no
console error; the map draws tiles and its point canvas; the area page draws its Plotly charts (self-hosted), localStorage works (favourite round trip), the
Ensemble switch and the model chips work; every button / select / input is at least 40 px tall at 375 px (tap targets). Inputs are frozen like browser_check:
a private copy of the build with the recorded alerts made "active now", every https request answered from tests/fixtures/browser (anything else refused).
Exit 1 on a failure. Screenshots go to --shots (default data_cache/xbrowser).
"""
from __future__ import annotations

import argparse
import contextlib
import functools
import http.server
import json
import shutil
import socket
import socketserver
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))
import browser_fixtures  # noqa: E402  (stdlib only)

PAGES = [("index.html#v=depth_24h&map=7/40.6/-111.6", "map"), ("area.html#alta-ski-area", "area"), ("finder.html", "finder"),
         ("models.html", "models"), ("status.html", "status"), ("about.html", "about")]
READY = {
    "map": "window.snowwx && window.snowwx.map && window.snowwx.points && document.querySelectorAll('img.leaflet-tile-loaded').length > 0",
    "area": "(document.getElementById('area') || {textContent: ''}).textContent.length > 200 && document.querySelector('#area .chart')",
    "finder": "document.querySelector('#rows .frow, #rows p')",
    "models": "document.readyState === 'complete' && document.querySelector('main')",
    "status": "document.querySelector('#st-table tbody tr, #st-table .snotel-note')",
    "about": "document.readyState === 'complete' && document.querySelector('main h2, main h3')",
}
# a tap target is a control the visitor presses; inline text links inside sentences are exempt (WCAG 2.5.8 inline exception)
TAPS = """(() => { const bad = [];
  for (const el of document.querySelectorAll('button, select, input:not([type=hidden]), [role=button], summary')) {
    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    if (!r.width || !r.height || cs.visibility === 'hidden' || el.closest('[hidden], .leaflet-control-attribution, .js-plotly-plot, .modebar')) continue;
    if (el.type === 'checkbox' || el.type === 'radio') { const l = el.closest('label'); const lr = l ? l.getBoundingClientRect() : r; if (lr.height >= 40) continue; }
    if (r.height < 40) bad.push(`${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${el.className && typeof el.className === 'string' ? '.' + el.className.split(' ')[0] : ''} "${(el.textContent || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 24)}" ${Math.round(r.height)}px`);
  }
  return bad; })()"""


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

        def do_GET(self):
            if "If-Modified-Since" in self.headers:
                del self.headers["If-Modified-Since"]
            super().do_GET()

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True
        request_queue_size = 128          # dev21: the default listen backlog (5) refused connections in page-load bursts under parallel workers (flaky script loads)
        allow_reuse_address = True

        def handle_error(self, request, client_address):
            pass
    httpd = Server(("127.0.0.1", port), functools.partial(Quiet, directory=str(folder)))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        httpd.shutdown()


def wait(page, expr: str, timeout: float = 25.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if page.evaluate(f"() => {{ try {{ return !!({expr}); }} catch (e) {{ return false; }} }}"):
                return True
        except Exception:  # noqa: BLE001 - navigation in progress
            pass
        time.sleep(0.25)
    return False


def smoke_page(ctx, base: str, path: str, kind: str, width: int, shots: Path, engine: str, log) -> list[str]:
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {str(e)[:200]}"))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text[:200]}") if m.type == "error" else None)
    page.on("response", lambda r: errors.append(f"HTTP {r.status} {r.url[-90:]}") if r.status >= 400 and r.url.startswith(base) else None)
    fails: list[str] = []

    def need(cond, msg):
        if not cond:
            fails.append(msg)
    page.set_viewport_size({"width": width, "height": 900 if width > 500 else 780})
    page.goto(f"{base}/{path}", wait_until="load", timeout=60000)
    need(wait(page, READY[kind]), f"{kind}: page never became ready")
    if kind == "map":
        st = page.evaluate("() => ({tiles: document.querySelectorAll('img.leaflet-tile-loaded').length, canvas: document.querySelectorAll('.leaflet-pane canvas').length})")
        need(st["tiles"] > 0 and st["canvas"] > 0, f"map: tiles/canvas missing {st}")
    if kind == "area":
        page.evaluate("""async () => { for (const el of document.querySelectorAll('.chart')) { el.scrollIntoView(); await new Promise(r => setTimeout(r, 500)); } }""")
        need(wait(page, "window.Plotly && document.querySelectorAll('.js-plotly-plot').length >= 4", 30), "area: Plotly charts did not render")
        n = page.evaluate("() => document.querySelectorAll('.js-plotly-plot').length")
        ls = page.evaluate("() => { try { localStorage.setItem('xb', '1'); const v = localStorage.getItem('xb'); localStorage.removeItem('xb'); return v; } catch (e) { return 'ERR ' + e; } }")
        need(ls == "1", f"area: localStorage round trip failed: {ls}")
        fav = page.evaluate("""() => { const b = document.querySelector('#fav, .fav, [data-fav]'); if (!b) return 'none'; b.click();
            let v; try { v = localStorage.getItem('snowwx.favorites'); } catch (e) { v = 'ERR'; } b.click(); return v || ''; }""")
        need(fav == "none" or "alta-ski-area" in fav, f"area: favourite not stored: {fav}")
        page.evaluate("() => document.getElementById('mm-sec') && document.getElementById('mm-sec').scrollIntoView()")
        if wait(page, "(document.getElementById('mm-chart').data || []).length > 0", 20):
            n0 = page.evaluate("() => document.getElementById('mm-chart').data.length")
            chip = page.evaluate("() => { const c = [...document.querySelectorAll('#mm-chips .mm-chip[aria-pressed=true]')].pop(); if (!c) return null; c.click(); return c.dataset.k; }")
            need(chip and wait(page, f"document.getElementById('mm-chart').data.length === {n0 - 1}", 6), f"area: model chip did not hide a line (n0={n0}, chip={chip})")
            page.evaluate(f"() => document.querySelector('#mm-chips [data-k={chip}]') && document.querySelector('#mm-chips [data-k={chip}]').click()")
            if page.evaluate("() => !document.getElementById('mm-view').hidden"):
                page.evaluate("() => document.querySelector('#mm-view [data-v=ens]').click()")
                need(wait(page, "(document.getElementById('mm-chart').data || []).some(t => t.name === 'Median')", 20), "area: Ensemble view did not draw the plume")
                if page.evaluate("() => !document.getElementById('ens-src').hidden"):
                    page.evaluate("() => document.querySelector('#ens-src [data-s=gefs]').click()")
                    need(wait(page, "/GEFS/.test(document.getElementById('mm-badge').textContent)", 20), "area: the GEFS switch did not change the plume")
                page.evaluate("() => document.querySelector('#mm-view [data-v=models]').click()")
        else:
            fails.append("area: precipitation-by-model chart did not draw")
        log(f"    {engine} {width}px area: {n} charts, localStorage {ls}")
    if kind == "finder":
        rows = page.evaluate("() => document.querySelectorAll('#rows .frow').length")
        need(rows > 10, f"finder: only {rows} rows")
    if kind == "status":
        need(page.evaluate("() => document.querySelectorAll('#st-table tbody tr').length") >= 8, "status: table rows missing")
    if width < 500:
        small = page.evaluate(TAPS)
        need(not small, f"{kind}: tap targets under 40 px at {width}px: {small[:8]}")
    hs = page.evaluate("() => document.documentElement.scrollWidth > innerWidth + 2")
    need(not hs, f"{kind}: sideways scroll at {width}px")
    time.sleep(0.5)
    shots.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(shots / f"{engine}_{kind}_{width}.png"))
    need(not errors, f"{kind}: {errors[:5]}")
    page.close()
    return fails


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--build", default=str(REPO / "build"))
    ap.add_argument("--engines", nargs="*", default=["webkit", "firefox"])
    ap.add_argument("--shots", default=str(REPO / "data_cache" / "xbrowser"))
    ap.add_argument("--project-python", default="C:/miniforge3/envs/snow-wx/python.exe", help="the project env's python (writes the model-viewer fixture)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    from playwright.sync_api import sync_playwright
    log = print
    results, t0 = {}, time.time()
    with tempfile.TemporaryDirectory() as tmp:
        site = Path(tmp) / "site"
        shutil.copytree(a.build, site)
        browser_fixtures.freeze(site)
        # the model viewer from the fixture catalog + frames (tools/model_fixture.py), like browser_check's models check: a local build's own renders may be partial
        keep = {d.name: d for d in (site / "models").iterdir() if d.is_dir() and (d / "plume").exists() or d.name in ("verify",)} if (site / "models").exists() else {}
        tmp_keep = Path(tmp) / "keep"
        tmp_keep.mkdir()
        for name, d in keep.items():
            shutil.move(str(d), str(tmp_keep / name))
        shutil.rmtree(site / "models", ignore_errors=True)
        import subprocess                                                         # model_fixture needs the project env (pipeline imports requests, yaml)
        subprocess.run([a.project_python, "-c", "import sys; from pathlib import Path; sys.path.insert(0, 'tools'); sys.path.insert(0, '.'); "
                        "from model_fixture import write_fixture; write_fixture(Path(sys.argv[1]))", str(site / "models")], cwd=REPO, check=True, capture_output=True)
        for name in keep:
            shutil.move(str(tmp_keep / name), str(site / "models" / name))       # ECMWF / GEFS plumes and verification stay (the area page reads them)
        with serve(site) as base, sync_playwright() as p:
            for engine in a.engines:
                try:
                    br = getattr(p, engine).launch()
                except Exception as exc:  # noqa: BLE001
                    results[engine] = [f"could not launch {engine}: {exc}"]
                    continue
                fails = []
                for width in (375, 1280):
                    ctx = br.new_context(viewport={"width": width, "height": 900}, is_mobile=False, has_touch=width < 500)

                    def route(r):
                        ans = browser_fixtures.respond(r.request.url)
                        if ans is None:
                            return r.abort()
                        code, ctype, body = ans
                        return r.fulfill(status=code, content_type=ctype, body=body, headers={"Access-Control-Allow-Origin": "*"})
                    ctx.route("https://**/*", route)
                    for path, kind in PAGES:
                        try:
                            f = smoke_page(ctx, base, path, kind, width, Path(a.shots), engine, log)
                        except Exception as exc:  # noqa: BLE001
                            f = [f"{kind}: {type(exc).__name__}: {str(exc)[:200]}"]
                        log(f"  {engine:7s} {width:4d}px {kind:7s} {'ok' if not f else 'FAIL ' + '; '.join(f)[:400]}")
                        fails += [f"{width}px {x}" for x in f]
                    ctx.close()
                br.close()
                results[engine] = fails
    bad = {k: v for k, v in results.items() if v}
    print(json.dumps({"seconds": round(time.time() - t0), "engines": {k: ("ok" if not v else v) for k, v in results.items()}}, indent=1))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
