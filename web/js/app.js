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
  avyLayer.addTo(map);
  snotelLayer.addTo(map);
  asosLayer.addTo(map);

  L.control.layers(baseLayers, {
    "Avalanche danger": avyLayer,
    "SNOTEL": snotelLayer,
    "ASOS / AWOS (wind, temp)": asosLayer,
  }, { collapsed: window.innerWidth < 800 }).addTo(map);
  L.control.scale({ imperial: true, metric: true }).addTo(map);

  const setZoomClass = () =>
    map.getContainer().classList.toggle("z-low", map.getZoom() < LOW_ZOOM);
  map.on("zoomend", setZoomClass);

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

  // ---------------------------------------------------------------- SNOTEL
  let snotelData = null;
  let currentVar = "depth_24h";

  function drawSnotel() {
    snotelLayer.clearLayers();
    if (!snotelData) return;
    const spec = SNOTEL_VARS[currentVar];
    for (const f of snotelData.features) {
      const p = f.properties;
      const v = p[currentVar];
      const bg = colorFor(spec, v);
      const html = bg
        ? `<div class="stn" style="background:${bg};color:${textOn(bg)}">${fmtValue(spec, v)}</div>`
        : `<div class="stn na">–</div>`;
      const [lon, lat] = f.geometry.coordinates;
      const m = L.marker([lat, lon], {
        icon: L.divIcon({ html, className: "", iconSize: null }),
        title: `${p.name} (${num(p.elev_ft, 0)} ft)`,
        zIndexOffset: bg ? Math.round((v ?? 0) * 10) : -1000,
      });
      m.on("click", () => showStation(p));
      snotelLayer.addLayer(m);
    }
    drawLegend(spec);
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
        <tr><td>SWE</td><td>${num(p.swe_in, 1, '"')}${p.pct_median ? ` (${num(p.pct_median, 0)}% of median)` : ""}</td></tr>
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
    const traces = [
      { x, y: ts.SNWD, name: "Depth (in)", type: "scatter", mode: "lines",
        line: { color: "#2171b5", width: 2 }, yaxis: "y" },
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
  $("var-select").addEventListener("change", (e) => { currentVar = e.target.value; drawSnotel(); });

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

  function drawAsos(fc) {
    asosLayer.clearLayers();
    for (const f of fc.features) {
      const p = f.properties;
      const [lon, lat] = f.geometry.coordinates;
      const html = `<div class="asos${p.stale ? " stale" : ""}">${barbSVG(p.wind_kt, p.wind_dir)}
        <span class="asos-temp">${p.temp_f ?? ""}</span></div>`;
      const m = L.marker([lat, lon], {
        icon: L.divIcon({ html, className: "", iconSize: null }), title: p.name,
      });
      m.bindPopup(`
        <strong>${esc(p.id)} – ${esc(p.name)}</strong><br>
        <span class="hint">${localTime(p.valid_utc)}${p.stale ? " · <strong>stale</strong>" : ""}</span>
        <table class="metrics">
          <tr><td>Temp / Dewpoint</td><td>${num(p.temp_f, 0, "°F")} / ${num(p.dewp_f, 0, "°F")}</td></tr>
          <tr><td>Wind</td><td>${num(p.wind_dir, 0, "°")} @ ${num(p.wind_kt, 0, " kt")}${p.gust_kt ? ` G${num(p.gust_kt, 0)}` : ""}</td></tr>
          <tr><td>Visibility</td><td>${num(p.vis_mi, 1, " mi")}</td></tr>
          <tr><td>Today hi / lo</td><td>${num(p.tmax_f, 0, "°")} / ${num(p.tmin_f, 0, "°")}</td></tr>
          <tr><td>Precip today</td><td>${num(p.precip_today_in, 2, '"')}</td></tr>
        </table>
        ${p.metar ? `<code style="font-size:11px">${esc(p.metar)}</code>` : ""}`);
      asosLayer.addLayer(m);
    }
  }

  // ---------------------------------------------------------------- load
  let lastUpdated = "";

  function drawStatus(meta) {
    const items = Object.entries(meta.sources || {}).map(([name, s]) =>
      `<li class="${s.ok ? "ok" : "bad"}">${esc(name)}: ${s.ok ? `${s.count} ${name === "avalanche" ? "zones" : "stations"}` : `failed (${esc(s.error)})`}</li>`);
    $("status").innerHTML = items.join("");
  }

  async function load() {
    let meta = null;
    try {
      meta = await getJSON("meta.json", Date.now());
      lastUpdated = meta.generated_at;
      $("updated").textContent = `Updated ${localTime(meta.generated_at)}`;
      drawStatus(meta);
      if (meta.region?.map_center) {
        map.setView(meta.region.map_center, meta.region.map_zoom || 5);
      }
    } catch (e) {
      $("updated").textContent = "No data yet – run the pipeline (see README).";
      map.setView([41.5, -113], 5);
    }
    setZoomClass();

    const [avy, sno, aso] = await Promise.allSettled([
      getJSON("avalanche.geojson", lastUpdated),
      getJSON("snotel.geojson", lastUpdated),
      getJSON("asos.geojson", lastUpdated),
    ]);
    if (avy.status === "fulfilled") avyLayer.addData(avy.value);
    if (sno.status === "fulfilled") { snotelData = sno.value; drawSnotel(); }
    if (aso.status === "fulfilled") drawAsos(aso.value);
  }

  load();
})();
