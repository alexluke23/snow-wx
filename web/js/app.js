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

  // Plotly is only needed when a station chart opens: load it then (once).
  let plotlyPromise = null;
  const loadPlotly = () => (plotlyPromise ||= new Promise((resolve, reject) => {
    if (window.Plotly) return resolve(window.Plotly);
    const sc = document.createElement("script");
    sc.src = "https://cdn.plot.ly/plotly-basic-2.35.2.min.js"; sc.async = true;
    sc.onload = () => resolve(window.Plotly); sc.onerror = () => reject(new Error("chart library failed to load"));
    document.head.appendChild(sc);
  }));

  async function getJSON(name, bust) {
    const r = await fetch(`${DATA}${name}${bust ? `?v=${encodeURIComponent(bust)}` : ""}`);
    if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
    return r.json();
  }

  // ---------------------------------------------------------------- map
  const map = L.map("map", { zoomControl: true, preferCanvas: false });
  window.snowwx = { map, ready: false };   // debugging / benchmark handle

  // base maps with overzoom and automatic fallback (basemap.js, PLAN.md §6-C)
  const baseLayers = snowBasemaps(map).layers;

  const avyLayer = L.geoJSON(null, { style: avyStyle, onEachFeature: avyPopup });
  // NOHRSC / SNODAS raster overlays (overlays.js), one at a time; o= in the URL hash.
  const overlays = SnowOverlays(map, { panel: document.getElementById("overlays"),
    onChange: () => { avyLayer.setStyle(avyStyle); writeHash(); } });

  // SNOTEL, ASOS and ski areas share one canvas (points-canvas.js); the layer
  // control gets one toggle per group.
  const points = new PointsCanvas({ lowZoom: LOW_ZOOM });
  const snotelLayer = points.toggleLayer("snotel");
  const asosLayer = points.toggleLayer("asos");
  const skiLayer = points.toggleLayer("ski");
  avyLayer.addTo(map);
  points.addTo(map);
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

  // ---------------------------------------------------------------- canvas symbols
  // Drawn by PointsCanvas. From LOW_ZOOM up, labels are placed greedily by
  // priority (once per zoom level); a label that would overlap one already placed
  // collapses to a dot (SNOTEL) or a bare wind barb (ASOS). Everything stays clickable.
  const FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
  const LABEL_FONT = `600 11px ${FONT}`, TEMP_FONT = `700 11px ${FONT}`;
  const measure = document.createElement("canvas").getContext("2d");
  const textWidth = (t, font) => { measure.font = font; return measure.measureText(t).width; };
  const rrect = (ctx, x, y, w, h, r) => {
    ctx.beginPath();
    if (ctx.roundRect) ctx.roundRect(x, y, w, h, r); else ctx.rect(x, y, w, h);
  };

  function snotelItem(f, spec) {
    const p = f.properties, [lon, lat] = f.geometry.coordinates;
    const v = p[currentVar], bg = colorFor(spec, v);
    const text = bg ? fmtValue(spec, v) : "–";
    const w = Math.max(26, Math.ceil(textWidth(text, LABEL_FONT)) + 10), h = 16;
    return {
      group: "snotel", lat, lon, props: p, title: `${p.name} (${num(p.elev_ft, 0)} ft)`,
      labelBox: [-w / 2 - 1, -h / 2 - 1, w / 2 + 1, h / 2 + 1],
      prio: () => (p.triplet === selected ? 1e9 : bg ? 3 + Math.min(Math.abs(v), 1e6) / 1e6 : 1),
      hit: (full) => (full ? [-w / 2 - 2, -h / 2 - 2, w / 2 + 2, h / 2 + 2] : [-7, -7, 7, 7]),
      draw(ctx, x, y, full) {
        const sel = p.triplet === selected;
        ctx.lineWidth = 1;
        ctx.strokeStyle = "rgba(0,0,0,.45)";
        ctx.fillStyle = bg || "#fff";
        if (full) {
          rrect(ctx, x - w / 2, y - h / 2, w, h, 3); ctx.fill(); ctx.stroke();
          ctx.fillStyle = bg ? textOn(bg) : "#888";
          ctx.font = LABEL_FONT; ctx.textAlign = "center"; ctx.textBaseline = "middle";
          ctx.fillText(text, x, y + 0.5);
          if (sel) { ctx.strokeStyle = "#e6007e"; ctx.lineWidth = 2; rrect(ctx, x - w / 2 - 3, y - h / 2 - 3, w + 6, h + 6, 4); ctx.stroke(); }
        } else {
          ctx.beginPath(); ctx.arc(x, y, 5.5, 0, 2 * Math.PI); ctx.fill(); ctx.stroke();
          if (sel) { ctx.strokeStyle = "#e6007e"; ctx.lineWidth = 2; ctx.beginPath(); ctx.arc(x, y, 8.5, 0, 2 * Math.PI); ctx.stroke(); }
        }
      },
      onClick: () => selectSnotel(p),
    };
  }

  // Same geometry as the old SVG barbs: staff 20 px toward the wind direction.
  function drawBarb(ctx, x, y, kt, dir, scale) {
    if (kt === null || kt === undefined) return;
    ctx.save();
    ctx.translate(x, y); ctx.scale(scale, scale);
    ctx.strokeStyle = ctx.fillStyle = "#14202e"; ctx.lineWidth = 1.5;
    if (kt < 3) { ctx.beginPath(); ctx.arc(0, 0, 4, 0, 2 * Math.PI); ctx.stroke(); ctx.restore(); return; }
    ctx.rotate(((dir || 0) * Math.PI) / 180);
    let s = Math.round(kt / 5) * 5, yy = -20;
    ctx.beginPath(); ctx.moveTo(0, 0); ctx.lineTo(0, -20); ctx.stroke();
    while (s >= 50) { ctx.beginPath(); ctx.moveTo(0, yy); ctx.lineTo(9, yy + 2.5); ctx.lineTo(0, yy + 5); ctx.closePath(); ctx.fill(); yy += 6; s -= 50; }
    while (s >= 10) { ctx.beginPath(); ctx.moveTo(0, yy); ctx.lineTo(9, yy - 3); ctx.stroke(); yy += 3.5; s -= 10; }
    if (s >= 5) { if (yy === -20) yy += 3.5; ctx.beginPath(); ctx.moveTo(0, yy); ctx.lineTo(4.5, yy - 1.5); ctx.stroke(); }
    ctx.beginPath(); ctx.arc(0, 0, 2, 0, 2 * Math.PI); ctx.fill();
    ctx.restore();
  }

  function asosItem(f) {
    const p = f.properties, [lon, lat] = f.geometry.coordinates, id = String(p.id);
    // Whole degrees on the map (short labels overlap less); decimals in the popup.
    const t = p.temp_f === null || p.temp_f === undefined ? "" : String(Math.round(p.temp_f));
    const w = t ? Math.ceil(textWidth(t, TEMP_FONT)) + 2 : 0;
    const it = {
      group: "asos", lat, lon, props: p, title: `${p.id} – ${p.name}`,
      labelBox: t ? [-4 - w - 1, -15, -3, -1] : null,
      prio: () => (selected === `asos:${id}` ? 1e9 : p.stale ? 0.5 : 2),
      hit: () => [-12, -12, 12, 12],
      draw(ctx, x, y, full, z) {
        ctx.globalAlpha = p.stale ? 0.35 : 1;
        const low = z < LOW_ZOOM;
        drawBarb(ctx, x, y, p.wind_kt, p.wind_dir, low ? 0.7 : 1);
        if (full && t && !low) {
          ctx.font = TEMP_FONT; ctx.textAlign = "right"; ctx.textBaseline = "bottom";
          ctx.lineWidth = 3; ctx.strokeStyle = "rgba(255,255,255,.9)"; ctx.strokeText(t, x - 4, y - 2);
          ctx.fillStyle = "#c0262d"; ctx.fillText(t, x - 4, y - 2);
        }
        ctx.globalAlpha = 1;
      },
      onClick: () => openAsos(it),
    };
    return it;
  }

  function skiItem(a) {
    const size = a.major ? 16 : 11;
    const it = {
      group: "ski", top: true, lat: a.summit.lat, lon: a.summit.lon, area: a, title: `${a.name} ski area`,
      labelBox: null, prio: () => 0,
      hit: () => [-size / 2 - 3, -size / 2 - 3, size / 2 + 3, size / 2 + 3],
      draw(ctx, x, y) {
        const h = size * 0.85;
        ctx.beginPath(); ctx.moveTo(x, y - h / 2 - 1); ctx.lineTo(x + size / 2, y + h / 2); ctx.lineTo(x - size / 2, y + h / 2); ctx.closePath();
        ctx.fillStyle = selected === `area:${a.id}` ? "#c2185b" : a.major ? "#0b1530" : "#1b2a4a";
        ctx.lineJoin = "round"; ctx.lineWidth = 1.6; ctx.strokeStyle = "#fff";
        ctx.fill(); ctx.stroke();
        if (areaAlerts[a.id]?.length) {          // NWS alert: red ring
          ctx.beginPath(); ctx.arc(x, y + 1, size * 0.85, 0, 2 * Math.PI);
          ctx.strokeStyle = "#b42318"; ctx.lineWidth = 2.2; ctx.stroke();
        }
      },
      onClick: () => openSki(it),
    };
    return it;
  }

  // Popups for canvas items: the selection drives the URL hash and label priority.
  function openItemPopup(it, html, key) {
    const pop = L.popup({ offset: [0, -8], autoPanPadding: [40, 40] }).setLatLng([it.lat, it.lon]).setContent(html);
    pop.on("remove", () => { if (selected === key) { selected = null; points.invalidate(); writeHash(); } });
    pop.openOn(map);
    selected = key;
    points.invalidate();
    writeHash();
  }

  // ---------------------------------------------------------------- avalanche
  function avyStyle(f) {
    const p = f.properties;
    return {
      color: p.warning ? "#b00020" : "#333",
      weight: p.warning ? 3 : 1,
      dashArray: p.expired ? "4 4" : null,
      fillColor: p.color || "#ccc",
      // outlines only while a snow-analysis overlay is shown (owner S3), so its colours read cleanly
      fillOpacity: overlays?.current?.() ? 0 : p.danger_level > 0 ? 0.45 : 0.15,
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
    const out = { v: q.get("v"), s: q.get("s"), o: q.get("o") };
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
    if (overlays.current()) parts.push(`o=${encodeURIComponent(overlays.current())}`);
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
    if (!snotelData) return;
    const spec = SNOTEL_VARS[currentVar];
    points.setGroup("snotel", snotelData.features.map((f) => snotelItem(f, spec)), { order: 1 });
    drawLegend(spec);
  }

  function selectSnotel(p) {
    map.closePopup();
    selected = p.triplet;
    points.invalidate();   // highlight; the selected station always keeps its label
    writeHash();
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
      <p class="forecast-link"><a href="area.html#snotel-${encodeURIComponent(p.triplet.replace(/:/g, "-"))}">Forecast for this site (NBM / NWS) →</a></p>
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
    loadPlotly().then((P) => P.newPlot("chart", traces, layout, { displayModeBar: false, responsive: true }))
      .catch((e) => { $("chart").textContent = `Chart unavailable (${e.message})`; });
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
  const asosItems = new Map();  // id -> canvas item

  function asosPopup(p) {
    return `
        <strong>${esc(p.id)} – ${esc(p.name)}</strong><br>
        <span class="hint">${localTime(p.valid_utc)}${p.stale ? " · <strong>stale</strong>" : ""}</span>
        <table class="metrics">
          <tr><td>Temp / Dewpoint</td><td>${num(p.temp_f, 1, "°F")} / ${num(p.dewp_f, 1, "°F")}</td></tr>
          <tr><td>Wind</td><td>${num(p.wind_dir, 0, "°")} @ ${num(p.wind_kt, 0, " kt")}${p.gust_kt ? ` G${num(p.gust_kt, 0)}` : ""}</td></tr>
          <tr><td>Visibility</td><td>${num(p.vis_mi, 1, " mi")}</td></tr>
          <tr><td>Today hi / lo</td><td>${num(p.tmax_f, 0, "°")} / ${num(p.tmin_f, 0, "°")}</td></tr>
          <tr><td>Precip today</td><td>${num(p.precip_today_in, 2, '"')}</td></tr>
        </table>
        ${p.metar ? `<code style="font-size:11px">${esc(p.metar)}</code>` : ""}`;
  }
  const openAsos = (it) => openItemPopup(it, asosPopup(it.props), `asos:${it.props.id}`);

  function drawAsos(fc) {
    asosItems.clear();
    const items = fc.features.map(asosItem);
    for (const it of items) asosItems.set(String(it.props.id), it);
    points.setGroup("asos", items, { order: 0 });
  }

  // ---------------------------------------------------------------- ski areas
  // data/ski_areas.json (pipeline catalog; OpenSkiMap/OSM, ODbL). Triangle markers,
  // larger for the major areas; popup links to the area page.
  const skiItems = new Map();
  const ft = (v) => (v === null || v === undefined ? "–" : `${Number(v).toLocaleString()} ft`);

  let areaAlerts = {};    // area id -> [{event, level, ends}] (data/alerts/index.json)
  function skiPopup(a) {
    const avy = a.avalanche ? `<br>Avalanche zone: ${esc(a.avalanche.zone)}` : "";
    const al = (areaAlerts[a.id] || []).map((r) => `<span class="alert-badge ${esc(r.level)}">${esc(r.event)}</span>`).join(" ");
    return `<strong>${esc(a.name)}</strong>
        <div class="hint">${esc(a.region)}, ${esc(a.state)}</div>${al ? `<div class="popup-alerts">${al}</div>` : ""}
        <p>Base ${ft(a.base.elev_ft)} · Summit ${ft(a.summit.elev_ft)}<br>
        Vertical ${ft(a.vertical_ft)} · ${a.lifts} lifts${avy}</p>
        <a href="area.html#${encodeURIComponent(a.id)}">Forecast and details →</a>
        ${a.url ? `<br><a href="${esc(safeUrl(a.url))}" target="_blank" rel="noopener">Area website</a>` : ""}`;
  }
  const openSki = (it) => openItemPopup(it, skiPopup(it.area), `area:${it.area.id}`);

  function drawSkiAreas(cat) {
    skiItems.clear();
    const items = (cat?.areas || []).map(skiItem);
    for (const it of items) skiItems.set(it.area.id, it);
    points.setGroup("ski", items, { order: 2 });
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
      const it = skiItems.get(s.key.slice(5));
      if (it) openSki(it);
    } else if (s.kind === "SNOTEL") {
      if (!map.hasLayer(snotelLayer)) snotelLayer.addTo(map);
      selectSnotel(s.props);
    } else {
      if (!map.hasLayer(asosLayer)) asosLayer.addTo(map);
      const it = asosItems.get(s.key.slice(5));
      if (it) openAsos(it);
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
  const SOURCE_LABEL = { snotel: "SNOTEL", asos: "ASOS", avalanche: "Avalanche", alerts: "NWS alerts", points: "NBM forecasts",
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

    const [avy, sno, aso, ski, alr] = await Promise.allSettled([
      getJSON("avalanche.geojson", lastUpdated),
      getJSON("snotel.geojson", lastUpdated),
      getJSON("asos.geojson", lastUpdated),
      getJSON("ski_areas.json", lastUpdated),
      getJSON("alerts/index.json", lastUpdated),
    ]);
    if (alr.status === "fulfilled") areaAlerts = alr.value.areas || {};
    if (avy.status === "fulfilled") avyLayer.addData(avy.value);
    if (sno.status === "fulfilled") { snotelData = sno.value; drawSnotel(); }
    if (aso.status === "fulfilled") drawAsos(aso.value);
    if (ski.status === "fulfilled") drawSkiAreas(ski.value);
    overlays.load(initialHash.o);
    buildIndex(sno.value, aso.value, ski.value);

    hashReady = true;
    openFromHash(initialHash, false);
    writeHash();
    window.snowwx.ready = true;
    // Warm the chart library once the map is idle, so the first station click is quick
    // without Plotly blocking the initial load.
    const idle = window.requestIdleCallback || ((fn) => setTimeout(fn, 2500));
    idle(() => loadPlotly().catch(() => {}), { timeout: 5000 });
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
    if ((h.o || null) !== overlays.current()) overlays.set(h.o || null);
    if (h.s && h.s !== selected) openFromHash(h, false);
  });

  load();
})();
