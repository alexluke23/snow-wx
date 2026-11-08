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
    // no-cache = revalidate (ETag) every time, so the data can load in parallel with meta.json
    const r = await fetch(`${DATA}${name}${bust ? `?v=${encodeURIComponent(bust)}` : ""}`, { cache: "no-cache" });
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
  window.snowwx.overlays = overlays;      // test handle (tools/browser_check.py)

  // SNOTEL, ASOS and ski areas share one canvas (points-canvas.js); the layer
  // control gets one toggle per group.
  const points = new PointsCanvas({ lowZoom: LOW_ZOOM });
  const snotelLayer = points.toggleLayer("snotel");
  const asosLayer = points.toggleLayer("asos");
  const skiLayer = points.toggleLayer("ski");
  const spLayer = points.toggleLayer("snopark");      // Sno-Parks / winter recreation (rec_points.json)
  avyLayer.addTo(map);
  points.addTo(map);
  snotelLayer.addTo(map);
  asosLayer.addTo(map);
  skiLayer.addTo(map);
  spLayer.addTo(map);

  L.control.layers(baseLayers, {
    "Ski areas": skiLayer,
    "Sno-Parks": spLayer,
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

  // Sno-Parks: small rounded squares with a "P" (distinct from the ski-area triangles)
  function spItem(a) {
    const size = 11;
    const it = {
      group: "snopark", top: true, lat: a.base.lat, lon: a.base.lon, area: a, title: `${a.name} (${a.type_label || "Sno-Park"})`,
      labelBox: null, prio: () => 0,
      hit: () => [-size / 2 - 3, -size / 2 - 3, size / 2 + 3, size / 2 + 3],
      draw(ctx, x, y) {
        const r = size / 2;
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(x - r, y - r, size, size, 2.5); else ctx.rect(x - r, y - r, size, size);
        ctx.fillStyle = selected === `sp:${a.id}` ? "#c2185b" : "#0f5f4a";
        ctx.lineWidth = 1.4; ctx.strokeStyle = "#fff"; ctx.fill(); ctx.stroke();
        if (size >= 10) { ctx.fillStyle = "#fff"; ctx.font = "700 8px system-ui, sans-serif"; ctx.textAlign = "center";
          ctx.textBaseline = "middle"; ctx.fillText("P", x, y + 0.5); }
        if (areaAlerts[a.id]?.length) {
          ctx.beginPath(); ctx.arc(x, y, size * 0.95, 0, 2 * Math.PI); ctx.strokeStyle = "#b42318"; ctx.lineWidth = 2; ctx.stroke();
        }
      },
      onClick: () => openSp(it),
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
      <div id="chart" class="st-charts"><div class="chart" id="ch-depth" style="height:210px"></div>
        <div class="chart" id="ch-swe" style="height:200px"></div><div class="chart" id="ch-temp" style="height:200px"></div></div>
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

  // Station charts (PLAN.md §6-B, shared theme js/charts/theme.js): one idea per panel —
  // depth (raw faint + 3-h median), SWE, temperature with a labelled 32 °F line. Times are
  // the station's local standard time, as AWDB reports them.
  function drawChart(ts) {
    const C = SnowCharts;
    const xs = ts.times.map((t) => t.slice(0, 16));
    const smooth = ts.SNWD_med3;   // 3-hr median; older data files may lack it
    const last = (arr) => { for (let i = (arr || []).length - 1; i >= 0; i--) if (arr[i] !== null) return arr[i]; return null; };
    const panel = (id, h, traces, title, extra = {}) => {
      const el = $(id);
      const ax = C.timeAxis(xs[0], xs[xs.length - 1], el.clientWidth - C.MARGIN.l - 58);
      return C.plot(el, traces, C.layout(h, { margin: { r: 58, b: ax.b, ...(extra.margin || {}) }, xaxis: ax.axis,
        shapes: [...ax.shapes, ...(extra.shapes || [])], yaxis: C.yaxis(extra.yaxis || {}),
        annotations: [C.axisTitle(title), ...(extra.annotations || [])].filter(Boolean) }));
    };
    loadPlotly().then(() => {
      const dep = smooth || ts.SNWD;
      panel("ch-depth", 210, [
        ...(smooth ? [{ x: xs, y: ts.SNWD, mode: "lines", line: { color: SnowCharts.OI.blue, width: 1 }, opacity: 0.35,
          hovertemplate: "raw %{y:.0f} in<extra></extra>" }] : []),
        { x: xs, y: dep, mode: "lines", line: { color: SnowCharts.OI.blue, width: 2.4 }, hovertemplate: "depth %{y:.0f} in<extra></extra>" },
      ], "Snow depth (in)", { yaxis: { range: SnowCharts.extent([dep, ts.SNWD], { zero: true, min: 4, pad: 0.1 }) },
        annotations: [C.endLabel(xs, dep, smooth ? "median" : "Depth", SnowCharts.OI.blue)] });
      panel("ch-swe", 200, [{ x: xs, y: ts.WTEQ, mode: "lines", line: { color: SnowCharts.OI.green, width: 2.2 },
        hovertemplate: "SWE %{y:.1f} in<extra></extra>" }], "Snow water equivalent (in)",
        { yaxis: { range: SnowCharts.extent([ts.WTEQ], { zero: true, min: 1, pad: 0.1 }) } });
      const r32 = C.refLine(32, "32 °F", { color: "#0b6e85", dash: "dot", where: "left" });
      panel("ch-temp", 200, [{ x: xs, y: ts.TOBS, mode: "lines", line: { color: SnowCharts.OI.vermillion, width: 1.8 },
        hovertemplate: "%{y:.0f} °F<extra></extra>" }], "Temperature (°F)", { shapes: [r32.shape], annotations: [r32.ann] });
      const d = last(dep), w = last(ts.WTEQ), t = last(ts.TOBS);
      C.summary($("ch-depth"), `Snow depth ${d === null ? "not reported" : `${Math.round(d)} in`} at the last report (faint line: raw sensor; bold: 3-hour median).`);
      C.summary($("ch-swe"), `Snow water equivalent ${w === null ? "not reported" : `${w.toFixed(1)} in`} at the last report.`);
      C.summary($("ch-temp"), `Air temperature ${t === null ? "not reported" : `${Math.round(t)} °F`} at the last report; dotted line = freezing.`);
      C.tableToggle($("ch-temp"), "Hourly observations (local standard time)", ["Time", "Depth (in)", "SWE (in)", "Temp (°F)"],
        xs.map((x, i) => [x, ts.SNWD?.[i] ?? "–", ts.WTEQ?.[i] ?? "–", ts.TOBS?.[i] ?? "–"]).reverse());
    }).catch((e) => { $("chart").textContent = `Chart unavailable (${e.message})`; });
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
  const spItems = new Map();
  function spPopup(a) {
    const al = (areaAlerts[a.id] || []).map((r) => `<span class="alert-badge ${esc(r.level)}">${esc(r.event)}</span>`).join(" ");
    return `<strong>${esc(a.name)}</strong>
        <div class="hint">${esc(a.type_label || "Sno-Park")} · ${esc(a.region)}, ${esc(a.state)}</div>${al ? `<div class="popup-alerts">${al}</div>` : ""}
        <p>Trailhead ${ft(a.base.elev_ft)} · high terrain ${ft(a.summit.elev_ft)}${a.avalanche ? `<br>Avalanche zone: ${esc(a.avalanche.zone)}` : ""}
        ${a.permit ? `<br><span class="hint">Permit: ${esc(a.permit)}</span>` : `<br><span class="hint">Parking permits may be required</span>`}</p>
        <a href="area.html#${encodeURIComponent(a.id)}">Forecast and details →</a>`;
  }
  const openSp = (it) => openItemPopup(it, spPopup(it.area), `sp:${it.area.id}`);
  function drawSnoParks(cat) {
    spItems.clear();
    const items = (cat?.areas || []).map(spItem);
    for (const it of items) spItems.set(it.area.id, it);
    points.setGroup("snopark", items, { order: 2 });
    if (items.length) map.attributionControl.addAttribution("Sno-Parks: USDA Forest Service, © OpenStreetMap contributors (ODbL)");
  }

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

  function buildIndex(sno, aso, ski, rec) {
    stationIndex = [];
    for (const a of rec?.areas || []) {
      stationIndex.push({ key: `sp:${a.id}`, kind: "SNOPARK", ids: [a.id], name: a.name,
        sub: `${a.type_label || "Sno-Park"} · ${a.region}, ${a.state}`, lat: a.base.lat, lon: a.base.lon });
    }
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

  // same ranking as the header search (js/search.js)
  const searchStations = (query, limit = 10) => SnowSearch.rank(stationIndex, query, limit);

  function selectStation(s, { fly = true } = {}) {
    if (fly) map.setView([s.lat, s.lon], Math.max(map.getZoom(), 10));
    if (s.kind === "SNOPARK") {
      if (!map.hasLayer(spLayer)) spLayer.addTo(map);
      const it = spItems.get(s.key.slice(3));
      if (it) openSp(it);
    } else if (s.kind === "AREA") {
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
      // "1 alert", "2 alerts" (units are plural nouns: drop the "s" for exactly one)
      const unit = (n, u) => (n === 1 && /s$/.test(u) ? u.slice(0, -1) : u);
      const what = s.ok ? [s.count !== undefined ? `${s.count} ${unit(s.count, s.unit || UNIT[name] || "")}`.trim() : "",
        (s.detail || "").replace(/^1 (ski areas|offices|alerts|stations|layers|models) /, (m, u) => `1 ${u.slice(0, -1)} `)]
        .filter(Boolean).join(" · ") : `failed (${esc(s.error)})`;
      const when = s.at ? ` <span class="hint" title="${esc(s.at)}">${ago(s.at)}</span>` : "";
      return `<li class="${s.ok ? "ok" : "bad"}">${esc(label)}: ${esc(what)}${when}</li>`;
    });
    $("status").innerHTML = items.join("");
  }

  // ---------------------------------------------------------------- My mountains landing (owner S9)
  // A visitor with favorites who opens the map directly (no hash, not coming from another page of
  // this site) gets a dismissible banner, or straight to My mountains if they chose "Always".
  // Shared links (with a hash) and new visitors always land on the map.
  (function homeBanner() {
    let favs = [], pref = null;
    try { favs = JSON.parse(localStorage.getItem("snowwx.favorites")) || []; pref = localStorage.getItem("snowwx.home"); } catch { return; }
    const fromSite = document.referrer && new URL(document.referrer, location.href).origin === location.origin;
    if (!favs.length || location.hash.length > 1 || fromSite) return;
    let dismissed = false;
    try { dismissed = sessionStorage.getItem("snowwx.home.dismissed") === "1"; } catch { /* ignore */ }
    if (pref === "mine") { location.replace("mine.html"); return; }
    if (dismissed) return;
    const C = L.Control.extend({ options: { position: "topright" },
      onAdd() {
        const d = L.DomUtil.create("div", "home-banner");
        d.setAttribute("role", "region"); d.setAttribute("aria-label", "My mountains");
        d.innerHTML = `<p>You have ${favs.length} favorite${favs.length === 1 ? "" : "s"}.</p>
          <a class="btn" href="mine.html">Go to My mountains</a>
          <button type="button" class="btn ghost" data-act="always">Always open My mountains</button>
          <button type="button" class="close" data-act="close" aria-label="Dismiss">×</button>`;
        L.DomEvent.disableClickPropagation(d);
        d.addEventListener("click", (e) => {
          const act = e.target.closest("[data-act]")?.dataset.act;
          if (act === "always") { try { localStorage.setItem("snowwx.home", "mine"); } catch { /* ignore */ } location.href = "mine.html"; }
          if (act === "close") { try { sessionStorage.setItem("snowwx.home.dismissed", "1"); } catch { /* ignore */ } map.removeControl(ctl); }
        });
        return d;
      } });
    const ctl = new C().addTo(map);
  })();

  async function load() {
    // Start the base-map tiles and every data file at once (they used to wait for meta.json).
    if (initialHash.view) map.setView(initialHash.view.center, initialHash.view.zoom);
    else map.setView([41.5, -113], 5);
    setZoomClass();
    const dataP = Promise.allSettled([
      getJSON("avalanche.geojson"), getJSON("snotel.geojson"), getJSON("asos.geojson"),
      getJSON("map_points.json"),                      // compact ski areas + Sno-Parks (pipeline/search.py)
      getJSON("alerts/index.json")]);
    let meta = null;
    try {
      meta = await getJSON("meta.json");
      lastUpdated = meta.generated_at;
      $("updated").textContent = `Updated ${localTime(meta.generated_at)}`;
      drawStatus(meta);
    } catch (e) {
      $("updated").textContent = "No data yet – run the pipeline (see README).";
    }
    if (!initialHash.view && meta?.region?.map_center) map.setView(meta.region.map_center, meta.region.map_zoom || 5);

    const [avy, sno, aso, ski, alr] = await dataP;
    if (alr.status === "fulfilled") areaAlerts = alr.value.areas || {};
    if (avy.status === "fulfilled") avyLayer.addData(avy.value);
    if (sno.status === "fulfilled") { snotelData = sno.value; drawSnotel(); }
    if (aso.status === "fulfilled") drawAsos(aso.value);
    if (ski.status === "fulfilled") drawSkiAreas(ski.value);
    const rec = ski.status === "fulfilled" ? { areas: ski.value.snoparks || [] } : null;
    if (rec) drawSnoParks(rec);
    overlays.load(initialHash.o);
    buildIndex(sno.value, aso.value, ski.value, rec);

    hashReady = true;
    openFromHash(initialHash, false);
    writeHash();
    window.snowwx.ready = true;
    // Warm the chart library once the map is idle, so the first station click is quick
    // without Plotly blocking the initial load.
    // Only after the first interaction (or 15 s): an idle-time prefetch competed with the base-map
    // tiles and the station data on phones (Track 2 performance pass).
    const warm = () => { loadPlotly().catch(() => {}); ["pointerdown", "keydown"].forEach((t) => removeEventListener(t, warm, true)); };
    ["pointerdown", "keydown"].forEach((t) => addEventListener(t, warm, { capture: true, once: true }));
    setTimeout(warm, 15000);
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
