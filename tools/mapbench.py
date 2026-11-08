"""Obs-map interaction benchmark over the Chrome DevTools protocol (4x CPU throttle).

C:/miniforge3/envs/snow-wx/python.exe tools/mapbench.py "http://localhost:8000/index.html#v=depth_24h&map=8/40.6/-111.6" label
Prints DOM size, pan/zoom main-thread time (sync + long tasks), click -> first frame and -> chart.
Needs the window.snowwx debug handle in web/js/app.js and websocket-client.
"""
import json, subprocess, sys, tempfile, time, urllib.request
import websocket

CHROME = r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
URL = sys.argv[1]
LABEL = sys.argv[2] if len(sys.argv) > 2 else ""
PORT = 9227

prof = tempfile.mkdtemp()
proc = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={prof}",
                         "--no-first-run", "--window-size=1280,800", "about:blank"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
            break
        except Exception:
            time.sleep(0.2)
    tab = next(t for t in tabs if t["type"] == "page")
    ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=180)
    n = [0]

    def cmd(method, **params):
        n[0] += 1
        ws.send(json.dumps({"id": n[0], "method": method, "params": params}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == n[0]:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    cmd("Page.enable"); cmd("Runtime.enable"); cmd("Network.enable")
    cmd("Network.setCacheDisabled", cacheDisabled=True)
    cmd("Emulation.setDeviceMetricsOverride", width=1280, height=800, deviceScaleFactor=1, mobile=False)
    cmd("Emulation.setCPUThrottlingRate", rate=4)
    t0 = time.time()
    cmd("Page.navigate", url=URL)
    js = r"""
    (async () => {
      const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
      const frame = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));
      const t0 = performance.now();
      while (!(window.snowwx && window.snowwx.ready)) { await sleep(20); if (performance.now() - t0 > 60000) return {error: "not ready"}; }
      const ready = performance.timeOrigin + performance.now();
      await sleep(400); await frame();
      const map = window.snowwx.map;
      const long = []; new PerformanceObserver((l) => l.getEntries().forEach((e) => long.push(e.duration))).observe({type: "longtask"});
      const settle = async () => { await frame(); await sleep(80); await frame(); };   // includes the 50-ms declutter debounce
      const busy = async (fn) => {           // main-thread time of fn + everything it schedules within ~150 ms
        const before = long.length; const s = performance.now(); fn(); const sync = performance.now() - s;
        await settle(); return { sync, longtask: long.slice(before).reduce((a, b) => a + b, 0) };
      };
      const res = { dom: document.getElementsByTagName("*").length, markers: document.querySelectorAll(".leaflet-marker-icon").length,
                    canvases: document.querySelectorAll("canvas").length, readyMs: Math.round(performance.now()) };
      const pans = [];
      for (let i = 0; i < 8; i++) pans.push(await busy(() => map.panBy([i % 2 ? -220 : 220, i % 4 < 2 ? 120 : -120], { animate: false })));
      const zooms = [];
      for (let i = 0; i < 6; i++) zooms.push(await busy(() => map.setZoom(map.getZoom() + (i % 2 ? -1 : 1), { animate: false })));
      // clicks: first visual response (next frame) and full panel/chart
      const clicks = [];
      const fc = await (await fetch("data/snotel.geojson")).json();
      const ski = ((await (await fetch("data/ski_areas.json")).json()).areas || []).map((a) => map.latLngToContainerPoint([a.summit.lat, a.summit.lon]));
      const pts = fc.features.map((f) => map.latLngToContainerPoint([f.geometry.coordinates[1], f.geometry.coordinates[0]]))
        .filter((pt) => pt.x > 60 && pt.y > 60 && pt.x < map.getSize().x - 60 && pt.y < map.getSize().y - 60)
        .filter((pt) => ski.every((q) => Math.hypot(q.x - pt.x, q.y - pt.y) > 20)).slice(0, 6);
      const rect = map.getContainer().getBoundingClientRect();
      const els = pts.map((pt) => ({ x: rect.left + pt.x, y: rect.top + pt.y }));
      for (const c of els) {
        const s = performance.now();
        const target = document.elementFromPoint(c.x, c.y);
        target.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, clientX: c.x, clientY: c.y, view: window }));
        await new Promise((r) => requestAnimationFrame(r));
        const firstFrame = performance.now() - s;
        let full = null;
        for (let k = 0; k < 400; k++) { if (document.querySelector("#chart .main-svg")) { full = performance.now() - s; break; } await sleep(10); }
        clicks.push({ firstFrame, full, s: location.hash.split("s=")[1] || "" });
        document.querySelector("#chart")?.replaceChildren();
        await sleep(200);
      }
      const med = (a) => { const b = [...a].sort((x, y) => x - y); return b.length ? b[Math.floor(b.length / 2)] : null; };
      const r = (x) => x === null ? null : Math.round(x);
      res.pan = { sync_med: r(med(pans.map((p) => p.sync))), longtask_med: r(med(pans.map((p) => p.longtask))), longtask_max: r(Math.max(...pans.map((p) => p.longtask))) };
      res.zoom = { sync_med: r(med(zooms.map((p) => p.sync))), longtask_med: r(med(zooms.map((p) => p.longtask))), longtask_max: r(Math.max(...zooms.map((p) => p.longtask))) };
      res.click = { n: clicks.length, firstFrame_med: r(med(clicks.map((c) => c.firstFrame))), firstFrame_max: r(Math.max(...clicks.map((c) => c.firstFrame))),
                    chart_med: r(med(clicks.map((c) => c.full).filter((x) => x !== null))), sel: clicks.map((c) => c.s), full: clicks.map((c) => c.full && Math.round(c.full)) };
      return res;
    })()
    """
    out = cmd("Runtime.evaluate", expression=js, awaitPromise=True, returnByValue=True, timeout=170000)
    val = out.get("result", {}).get("value")
    print(LABEL, json.dumps(val))
    ws.close()
finally:
    proc.kill()
