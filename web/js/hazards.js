// NWS winter hazards layer for the obs map (dev13 item 2).
// Draws the official NWS watch / warning / advisory polygons live from NOAA's map service
// (mapservices.weather.noaa.gov WWA/watch_warn_adv, layer 1 "WatchesWarnings"; public domain, credit NOAA/NWS),
// filtered to the winter product names listed in data/hazards.json (built from the service's CURRENT products by
// pipeline/hazards.py). Vector GeoJSON (~0.2 MB for the whole West) instead of exported image tiles: one request,
// real polygons for popups, our own legend. Loaded after the first paint, only when the layer is on.
// Never a silent blank: if the service fails, or returns nothing while our own alerts index lists winter alerts,
// the sidebar says so and lists the alerts from data/alerts/index.json (api.weather.gov, fetched by our pipeline) instead.

/* global L */
// eslint-disable-next-line no-unused-vars
function SnowHazards(map, { dataBase = "data/", bbox = [-125, 31, -102, 49.5], onStatus = () => {} } = {}) {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const WINTER_RE = /winter|blizzard|snow|ice storm|freez|wind chill|cold|wind|avalanche/i;
  map.createPane("hazards");
  map.getPane("hazards").style.zIndex = 235;           // above the relief, below the roads/towns reference (250)
  const group = L.layerGroup();
  let cfg = null, geo = null, started = false, ready = false, loading = null, loadedAt = 0;
  const state = { status: "idle", count: 0, active: [] };

  const where = () => `prod_type IN (${cfg.products.map((p) => `'${p.name.replace(/'/g, "''")}'`).join(",")})`;
  const colorOf = (name) => (cfg.products.find((p) => p.name === name) || {}).color || "#666666";
  const levelOf = (name) => (cfg.products.find((p) => p.name === name) || {}).level || "advisory";
  const fmtTime = (iso) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? "" : d.toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  };
  const style = (f) => {
    const name = f.properties.prod_type, level = levelOf(name), c = colorOf(name);
    // level is not carried by color alone: warnings have the heaviest outline, watches are dashed, advisories thin
    return { pane: "hazards", color: c, weight: level === "warning" ? 1.6 : level === "watch" ? 1.3 : 0.8, opacity: 0.85,
      dashArray: level === "watch" ? "7 5" : null, fillColor: c, fillOpacity: level === "advisory" ? 0.25 : level === "watch" ? 0.28 : 0.32 };
  };
  // ---- popup: readable product text IN the page (never a link to the api.weather.gov JSON record). Alert text is untrusted external
  // content: everything is written with textContent (no innerHTML), line breaks via CSS pre-wrap, long text scrolls inside the popup.
  const FIELD_LABEL = [["headline", "Headline"], ["area", "Area"], ["description", "Details"], ["instruction", "Instructions"]];
  let idxP = null, detP = null, htP = null;
  const getIdx = () => (idxP ||= fetchJSON(`${dataBase}alerts/index.json`, 10000).catch(() => null));
  const getDet = () => (detP ||= fetchJSON(`${dataBase}alerts/details.json`, 15000).catch(() => null));
  const getHT = () => (htP ||= fetchJSON(`${dataBase}alerts/hazard_text.json`, 15000).catch(() => null));
  /** the alert id ("urn:oid:...") from the service's url field; used ONLY to look the alert up, never as an href */
  const alertId = (u) => { try { return decodeURIComponent(String(u || "").split("/alerts/")[1] || "").split(/[?#]/)[0]; } catch { return ""; } };
  async function sha10(text) {
    const buf = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(text));
    return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 10);
  }
  /** {event, headline, sender, effective, expires, area, description, instruction} from our own alert files (same origin), else null.
   *  hazard_text.json (every active alert of the layer's event types, built from the pipeline's one /alerts/active call) first, then the
   *  older index/details pair (alerts touching a ski area or SNOTEL site). */
  async function localAlert(id) {
    if (!id || !crypto?.subtle) return null;
    const key = await sha10(id), ht = (await getHT())?.alerts?.[key];
    if (ht) return { event: ht.e, headline: ht.h, sender: ht.o, effective: ht.f, expires: ht.x, area: ht.a, description: ht.d, instruction: ht.i };
    const [idx, det] = await Promise.all([getIdx(), getDet()]);
    const a = idx?.alerts?.[key];
    if (!a) return null;
    return { event: a.event, headline: a.headline, sender: a.sender, effective: a.effective, expires: a.expires || a.ends, area: a.area,
      description: det?.[key]?.description, instruction: det?.[key]?.instruction };
  }
  const mk = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  /** DOM for one hazard popup; never uses innerHTML */
  function buildPopup(f) {
    const p = f.properties, wfo = String(p.wfo || "").replace(/^K/, "").toLowerCase();
    const box = mk("div", "hz-pop");
    box.append(mk("strong", "", p.prod_type));
    box.append(mk("div", "hint", `NWS ${levelOf(p.prod_type)}${p.expiration ? ` · expires ${fmtTime(p.expiration)}` : ""}`));
    const body = mk("div", "hz-body"), status = mk("p", "hint", "Loading the full text…");
    body.append(status);
    box.append(body);
    const foot = mk("p", "hz-foot");
    if (/^[a-z]{3,4}$/.test(wfo)) {                                  // a human-readable page: the issuing office on weather.gov
      const a = mk("a", "", "View on weather.gov");
      a.href = `https://www.weather.gov/${wfo}/`; a.target = "_blank"; a.rel = "noopener";
      foot.append(a, document.createTextNode(` (NWS ${String(p.wfo).toUpperCase()}) · `));
    }
    foot.append(mk("span", "hint", "Source: NOAA/NWS"));
    box.append(foot);
    (async () => {
      const id = alertId(p.url);
      const a = await localAlert(id).catch(() => null);                // our own files only: the browser never calls api.weather.gov (dev19)
      body.replaceChildren();
      if (!a) {
        body.append(mk("p", "hint", "The full text is not in our files. Open the issuing office on weather.gov for the current warning, and check your local avalanche center."));
        return;
      }
      const meta = [a.sender, a.effective ? `issued ${fmtTime(a.effective)}` : "", a.expires ? `expires ${fmtTime(a.expires)}` : ""].filter(Boolean).join(" · ");
      if (meta) body.append(mk("div", "hint", meta));
      for (const [k, label] of FIELD_LABEL) if (a[k]) { body.append(mk("div", "hz-label", label)); body.append(mk("div", "hz-text", String(a[k]))); }
    })();
    return box;
  }

  async function fetchJSON(url, ms = 20000) {
    const ctl = new AbortController(), t = setTimeout(() => ctl.abort(), ms);
    try {
      const r = await fetch(url, { signal: ctl.signal, cache: "no-cache" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return await r.json();
    } finally { clearTimeout(t); }
  }

  /** Winter alerts from our own index (api.weather.gov): the fallback list. */
  async function fallbackAlerts() {
    try {
      const idx = await fetchJSON(`${dataBase}alerts/index.json`, 10000);
      const by = {};
      for (const list of Object.values(idx.areas || {})) {
        for (const a of list) if (a.relevant !== false && WINTER_RE.test(a.event)) by[a.event] = (by[a.event] || 0) + 1;
      }
      return Object.entries(by).sort((x, y) => y[1] - x[1]);
    } catch { return []; }
  }

  async function load(force = false) {
    if (loading) return loading;
    if (!force && geo && Date.now() - loadedAt < 10 * 60 * 1000) return null;
    loading = (async () => {
      state.status = "loading"; onStatus({ ...state });
      try {
        if (!cfg) cfg = await fetchJSON(`${dataBase}hazards.json`, 10000);
        const q = new URLSearchParams({ where: where(), geometry: bbox.join(","), geometryType: "esriGeometryEnvelope", inSR: "4326",
          outSR: "4326", spatialRel: "esriSpatialRelIntersects", outFields: "prod_type,expiration,url,wfo", geometryPrecision: "3",
          maxAllowableOffset: "0.02", f: "geojson" });
        // The service sometimes answers a valid but EMPTY result (seen in ~1 of 5 live loads, Nov 2026): never trust a
        // single empty answer. Retry (with a cache-busting parameter) up to 3 times before accepting "no products".
        let gj = null;
        for (let attempt = 0; attempt < 3; attempt++) {
          q.set("_", String(Date.now() + attempt));
          gj = await fetchJSON(`${cfg.service.replace(/\/$/, "")}/${cfg.layer}/query?${q}`);
          if (!gj || gj.error || !Array.isArray(gj.features)) throw new Error("bad response");
          if (gj.features.length) break;
          await new Promise((r) => setTimeout(r, 1200));
        }
        if (geo) group.removeLayer(geo);
        geo = L.geoJSON(gj, { style, renderer: L.canvas({ pane: "hazards" }), onEachFeature: (f, lyr) => lyr.bindPopup(() => buildPopup(f), { maxWidth: 380, className: "hz-popup" }) });
        group.addLayer(geo);
        loadedAt = Date.now();
        const counts = {};
        for (const f of gj.features) counts[f.properties.prod_type] = (counts[f.properties.prod_type] || 0) + 1;
        state.active = Object.entries(counts).map(([name, n]) => ({ name, n, color: colorOf(name), level: levelOf(name) }))
          .sort((a, b) => ["warning", "watch", "advisory"].indexOf(a.level) - ["warning", "watch", "advisory"].indexOf(b.level) || a.name.localeCompare(b.name));
        state.count = gj.features.length;
        state.status = "ok"; state.fallback = null;
        if (!state.count) {                      // empty: legitimate, unless our alerts index disagrees (never a silent blank)
          const fb = await fallbackAlerts();
          if (fb.length) { state.status = "fallback"; state.fallback = fb; state.reason = "the NWS map service returned no polygons"; }
        }
      } catch (err) {
        state.status = "fallback"; state.reason = `the NWS map service did not respond (${String(err.message || err).slice(0, 60)})`;
        state.fallback = await fallbackAlerts();
      }
      state.at = new Date().toISOString();
      onStatus({ ...state });
    })().finally(() => { loading = null; });
    return loading;
  }

  group.on("add", () => { if (ready) load(); });          // switched on after the initial delay: load now
  return {
    group, state,
    /** Called once the page's own data and markers are drawn (never before first paint). */
    start() {
      started = true;
      // after the LCP / main-thread-busy window: ~2 s later, at an idle moment (keeps the obs map's Lighthouse score)
      const go = () => { ready = true; if (map.hasLayer(group)) load(); };
      setTimeout(() => ("requestIdleCallback" in window ? requestIdleCallback(go, { timeout: 4000 }) : go()), 2500);
    },
    refresh: () => load(true),
    /** test hooks (tools/browser_check.py): the popup DOM for a feature, and alert files injected in place of the network */
    popupFor: buildPopup,
    injectAlertFiles(idx, det, ht = null) { idxP = Promise.resolve(idx); detP = Promise.resolve(det); htP = Promise.resolve(ht); },
  };
}
