// Ski-area page (area.html#<id>): NBM point forecast for base and summit, snow
// level vs the mountain, hourly meteogram, nearest SNOTEL, avalanche danger.
// Mobile-first; numbers before charts; every range is NBM 10th–90th percentile.

(() => {
  "use strict";
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

  // ---------------------------------------------------------------- formatting
  const inches = (v) => (v === null || v === undefined ? "–" : v < 1 ? (v < 0.5 ? "0" : "<1") : `${Math.round(v)}`);
  function range(s) {          // {"10","50","90"} -> "4–9 in"
    if (!s || s["90"] === null || s["90"] === undefined) return "–";
    if (s["90"] < 0.5) return "0 in";
    const lo = Math.round(s["10"] ?? 0), hi = Math.max(Math.round(s["90"]), 1);
    return lo === hi ? `${hi} in` : `${lo}–${hi} in`;
  }
  const ago = (iso) => {
    const h = (Date.now() - new Date(iso)) / 3.6e6;
    return h < 1 ? "under an hour ago" : h < 36 ? `${Math.round(h)} h ago` : `${Math.round(h / 24)} days ago`;
  };
  const localFmt = (iso, tz, opts) => new Date(iso).toLocaleString([], { timeZone: tz, ...opts });

  function headline(fc, a) {
    const s = fc.points.summit.totals["72h"], b = fc.points.base.totals["72h"];
    if (!s) return "";
    let txt;
    if ((s.snow_in["90"] ?? 0) < 0.5) {
      txt = "No significant snow in the next 72 hours.";
    } else {
      txt = `Next 72 h at the summit: <strong>${range(s.snow_in)}</strong>, most likely <strong>${inches(s.snow_in["50"])} in</strong>.`;
      if (b) txt += ` Base: ${range(b.snow_in)}.`;
    }
    // rain vs snow by elevation, from the day/night periods with precipitation
    const per = (pt) => fc.points[pt].periods.slice(0, 6).filter((p) => (p.qpf_in["50"] ?? 0) >= 0.05);
    const types = (pt) => new Set(per(pt).map((p) => p.type));
    const bt = types("base"), st = types("summit");
    if ((bt.has("rain") || bt.has("mix")) && st.has("snow")) {
      const sl = per("summit").map((p) => p.snowlvl_min_ft).filter((v) => v !== null);
      txt += ` <span class="mixnote">Rain or mix possible at the base, snow up top${sl.length ? ` (snow level down to ~${ft(Math.min(...sl))})` : ""}.</span>`;
    } else if (bt.has("rain") && st.has("rain")) {
      txt += ` <span class="mixnote">Precipitation mostly rain, even at the summit.</span>`;
    }
    return txt;
  }

  function tiles(fc) {
    const cell = (name, label) => {
      const s = fc.points.summit.totals[name], b = fc.points.base.totals[name];
      if (!s) return "";
      const c = colorFor(SNOWFALL, s.snow_in["50"]) || "#f4f6f8";
      return `<div class="tile"><span class="label">${label}${s.approx ? " ≈" : ""}</span>
        <span class="swatch" style="background:${c}"></span><strong>${inches(s.snow_in["50"])}<small> in</small></strong>
        <span class="rng">${range(s.snow_in)} summit</span><span class="rng">${range(b?.snow_in)} base</span></div>`;
    };
    return `<div class="tiles">${cell("24h", "24 hours")}${cell("72h", "72 hours")}${cell("7d", "7 days")}${cell("10d", "10 days")}</div>
      <p class="note">Totals use NBM's multi-day precipitation ranges, so they are usually larger than the
        most-likely day/night bars added up (each bar is the middle value for that 12 h alone). ≈ = approximate range.</p>`;
  }

  // ---------------------------------------------------------------- charts
  const baseLayout = (h, extra = {}) => ({
    height: h, margin: { l: 44, r: 12, t: 8, b: 36 }, font: FONT, paper_bgcolor: "#fff", plot_bgcolor: "#fff",
    showlegend: false, hovermode: "x unified", ...extra });

  function periodChart(el, fc, which, tz) {
    const per = fc.points[which].periods;
    const x = per.map((p, i) => i);   // one tick label per day (under the day bar); nights lighter
    const y = per.map((p) => p.snow_in["50"] ?? 0);
    const hi = per.map((p) => Math.max(0, (p.snow_in["90"] ?? 0) - (p.snow_in["50"] ?? 0)));
    const lo = per.map((p) => Math.max(0, (p.snow_in["50"] ?? 0) - (p.snow_in["10"] ?? 0)));
    const colors = per.map((p, i) => colorFor(SNOWFALL, y[i]) || "#e9edf2");
    const opacity = per.map((p) => (p.is_day ? 1 : 0.6));
    const ticks = per.map((p, i) => [i, p]).filter(([, p]) => p.is_day);
    const text = per.map((p, i) => (y[i] >= 0.5 ? inches(y[i]) : ""));
    const hover = per.map((p) => {
      const t0 = localFmt(p.start, tz, { weekday: "short", hour: "numeric" });
      const t1 = localFmt(p.end, tz, { hour: "numeric", timeZoneName: "short" });
      return `${t0}–${t1}<br>Snow ${range(p.snow_in)} (median ${p.snow_in["50"] ?? "–"} in)` +
        `<br>Liquid ${p.qpf_in["10"] ?? "–"}–${p.qpf_in["90"] ?? "–"} in` +
        (p.type ? `<br>${p.type}${p.p_snow !== null ? `, P(snow) ${Math.round(p.p_snow * 100)}%` : ""}` : "") +
        (p.powder ? `<br>${p.powder}` : "") +
        (p.snowlvl_min_ft ? `<br>Snow level ≥ ${ft(p.snowlvl_min_ft)}` : "");
    });
    Plotly.react(el, [{
      type: "bar", x, y, text, textposition: "outside", cliponaxis: false, marker: { color: colors, opacity, line: { color: "#8090a4", width: 0.6 } },
      error_y: { type: "data", symmetric: false, array: hi, arrayminus: lo, color: "#334", thickness: 1.2, width: 3 },
      hovertext: hover, hoverinfo: "text",
    }], baseLayout(240, { hovermode: "closest", bargap: 0.25,
      yaxis: { title: { text: "in", standoff: 4 }, rangemode: "tozero", gridcolor: "#eef1f5", fixedrange: true },
      xaxis: { fixedrange: true, tickfont: { size: 10 }, tickvals: ticks.map(([i]) => i), tickangle: 0,
               ticktext: ticks.map(([, p]) => p.label.split(" ")[0]) } }), PLOT_CFG);
  }

  function snowLevelChart(el, fc, a) {
    const s = fc.points.summit.series, t = fc.times;
    const n48 = s.snowlvl_p90.filter((v) => v !== null).length;
    const tb = t.slice(0, n48);
    const traces = [
      { x: tb, y: s.snowlvl_p90.slice(0, n48), mode: "lines", line: { width: 0 }, hoverinfo: "skip" },
      { x: tb, y: s.snowlvl_p10.slice(0, n48), mode: "lines", line: { width: 0 }, fill: "tonexty",
        fillcolor: "rgba(49,130,189,0.22)", name: "10–90%", hovertemplate: "10th %{y:,.0f} ft<extra></extra>" },
      { x: t, y: s.snowlvl_ft, mode: "lines", line: { color: "#08519c", width: 2 }, name: "snow level",
        hovertemplate: "Snow level %{y:,.0f} ft<extra></extra>" },
    ];
    const lines = [["Summit", a.summit.elev_ft, "#222"], ["Base", a.base.elev_ft, "#7a5a2a"]];
    const shapes = lines.map(([, y, c]) => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y,
      line: { color: c, width: 1.5, dash: "dot" } }));
    const annotations = lines.map(([lab, y, c]) => ({ xref: "paper", x: 0.01, y, xanchor: "left", yanchor: "bottom",
      bgcolor: "rgba(255,255,255,0.8)",
      text: `${lab} ${ft(y)}`, showarrow: false, font: { size: 11, color: c } }));
    const vals = s.snowlvl_ft.concat(s.snowlvl_p10, s.snowlvl_p90, [a.base.elev_ft, a.summit.elev_ft]).filter((v) => v !== null);
    Plotly.react(el, traces, baseLayout(220, { shapes, annotations,
      yaxis: { title: { text: "ft", standoff: 4 }, gridcolor: "#eef1f5", fixedrange: true,
               range: [Math.max(0, Math.min(...vals) - 800), Math.max(...vals) + 800] },
      xaxis: { type: "date", fixedrange: true } }), PLOT_CFG);
  }

  function meteogram(el, fc, a) {
    const t = fc.times, s = fc.points.summit.series, b = fc.points.base.series;
    const pr = fc.points.summit.precip, prb = fc.points.base.precip;
    const width = pr.hours.map((h) => h * 3.6e6 * 0.85);
    const mid = pr.end.map((e, i) => new Date(new Date(e) - pr.hours[i] * 1.8e6).toISOString());
    const traces = [
      { x: t, y: s.t_f, name: "Summit °F", line: { color: "#3b5bdb", width: 2 }, yaxis: "y" },
      { x: t, y: b.t_f, name: "Base °F", line: { color: "#c2410c", width: 2 }, yaxis: "y" },
      { x: t, y: s.gust_mph, name: "Summit gust", line: { color: "#7c3aed", width: 1, dash: "dot" }, yaxis: "y2" },
      { x: t, y: s.wind_mph, name: "Summit wind", line: { color: "#7c3aed", width: 2 }, yaxis: "y2" },
      { x: mid, y: pr.snow_in, width, name: "Summit snow (in)", type: "bar", marker: { color: "#3182bd" }, yaxis: "y3" },
      { x: mid, y: prb.qpf_in, width, name: "Base liquid (in)", type: "bar", marker: { color: "rgba(194,65,12,0.45)" }, yaxis: "y4" },
      { x: t, y: t.map(() => 0), name: "Sky cover %", mode: "markers", yaxis: "y5", hoverinfo: "text",
        text: s.sky.map((v) => `Sky ${v ?? "–"}%`),
        marker: { symbol: "square", size: 9, color: s.sky.map((v) => `hsl(210,10%,${100 - 0.55 * (v ?? 0)}%)`) } },
    ];
    Plotly.react(el, traces, baseLayout(470, {
      showlegend: true, legend: { orientation: "h", y: -0.08, font: { size: 11 } }, margin: { l: 44, r: 44, t: 8, b: 60 },
      grid: { rows: 5, columns: 1, pattern: "independent", roworder: "top to bottom" },
      xaxis: { type: "date", matches: "x5", showticklabels: false }, xaxis2: { matches: "x5", showticklabels: false },
      xaxis3: { matches: "x5", showticklabels: false }, xaxis4: { matches: "x5", showticklabels: false },
      xaxis5: { type: "date", fixedrange: true },
      yaxis: { domain: [0.66, 1], title: { text: "°F", standoff: 2 }, gridcolor: "#eef1f5", fixedrange: true },
      yaxis2: { domain: [0.42, 0.62], title: { text: "mph", standoff: 2 }, gridcolor: "#eef1f5", rangemode: "tozero", fixedrange: true },
      yaxis3: { domain: [0.2, 0.38], title: { text: "snow", standoff: 2 }, rangemode: "tozero", fixedrange: true, gridcolor: "#eef1f5" },
      yaxis4: { domain: [0.2, 0.38], overlaying: "y3", side: "right", rangemode: "tozero", fixedrange: true, showgrid: false,
                title: { text: "liquid", standoff: 2 } },
      yaxis5: { domain: [0.08, 0.13], visible: false, fixedrange: true },
      shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: 32, y1: 32, line: { color: "#0b7285", width: 1, dash: "dash" } }],
    }), PLOT_CFG);
  }

  async function recentObs(el, a) {
    const st = a.nearest.snotel[0];
    if (!st) { el.innerHTML = `<p class="hint">No SNOTEL station within range.</p>`; return; }
    let d;
    try { d = await getJSON(`data/snotel/${st.id.replace(/:/g, "_")}.json`); } catch {
      el.innerHTML = `<p class="hint">${esc(st.name)}: no recent data.</p>`; return;
    }
    const last = (arr) => { for (let i = arr.length - 1; i >= 0; i--) if (arr[i] !== null) return [arr[i], i]; return [null, -1]; };
    const [depth, i] = last(d.SNWD_med3 || d.SNWD);
    const prev = i >= 72 ? (d.SNWD_med3 || d.SNWD)[i - 72] : null;
    const chg = depth !== null && prev !== null ? depth - prev : null;
    el.innerHTML = `<p><strong>${esc(st.name)}</strong> SNOTEL, ${ft(st.elev_ft)} (${st.dist_km} km away):
      snow depth <strong>${depth === null ? "–" : `${Math.round(depth)} in`}</strong>${chg === null ? "" :
      ` (${chg >= 0 ? "+" : ""}${Math.round(chg)} in in 72 h)`}.</p><div class="chart" id="obs-chart"></div>`;
    const times = d.times.map((s) => s.replace(" ", "T"));
    Plotly.react($("obs-chart"), [
      { x: times, y: d.SNWD_med3 || d.SNWD, name: "Depth (in)", line: { color: "#08519c", width: 2 } },
      { x: times, y: d.WTEQ, name: "SWE (in)", yaxis: "y2", line: { color: "#238b45", width: 1.5 } },
    ], baseLayout(200, { showlegend: true, legend: { orientation: "h", y: 1.15 }, margin: { l: 40, r: 40, t: 22, b: 32 },
      yaxis: { title: { text: "depth", standoff: 2 }, rangemode: "tozero", fixedrange: true, gridcolor: "#eef1f5" },
      yaxis2: { overlaying: "y", side: "right", rangemode: "tozero", fixedrange: true, showgrid: false, title: { text: "SWE", standoff: 2 } },
      xaxis: { type: "date", fixedrange: true } }), PLOT_CFG);
  }

  function avalanche(a, fc) {
    if (!a) return `<p class="hint">Outside the avalanche-center forecast zones.</p>`;
    const f = (fc?.features || []).find((x) => x.properties.zone_id === a.zone_id);
    if (!f) return `<p>${esc(a.zone)}</p>`;
    const p = f.properties;
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
    let cat;
    try { cat = await getJSON("data/ski_areas.json"); } catch (e) {
      main.innerHTML = `<p>Ski-area catalog not available (${esc(e.message)}).</p>`; return;
    }
    const a = cat.areas.find((x) => x.id === id);
    if (!a) return listPage(cat);
    document.title = `Snow-Wx · ${a.name}`;
    const [fcR, avyR] = await Promise.allSettled([getJSON(`data/points/${encodeURIComponent(a.id)}.json`),
                                                 getJSON("data/avalanche.geojson")]);
    const fc = fcR.status === "fulfilled" ? fcR.value : null;
    const tz = a.tz || "America/Denver";
    const isFav = favs().includes(a.id);
    const stale = fc && (Date.now() - new Date(fc.issued)) / 3.6e6 > 18;
    const nwsLink = (p) => `https://forecast.weather.gov/MapClick.php?lat=${p.lat}&lon=${p.lon}`;
    main.innerHTML = `
      <div class="area-head">
        <h2>${esc(a.name)}</h2>
        <div class="actions">
          <button id="fav" type="button" aria-pressed="${isFav}" title="Favorite">${isFav ? "★" : "☆"}<span class="sr"> Favorite</span></button>
          <button id="share" type="button" title="Share link">Share</button>
        </div>
      </div>
      <p class="sub">${esc(a.region)}, ${esc(a.state)} · Summit ${ft(a.summit.elev_ft)} · Base ${ft(a.base.elev_ft)} · ${ft(a.vertical_ft)} vertical</p>
      ${fc ? `<p class="headline">${headline(fc, a)}</p>
      <p class="fresh${stale ? " stale" : ""}">NBM ${esc(localFmt(fc.issued, tz, { weekday: "short", hour: "numeric", timeZoneName: "short" }))} run ·
        issued ${ago(fc.issued)}${stale ? " — out of date" : ""} · ranges are 10th–90th percentile</p>
      ${tiles(fc)}
      <section><div class="sec-head"><h3>Snowfall by day and night</h3>
        <div class="seg" role="group" aria-label="Elevation"><button type="button" data-pt="summit" class="on">Summit</button><button type="button" data-pt="base">Base</button></div></div>
        <div class="chart" id="period-chart"></div>
        <p class="note">Bars: most likely amount; whiskers: 10–90% range. Solid bars = day (12Z–00Z, about 5 AM–5 PM), light = night. Hover or tap for details.</p></section>
      <section><h3>Snow level vs the mountain</h3><div class="chart" id="sl-chart"></div>
        <p class="note">Below the snow-level line precipitation falls as rain. Shaded: 10–90% (first 48 h).</p></section>
      <section><h3>Hour by hour</h3><div class="chart" id="met-chart"></div>
        <p class="note">Temperatures adjusted from the 2.5-km NBM grid to each elevation (6.5 °C/km). Hourly to 36 h, then 6-hourly bars.</p></section>`
      : `<p class="hint">The NBM point forecast is not available yet.</p>`}
      <section><h3>Recent observations</h3><div id="obs"></div></section>
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
      periodChart($("period-chart"), fc, "summit", tz);
      main.querySelectorAll(".seg button").forEach((btn) => btn.addEventListener("click", () => {
        main.querySelectorAll(".seg button").forEach((b) => b.classList.toggle("on", b === btn));
        periodChart($("period-chart"), fc, btn.dataset.pt, tz);
      }));
      snowLevelChart($("sl-chart"), fc, a);
      meteogram($("met-chart"), fc, a);
    }
    recentObs($("obs"), a);
  }

  window.addEventListener("hashchange", () => { window.scrollTo(0, 0); render(); });
  render();
})();
