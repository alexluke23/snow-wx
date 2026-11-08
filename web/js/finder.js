// Powder Finder (finder.html): every ski area ranked by forecast snowfall.
// Plain HTML list first (fast on phones); Leaflet map loads afterwards.
// Data: data/points/summary.json (NBM), data/ndfd/summary.json (NWS),
//       data/nohrsc/ski.json (observed 24 h), data/alerts/index.json (NWS alerts).

(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const getJSON = async (p) => { const r = await fetch(p, { cache: "no-cache" }); if (!r.ok) throw new Error(p); return r.json(); };
  const FAV_KEY = "snowwx.favorites";
  const favs = () => { try { return new Set(JSON.parse(localStorage.getItem(FAV_KEY)) || []); } catch { return new Set(); } };
  const saveFavs = (s) => { try { localStorage.setItem(FAV_KEY, JSON.stringify([...s])); } catch { /* private mode */ } };
  const WINDOWS = [["24h", "24 h"], ["72h", "72 h"], ["7d", "7 d"], ["10d", "10 d"]];
  const fmt = (v) => (v === null || v === undefined ? "–" : v < 0.5 ? (v < 0.05 ? "0" : "<1") : `${Math.round(v)}`);
  const kft = (v) => `${(v / 1000).toFixed(1)}k`;

  // ---- state (URL hash: #w=72h&e=summit&src=nbm&st=UT&r=Wasatch&sort=snow&fav=1)
  const q = new URLSearchParams(location.hash.slice(1));
  const st = { w: q.get("w") || "72h", e: q.get("e") || "summit", src: q.get("src") || "nbm",
               state: q.get("st") || "", region: q.get("r") || "", sort: q.get("sort") || "snow", fav: q.get("fav") === "1" };
  const writeHash = () => {
    const p = new URLSearchParams({ w: st.w, e: st.e, src: st.src, sort: st.sort });
    if (st.state) p.set("st", st.state);
    if (st.region) p.set("r", st.region);
    if (st.fav) p.set("fav", "1");
    history.replaceState(null, "", `#${p}`);
  };

  let nbm = null, nws = null, obs = null, alerts = {}, rows = [];

  function segment(el, items, key, onChange) {
    el.innerHTML = items.map(([v, label, disabled]) =>
      `<button type="button" data-v="${v}" class="${st[key] === v ? "on" : ""}" aria-pressed="${st[key] === v}"${disabled ? " disabled" : ""}>${label}</button>`).join("");
    el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { st[key] = b.dataset.v; onChange(); }));
  }

  function buildRows() {
    const nwsBy = new Map((nws?.areas || []).map((r) => [r.id, r]));
    rows = (nbm?.areas || []).map((a) => {
      const src = st.src === "nws" ? nwsBy.get(a.id) : a;
      const t = src?.[st.e]?.[st.w] || null;               // [mean, lo, hi]
      const o = obs?.areas?.[a.id]?.[st.e]?.sf24 ?? null;
      const sl = src?.snowlvl_min_72h_ft ?? null;
      return { a, snow: t ? t[0] : null, lo: t ? t[1] : null, hi: t ? t[2] : null, obs: o, sl,
               slVsBase: sl === null ? null : sl - a.elev.base, gust: src?.gust_max_72h_mph ?? null,
               alerts: alerts[a.id] || [] };
    });
  }

  function render() {
    writeHash();
    const fav = favs();
    const nwsOnly = st.src === "nws";
    segment($("win"), WINDOWS.map(([v, l]) => [v, l, nwsOnly && (v === "7d" || v === "10d")]), "w", update);
    segment($("elev"), [["summit", "Summit"], ["base", "Base"]], "e", update);
    segment($("src"), [["nbm", "NBM"], ["nws", "NWS", !nws]], "src", () => {
      if (st.src === "nws" && (st.w === "7d" || st.w === "10d")) st.w = "72h";
      update();
    });
    let list = rows.filter((r) => (!st.state || r.a.state === st.state) && (!st.region || r.a.region === st.region)
      && (!st.fav || fav.has(r.a.id)));
    const val = (x) => (x === null || x === undefined ? -1 : x);
    const by = {
      snow: (x, y) => val(y.snow) - val(x.snow) || val(y.hi) - val(x.hi),
      obs: (x, y) => val(y.obs) - val(x.obs),
      sl: (x, y) => (x.slVsBase ?? 1e9) - (y.slVsBase ?? 1e9),
      name: (x, y) => x.a.name.localeCompare(y.a.name),
    }[st.sort];
    list.sort((x, y) => (fav.has(y.a.id) - fav.has(x.a.id)) || by(x, y) || x.a.name.localeCompare(y.a.name));
    const rangeName = st.src === "nws" ? "" : st.w === "24h" ? "NBM 10–90%" : "likely range";
    $("snow-head").textContent = `${WINDOWS.find(([v]) => v === st.w)[1]} snow`;
    $("rows").innerHTML = list.length ? list.map((r) => {
      const c = colorFor(SNOWFALL, r.snow) || "#f4f6f8";
      const rng = r.hi === null || r.hi === undefined ? "" : `<small>${fmt(r.lo)}–${fmt(r.hi)}</small>`;
      const slTxt = r.sl === null ? "–" : r.slVsBase <= 0 ? `<span class="tobase">to base</span>` : `+${kft(r.slVsBase)}`;
      const badge = r.alerts.length ? `<span class="alert-badge ${esc(r.alerts[0].level)}" title="${esc(r.alerts.map((x) => x.event).join(", "))}">${esc(r.alerts[0].short || "Alert")}</span>` : "";
      return `<div class="frow" role="listitem">
        <button type="button" class="star${fav.has(r.a.id) ? " on" : ""}" data-id="${esc(r.a.id)}" aria-pressed="${fav.has(r.a.id)}"
          title="Favorite">${fav.has(r.a.id) ? "★" : "☆"}<span class="sr"> favorite ${esc(r.a.name)}</span></button>
        <span class="who"><a href="area.html#${encodeURIComponent(r.a.id)}">${esc(r.a.name)}</a>${badge}
          <small>${esc(r.a.region)}, ${esc(r.a.state)}</small></span>
        <span class="num snow"><i class="sw" style="background:${c}"></i><b>${fmt(r.snow)}"</b>${rng}</span>
        <span class="details">
          <span class="num" data-label="Obs 24 h">${r.obs === null ? "–" : `${fmt(r.obs)}"`}</span>
          <span class="num" data-label="Snow level" title="${r.sl === null ? "" : `lowest snow level in 72 h: ${Math.round(r.sl).toLocaleString()} ft`}">${slTxt}</span>
          <span class="num" data-label="Gust">${r.gust === null ? "–" : `${Math.round(r.gust)}`}<small> mph</small></span>
        </span>
      </div>`;
    }).join("") : `<p class="hint">No ski areas match these filters.</p>`;
    $("legend-note").textContent = `Most likely snowfall at the ${st.e} (${st.src === "nws" ? "NWS forecast, 2.5 km grid cell" : "NBM"})` +
      `${rangeName ? `; small numbers: ${rangeName}` : ""}. Obs 24 h: NOHRSC snowfall analysis. Snow level: lowest in the next 72 h vs the base.` +
      ` Gust: highest summit gust in 72 h. ★ favorites list first.`;
    $("rows").querySelectorAll(".star").forEach((b) => b.addEventListener("click", () => {
      const s = favs(); s.has(b.dataset.id) ? s.delete(b.dataset.id) : s.add(b.dataset.id); saveFavs(s); render();
    }));
    drawMap(list);
  }

  function update() { buildRows(); render(); }

  // ---- map (Leaflet loads after the list is on screen)
  let map = null, layer = null, leafletP = null;
  const loadLeaflet = () => (leafletP ||= new Promise((resolve, reject) => {
    const css = document.createElement("link");
    css.rel = "stylesheet"; css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    document.head.appendChild(css);
    const s = document.createElement("script");
    s.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"; s.async = true;
    s.onload = () => resolve(window.L); s.onerror = () => reject(new Error("map failed to load"));
    document.head.appendChild(s);
  }));
  let lastFit = "";
  function drawMap(list) {
    if (!map) return;
    layer.clearLayers();
    const fitKey = `${st.state}|${st.region}|${st.fav}`;   // re-frame only when the filter changes
    if (fitKey !== lastFit && list.length) {
      lastFit = fitKey;
      map.fitBounds(L.latLngBounds(list.map((r) => [r.a.lat, r.a.lon])).pad(0.15), { maxZoom: 9 });
    }
    for (const r of [...list].reverse()) {          // biggest last = on top
      const c = colorFor(SNOWFALL, r.snow) || "#f4f6f8";
      L.circleMarker([r.a.lat, r.a.lon], { radius: r.a.major ? 7 : 5, color: "#1b2a4a", weight: 1, fillColor: c, fillOpacity: 0.95 })
        .bindTooltip(`${esc(r.a.name)}: ${fmt(r.snow)}"`, { direction: "top" })
        .bindPopup(`<strong>${esc(r.a.name)}</strong><br>${fmt(r.snow)}" (${esc(st.w)}, ${esc(st.e)})<br><a href="area.html#${encodeURIComponent(r.a.id)}">Forecast →</a>`)
        .addTo(layer);
    }
  }
  async function initMap() {
    try { await loadLeaflet(); } catch { $("fmap").innerHTML = `<p class="hint">Map unavailable.</p>`; return; }
    map = L.map("fmap", { preferCanvas: true, zoomControl: true, attributionControl: true }).setView([41.5, -113], 5);
    L.tileLayer("https://basemap.nationalmap.gov/arcgis/rest/services/USGSShadedReliefOnly/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 13, attribution: "Relief: USGS" }).addTo(map);
    layer = L.layerGroup().addTo(map);
    render();
  }

  async function load() {
    const [a, b, c, d] = await Promise.allSettled([getJSON("data/points/summary.json"), getJSON("data/ndfd/summary.json"),
      getJSON("data/nohrsc/ski.json"), getJSON("data/alerts/index.json")]);
    if (a.status !== "fulfilled") { $("rows").innerHTML = `<p>Forecasts are not available yet.</p>`; $("fresh").textContent = ""; return; }
    nbm = a.value; nws = b.status === "fulfilled" ? b.value : null; obs = c.status === "fulfilled" ? c.value : null;
    alerts = d.status === "fulfilled" ? d.value.areas || {} : {};
    const states = [...new Set(nbm.areas.map((x) => x.state))].sort();
    const regions = [...new Set(nbm.areas.map((x) => x.region))].sort();
    $("state").innerHTML = `<option value="">All</option>${states.map((x) => `<option${x === st.state ? " selected" : ""}>${esc(x)}</option>`).join("")}`;
    $("region").innerHTML = `<option value="">All</option>${regions.map((x) => `<option${x === st.region ? " selected" : ""}>${esc(x)}</option>`).join("")}`;
    $("sort").value = st.sort; $("favonly").checked = st.fav;
    $("state").addEventListener("change", (e) => { st.state = e.target.value; render(); });
    $("region").addEventListener("change", (e) => { st.region = e.target.value; render(); });
    $("sort").addEventListener("change", (e) => { st.sort = e.target.value; render(); });
    $("favonly").addEventListener("change", (e) => { st.fav = e.target.checked; render(); });
    const when = (iso) => new Date(iso).toLocaleString([], { weekday: "short", hour: "numeric", timeZoneName: "short" });
    $("fresh").textContent = `NBM ${when(nbm.issued)} run${nws ? ` · NWS issued ${when(nws.issued)}` : ""}${obs?.snowfall_end ? ` · observed to ${when(obs.snowfall_end)}` : ""}`;
    update();
    (window.requestIdleCallback || ((f) => setTimeout(f, 300)))(initMap, { timeout: 1500 });
  }
  load();
})();
