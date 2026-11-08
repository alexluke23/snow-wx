// Ski-area page (area.html#<id>): NBM point forecast for base and summit, snow
// level vs the mountain, hourly meteogram, nearest SNOTEL, avalanche danger.
// Numbers render as plain HTML first; Plotly loads afterwards for the charts.
// Amounts are NBM means (bars add up to totals); ranges are 10th–90th percentile.

(() => {
  "use strict";
  const PLOTLY_URL = "https://cdn.plot.ly/plotly-basic-2.35.2.min.js";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ft = (v) => (v === null || v === undefined ? "–" : `${Math.round(v).toLocaleString()} ft`);
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
  const getJSON = async (path) => {
    const r = await fetch(path, { cache: "no-cache" });
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  };
  const FAV_KEY = "snowwx.favorites";
  const favs = () => { try { return JSON.parse(localStorage.getItem(FAV_KEY)) || []; } catch { return []; } };
  const setFavs = (list) => { try { localStorage.setItem(FAV_KEY, JSON.stringify(list)); } catch { /* private mode */ } };
  const PLOT_CFG = { displayModeBar: false, responsive: true };
  const FONT = { family: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif", size: 12, color: "#1d2733" };
  const POINT_LABEL = { summit: "Summit", base: "Base", point: "Station" };

  let plotlyPromise = null;
  const loadPlotly = () => (plotlyPromise ||= new Promise((resolve, reject) => {
    if (window.Plotly) return resolve(window.Plotly);
    const s = document.createElement("script");
    s.src = PLOTLY_URL; s.async = true;
    s.onload = () => resolve(window.Plotly); s.onerror = () => reject(new Error("chart library failed to load"));
    document.head.appendChild(s);
  }));

  // ---------------------------------------------------------------- formatting
  const inches = (v) => (v === null || v === undefined ? "–" : v < 0.5 ? (v < 0.05 ? "0" : "<1") : `${Math.round(v)}`);
  function range(lo, hi) {
    if (hi === null || hi === undefined) return "–";
    if (hi < 0.05) return "0 in";
    if (hi < 0.5) return "0–1 in";
    const a = Math.round(lo ?? 0), b = Math.max(Math.round(hi), 1);
    return a === b ? `${b} in` : `${a}–${b} in`;
  }
  const ago = (iso) => {
    const h = (Date.now() - new Date(iso)) / 3.6e6;
    return h < 1 ? "under an hour ago" : h < 36 ? `${Math.round(h)} h ago` : `${Math.round(h / 24)} days ago`;
  };
  const localFmt = (iso, tz, opts) => new Date(iso).toLocaleString([], { timeZone: tz, ...opts });
  const TYPE_LABEL = { snow: "snow", mixed: "mixed rain and snow", "mostly rain": "mostly rain" };

  function headline(fc, keys) {
    const pt = keys[0], s = fc.points[pt].totals["72h"];
    if (!s) return "";
    const where = keys.length > 1 ? " at the summit" : "";
    let txt;
    if ((s.snow_hi ?? 0) < 0.5) {
      txt = `No significant snow in the next 72 hours${where}.`;
    } else {
      txt = `Next 72 h${where}: most likely <strong>${inches(s.snow_in)} in</strong> ` +
            `<span class="rng">(${range(s.snow_lo, s.snow_hi)} range)</span>.`;
      const b = keys.includes("base") ? fc.points.base.totals["72h"] : null;
      if (b) txt += ` Base: ${inches(b.snow_in)} in (${range(b.snow_lo, b.snow_hi)}).`;
    }
    // rain vs snow by elevation, from the wet day/night periods in the first 72 h
    const wet = (k) => fc.points[k].periods.slice(0, 6).filter((p) => (p.qpf_in ?? 0) >= 0.05);
    const types = (k) => new Set(wet(k).map((p) => p.type));
    if (keys.includes("base")) {
      const bt = types("base"), st = types("summit");
      if ((bt.has("mostly rain") || bt.has("mixed")) && st.has("snow")) {
        const sl = wet("summit").map((p) => p.snowlvl_min_ft).filter((v) => v !== null);
        txt += ` <span class="mixnote">Rain or mixed at the base, snow up top${sl.length ? ` (snow level down to ~${ft(Math.min(...sl))})` : ""}.</span>`;
      } else if (bt.has("mostly rain") && st.has("mostly rain")) {
        txt += ` <span class="mixnote">Precipitation mostly rain, even at the summit.</span>`;
      }
    } else if (types(pt).has("mostly rain")) {
      txt += ` <span class="mixnote">Some precipitation may fall as rain here.</span>`;
    }
    return txt;
  }

  function tiles(fc, pt, elev) {
    const cell = (name, label) => {
      const t = fc.points[pt].totals[name];
      if (!t) return "";
      const c = colorFor(SNOWFALL, t.snow_in) || "#f4f6f8";
      return `<div class="tile${t.extended ? " ext" : ""}"><span class="label">${label}</span>
        <span class="swatch" style="background:${c}"></span><strong>${inches(t.snow_in)}<small> in</small></strong>
        <span class="rng">${range(t.snow_lo, t.snow_hi)} range</span>
        <span class="rng liquid">${(t.qpf_in ?? 0).toFixed(2)} in liquid</span></div>`;
    };
    return `<p class="tiles-for">${POINT_LABEL[pt]} · ${ft(elev)} · most likely snowfall</p>
      <div class="tiles">${cell("24h", "Next 24 h")}${cell("72h", "Next 72 h")}${cell("7d", "Next 7 days")}${cell("10d", "Next 10 days")}</div>`;
  }

  // ---------------------------------------------------------------- charts
  // remove the "Loading chart…" placeholder before Plotly draws into a container
  const ready = (el) => { el.querySelector(":scope > .hint")?.remove(); return el; };
  const baseLayout = (h, extra = {}) => ({
    height: h, margin: { l: 46, r: 12, t: 8, b: 36 }, font: FONT, paper_bgcolor: "#fff", plot_bgcolor: "#fff",
    showlegend: false, hovermode: "x unified", ...extra });

  function periodChart(el, fc, pt) {
    const per = fc.points[pt].periods;
    const x = per.map((p, i) => i);
    const y = per.map((p) => p.snow_in ?? 0);
    const hi = per.map((p, i) => Math.max(0, (p.snow_hi ?? y[i]) - y[i]));
    const lo = per.map((p, i) => Math.max(0, y[i] - (p.snow_lo ?? y[i])));
    const colors = per.map((p, i) => colorFor(SNOWFALL, y[i]) || "#e9edf2");
    const ticks = per.map((p, i) => [i, p]).filter(([, p]) => p.is_day);
    const hover = per.map((p) =>
      `<b>${esc(p.label)}</b> (${esc(p.local)})<br>Most likely ${p.snow_in ?? "–"} in · 10–90%: ${range(p.snow_lo, p.snow_hi)}` +
      `<br>Liquid ${p.qpf_in ?? "–"} in${p.pop !== null ? ` · chance of precip ${Math.round(p.pop * 100)}%` : ""}` +
      (p.type ? `<br>${TYPE_LABEL[p.type] || p.type}${p.p_snow !== null ? `, P(snow) ${Math.round(p.p_snow * 100)}%` : ""}` : "") +
      (p.powder ? `<br>${esc(p.powder)}` : "") +
      (p.snowlvl_min_ft ? `<br>Snow level down to ${ft(p.snowlvl_min_ft)}` : "") +
      (p.extended ? "<br><i>Extended outlook</i>" : ""));
    const firstExt = per.findIndex((p) => p.extended);
    const shapes = firstExt >= 0 ? [{ type: "rect", xref: "x", yref: "paper", x0: firstExt - 0.5, x1: per.length - 0.5,
      y0: 0, y1: 1, fillcolor: "rgba(120,130,150,0.07)", line: { width: 0 }, layer: "below" }] : [];
    const annotations = firstExt >= 0 ? [{ xref: "x", yref: "paper", x: firstExt - 0.4, y: 1, xanchor: "left", yanchor: "top",
      text: "Extended outlook", showarrow: false, font: { size: 10.5, color: "#5b6878" } }] : [];
    Plotly.react(el, [{
      type: "bar", x, y, marker: {
        color: colors, line: { color: "#8090a4", width: 0.6 },
        opacity: per.map((p) => (p.is_day ? 1 : 0.65)),
        pattern: { shape: per.map((p) => (p.extended ? "/" : "")), fgcolor: "rgba(40,50,70,0.35)", size: 5 },
      },
      text: y.map((v) => (v >= 0.5 ? inches(v) : "")), textposition: "outside", cliponaxis: false,
      error_y: { type: "data", symmetric: false, array: hi, arrayminus: lo, color: "#334", thickness: 1.1, width: 3 },
      hovertext: hover, hoverinfo: "text",
    }], baseLayout(250, { hovermode: "closest", bargap: 0.25, shapes, annotations,
      yaxis: { title: { text: "in", standoff: 4 }, rangemode: "tozero", gridcolor: "#eef1f5", fixedrange: true },
      xaxis: { fixedrange: true, tickfont: { size: 10.5 }, tickvals: ticks.map(([i]) => i), tickangle: 0,
               ticktext: ticks.map(([, p]) => p.label.split(" ")[0]) } }), PLOT_CFG);
  }

  function snowLevelChart(el, fc, keys) {
    const s = fc.points[keys[0]].series, t = fc.times;
    const n48 = s.snowlvl_p90.filter((v) => v !== null).length;
    const tb = t.slice(0, n48);
    const wet = s.snowlvl_ft.map((v, i) => ((s.pop[i] ?? 0) >= 0.2 ? v : null));
    const lines = keys.map((k) => [POINT_LABEL[k], fc.points[k].elev_ft, k === "base" ? "#7a5a2a" : "#222"]);
    const elevs = keys.map((k) => fc.points[k].elev_ft);
    const minBase = Math.min(...elevs);
    const lo = Math.max(0, minBase - 3000), top = Math.max(...elevs) + 3000;
    const traces = [
      { x: tb, y: s.snowlvl_p90.slice(0, n48), mode: "lines", line: { width: 0 }, hoverinfo: "skip" },
      { x: tb, y: s.snowlvl_p10.slice(0, n48), mode: "lines", line: { width: 0 }, fill: "tonexty",
        fillcolor: "rgba(49,130,189,0.18)", hovertemplate: "10th %{y:,.0f} ft<extra></extra>" },
      { x: t, y: s.snowlvl_ft, mode: "lines", line: { color: "#aab3bf", width: 1.5, dash: "dot" },
        hovertemplate: "Snow level %{y:,.0f} ft<extra></extra>" },
      { x: t, y: wet, mode: "lines", line: { color: "#08519c", width: 2.5 }, connectgaps: false, hoverinfo: "skip" },
    ];
    const shapes = [{ type: "rect", xref: "paper", x0: 0, x1: 1, y0: lo, y1: minBase, fillcolor: "rgba(107,174,214,0.16)",
      line: { width: 0 }, layer: "below" },
      ...lines.map(([, y, c]) => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y, line: { color: c, width: 1.5, dash: "dot" } }))];
    const annotations = [
      ...lines.map(([lab, y, c]) => ({ xref: "paper", x: 0.01, y, xanchor: "left", yanchor: "bottom",
        text: `${lab} ${ft(y)}`, showarrow: false, font: { size: 11, color: c }, bgcolor: "rgba(255,255,255,0.8)" })),
      { xref: "paper", x: 0.99, y: (lo + minBase) / 2, xanchor: "right", showarrow: false, font: { size: 10.5, color: "#2b5d8a" },
        text: `snow level in here = snow to the ${keys.includes("base") ? "base" : "station"}` }];
    Plotly.react(el, traces, baseLayout(230, { shapes, annotations,
      yaxis: { title: { text: "ft", standoff: 4 }, gridcolor: "#eef1f5", fixedrange: true, range: [lo, top] },
      xaxis: { type: "date", fixedrange: true } }), PLOT_CFG);
  }

  function meteogram(el, fc, pt, keys) {
    const t = fc.times, P = fc.points, s = P[pt].series;
    const pr = P[pt].precip;
    const width = pr.hours.map((h) => h * 3.6e6 * 0.85);
    const mid = pr.end.map((e, i) => new Date(new Date(e) - pr.hours[i] * 1.8e6).toISOString());
    const wk = keys.includes("summit") ? "summit" : pt;
    const temps = keys.map((k) => ({ x: t, y: P[k].series.t_f, name: `${POINT_LABEL[k]} °F`, yaxis: "y",
      line: { color: k === "base" ? "#c2410c" : "#3b5bdb", width: 2 } }));
    const traces = [
      ...temps,
      { x: t, y: P[wk].series.gust_mph, name: `${POINT_LABEL[wk]} gust`, line: { color: "#7c3aed", width: 1, dash: "dot" }, yaxis: "y2" },
      { x: t, y: P[wk].series.wind_mph, name: `${POINT_LABEL[wk]} wind`, line: { color: "#7c3aed", width: 2 }, yaxis: "y2" },
      { x: mid, y: pr.snow_in, width, name: `Snow at ${POINT_LABEL[pt].toLowerCase()} (in)`, type: "bar", marker: { color: "#3182bd" }, yaxis: "y3" },
      { x: mid, y: pr.qpf_in, name: "Liquid (in, right axis)", mode: "lines+markers", line: { color: "#b45309", width: 1.5, shape: "hvh" },
        marker: { size: 3 }, yaxis: "y4" },
      { x: t, y: t.map(() => 0), name: "Sky cover", mode: "markers", yaxis: "y5", hoverinfo: "text", showlegend: false,
        text: s.sky.map((v) => `Sky cover ${v ?? "–"}%`),
        marker: { symbol: "square", size: 9, color: s.sky.map((v) => `hsl(210,10%,${100 - 0.55 * (v ?? 0)}%)`) } },
    ];
    Plotly.react(el, traces, baseLayout(480, {
      showlegend: true, legend: { orientation: "h", y: -0.07, font: { size: 11 } }, margin: { l: 46, r: 46, t: 8, b: 64 },
      xaxis: { type: "date", matches: "x5", showticklabels: false }, xaxis2: { matches: "x5", showticklabels: false },
      xaxis3: { matches: "x5", showticklabels: false }, xaxis4: { matches: "x5", showticklabels: false },
      xaxis5: { type: "date", fixedrange: true },
      yaxis: { domain: [0.68, 1], title: { text: "°F", standoff: 2 }, gridcolor: "#eef1f5", fixedrange: true },
      yaxis2: { domain: [0.45, 0.63], title: { text: "mph", standoff: 2 }, gridcolor: "#eef1f5", rangemode: "tozero", fixedrange: true },
      yaxis3: { domain: [0.17, 0.4], title: { text: "snow in", standoff: 2 }, rangemode: "tozero", fixedrange: true, gridcolor: "#eef1f5" },
      yaxis4: { domain: [0.17, 0.4], overlaying: "y3", side: "right", rangemode: "tozero", fixedrange: true, showgrid: false,
                title: { text: "liquid in", standoff: 2 } },
      yaxis5: { domain: [0.06, 0.1], visible: false, fixedrange: true },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: 32, y1: 32, line: { color: "#0b7285", width: 1, dash: "dash" } }],
      annotations: [{ xref: "paper", yref: "paper", x: 0, y: 0.115, xanchor: "left", yanchor: "bottom", showarrow: false,
        text: "Sky cover (white = clear, grey = cloudy)", font: { size: 10.5, color: "#5b6878" } }],
    }), PLOT_CFG);
  }

  async function recentObs(el, a) {
    const st = a.nearest?.snotel?.[0];
    if (!st) { el.innerHTML = `<p class="hint">No SNOTEL station within range.</p>`; return; }
    let d;
    try { d = await getJSON(`data/snotel/${st.id.replace(/:/g, "_")}.json`); } catch {
      el.innerHTML = `<p class="hint">${esc(st.name)}: no recent data.</p>`; return;
    }
    const series = d.SNWD_med3 || d.SNWD;
    const last = (arr) => { for (let i = arr.length - 1; i >= 0; i--) if (arr[i] !== null) return [arr[i], i]; return [null, -1]; };
    const [depth, i] = last(series);
    const prev = i >= 72 ? series[i - 72] : null;
    const chg = depth !== null && prev !== null ? depth - prev : null;
    el.innerHTML = `<p><strong>${esc(st.name)}</strong> SNOTEL, ${ft(st.elev_ft)}${st.dist_km !== undefined ? ` (${st.dist_km} km away)` : ""}:
      snow depth <strong>${depth === null ? "–" : `${Math.round(depth)} in`}</strong>${chg === null ? "" :
      ` (${chg >= 0 ? "+" : ""}${Math.round(chg)} in in 72 h)`}.</p><div class="chart" id="obs-chart"><p class="hint">Loading chart…</p></div>`;
    const P = await loadPlotly();
    const times = d.times.map((s) => s.replace(" ", "T"));
    P.react(ready($("obs-chart")), [
      { x: times, y: series, name: "Depth (in)", line: { color: "#08519c", width: 2 } },
      { x: times, y: d.WTEQ, name: "SWE (in)", yaxis: "y2", line: { color: "#238b45", width: 1.5 } },
    ], baseLayout(200, { showlegend: true, legend: { orientation: "h", y: 1.15 }, margin: { l: 40, r: 40, t: 22, b: 32 },
      yaxis: { title: { text: "depth", standoff: 2 }, rangemode: "tozero", fixedrange: true, gridcolor: "#eef1f5" },
      yaxis2: { overlaying: "y", side: "right", rangemode: "tozero", fixedrange: true, showgrid: false, title: { text: "SWE", standoff: 2 } },
      xaxis: { type: "date", fixedrange: true } }), PLOT_CFG);
  }

  // NOHRSC snowfall analysis + SNODAS at the area's base and summit (data/nohrsc/ski.json).
  async function nohrscObs(el, a, tz) {
    let js;
    try { js = await getJSON("data/nohrsc/ski.json"); } catch { return; }
    const r = js.areas?.[a.id];
    if (!r) return;
    const f = (v, d = 1) => (v === null || v === undefined ? "–" : `${Number(v).toFixed(d)}"`);
    const when = (iso) => (iso ? localFmt(iso, tz, { weekday: "short", hour: "numeric", timeZoneName: "short" }) : "–");
    const row = (k) => `<tr><td>${POINT_LABEL[k]} ${ft(a[k].elev_ft)}</td><td>${f(r[k].sf24)}</td><td>${f(r[k].sf48)}</td>
      <td>${f(r[k].sf72)}</td><td>${f(r[k].depth, 0)}</td><td>${f(r[k].swe)}</td></tr>`;
    el.innerHTML = `<table class="metrics nohrsc"><thead><tr><th></th><th>24 h</th><th>48 h</th><th>72 h</th>
        <th>Depth</th><th>SWE</th></tr></thead><tbody>${row("summit")}${row("base")}</tbody></table>
      <p class="note">Observed snowfall: NOAA/NWS NOHRSC National Snowfall Analysis, windows ending ${esc(when(js.snowfall_end))}.
        Depth and SWE: SNODAS, ${esc(when(js.snodas_valid))}. Analyses on ~1–4 km grids, not measurements at the lifts.</p>`;
  }

  function avalanche(a, ratings) {
    if (!a) return `<p class="hint">Outside the avalanche-center forecast zones.</p>`;
    const p = ratings?.[String(a.zone_id)];
    if (!p) return `<p>${esc(a.zone)}</p>`;
    return `<p><span class="danger-chip${p.expired ? " expired" : ""}" style="background:${esc(p.color)}">${esc(p.danger)}</span>
      ${esc(p.name)}${p.expired ? ` <span class="hint">(expired)</span>` : ""}</p>
      <a href="${esc(safeUrl(p.link))}" target="_blank" rel="noopener">Read the full forecast →</a>`;
  }

  function stationRows(list, kind) {
    if (!list?.length) return `<li class="hint">None within range</li>`;
    return list.map((s) => {
      const href = kind === "snotel" ? `index.html#v=depth_in&s=${encodeURIComponent(s.id).replace(/%3A/gi, ":")}`
                                     : `index.html#s=asos:${encodeURIComponent(s.id)}`;
      const dz = s.dz_base_ft === undefined ? "" : ` · ${s.dz_base_ft > 0 ? "+" : ""}${s.dz_base_ft.toLocaleString()} ft vs base`;
      return `<li><a href="${href}">${esc(s.name)}</a> <span class="hint">${s.dist_km} km · ${ft(s.elev_ft)}${dz}</span></li>`;
    }).join("");
  }

  // ---------------------------------------------------------------- page
  function listPage(cat) {
    const fav = new Set(favs());
    const items = [...cat.areas].sort((x, y) => (fav.has(y.id) - fav.has(x.id)) || x.name.localeCompare(y.name));
    $("area").innerHTML = `<h2>Ski areas</h2><ul class="area-list">${items.map((x) =>
      `<li>${fav.has(x.id) ? "★ " : ""}<a href="#${encodeURIComponent(x.id)}">${esc(x.name)}</a>
       <span class="hint">${esc(x.region)}, ${esc(x.state)}</span></li>`).join("")}</ul>`;
    document.title = "Snow-Wx · Ski areas";
  }

  async function render() {
    const id = decodeURIComponent(location.hash.replace(/^#/, ""));
    const main = $("area");
    // One request for the forecast (it embeds the catalog record); the whole
    // catalog only for the list page or when no forecast exists yet.
    const [fcR, avyR] = await Promise.allSettled([
      id ? getJSON(`data/points/${encodeURIComponent(id)}.json`) : Promise.reject(new Error("no id")),
      getJSON("data/avalanche_ratings.json")]);
    const fc = fcR.status === "fulfilled" ? fcR.value : null;
    let a = fc?.area;
    if (!a) {
      let cat;
      try { cat = await getJSON("data/ski_areas.json"); } catch (e) {
        main.innerHTML = `<p>Ski-area catalog not available (${esc(e.message)}).</p>`; return;
      }
      a = cat.areas.find((x) => x.id === id);
      if (!a) return listPage(cat);
    }
    document.title = `Snow-Wx · ${a.name}`;
    const tz = a.tz || "America/Denver";
    const keys = fc ? ["summit", "base"].filter((k) => fc.points[k]) : [];
    let pt = keys[0];
    const isFav = favs().includes(a.id);
    const stale = fc && (Date.now() - new Date(fc.issued)) / 3.6e6 > 18;
    const nwsLink = (p) => `https://forecast.weather.gov/MapClick.php?lat=${p.lat}&lon=${p.lon}`;
    const seg = keys.length > 1 ? `<div class="seg" role="group" aria-label="Elevation">${keys.map((k, i) =>
      `<button type="button" data-pt="${k}" class="${i ? "" : "on"}" aria-pressed="${!i}">${POINT_LABEL[k]} ${ft(fc.points[k].elev_ft)}</button>`).join("")}</div>` : "";
    const dayLocal = fc?.points[pt].periods.find((p) => p.is_day)?.local || "about 5 AM–5 PM";
    main.innerHTML = `
      <div class="area-head">
        <h2>${esc(a.name)}</h2>
        <div class="actions">
          <button id="fav" type="button" aria-pressed="${isFav}" title="Favorite">${isFav ? "★" : "☆"}<span class="sr"> Favorite</span></button>
          <button id="share" type="button" title="Share link">Share</button>
        </div>
      </div>
      <p class="sub">${esc(a.region)}, ${esc(a.state)} · Summit ${ft(a.summit.elev_ft)} · Base ${ft(a.base.elev_ft)} · ${ft(a.vertical_ft)} vertical</p>
      ${fc ? `<p class="headline">${headline(fc, keys)}</p>
      <p class="fresh${stale ? " stale" : ""}">NBM ${esc(localFmt(fc.issued, tz, { weekday: "short", hour: "numeric", timeZoneName: "short" }))} run ·
        issued ${ago(fc.issued)}${stale ? " — out of date" : ""}</p>
      <div class="sec-head">${seg}</div>
      <div id="tiles"></div>
      <section><h3>Snowfall by day and night</h3>
        <div class="chart" id="period-chart"><p class="hint">Loading chart…</p></div>
        <p class="note">Bars: most likely (NBM mean; they add up to the totals). Whiskers: 10–90% range.
          Days are 12Z–00Z (${esc(dayLocal)}); nights are lighter. Hatched: extended outlook, where the range
          comes from NBM precipitation × snow ratio.</p></section>
      <section><h3>Snow level vs the mountain</h3><div class="chart" id="sl-chart"><p class="hint">Loading chart…</p></div>
        <p class="note">Below the line precipitation falls as rain. Solid blue where precipitation is possible
          (≥ 20% chance), dotted grey where it is unlikely; shaded 10–90% for the first 48 h.</p></section>
      <section><h3>Hour by hour</h3><div class="chart" id="met-chart"><p class="hint">Loading chart…</p></div>
        <p class="note">Temperatures adjusted from the 2.5-km NBM grid to each elevation (6.5 °C/km).
          Hourly to 36 h, then 6-hour amounts.</p></section>`
      : `<p class="hint">The NBM point forecast is not available yet.</p>`}
      <section><h3>Recent observations</h3><div id="nohrsc-obs"></div><div id="obs"></div></section>
      <section><h3>Avalanche danger</h3>${avalanche(a.avalanche, avyR.status === "fulfilled" ? avyR.value : null)}</section>
      <section><h3>More</h3>
        <p>NWS point forecast: <a href="${nwsLink(a.summit)}" target="_blank" rel="noopener">summit</a> ·
          <a href="${nwsLink(a.base)}" target="_blank" rel="noopener">base</a>
          ${a.url ? ` · <a href="${esc(safeUrl(a.url))}" target="_blank" rel="noopener">Area website</a>` : ""}
          · <a href="index.html#map=12/${a.summit.lat}/${a.summit.lon}&s=area:${encodeURIComponent(a.id)}">Map</a></p>
        <h4>Nearby SNOTEL</h4><ul>${stationRows(a.nearest.snotel, "snotel")}</ul>
        <h4>Nearby airports</h4><ul>${stationRows(a.nearest.asos, "asos")}</ul></section>`;

    $("fav").addEventListener("click", (e) => {
      const list = favs(), on = !list.includes(a.id);
      setFavs(on ? [...list, a.id] : list.filter((x) => x !== a.id));
      e.currentTarget.textContent = on ? "★" : "☆";
      e.currentTarget.setAttribute("aria-pressed", String(on));
    });
    $("share").addEventListener("click", async (e) => {
      const data = { title: `${a.name} snow forecast`, url: location.href };
      try {
        if (navigator.share) await navigator.share(data);
        else { await navigator.clipboard.writeText(location.href); e.currentTarget.textContent = "Link copied"; }
      } catch { /* dismissed */ }
    });
    if (fc) {
      const drawNumbers = () => { $("tiles").innerHTML = tiles(fc, pt, fc.points[pt].elev_ft); };
      const drawCharts = () => loadPlotly().then(() => {
        periodChart(ready($("period-chart")), fc, pt);
        meteogram(ready($("met-chart")), fc, pt, keys);
      });
      drawNumbers();     // plain HTML first; charts after the library arrives
      main.querySelectorAll(".seg button").forEach((btn) => btn.addEventListener("click", () => {
        pt = btn.dataset.pt;
        main.querySelectorAll(".seg button").forEach((b) => {
          b.classList.toggle("on", b === btn); b.setAttribute("aria-pressed", String(b === btn));
        });
        drawNumbers(); drawCharts();
      }));
      requestAnimationFrame(() => drawCharts().then(() => snowLevelChart(ready($("sl-chart")), fc, keys)).catch((e) => {
        main.querySelectorAll(".chart .hint").forEach((h) => { h.textContent = `Charts unavailable: ${e.message}`; });
      }));
    }
    nohrscObs($("nohrsc-obs"), a, tz);
    recentObs($("obs"), a);
  }

  window.addEventListener("hashchange", () => { window.scrollTo(0, 0); render(); });
  render();
})();
