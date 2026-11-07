// Snow-Wx front end: reads the static JSON/GeoJSON written by the pipeline
// (data/*.json) and draws it on a Leaflet map. No build step required.

(() => {
  "use strict";

  const DATA = "data/";
  const LOW_ZOOM = 7; // below this, station labels shrink to dots

  // ---------------------------------------------------------------- helpers
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v, d = 0, unit = "") =>
    v === null || v === undefined ? "–" : `${Number(v).toFixed(d)}${unit}`;
  const signed = (v, d = 1, unit = "") =>
    v === null || v === undefined ? "–" : `${v > 0 ? "+" : ""}${Number(v).toFixed(d)}${unit}`;
  const localTime = (iso) => {
    if (!iso) return "–";
    const t = new Date(iso);
    return isNaN(t) ? esc(iso) : t.toLocaleString([], {
      month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" });
  };
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");

  async function getJSON(name, bust) {
    const r = await fetch(`${DATA}${name}${bust ? `?v=${encodeURIComponent(bust)}` : ""}`);
    if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
    return r.json();
  }

  // ---------------------------------------------------------------- map
  const map = L.map("map", { zoomControl: true, preferCanvas: false });

  const tiles = (url, attribution, maxZoom = 16) => L.tileLayer(url, { attribution, maxZoom });
  const USGS = "https://basemap.nationalmap.gov/arcgis/rest/services";
  const baseLayers = {
    "Shaded relief (USGS)": tiles(`${USGS}/USGSShadedReliefOnly/MapServer/tile/{z}/{y}/{x}`,
      'Relief: <a href="https://www.usgs.gov/programs/national-geospatial-program/national-map">USGS</a>', 13),
    "Topo (USGS)": tiles(`${USGS}/USGSTopo/MapServer/tile/{z}/{y}/{x}`,
      'Topo: <a href="https://www.usgs.gov/programs/national-geospatial-program/national-map">USGS</a>'),
    "Imagery + topo (USGS)": tiles(`${USGS}/USGSImageryTopo/MapServer/tile/{z}/{y}/{x}`,
      'Imagery: <a href="https://www.usgs.gov/programs/national-geospatial-program/national-map">USGS</a>'),
    "OpenTopoMap": tiles("https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
      '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, SRTM | © <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)', 17),
  };
  baseLayers["Shaded relief (USGS)"].addTo(map);

  const avyLayer = L.geoJSON(null, { style: avyStyle, onEachFeature: avyPopup });
  const snotelLayer = L.layerGroup();
  const asosLayer = L.layerGroup();
  const skiLayer = L.layerGroup();
  avyLayer.addTo(map);
  snotelLayer.addTo(map);
  asosLayer.addTo(map);
  skiLayer.addTo(map);

  L.control.layers(baseLayers, {
    "Ski areas": skiLayer,
    "Avalanche danger": avyLayer,
    "SNOTEL": snotelLayer,
    "ASOS / AWOS (wind, temp)": asosLayer,
  }, { collapsed: window.innerWidth < 800 }).addTo(map);
  L.control.scale({ imperial: true, metric: true }).addTo(map);

  const setZoomClass = () =>
    map.getContainer().classList.toggle("z-low", map.getZoom() < LOW_ZOOM);
  map.on("zoomend", setZoomClass);

  // ---------------------------------------------------------------- declutter
  // From LOW_ZOOM up, labels are placed greedily by priority; a label that
  // would overlap one already placed collapses to a dot (SNOTEL) or a bare
  // wind barb (ASOS). Every marker stays on the map and clickable.
  const CELL = 64; // spatial-hash cell size, px

  function labelItems() {
    const items = [];
    const size = map.getSize(), margin = 60;
    const onScreen = (pt) => pt.x > -margin && pt.y > -margin && pt.x < size.x + margin && pt.y < size.y + margin;
    if (map.hasLayer(snotelLayer)) {
      const spec = SNOTEL_VARS[currentVar];
      snotelLayer.eachLayer((m) => {
        const el = m.getElement()?.firstElementChild;
        const pt = map.latLngToContainerPoint(m.getLatLng());
        if (!el || !onScreen(pt)) return;
        const v = m.options.value;
        const text = v === null || v === undefined ? "–" : fmtValue(spec, v);
        const w = Math.max(26, 10 + 6.6 * text.length), h = 16;
        const prio = m.options.triplet === selected ? 1e9
          : v === null || v === undefined ? 1 : 3 + Math.min(Math.abs(v), 1e6) / 1e6;
        items.push({ m, el, kind: "snotel", prio,
          box: [pt.x - w / 2 - 1, pt.y - h / 2 - 1, pt.x + w / 2 + 1, pt.y + h / 2 + 1] });
      });
    }
    if (map.hasLayer(asosLayer)) {
      for (const [id, m] of asosMarkers) {
        const el = m.getElement()?.firstElementChild;
        const t = m.options.tempLabel;
        const pt = map.latLngToContainerPoint(m.getLatLng());
        if (!el || t === "" || !onScreen(pt)) continue;
        // .asos-temp sits up-left of the station: right edge 4 px left of it, bottom 2 px above.
        const w = 7 * String(t).length + 2;
        const prio = selected === `asos:${id}` ? 1e9 : m.options.stale ? 0.5 : 2;
        items.push({ m, el, kind: "asos", prio, box: [pt.x - 4 - w, pt.y - 16, pt.x - 3, pt.y - 1] });
      }
    }
    return items;
  }

  function declutter() {
    const items = labelItems();
    if (map.getZoom() < LOW_ZOOM) {      // z-low CSS already shows dots / hides temps
      for (const it of items) it.el.classList.remove("dot");
      return;
    }
    items.sort((a, b) => b.prio - a.prio);
    const grid = new Map();
    const cells = (b) => {
      const out = [];
      for (let cx = Math.floor(b[0] / CELL); cx <= Math.floor(b[2] / CELL); cx++)
        for (let cy = Math.floor(b[1] / CELL); cy <= Math.floor(b[3] / CELL); cy++) out.push(`${cx},${cy}`);
      return out;
    };
    const hits = (a, b) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
    for (const it of items) {
      const keys = cells(it.box);
      const blocked = keys.some((k) => (grid.get(k) || []).some((b) => hits(it.box, b)));
      it.el.classList.toggle("dot", blocked);
      it.m.setZIndexOffset(blocked ? -2000 : it.kind === "snotel" ? 1000 : 500);
      if (!blocked) for (const k of keys) (grid.get(k) || grid.set(k, []).get(k)).push(it.box);
    }
  }

  let declutterTimer = null;
  const scheduleDeclutter = () => { clearTimeout(declutterTimer); declutterTimer = setTimeout(declutter, 50); };
  map.on("zoomend moveend overlayadd overlayremove", scheduleDeclutter);

  // ---------------------------------------------------------------- avalanche
  function avyStyle(f) {
    const p = f.properties;
    return {
      color: p.warning ? "#b00020" : "#333",
      weight: p.warning ? 3 : 1,
      dashArray: p.expired ? "4 4" : null,
      fillColor: p.color || "#ccc",
      fillOpacity: p.danger_level > 0 ? 0.45 : 0.15,
    };
  }

  function avyPopup(f, layer) {
    const p = f.properties;
    const lvl = p.danger_level || 0;
    const badge = `<span class="danger" style="background:${esc(p.color)};color:${DANGER_TEXT[lvl] || "#111"}">
      ${lvl > 0 ? `${lvl} – ` : ""}${esc(p.danger)}</span>`;
    const note = p.expired
      ? "<p><em>This rating has expired. Check the center for the current forecast.</em></p>"
      : (lvl === 0 ? "<p><em>No current rating. Check the center for information.</em></p>" : "");
    layer.bindPopup(`
      <strong>${esc(p.name)}</strong><br>
      <span class="hint">${esc(p.center || p.center_id)} · ${esc(p.state)}</span>
      <p>${badge}${p.warning ? ' <strong style="color:#b00020">AVALANCHE WARNING</strong>' : ""}</p>
      ${lvl > 0 && p.travel_advice ? `<p>${esc(p.travel_advice)}</p>` : ""}
      ${note}
      <p class="hint">Issued ${localTime(p.start_date)}<br>Expires ${localTime(p.end_date)}</p>
      <a href="${esc(safeUrl(p.link))}" target="_blank" rel="noopener">Read the full forecast →</a>`);
  }

  // ---------------------------------------------------------------- URL hash state
  // #v=<SNOTEL variable>&map=<zoom>/<lat>/<lon>&s=<station>
  // s is a SNOTEL triplet (766:UT:SNTL), asos:<id> (asos:SLC) or area:<id> (area:alta-ski-area).
  function readHash() {
    const q = new URLSearchParams(location.hash.replace(/^#/, ""));
    const out = { v: q.get("v"), s: q.get("s") };
    const m = (q.get("map") || "").split("/").map(Number);
    if (m.length === 3 && m.every(Number.isFinite)) out.view = { zoom: m[0], center: [m[1], m[2]] };
    return out;
  }

  let selected = null;     // station key kept in the hash
  let hashReady = false;   // don't write the hash before the first view is set
  function writeHash() {
    if (!hashReady) return;
    const c = map.getCenter();
    const parts = [`v=${encodeURIComponent(currentVar)}`,
      `map=${map.getZoom()}/${c.lat.toFixed(4)}/${c.lng.toFixed(4)}`];
    if (selected) parts.push(`s=${encodeURIComponent(selected).replace(/%3A/gi, ":")}`);
    const h = `#${parts.join("&")}`;
    if (h !== location.hash) history.replaceState(null, "", h);
  }
  map.on("moveend", writeHash);

  // ---------------------------------------------------------------- SNOTEL
  let snotelData = null;
  let currentVar = "depth_24h";
  const initialHash = readHash();
  if (initialHash.v && SNOTEL_VARS[initialHash.v]) currentVar = initialHash.v;

  function drawSnotel() {
    snotelLayer.clearLayers();
    if (!snotelData) return;
    const spec = SNOTEL_VARS[currentVar];
    for (const f of snotelData.features) {
      const p = f.properties;
      const v = p[currentVar];
      const bg = colorFor(spec, v);
      const sel = p.triplet === selected ? " sel" : "";
      const html = bg
        ? `<div class="stn${sel}" style="background:${bg};color:${textOn(bg)}">${fmtValue(spec, v)}</div>`
        : `<div class="stn na${sel}">–</div>`;
      const [lon, lat] = f.geometry.coordinates;
      const m = L.marker([lat, lon], {
        icon: L.divIcon({ html, className: "", iconSize: null }),
        title: `${p.name} (${num(p.elev_ft, 0)} ft)`,
        triplet: p.triplet,
        value: bg ? v : null,
        zIndexOffset: bg ? 1000 : -1000,
      });
      m.on("click", () => selectSnotel(p));
      snotelLayer.addLayer(m);
    }
    drawLegend(spec);
    scheduleDeclutter();
  }

  function selectSnotel(p) {
    selected = p.triplet;
    for (const el of document.querySelectorAll(".stn.sel")) el.classList.remove("sel");
    snotelLayer.eachLayer((m) => {
      if (m.options.triplet === p.triplet) m.getElement()?.firstElementChild?.classList.add("sel");
    });
    writeHash();
    scheduleDeclutter();   // the selected station always keeps its label
    showStation(p);
  }

  function drawLegend(spec) {
    const items = spec.colors.map((c, i) => {
      const lo = i === 0 ? null : spec.bins[i - 1];
      const hi = i < spec.bins.length ? spec.bins[i] : null;
      const txt = lo === null ? `< ${hi}` : hi === null ? `≥ ${lo}` : `${lo}`;
      return `<div class="sw" style="background:${c};color:${textOn(c)}">${txt}</div>`;
    });
    $("legend").innerHTML = items.join("");
  }

  async function showStation(p) {
    const box = $("station");
    box.innerHTML = `
      <h2>${esc(p.name)}</h2>
      <div class="sub">SNOTEL ${esc(p.triplet)} · ${num(p.elev_ft, 0)} ft ·
        obs ${esc(p.obs_time || "–")} (local std. time)</div>
      <table class="metrics">
        <tr><td>Snow depth</td><td>${num(p.depth_in, 0, '"')}</td></tr>
        <tr><td>Depth change 24 / 72 hr</td><td>${signed(p.depth_24h, 0, '"')} / ${signed(p.depth_72h, 0, '"')}</td></tr>
        <tr><td>SWE</td><td>${num(p.swe_in, 1, '"')} (${num(p.pct_median, 0)}% of median${
          p.pct_median == null && p.median_swe_in != null ? `; median ${num(p.median_swe_in, 1, '"')}` : ""})</td></tr>
        <tr><td>SWE change 24 / 72 hr</td><td>${signed(p.swe_24h, 1, '"')} / ${signed(p.swe_72h, 1, '"')}</td></tr>
        <tr><td>Precip 24 hr</td><td>${num(p.precip_24h, 2, '"')}</td></tr>
        <tr><td>Temp now (24-hr hi / lo)</td><td>${num(p.temp_f, 0, "°")} (${num(p.tmax_24h, 0, "°")} / ${num(p.tmin_24h, 0, "°")})</td></tr>
      </table>
      <div id="chart"></div>
      <p class="hint"><a href="https://wcc.sc.egov.usda.gov/nwcc/site?sitenum=${encodeURIComponent(p.id)}"
        target="_blank" rel="noopener">NRCS station page →</a></p>`;
    if (window.innerWidth < 800) box.scrollIntoView({ behavior: "smooth" });
    try {
      const ts = await getJSON(p.file, lastUpdated);
      drawChart(ts);
    } catch (e) {
      $("chart").textContent = `Chart unavailable (${e.message})`;
    }
  }

  function drawChart(ts) {
    const x = ts.times;
    const smooth = ts.SNWD_med3;   // 3-hr median; older data files may lack it
    const traces = [
      { x, y: ts.SNWD, name: smooth ? "Depth, raw" : "Depth (in)", type: "scatter", mode: "lines",
        line: { color: "#2171b5", width: smooth ? 1 : 2 }, opacity: smooth ? 0.35 : 1, yaxis: "y" },
      ...(smooth ? [{ x, y: smooth, name: "Depth (in, 3-hr median)", type: "scatter", mode: "lines",
        line: { color: "#2171b5", width: 2.2 }, yaxis: "y" }] : []),
      { x, y: ts.WTEQ, name: "SWE (in)", type: "scatter", mode: "lines",
        line: { color: "#238b45", width: 2 }, yaxis: "y2" },
      { x, y: ts.TOBS, name: "Temp (°F)", type: "scatter", mode: "lines",
        line: { color: "#d6604d", width: 1.5 }, yaxis: "y3" },
    ];
    const layout = {
      margin: { l: 44, r: 44, t: 10, b: 36 },
      showlegend: true, legend: { orientation: "h", y: -0.18, font: { size: 11 } },
      xaxis: { anchor: "y3", type: "date", tickfont: { size: 10 } },
      yaxis: { domain: [0.42, 1], title: { text: "Depth", font: { size: 11 } }, tickfont: { size: 10 } },
      yaxis2: { overlaying: "y", side: "right", title: { text: "SWE", font: { size: 11 } },
                tickfont: { size: 10 }, showgrid: false },
      yaxis3: { domain: [0, 0.32], title: { text: "°F", font: { size: 11 } }, tickfont: { size: 10 } },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y3", y0: 32, y1: 32,
                 line: { color: "#888", width: 1, dash: "dot" } }],
      hovermode: "x unified",
    };
    Plotly.newPlot("chart", traces, layout, { displayModeBar: false, responsive: true });
  }

  $("var-select").innerHTML = Object.entries(SNOTEL_VARS)
    .map(([k, s]) => `<option value="${k}">${esc(s.label)}</option>`).join("");
  $("var-select").value = currentVar;
  $("var-select").addEventListener("change", (e) => {
    currentVar = e.target.value; drawSnotel(); writeHash();
  });

  // ---------------------------------------------------------------- ASOS
  // Wind barb pointing toward the direction the wind blows FROM, with
  // barbs on the clockwise side (Northern Hemisphere convention).
  function barbSVG(kt, dir) {
    const c = 22, col = "#14202e";
    if (kt === null || kt === undefined) return "";
    if (kt < 3) {
      return `<svg width="44" height="44"><circle cx="${c}" cy="${c}" r="4" fill="none" stroke="${col}" stroke-width="1.5"/></svg>`;
    }
    let s = Math.round(kt / 5) * 5;
    const parts = [`<line x1="${c}" y1="${c}" x2="${c}" y2="2"/>`];
    let y = 2;
    while (s >= 50) { parts.push(`<polygon points="${c},${y} ${c + 9},${y + 2.5} ${c},${y + 5}" fill="${col}"/>`); y += 6; s -= 50; }
    while (s >= 10) { parts.push(`<line x1="${c}" y1="${y}" x2="${c + 9}" y2="${y - 3}"/>`); y += 3.5; s -= 10; }
    if (s >= 5) {
      if (y === 2) y += 3.5; // lone half barb sits one step in from the end
      parts.push(`<line x1="${c}" y1="${y}" x2="${c + 4.5}" y2="${y - 1.5}"/>`);
    }
    parts.push(`<circle cx="${c}" cy="${c}" r="2" fill="${col}"/>`);
    return `<svg width="44" height="44"><g transform="rotate(${dir || 0} ${c} ${c})" stroke="${col}" stroke-width="1.5">${parts.join("")}</g></svg>`;
  }

  const asosMarkers = new Map();  // id -> marker

  function drawAsos(fc) {
    asosLayer.clearLayers();
    asosMarkers.clear();
    for (const f of fc.features) {
      const p = f.properties;
      const [lon, lat] = f.geometry.coordinates;
      // Whole degrees on the map (short labels overlap less); decimals in the popup.
      const tLabel = p.temp_f === null || p.temp_f === undefined ? "" : Math.round(p.temp_f);
      const html = `<div class="asos${p.stale ? " stale" : ""}">${barbSVG(p.wind_kt, p.wind_dir)}
        <span class="asos-temp">${tLabel}</span></div>`;
      const m = L.marker([lat, lon], {
        icon: L.divIcon({ html, className: "", iconSize: null }), title: p.name,
        tempLabel: tLabel, stale: !!p.stale,
      });
      m.bindPopup(`
        <strong>${esc(p.id)} – ${esc(p.name)}</strong><br>
        <span class="hint">${localTime(p.valid_utc)}${p.stale ? " · <strong>stale</strong>" : ""}</span>
        <table class="metrics">
          <tr><td>Temp / Dewpoint</td><td>${num(p.temp_f, 1, "°F")} / ${num(p.dewp_f, 1, "°F")}</td></tr>
          <tr><td>Wind</td><td>${num(p.wind_dir, 0, "°")} @ ${num(p.wind_kt, 0, " kt")}${p.gust_kt ? ` G${num(p.gust_kt, 0)}` : ""}</td></tr>
          <tr><td>Visibility</td><td>${num(p.vis_mi, 1, " mi")}</td></tr>
          <tr><td>Today hi / lo</td><td>${num(p.tmax_f, 0, "°")} / ${num(p.tmin_f, 0, "°")}</td></tr>
          <tr><td>Precip today</td><td>${num(p.precip_today_in, 2, '"')}</td></tr>
        </table>
        ${p.metar ? `<code style="font-size:11px">${esc(p.metar)}</code>` : ""}`);
      m.on("popupopen", () => { selected = `asos:${p.id}`; writeHash(); });
      m.on("popupclose", () => { if (selected === `asos:${p.id}`) { selected = null; writeHash(); } });
      asosLayer.addLayer(m);
      asosMarkers.set(String(p.id), m);
    }
    scheduleDeclutter();
  }

  // ---------------------------------------------------------------- ski areas
  // data/ski_areas.json (pipeline catalog; OpenSkiMap/OSM, ODbL). Triangle markers,
  // larger for the major areas; popup links to the area page.
  const skiMarkers = new Map();
  const ft = (v) => (v === null || v === undefined ? "–" : `${Number(v).toLocaleString()} ft`);

  function drawSkiAreas(cat) {
    skiLayer.clearLayers();
    skiMarkers.clear();
    for (const a of cat?.areas || []) {
      const size = a.major ? 16 : 11;
      const icon = L.divIcon({
        className: `ski${a.major ? " major" : ""}`, iconSize: [size, size], iconAnchor: [size / 2, size / 2],
        html: `<svg viewBox="0 0 16 16" width="${size}" height="${size}" aria-hidden="true">` +
          `<path d="M8 1.5 15 14.5H1z"/></svg>` });
      const m = L.marker([a.summit.lat, a.summit.lon], { icon, title: a.name, zIndexOffset: 1500,
        keyboard: true, alt: `${a.name} ski area` });
      const avy = a.avalanche ? `<br>Avalanche zone: ${esc(a.avalanche.zone)}` : "";
      m.bindPopup(`<strong>${esc(a.name)}</strong>
        <div class="hint">${esc(a.region)}, ${esc(a.state)}</div>
        <p>Base ${ft(a.base.elev_ft)} · Summit ${ft(a.summit.elev_ft)}<br>
        Vertical ${ft(a.vertical_ft)} · ${a.lifts} lifts${avy}</p>
        <a href="area.html#${encodeURIComponent(a.id)}">Forecast and details →</a>
        ${a.url ? `<br><a href="${esc(safeUrl(a.url))}" target="_blank" rel="noopener">Area website</a>` : ""}`);
      m.on("popupopen", () => { selected = `area:${a.id}`; writeHash(); });
      m.on("popupclose", () => { if (selected === `area:${a.id}`) { selected = null; writeHash(); } });
      m.addTo(skiLayer);
      skiMarkers.set(a.id, m);
    }
    if (cat?.attribution) map.attributionControl.addAttribution(`Ski areas ${esc(cat.attribution)}`);
  }

  // ---------------------------------------------------------------- search
  // One list of ski areas + SNOTEL + ASOS stations, matched on name or ID.
  let stationIndex = [];

  function buildIndex(sno, aso, ski) {
    stationIndex = [];
    for (const a of ski?.areas || []) {
      stationIndex.push({ key: `area:${a.id}`, kind: "AREA", ids: [a.id], name: a.name,
        sub: `Ski area · ${a.region}, ${a.state}`, lat: a.summit.lat, lon: a.summit.lon });
    }
    for (const f of sno?.features || []) {
      const p = f.properties, [lon, lat] = f.geometry.coordinates;
      stationIndex.push({ key: p.triplet, kind: "SNOTEL", ids: [String(p.id), p.triplet], name: p.name,
        sub: `SNOTEL ${p.id} · ${p.state || ""} · ${num(p.elev_ft, 0)} ft`, lat, lon, props: p });
    }
    for (const f of aso?.features || []) {
      const p = f.properties, [lon, lat] = f.geometry.coordinates, id = String(p.id);
      const ids = /^[A-Z0-9]{3}$/.test(id) ? [id, `K${id}`] : [id];  // accept ICAO "KSLC"
      stationIndex.push({ key: `asos:${id}`, kind: "ASOS", ids, name: p.name || id,
        sub: `ASOS ${id}${p.stale ? " · stale" : ""}`, lat, lon });
    }
  }

  function searchStations(query, limit = 10) {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const hits = [];
    for (const s of stationIndex) {
      const ids = s.ids.map((x) => x.toLowerCase()), name = s.name.toLowerCase();
      let score = -1;
      if (ids.includes(q)) score = 0;
      else if (name.startsWith(q) || ids.some((x) => x.startsWith(q))) score = 1;
      else if (name.split(/[\s\-/()]+/).some((w) => w.startsWith(q))) score = 2;
      else if (name.includes(q)) score = 3;
      if (score >= 0) hits.push([score, s]);
    }
    hits.sort((a, b) => a[0] - b[0] || a[1].name.localeCompare(b[1].name));
    return hits.slice(0, limit).map((h) => h[1]);
  }

  function selectStation(s, { fly = true } = {}) {
    if (fly) map.setView([s.lat, s.lon], Math.max(map.getZoom(), 10));
    if (s.kind === "AREA") {
      if (!map.hasLayer(skiLayer)) skiLayer.addTo(map);
      skiMarkers.get(s.key.slice(5))?.openPopup();
    } else if (s.kind === "SNOTEL") {
      if (!map.hasLayer(snotelLayer)) snotelLayer.addTo(map);
      selectSnotel(s.props);
    } else {
      if (!map.hasLayer(asosLayer)) asosLayer.addTo(map);
      asosMarkers.get(s.key.slice(5))?.openPopup();
    }
  }

  (function setupSearch() {
    const input = $("search"), list = $("search-results");
    let results = [], active = -1;
    const close = () => { list.hidden = true; input.setAttribute("aria-expanded", "false"); active = -1; };
    const render = () => {
      if (!input.value.trim()) return close();
      list.innerHTML = results.length
        ? results.map((s, i) => `<li role="option" data-i="${i}" class="${i === active ? "active" : ""}">
            ${esc(s.name)}<span class="kind">${esc(s.sub)}</span></li>`).join("")
        : `<li class="empty">No match</li>`;
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
    };
    const choose = (i) => {
      const s = results[i];
      if (!s) return;
      input.value = s.name;
      close();
      input.blur();
      selectStation(s);
    };
    input.addEventListener("input", () => { results = searchStations(input.value); active = results.length ? 0 : -1; render(); });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (!results.length) return;
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : results.length - 1)) % results.length;
        render();
        list.querySelector("li.active")?.scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter") {
        e.preventDefault();
        choose(active >= 0 ? active : 0);
      } else if (e.key === "Escape") {
        close();
      }
    });
    // mousedown (not click) so the choice lands before the input's blur closes the list
    list.addEventListener("mousedown", (e) => {
      const li = e.target.closest("li[data-i]");
      if (li) { e.preventDefault(); choose(Number(li.dataset.i)); }
    });
    input.addEventListener("blur", () => setTimeout(close, 100));
  })();

  // ---------------------------------------------------------------- load
  let lastUpdated = "";

  // One line per source: obs fetched by this build plus products merged in from
  // other jobs (NBM points, model maps, NOHRSC), each with its own time.
  const SOURCE_LABEL = { snotel: "SNOTEL", asos: "ASOS", avalanche: "Avalanche", points: "NBM forecasts",
    models: "Model maps", nohrsc: "NOHRSC snow" };
  const UNIT = { snotel: "stations", asos: "stations", avalanche: "zones" };
  const ago = (iso) => {
    if (!iso) return "";
    const m = (Date.now() - new Date(iso)) / 6e4;
    return m < 90 ? `${Math.max(1, Math.round(m))} min ago` : m < 2880 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`;
  };
  function drawStatus(meta) {
    const items = Object.entries(meta.sources || {}).map(([name, s]) => {
      const label = SOURCE_LABEL[name] || name;
      const what = s.ok ? [s.count !== undefined ? `${s.count} ${s.unit || UNIT[name] || ""}`.trim() : "", s.detail || ""]
        .filter(Boolean).join(" · ") : `failed (${esc(s.error)})`;
      const when = s.at ? ` <span class="hint" title="${esc(s.at)}">${ago(s.at)}</span>` : "";
      return `<li class="${s.ok ? "ok" : "bad"}">${esc(label)}: ${esc(what)}${when}</li>`;
    });
    $("status").innerHTML = items.join("");
  }

  async function load() {
    let meta = null;
    try {
      meta = await getJSON("meta.json", Date.now());
      lastUpdated = meta.generated_at;
      $("updated").textContent = `Updated ${localTime(meta.generated_at)}`;
      drawStatus(meta);
    } catch (e) {
      $("updated").textContent = "No data yet – run the pipeline (see README).";
    }
    // A view in the URL hash wins over the configured default.
    if (initialHash.view) map.setView(initialHash.view.center, initialHash.view.zoom);
    else map.setView(meta?.region?.map_center || [41.5, -113], meta?.region?.map_zoom || 5);
    setZoomClass();

    const [avy, sno, aso, ski] = await Promise.allSettled([
      getJSON("avalanche.geojson", lastUpdated),
      getJSON("snotel.geojson", lastUpdated),
      getJSON("asos.geojson", lastUpdated),
      getJSON("ski_areas.json", lastUpdated),
    ]);
    if (avy.status === "fulfilled") avyLayer.addData(avy.value);
    if (sno.status === "fulfilled") { snotelData = sno.value; drawSnotel(); }
    if (aso.status === "fulfilled") drawAsos(aso.value);
    if (ski.status === "fulfilled") drawSkiAreas(ski.value);
    buildIndex(sno.value, aso.value, ski.value);

    hashReady = true;
    openFromHash(initialHash, false);
    writeHash();
  }

  function openFromHash(h, fly) {
    if (!h.s) return;
    const s = stationIndex.find((x) => x.key === h.s);
    if (s) selectStation(s, { fly: fly || !h.view });
  }

  // Hand-edited hashes / pasted links while the page is open.
  window.addEventListener("hashchange", () => {
    const h = readHash();
    if (h.v && SNOTEL_VARS[h.v] && h.v !== currentVar) {
      currentVar = h.v; $("var-select").value = currentVar; drawSnotel();
    }
    if (h.view) map.setView(h.view.center, h.view.zoom);
    if (h.s && h.s !== selected) openFromHash(h, false);
  });

  load();
})();
