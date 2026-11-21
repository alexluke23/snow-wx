/* Snow-Wx service worker (W4, docs/specs/pwa.md). GENERATED from pipeline/pwa_sw.js by `python -m pipeline pwa`; never served
 * unless config pwa.enabled is true. Version, base path and the shell list are filled in at build time.
 *
 * What it caches (and nothing else; no map tiles, no third-party bulk):
 *   shell   versioned precache of our own pages/CSS/JS (cache "snowwx-shell-<version>", old versions deleted on activate)
 *   data    stale-while-revalidate for the small JSON the pages need: summary.json, meta.json, alerts/avalanche indexes and each
 *           FAVORITE's points/<id>.json (the page tells us the favorites; see message FAVORITES)
 *   lib     the Plotly bundle (CORS, cache-first), so charts draw offline
 * Update flow: a new worker installs and WAITS; pages show "Update available" and post SKIP_WAITING; then they reload.
 * Kill switch: pwa.kill=true in config makes the build emit a worker that unregisters itself and deletes every snowwx-* cache.
 */
const VERSION = "__VERSION__";
const BASE = "__BASE__";                       // "" or "/snow-wx" (config site.base_path)
const SHELL = __SHELL__;                       // paths relative to BASE
const PLOTLY = self.location.origin + BASE + "/vendor/plotly-2.35.2/plotly-basic.min.js";      // self-hosted since dev19 (same origin; cache-first in the lib cache)
const CORE = `snowwx-shell-${VERSION}`, DATA = "snowwx-data-v1", LIB = "snowwx-lib-v1";
const FAV_KEY = "https://snowwx.invalid/favorites";
const SMALL_DATA = ["data/points/summary.json", "data/meta.json", "data/alerts/index.json", "data/avalanche_ratings.json",
  "data/ski_areas.json", "data/snotel_points.json", "data/rec_points.json"].map((p) => BASE + "/" + p);
let favs = null;                                // Set of favorite ids (in memory; mirrored into the DATA cache)

async function loadFavs() {
  if (favs) return favs;
  try {
    const r = await (await caches.open(DATA)).match(FAV_KEY);
    favs = new Set(r ? await r.json() : []);
  } catch { favs = new Set(); }
  return favs;
}
async function saveFavs(ids) {
  favs = new Set(ids);
  await (await caches.open(DATA)).put(FAV_KEY, new Response(JSON.stringify([...favs]), { headers: { "content-type": "application/json" } }));
}

self.addEventListener("install", (e) => {
  e.waitUntil((async () => {
    const c = await caches.open(CORE);
    await Promise.all(SHELL.map((p) => c.add(new Request(BASE + "/" + p, { cache: "reload" })).catch(() => null)));   // one miss must not block install
  })());
});

self.addEventListener("activate", (e) => {
  e.waitUntil((async () => {
    for (const k of await caches.keys()) if (k.startsWith("snowwx-shell-") && k !== CORE) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener("message", (e) => {
  const m = e.data || {};
  if (m.type === "SKIP_WAITING") self.skipWaiting();
  else if (m.type === "FAVORITES") e.waitUntil(saveFavs(Array.isArray(m.ids) ? m.ids.slice(0, 50) : []));
  else if (m.type === "PREFETCH") e.waitUntil(prefetch(m.ids || [], e.source));
  else if (m.type === "CLEAR") e.waitUntil((async () => { for (const k of await caches.keys()) if (k.startsWith("snowwx-data")) await caches.delete(k); favs = null; })());
});

async function swr(req, cacheName) {
  const cache = await caches.open(cacheName);
  const hit = await cache.match(req);
  const net = fetch(req).then((r) => { if (r && r.ok) cache.put(req, r.clone()); return r; }).catch(() => null);
  if (hit) { net.catch(() => 0); return hit; }                  // stale-while-revalidate
  return (await net) || new Response(JSON.stringify({ offline: true }), { status: 503, headers: { "content-type": "application/json" } });
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (req.url === PLOTLY) {
    e.respondWith((async () => {
      const cache = await caches.open(LIB);
      return (await cache.match(req)) || fetch(req).then((r) => { if (r.ok) cache.put(req, r.clone()); return r; });
    })());
    return;
  }
  if (url.origin !== self.location.origin || !url.pathname.startsWith(BASE + "/")) return;        // tiles, other CDNs: untouched
  const rel = url.pathname.slice(BASE.length + 1);
  if (rel === "data/meta.json") {          // the freshness clock: network first (a stale copy only when offline), so the banner is honest
    e.respondWith((async () => {
      const cache = await caches.open(DATA), key = new Request(url.origin + url.pathname);
      try { const r = await fetch(req, { cache: "no-cache" }); if (r.ok) cache.put(key, r.clone()); return r; }
      catch { return (await cache.match(key)) || new Response(JSON.stringify({ offline: true }), { status: 503, headers: { "content-type": "application/json" } }); }
    })());
    return;
  }
  if (SMALL_DATA.includes(url.pathname)) { e.respondWith(swr(new Request(url.origin + url.pathname), DATA)); return; }
  const m = /^data\/(points)\/([^/]+)\.json$/.exec(rel);
  if (m && m[2] !== "summary") {
    e.respondWith((async () => {
      const f = await loadFavs();
      const key = new Request(url.origin + url.pathname);
      if (f.has(decodeURIComponent(m[2]))) return swr(key, DATA);           // favorites: kept for offline
      const cache = await caches.open(DATA);
      try { return await fetch(req); } catch { return (await cache.match(key)) || new Response("{}", { status: 503 }); }
    })());
    return;
  }
  if (rel === "data/snotel.geojson") { e.respondWith(swr(new Request(url.origin + url.pathname), DATA)); return; }     // latest obs
  if (SHELL.includes(rel) || req.mode === "navigate" || /\.(html)$/.test(rel) || rel === "") {
    e.respondWith((async () => {
      const cache = await caches.open(CORE);
      const key = new Request(url.origin + url.pathname);
      const hit = await cache.match(key);
      if (hit) return hit;                                                    // precached shell: cache-first (versioned)
      try { return await fetch(req); } catch { return (await cache.match(BASE + "/mine.html")) || Response.error(); }
    })());
  }
});

async function prefetch(ids, client) {
  const cache = await caches.open(DATA);
  let bytes = 0, ok = 0;
  const get = async (p) => {
    try {
      const r = await fetch(BASE + "/" + p, { cache: "no-cache" });
      if (!r.ok) return;
      const b = await r.clone().blob(); bytes += b.size;
      await cache.put(new Request(self.location.origin + BASE + "/" + p), r);
    } catch { /* offline or missing: skip */ }
  };
  await saveFavs(ids);
  for (const p of SMALL_DATA.map((x) => x.slice(BASE.length + 1)).filter((x) => /summary|meta|alerts|avalanche/.test(x))) await get(p);
  for (const id of ids) { await get(`data/points/${encodeURIComponent(id)}.json`); ok++; }
  try { const l = await caches.open(LIB); if (!(await l.match(PLOTLY))) { const r = await fetch(PLOTLY); if (r.ok) { bytes += (await r.clone().blob()).size; await l.put(PLOTLY, r); } } } catch { /* offline */ }
  if (client) client.postMessage({ type: "PREFETCHED", count: ok, bytes });
}
