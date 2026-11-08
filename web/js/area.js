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
  // Range wording (owner S3): NBM probabilistic guidance to 48 h, "likely range" beyond.
  // NBM's own snowfall percentiles normally; the derived range is only a labelled fallback
  const rangeName = (t) => (t?.range === "derived 25-75" || t?.range === "likely 25-75" ? "derived range (fallback)" : "NBM 10–90%");
  const outside = (t) => t && t.snow_lo !== null && t.snow_lo !== undefined && t.snow_hi !== null && t.snow_hi !== undefined
    && t.snow_in !== null && (t.snow_in < t.snow_lo - 0.05 || t.snow_in > t.snow_hi + 0.05);
  const SEPARATE = "NBM's deterministic (most likely) and probabilistic forecasts are calibrated separately, " +
    "so the most-likely amount can fall outside the range.";

  function headline(fc, keys) {
    const pt = keys[0], s = fc.points[pt].totals["72h"];
    if (!s) return "";
    const where = keys.length > 1 ? " at the summit" : "";
    let txt;
    const rng = (t) => (t.snow_hi === null || t.snow_hi === undefined ? "" : ` (${rangeName(t)} ${range(t.snow_lo, t.snow_hi)})`);
    if ((s.snow_hi ?? s.snow_in ?? 0) < 0.5) {
      txt = `No significant snow in the next 72 hours${where}.`;
    } else {
      txt = `Next 72 h${where}: most likely <strong>${inches(s.snow_in)} in</strong>` +
            `<span class="rng">${rng(s)}</span>.`;
      const b = keys.includes("base") ? fc.points.base.totals["72h"] : null;
      if (b) txt += ` Base: ${inches(b.snow_in)} in${rng(b)}.`;
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
    const P = fc.points[pt];
    const cell = (name, label) => {
      const t = P.totals[name];
      if (!t) return "";
      const c = colorFor(SNOWFALL, t.snow_in) || "#f4f6f8";
      const note = outside(t) ? ` <a class="info" href="about.html#nbm" title="${esc(SEPARATE)}" aria-label="Why the ranges can disagree">ⓘ</a>` : "";
      return `<div class="tile${t.extended ? " ext" : ""}"><span class="label">${label}</span>
        <span class="swatch" style="background:${c}"></span><strong>${inches(t.snow_in)}<small> in</small></strong>
        <span class="rng">${t.snow_hi === null || t.snow_hi === undefined ? "NWS: no range" : `${rangeName(t)}: ${range(t.snow_lo, t.snow_hi)}${note}`}</span>
        <span class="rng liquid">${(t.qpf_in ?? 0).toFixed(2)} in liquid</span></div>`;
    };
    const head = P.raw
      ? `NWS forecast for the 2.5 km grid cell (elev. ${ft(P.grid_elev_ft)}) · ${POINT_LABEL[pt]} ${ft(elev)}`
      : `${POINT_LABEL[pt]} · ${ft(elev)} · most likely snowfall (NBM)`;
    return `<p class="tiles-for">${head}</p>
      <div class="tiles">${cell("24h", "Next 24 h")}${cell("72h", "Next 72 h")}${cell("7d", "Next 7 days")}${cell("10d", "Next 10 days")}</div>`;
  }

  // ---------------------------------------------------------------- charts (shared theme: js/charts/theme.js)
  const C = SnowCharts;
  const PT_STYLE = { summit: { color: C.OI.blue, dash: "solid" }, base: { color: C.OI.vermillion, dash: "dash" },
    point: { color: C.OI.blue, dash: "solid" } };
  const HOURS_DETAIL = 84;            // "Hour by hour" covers the ridge-wind range (HRRR 48 h, RRFS 84 h)
  const tzName = (tz) => new Date().toLocaleTimeString("en-US", { timeZone: tz, timeZoneName: "short" }).split(" ").pop();
  const localDT = (iso, tz) => localFmt(iso, tz, { weekday: "short", hour: "numeric" });   // "Mon 5 PM"
  const f1 = (v) => (v === null || v === undefined ? null : Math.round(v * 10) / 10);
  const plain = (v) => (v === null || v === undefined ? "–" : String(v));

  // Chance of at least X inches per 24/48/72-h window (NBM probability fields): heat table
  const EX_THR = { "24h": [4, 6, 8, 12, 18, 24], "48h": [4, 6, 8, 12, 18, 24, 36], "72h": [4, 6, 8, 12, 18, 24, 36, 48] };
  let exWin = "24h";
  function exceedTable(el, fc, pt, tz) {
    const ex = fc.points[pt].exceed?.[exWin];
    if (!ex || !ex.end?.length) { el.innerHTML = `<p class="hint">No NBM chances for this window.</p>`; return; }
    const want = EX_THR[exWin].filter((t) => ex.thr.includes(t));
    const day = (iso) => C.wall(iso, tz).slice(0, 10);
    const lastDay = (iso) => C.wall(new Date(iso).getTime() - 3.6e6, tz).slice(0, 10);   // window end at ~5 AM -> day before
    const cols = ex.start.map((s0, i) => (exWin === "24h" ? C.dayName(day(s0), true)
      : `${C.dayName(day(s0))}<br>–${C.dayName(lastDay(ex.end[i])).split(" ")[0]}`));
    const titles = ex.start.map((s0, i) => `${localDT(s0, tz)} → ${localDT(ex.end[i], tz)}`);
    const values = want.map((t) => ex.p.map((row) => row[ex.thr.indexOf(t)]));
    C.heatTable(el, { caption: `Chance (%) of at least each amount in ${exWin.replace("h", "-hour")} windows`,
      rowLabels: want.map((t) => `${t}"`), colLabels: cols, colTitles: titles, values, palette: PROB });
    // summary: the largest amount with a >= 30 % chance somewhere, else the best chance of the smallest
    let best = null;
    want.forEach((t, i) => values[i].forEach((v, j) => {
      if (v !== null && v >= 30 && (!best || t > best.t || (t === best.t && v > best.v))) best = { t, v, j };
    }));
    const w0 = values[0] ? Math.max(...values[0].map((v) => v ?? 0)) : 0;
    const j0 = values[0] ? values[0].indexOf(w0) : 0;
    const txt = best
      ? `Best odds: ${best.v}% chance of at least ${best.t} in during ${titles[best.j]} (${exWin.replace("h", " h")}).`
      : w0 > 0 ? `Low odds: at most ${w0}% chance of ${want[0]} in or more in any ${exWin.replace("h", "-hour")} window (${titles[j0]}).`
        : `No meaningful chance of ${want[0]} in or more in any ${exWin.replace("h", "-hour")} window.`;
    C.summary(el, txt);
    el.removeAttribute("role");               // a real table: keep its own semantics
  }

  function periodChart(el, fc, pt, tz) {
    const per = fc.points[pt].periods;
    const x = per.map((p, i) => i);
    const y = per.map((p) => p.snow_in ?? 0);
    // whiskers are their own trace (lo..hi), independent of the bar: NBM's deterministic
    // value may legitimately sit outside its probabilistic range (owner S3)
    const hasR = per.map((p) => p.snow_lo !== null && p.snow_lo !== undefined && p.snow_hi !== null && p.snow_hi !== undefined);
    const mid = per.map((p, i) => (hasR[i] ? (p.snow_lo + p.snow_hi) / 2 : null));
    const half = per.map((p, i) => (hasR[i] ? (p.snow_hi - p.snow_lo) / 2 : 0));
    const colors = per.map((p, i) => colorFor(SNOWFALL, y[i]) || "#e9edf2");
    const ticks = per.map((p, i) => [i, p]).filter(([, p]) => p.is_day);
    const hover = per.map((p) =>
      `<b>${esc(p.label)}</b> (${esc(p.local)})<br>Most likely ${p.snow_in ?? "–"} in` +
      (p.snow_hi !== null && p.snow_hi !== undefined ? ` · ${rangeName(p)}: ${range(p.snow_lo, p.snow_hi)}` : "") +
      (outside(p) ? `<br><i>${SEPARATE.replace("so the", "<br>so the")}</i>` : "") +
      `<br>Liquid ${p.qpf_in ?? "–"} in${p.pop !== null && p.pop !== undefined ? ` · chance of precip ${Math.round(p.pop * 100)}%` : ""}` +
      (p.type ? `<br>${TYPE_LABEL[p.type] || p.type}${p.p_snow !== null ? `, P(snow) ${Math.round(p.p_snow * 100)}%` : ""}` : "") +
      (p.powder ? `<br>${esc(p.powder)}` : "") +
      (p.snowlvl_min_ft ? `<br>Snow level down to ${ft(p.snowlvl_min_ft)}` : "") +
      (p.extended ? "<br><i>Extended outlook (hatched)</i>" : ""));
    const firstExt = per.findIndex((p) => p.extended);
    const shapes = firstExt >= 0 ? [{ type: "rect", xref: "x", yref: "paper", x0: firstExt - 0.5, x1: per.length - 0.5,
      y0: 0, y1: 1, fillcolor: "rgba(120,130,150,0.07)", line: { width: 0 }, layer: "below" }] : [];
    // value labels sit above the bar or its whisker, whichever is higher: never on a whisker
    const labels = per.map((p, i) => (y[i] >= 0.5 ? { x: i, y: Math.max(y[i], hasR[i] ? p.snow_hi : 0), yanchor: "bottom",
      yshift: 2, text: inches(y[i]), showarrow: false, font: C.font(12, C.INK) } : null)).filter(Boolean);
    const annotations = [C.axisTitle("Snow (in)"), ...labels,
      ...(firstExt >= 0 ? [{ xref: "x", yref: "paper", x: firstExt - 0.4, y: 1, xanchor: "left", yanchor: "bottom", yshift: 4,
        text: "Extended outlook (hatched)", showarrow: false, font: C.font(12, C.MUTED) }] : [])];
    const top = Math.max(1, ...per.map((p, i) => Math.max(y[i], hasR[i] ? p.snow_hi : 0)));
    const two = C.narrow(el.clientWidth - C.MARGIN.l - C.MARGIN.r, ticks.length);
    C.plot(el, [{
      type: "bar", x, y, marker: {
        color: colors, line: { color: "#5f6f84", width: 0.8 },
        opacity: per.map((p) => (p.is_day ? 1 : 0.6)),
        pattern: { shape: per.map((p) => (p.extended ? "/" : "")), fgcolor: "rgba(30,40,60,0.55)", size: 6, solidity: 0.25 },
      },
      hovertext: hover, hoverinfo: "text",
    }, {
      type: "scatter", mode: "markers", x, y: mid, hoverinfo: "skip", marker: { size: 0.1, color: "rgba(0,0,0,0)" },
      error_y: { type: "data", array: half, color: "#2b3442", thickness: 1, width: 2 },
    }], C.layout(260, { hovermode: "closest", bargap: 0.22, shapes, annotations, margin: { b: two ? 46 : C.MARGIN.b },
      yaxis: C.yaxis({ rangemode: "tozero", range: [0, top * 1.18] }),
      xaxis: { fixedrange: true, tickfont: C.font(C.tick()), tickvals: ticks.map(([i]) => i), tickangle: 0, ticks: "",
               ticktext: ticks.map(([, p]) => C.dayName(C.wall(p.start, tz).slice(0, 10), two)) } }));
    const tot = fc.points[pt].totals["10d"] || fc.points[pt].totals["7d"] || fc.points[pt].totals["72h"];
    const big = per.reduce((b, p) => ((p.snow_in ?? 0) > (b?.snow_in ?? 0) ? p : b), null);
    C.summary(el, big && big.snow_in >= 0.5
      ? `Snowiest period: ${big.label} (${big.local}), most likely ${inches(big.snow_in)} in${big.snow_hi !== null && big.snow_hi !== undefined ? ` (${range(big.snow_lo, big.snow_hi)})` : ""}. Total over ${per.length / 2} days: ${inches(tot?.snow_in)} in.`
      : `Little or no snow in any day or night period of the next ${Math.round(per.length / 2)} days.`);
    C.tableToggle(el, `Snowfall by day and night (${POINT_LABEL[pt].toLowerCase()})`,
      ["Period", "Local time", "Most likely (in)", "Range (in)", "Liquid (in)", "Chance of precip"],
      per.map((p) => [p.label, p.local, plain(p.snow_in), p.snow_hi === null || p.snow_hi === undefined ? "–" : range(p.snow_lo, p.snow_hi),
        plain(p.qpf_in), p.pop === null || p.pop === undefined ? "–" : `${Math.round(p.pop * 100)}%`]));
    return firstExt >= 0;
  }

  /** Chance of precipitation (0-1) at every forecast time, through the whole forecast (fix 4):
   *  the hourly 6-h PoP; where that is missing, the 12-h period's chance of precip; where both
   *  are missing (extended range), NBM's chance of >= 0.1" of snow in the 24-h window. */
  function precipChance(fc, key) {
    const P = fc.points[key], s = P.series, per = P.periods || [];
    const ex = P.exceed?.["24h"], k01 = ex ? ex.thr.indexOf(0.1) : -1;
    return fc.times.map((iso, i) => {
      let p = s.pop?.[i];
      if (p === null || p === undefined) p = per.find((q) => q.start < iso && iso <= q.end)?.pop ?? null;
      if ((p === null || p === undefined) && k01 >= 0) {
        const j = ex.end.findIndex((e, n) => ex.start[n] < iso && iso <= e);
        if (j >= 0 && ex.p[j][k01] !== null) p = ex.p[j][k01] / 100;
      }
      return p;
    });
  }
  const WET = 0.2;     // "precipitation likely": same rule as Powder Finder and the pipeline

  function snowLevelChart(el, fc, keys, tz) {
    const s = fc.points[keys[0]].series, t = fc.times;
    const xs = t.map((x) => C.wall(x, tz));
    let nb = 0;                                  // the 10-90 % band: as long as NBM has the percentiles
    while (nb < t.length && s.snowlvl_p10[nb] !== null && s.snowlvl_p90[nb] !== null) nb++;
    const chance = precipChance(fc, keys[0]);
    const wet = s.snowlvl_ft.map((v, i) => ((chance[i] ?? 0) >= WET ? v : null));
    const lines = keys.map((k) => [POINT_LABEL[k], fc.points[k].elev_ft, k === "summit" || k === "point" ? C.INK : "#7a4e12",
      k === "base" ? "dash" : "solid"]);
    const elevs = keys.map((k) => fc.points[k].elev_ft);
    const minBase = Math.min(...elevs);
    const allV = [...s.snowlvl_ft, ...s.snowlvl_p10.slice(0, nb)].filter((v) => v !== null);
    const lo = Math.max(0, Math.min(minBase - 2500, ...allV) - 500), top = Math.max(...elevs, ...allV.slice(0, 400)) + 1500;
    const ax = C.timeAxis(xs[0], xs[xs.length - 1], el.clientWidth - C.MARGIN.l - C.MARGIN.r);
    const traces = [
      { x: xs.slice(0, nb), y: s.snowlvl_p90.slice(0, nb), mode: "lines", line: { width: 0 }, hoverinfo: "skip" },
      { x: xs.slice(0, nb), y: s.snowlvl_p10.slice(0, nb), mode: "lines", line: { width: 0 }, fill: "tonexty",
        fillcolor: "rgba(230,159,0,0.28)", name: "10–90%", hovertemplate: "10–90%%: %{y:,.0f} ft (low end)<extra></extra>" },
      { x: xs, y: s.snowlvl_ft, mode: "lines", line: { color: "#98a2ae", width: 1.6, dash: "dot" }, name: "Snow level",
        hovertemplate: "Snow level %{y:,.0f} ft<extra></extra>" },
      { x: xs, y: wet, mode: "lines", line: { color: "#9a5300", width: 2.8 }, connectgaps: false, hoverinfo: "skip" },
    ];
    const shapes = [...ax.shapes, { type: "rect", xref: "paper", x0: 0, x1: 1, y0: lo, y1: minBase,
      fillcolor: "rgba(0,114,178,0.10)", line: { width: 0 }, layer: "below" }];
    const annotations = [C.axisTitle("Snow level (ft)")];
    for (const [lab, y, c, dash] of lines) {
      const r = C.refLine(y, `${lab} ${ft(y)}`, { color: c, dash, width: 1.6, where: "left" });
      shapes.push(r.shape); annotations.push(r.ann);
    }
    annotations.push({ xref: "paper", x: 0.99, y: lo, yanchor: "bottom", xanchor: "right", yshift: 3, showarrow: false,
      font: C.font(12, "#0b4f80"), text: `Line in the blue zone = snow to the ${keys.includes("base") ? "base" : "station"}` });
    if (nb > 1) annotations.push({ x: xs[Math.min(nb - 1, Math.floor(nb * 0.85))], y: s.snowlvl_p90[Math.min(nb - 1, Math.floor(nb * 0.85))],
      xref: "x", yref: "y", yanchor: "bottom", showarrow: false, text: "10–90% range", font: C.font(12, "#8a4b00"), yshift: 2 });
    C.plot(el, traces, C.layout(260, { shapes, annotations, xaxis: ax.axis, margin: { b: ax.b },
      yaxis: C.yaxis({ range: [lo, top], tickformat: ",.0f" }) }));
    // summary: lowest snow level while precipitation is likely, vs base/summit
    let wi = -1;
    wet.forEach((v, i) => { if (v !== null && (wi < 0 || v < wet[wi])) wi = i; });
    const base = keys.includes("base") ? fc.points.base.elev_ft : fc.points[keys[0]].elev_ft;
    const rel = (v) => (v <= base ? `below the ${keys.includes("base") ? "base" : "station"} (${ft(base)})`
      : keys.includes("summit") && v >= fc.points.summit.elev_ft ? `above the summit (${ft(fc.points.summit.elev_ft)})` : "between base and summit");
    const vals = s.snowlvl_ft.filter((v) => v !== null);
    C.summary(el, wi >= 0
      ? `Lowest snow level while precipitation is likely: ${ft(wet[wi])} (${localDT(t[wi], tz)}), ${rel(wet[wi])}.`
      : vals.length ? `Little precipitation expected; snow level ${ft(Math.min(...vals))} to ${ft(Math.max(...vals))}.` : "No snow-level forecast.");
    C.tableToggle(el, "Snow level (ft MSL), NBM", ["Time", "Snow level (ft)", "10th pct", "90th pct", "Chance of precip"],
      t.map((x, i) => [localDT(x, tz), plain(s.snowlvl_ft[i]), plain(s.snowlvl_p10[i]), plain(s.snowlvl_p90[i]),
        chance[i] === null || chance[i] === undefined ? "–" : `${Math.round(chance[i] * 100)}%`]));
  }

  // ridge-top (free-air) summit wind from HRRR then RRFS (pipeline/models/ridge.py)
  let ridgeP = null;
  const loadRidge = () => (ridgeP ||= getJSON("data/ridge.json").catch(() => null));
  const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  const compass = (d) => (d === null || d === undefined ? "" : COMPASS[Math.round(d / 22.5) % 16]);
  function ridgeSummary(ridge, id, hours = 24) {
    const r = ridge?.areas?.[id];
    if (!r) return null;
    const now = Date.now(), end = now + hours * 3.6e6;
    let best = null;
    ridge.valid.forEach((t, i) => {
      const x = new Date(t).getTime();
      if (x >= now - 1.8e6 && x <= end && r.mph[i] !== null && (!best || r.mph[i] > best.mph))
        best = { mph: r.mph[i], dir: r.dir[i], model: ridge.models[ridge.src[i]]?.label };
    });
    return best;
  }

  /** Index range of fc.times within the "hour by hour" window, plus its wall-clock bounds. */
  function detailWindow(fc, tz) {
    const t0 = new Date(fc.times[0]).getTime() - 3.6e6, t1 = t0 + (HOURS_DETAIL + 1) * 3.6e6;
    const idx = fc.times.map((x, i) => [i, new Date(x).getTime()]).filter(([, ms]) => ms <= t1).map(([i]) => i);
    return { t0, t1, n: idx.length, w0: C.wall(t0, tz), w1: C.wall(t1, tz) };
  }

  function tempChart(el, fc, keys, tz) {
    const D = detailWindow(fc, tz), P = fc.points;
    const xs = fc.times.slice(0, D.n).map((x) => C.wall(x, tz));
    const ax = C.timeAxis(D.w0, D.w1, el.clientWidth - C.MARGIN.l - 70);
    const traces = keys.map((k) => ({ x: xs, y: P[k].series.t_f.slice(0, D.n), name: POINT_LABEL[k], mode: "lines",
      line: { color: PT_STYLE[k].color, width: 2.2, dash: PT_STYLE[k].dash }, hovertemplate: `${POINT_LABEL[k]} %{y:.0f} °F<extra></extra>` }));
    const r32 = C.refLine(32, "32 °F", { color: "#0b6e85", dash: "dot", where: "left" });
    const annotations = [C.axisTitle("Temperature (°F)"), r32.ann,
      ...keys.map((k) => C.endLabel(xs, P[k].series.t_f.slice(0, D.n), POINT_LABEL[k], PT_STYLE[k].color)).filter(Boolean)];
    C.plot(el, traces, C.layout(220, { margin: { r: 70, b: ax.b }, shapes: [...ax.shapes, r32.shape], annotations, xaxis: ax.axis,
      yaxis: C.yaxis({ dtick: 10 }) }));
    const rng = (k) => { const v = P[k].series.t_f.slice(0, D.n).filter((x) => x !== null); return v.length ? [Math.round(Math.min(...v)), Math.round(Math.max(...v))] : null; };
    C.summary(el, keys.map((k) => { const r = rng(k); return r ? `${POINT_LABEL[k]} ${r[0]} to ${r[1]} °F` : ""; }).filter(Boolean).join(", ") +
      ` over the next ${Math.round(HOURS_DETAIL / 24 * 2) / 2} days${keys.some((k) => (rng(k)?.[1] ?? 99) < 32) ? ", staying below freezing" : ""}.`);
    C.tableToggle(el, "Temperature (°F) and sky cover", ["Time", ...keys.map((k) => `${POINT_LABEL[k]} °F`), "Sky cover"],
      fc.times.slice(0, D.n).map((x, i) => [localDT(x, tz), ...keys.map((k) => plain(P[k].series.t_f[i])),
        P[keys[0]].series.sky[i] === null ? "–" : `${P[keys[0]].series.sky[i]}%`]));
  }

  function windChart(el, fc, pt, keys, ridge, id, tz) {
    const D = detailWindow(fc, tz), P = fc.points;
    const wk = keys.includes("summit") ? "summit" : pt;
    const s = P[wk].series;
    const xs = fc.times.slice(0, D.n).map((x) => C.wall(x, tz));
    const ax = C.timeAxis(D.w0, D.w1, el.clientWidth - C.MARGIN.l - 70);
    const col = C.OI.blue, rc = C.OI.green;
    const traces = [
      { x: xs, y: s.wind_mph.slice(0, D.n), name: "Wind", mode: "lines", line: { color: col, width: 2.2 },
        hovertemplate: `${POINT_LABEL[wk]} wind %{y} mph<extra></extra>` },
      { x: xs, y: s.gust_mph.slice(0, D.n), name: "Gusts", mode: "lines", line: { color: col, width: 1.3, dash: "dot" },
        hovertemplate: "gusts %{y} mph<extra></extra>" },
    ];
    const annotations = [C.axisTitle(`Wind at the ${POINT_LABEL[wk].toLowerCase()} (mph)`),
      C.endLabel(xs, s.wind_mph.slice(0, D.n), "Wind", col), C.endLabel(xs, s.gust_mph.slice(0, D.n), "Gusts", col, { yshift: 10 })];
    const shapes = [...ax.shapes];
    const r = ridge?.areas?.[id];
    let ridgeTxt = "";
    if (r) {
      // HRRR first, then RRFS (ridge.json "src"): two segments of one series with a labelled handoff
      const rx = ridge.valid.map((x) => C.wall(x, tz));
      const seg = (n) => ridge.valid.map((x, i) => (ridge.src[i] === n || ridge.src[i + 1] === n ? r.mph[i] : null));
      const names = ridge.models.map((m) => m.label);
      names.forEach((nm, n) => traces.push({ x: rx, y: seg(n), mode: "lines", connectgaps: false, name: `Ridge-top (${nm})`,
        line: { color: rc, width: 2.4, dash: n === 0 ? "solid" : "dash" },
        customdata: r.dir.map((d) => compass(d)), hovertemplate: `ridge-top %{y} mph %{customdata} (${nm})<extra></extra>` }));
      const k = ridge.src.findIndex((x) => x === 1);
      if (k > 0 && rx[k] < D.w1) {
        shapes.push({ type: "line", xref: "x", yref: "paper", x0: rx[k - 1], x1: rx[k - 1], y0: 0, y1: 1, line: { color: rc, width: 1, dash: "dot" } });
        annotations.push(C.markLabel(rx[k - 1], `${names[0]} → ${names[1]}`, "#006b4f"));
      }
      const lastI = r.mph.map((v, i) => (v !== null ? i : -1)).reduce((a, b) => Math.max(a, b), -1);
      if (lastI >= 0) {
        annotations.push({ ...C.endLabel(rx.slice(0, lastI + 1), r.mph.slice(0, lastI + 1), "Ridge-top", rc), font: C.font(12, "#006b4f") });
        const endMs = new Date(ridge.valid[lastI]).getTime();
        if (endMs < D.t1 - 3 * 3.6e6) ridgeTxt = ` Ridge-top wind (${names.join(" then ")}) ends ${localDT(ridge.valid[lastI], tz)}.`;
      }
      let best = null;
      ridge.valid.forEach((x, i) => { if (r.mph[i] !== null && (!best || r.mph[i] > best.v)) best = { v: r.mph[i], i }; });
      if (best) ridgeTxt = ` Ridge-top wind up to ${best.v} mph from the ${compass(r.dir[best.i])} (${localDT(ridge.valid[best.i], tz)}, ${names[ridge.src[best.i]]}).${ridgeTxt}`;
    }
    C.plot(el, traces, C.layout(220, { margin: { r: 70, b: ax.b }, shapes, annotations: annotations.filter(Boolean), xaxis: ax.axis,
      yaxis: C.yaxis({ rangemode: "tozero" }) }));
    const mx = (a) => Math.max(0, ...a.slice(0, D.n).filter((v) => v !== null));
    C.summary(el, `${POINT_LABEL[wk]} wind up to ${mx(s.wind_mph)} mph, gusts to ${mx(s.gust_mph)} mph (NBM, 10 m).${ridgeTxt}`);
    const rows = fc.times.slice(0, D.n).map((x, i) => {
      const j = r ? ridge.valid.indexOf(x) : -1;
      return [localDT(x, tz), plain(s.wind_mph[i]), plain(s.gust_mph[i]),
        j >= 0 && r.mph[j] !== null ? `${r.mph[j]} ${compass(r.dir[j])} (${ridge.models[ridge.src[j]]?.label})` : "–"];
    });
    C.tableToggle(el, "Wind (mph)", ["Time", "Wind", "Gusts", "Ridge-top"], rows);
  }

  function snowRateChart(el, fc, pt, tz) {
    const D = detailWindow(fc, tz), pr = fc.points[pt].precip;
    const keep = pr.end.map((e, i) => i).filter((i) => new Date(pr.end[i]).getTime() <= D.t1);
    const mid = keep.map((i) => C.wall(new Date(pr.end[i]).getTime() - pr.hours[i] * 1.8e6, tz));
    const rate = keep.map((i) => (pr.snow_in[i] === null ? null : f1(pr.snow_in[i] / pr.hours[i] * 10) / 10));
    const ax = C.timeAxis(D.w0, D.w1, el.clientWidth - C.MARGIN.l - 70);
    const hourly = keep.map((i) => pr.hours[i] === 1);
    const text = keep.map((i) => `${localDT(new Date(new Date(pr.end[i]).getTime() - pr.hours[i] * 3.6e6).toISOString(), tz)}–` +
      `${localFmt(pr.end[i], tz, { hour: "numeric" })}: ${plain(pr.snow_in[i])} in snow` +
      (pr.hours[i] > 1 ? ` in ${pr.hours[i]} h` : "") + ` · liquid ${plain(pr.qpf_in[i])} in` +
      (pr.pop?.[i] !== null && pr.pop?.[i] !== undefined ? ` · precip chance ${Math.round(pr.pop[i] * 100)}%` : ""));
    const k6 = hourly.indexOf(false);
    const annotations = [C.axisTitle("Snow rate (in per hour)")];
    const shapes = [...ax.shapes];
    if (k6 > 0) {
      const xb = C.wall(new Date(pr.end[keep[k6]]).getTime() - pr.hours[keep[k6]] * 3.6e6, tz);
      shapes.push({ type: "line", xref: "x", yref: "paper", x0: xb, x1: xb, y0: 0, y1: 1, line: { color: C.MUTED, width: 1, dash: "dot" } });
      annotations.push(C.markLabel(xb, "6-h averages →"));
    }
    C.plot(el, [{ type: "bar", x: mid, y: rate, width: keep.map((i) => pr.hours[i] * 3.6e6 * 0.88),
      marker: { color: hourly.map((h) => (h ? C.OI.blue : "#4d9fd6")), line: { width: 0 } },
      customdata: text, hovertemplate: "%{customdata}<br>%{y:.2f} in/hr<extra></extra>" }],
    C.layout(220, { margin: { r: 70, b: ax.b }, bargap: 0, shapes, annotations, xaxis: ax.axis,
      yaxis: C.yaxis({ rangemode: "tozero", tickformat: ".2~f", range: [0, Math.max(0.1, ...rate.filter((v) => v !== null)) * 1.15] }) }));
    let bi = -1;
    rate.forEach((v, j) => { if (v !== null && (bi < 0 || v > rate[bi])) bi = j; });
    const total = keep.reduce((a, i) => a + (pr.snow_in[i] ?? 0), 0);
    C.summary(el, bi >= 0 && rate[bi] >= 0.05
      ? `Heaviest snow about ${rate[bi].toFixed(2)} in per hour (${text[bi].split(":")[0]}); about ${inches(total)} in in the next ${Math.round(HOURS_DETAIL / 24 * 2) / 2} days (most likely).`
      : `Little or no snow in the next ${Math.round(HOURS_DETAIL / 24 * 2) / 2} days (most likely ${inches(total)} in).`);
    C.tableToggle(el, `Snow and liquid precipitation (${POINT_LABEL[pt].toLowerCase()})`, ["Period", "Hours", "Snow (in)", "Liquid (in)", "Chance of precip"],
      keep.map((i, j) => [text[j].split(":")[0], pr.hours[i], plain(pr.snow_in[i]), plain(pr.qpf_in[i]),
        pr.pop?.[i] === null || pr.pop?.[i] === undefined ? "–" : `${Math.round(pr.pop[i] * 100)}%`]));
  }

  // ---------------------------------------------------------------- forecaster discussion (AFD)
  const AFD_STOP = new Set(["northern", "southern", "eastern", "western", "central", "northwest", "southwest", "inland",
    "california", "oregon", "washington", "idaho", "montana", "wyoming", "utah", "colorado", "nevada", "arizona", "mexico",
    "lake", "mount", "mountain", "mountains", "resort", "area", "valley", "basin", "peak", "lodge", "ridge", "creek",
    "high", "county", "summit", "snow", "bowl", "village", "park", "station", "pass", "ranch", "range", "front"]);
  const afdTerms = (a) => [...new Set(`${a.region || ""} ${a.name || ""}`.replace(/[^A-Za-z ]/g, " ").split(/\s+/)
    .filter((w) => w.length >= 4 && !AFD_STOP.has(w.toLowerCase())))];
  async function afdSection(el, a, wfo, tz) {
    if (!wfo) { el.hidden = true; return; }
    let idx;
    try { idx = await getJSON("data/afd/index.json"); } catch { el.hidden = true; return; }
    const o = idx.offices?.[wfo];
    if (!o) { el.hidden = true; return; }
    const link = `https://forecast.weather.gov/product.php?site=NWS&issuedby=${encodeURIComponent(wfo)}&product=AFD&format=txt&version=1`;
    el.innerHTML = `<h3>Forecaster discussion</h3>
      <details class="afd"><summary>Area Forecast Discussion, NWS ${esc(o.office)} · issued
        ${localFmt(o.issued, tz, { weekday: "short", hour: "numeric", minute: "2-digit", timeZoneName: "short" })} (${ago(o.issued)})</summary>
        <div class="afd-body"><p class="hint">Loading…</p></div></details>
      <p class="note"><a href="${link}" target="_blank" rel="noopener">Read it on weather.gov →</a> Written by NWS forecasters for the
        whole office area; paragraphs that mention ${esc(afdTerms(a).join(", ") || "this area")} are highlighted.</p>`;
    el.querySelector("details").addEventListener("toggle", async (e) => {
      const body = el.querySelector(".afd-body");
      if (!e.target.open || body.dataset.done) return;
      try {
        const d = await getJSON(`data/afd/${encodeURIComponent(wfo)}.json`);
        const terms = afdTerms(a), re = terms.length ? new RegExp(`\\b(${terms.join("|")})\\b`, "i") : null;
        const paras = d.text.split(/\n\s*\n/).map((x) => x.trim()).filter((x) => x && x !== "&&");
        body.innerHTML = paras.map((x) => `<p class="${re && re.test(x) ? "hit" : ""}">${esc(x.replace(/\n/g, " "))}</p>`).join("");
        body.dataset.done = "1";
      } catch (err) { body.innerHTML = `<p class="hint">Could not load the discussion (${esc(err.message)}).</p>`; }
    });
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
      ` (${chg >= 0 ? "+" : ""}${Math.round(chg)} in in 72 h)`}.</p><div class="chart" id="obs-chart" style="height:220px"><p class="hint">Loading chart…</p></div>`;
    // SNOTEL times are the station's local standard time (wall clock already)
    const xs = d.times.map((t) => t.slice(0, 16));
    const swe = d.WTEQ || [];
    C.lazy($("obs-chart"), () => loadPlotly().then(() => {
      const el = $("obs-chart");
      const ax = C.timeAxis(xs[0], xs[xs.length - 1], el.clientWidth - C.MARGIN.l - 60);
      C.plot(el, [
        { x: xs, y: series, name: "Depth", mode: "lines", line: { color: C.OI.blue, width: 2.2 }, hovertemplate: "depth %{y:.0f} in<extra></extra>" },
        { x: xs, y: swe, name: "SWE", mode: "lines", line: { color: C.OI.green, width: 2, dash: "dash" }, hovertemplate: "SWE %{y:.1f} in<extra></extra>" },
      ], C.layout(220, { margin: { r: 60, b: ax.b }, shapes: ax.shapes, xaxis: ax.axis, yaxis: C.yaxis({ rangemode: "tozero" }),
        annotations: [C.axisTitle("Snow depth and SWE (in)"), C.endLabel(xs, series, "Depth", C.OI.blue),
          C.endLabel(xs, swe, "SWE", "#00704f")].filter(Boolean) }));
      const [sw] = last(swe);
      C.summary(el, `${st.name}: snow depth ${depth === null ? "unknown" : `${Math.round(depth)} in`}${chg === null ? "" : ` (${chg >= 0 ? "+" : ""}${Math.round(chg)} in in 72 h)`}` +
        `${sw === null ? "" : `, snow water equivalent ${sw.toFixed(1)} in`} (last 7 days, local standard time).`);
      C.tableToggle(el, `${st.name} SNOTEL, hourly`, ["Time (local std.)", "Depth (in, 3-h median)", "SWE (in)"],
        xs.map((x, k) => [x, series[k] === null || series[k] === undefined ? "–" : Math.round(series[k]), swe[k] ?? "–"]).reverse());
    }));
  }

  // NOHRSC snowfall analysis + SNODAS at the area's base and summit (data/nohrsc/ski.json).
  async function nohrscObs(el, a, tz) {
    let js;
    try { js = await getJSON("data/nohrsc/ski.json"); } catch { return; }
    const r = js.areas?.[a.id];
    if (!r) return;
    const f = (v, d = 1) => (v === null || v === undefined ? "–" : `${Number(v).toFixed(d)}"`);
    const when = (iso) => (iso ? localFmt(iso, tz, { weekday: "short", hour: "numeric", timeZoneName: "short" }) : "–");
    const row = (k) => `<tr><th scope="row">${POINT_LABEL[k]} ${ft(a[k].elev_ft)}</th><td>${f(r[k].sf24)}</td><td>${f(r[k].sf48)}</td>
      <td>${f(r[k].sf72)}</td><td>${f(r[k].depth, 0)}</td><td>${f(r[k].swe)}</td></tr>`;
    el.innerHTML = `<table class="metrics nohrsc"><thead><tr><th scope="col"><span class="sr">Point</span></th><th scope="col">24 h</th><th scope="col">48 h</th><th scope="col">72 h</th>
        <th scope="col">Depth</th><th scope="col">SWE</th></tr></thead><tbody>${row("summit")}${row("base")}</tbody></table>
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

  // Active NWS alerts for this site (data/alerts/index.json; details.json on expand).
  function alertBanner(refs, index, link, tz) {
    if (!refs?.length) return "";
    const until = (iso) => (iso ? `until ${localFmt(iso, tz, { weekday: "short", hour: "numeric", timeZoneName: "short" })}` : "");
    // winter / wind / avalanche / blizzard / cold first; nothing is hidden, the rest collapse
    const main = refs.filter((r) => r.relevant !== false), other = refs.filter((r) => r.relevant === false);
    const one = (r) => {
      const a = index.alerts[r.id] || {};
      return `<details class="alert-banner ${esc(r.level)}" data-id="${esc(r.id)}">
        <summary><strong>${esc(r.event)}</strong> ${esc(until(r.ends))}<span class="by">${esc(a.sender || "")}</span></summary>
        <div class="alert-body"><p class="hint">${esc(a.area || "")}</p><div class="alert-text">Loading…</div>
          <p><a href="${esc(link)}" target="_blank" rel="noopener">NWS forecast and full alert →</a></p></div>
      </details>`;
    };
    return main.map(one).join("") + (other.length ? `<details class="other-alerts"><summary>Other alerts (${other.length}):
      ${other.map((r) => esc(r.event)).join(", ")}</summary>${other.map(one).join("")}</details>` : "");
  }
  async function wireAlertDetails(root) {
    let details = null;
    root.querySelectorAll("details.alert-banner").forEach((d) => d.addEventListener("toggle", async () => {
      if (!d.open) return;
      try { details = details || await getJSON("data/alerts/details.json"); } catch { details = {}; }
      const t = details[d.dataset.id] || {};
      d.querySelector(".alert-text").innerHTML = `<p>${esc(t.description || "No text.").replace(/\n\n/g, "</p><p>")}</p>` +
        (t.instruction ? `<p><strong>${esc(t.instruction)}</strong></p>` : "");
    }));
  }

  // A forecast site: a ski area (summit + base) or a SNOTEL station (one elevation).
  function siteFromStation(st) {
    return { kind: "snotel", id: `snotel-${st.triplet.replace(/:/g, "-")}`, name: st.name, state: st.state, tz: st.tz,
      lat: st.lat, lon: st.lon, elev_ft: st.elev_ft, triplet: st.triplet,
      nearest: { snotel: [{ id: st.triplet, name: st.name, elev_ft: st.elev_ft }] } };
  }

  async function render() {
    const id = decodeURIComponent(location.hash.replace(/^#/, ""));
    const main = $("area");
    const isStation = id.startsWith("snotel-");
    // One request per source (each file embeds its site record); catalogs only as fallback.
    const [fcR, nwsR, avyR, alR] = await Promise.allSettled([
      id ? getJSON(`data/points/${encodeURIComponent(id)}.json`) : Promise.reject(new Error("no id")),
      id ? getJSON(`data/ndfd/${encodeURIComponent(id)}.json`) : Promise.reject(new Error("no id")),
      isStation ? Promise.resolve(null) : getJSON("data/avalanche_ratings.json"),
      getJSON("data/alerts/index.json")]);
    const nbm = fcR.status === "fulfilled" ? fcR.value : null;
    const nws = nwsR.status === "fulfilled" ? nwsR.value : null;
    let a = isStation ? (nbm?.station && siteFromStation(nbm.station)) : nbm?.area;
    if (!a && isStation) {
      try {
        const st = (await getJSON("data/snotel_points.json")).points.find((x) => x.id === id);
        if (st) a = siteFromStation(st);
      } catch { /* fall through */ }
    }
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
    let src = nbm ? "nbm" : nws ? "nws" : null;
    const doc = () => (src === "nws" ? nws : nbm);
    const keysOf = (d) => (d ? ["summit", "base", "point"].filter((k) => d.points[k]) : []);
    let pt = keysOf(doc())[0];
    const isFav = favs().includes(a.id);
    const nwsLink = (p) => `https://forecast.weather.gov/MapClick.php?lat=${p.lat}&lon=${p.lon}`;
    const sub = isStation
      ? `SNOTEL ${esc(a.triplet)} · ${esc(a.state)} · ${ft(a.elev_ft)}`
      : `${esc(a.region)}, ${esc(a.state)} · Summit ${ft(a.summit.elev_ft)} · Base ${ft(a.base.elev_ft)} · ${ft(a.vertical_ft)} vertical`;
    const srcSeg = nbm && nws ? `<div class="seg" role="group" aria-label="Forecast source">
        <button type="button" data-src="nbm" class="on" aria-pressed="true">NBM blend</button>
        <button type="button" data-src="nws" aria-pressed="false">NWS official</button></div>` : "";
    main.innerHTML = `
      <div class="area-head">
        <h2>${esc(a.name)}</h2>
        <div class="actions">
          <button id="fav" type="button" aria-pressed="${isFav}" title="Favorite">${isFav ? "★" : "☆"}<span class="sr"> Favorite</span></button>
          <button id="share" type="button" title="Share link">Share</button>
        </div>
      </div>
      <p class="sub">${sub}</p>
      ${alR.status === "fulfilled" ? alertBanner((isStation ? alR.value.points : alR.value.areas)?.[a.id], alR.value,
        nwsLink(isStation ? a : a.summit), tz) : ""}
      ${src ? `<p class="headline" id="headline"></p>
      <p class="fresh" id="fresh"></p>
      <div class="sec-head seg-row">${srcSeg}<span id="elev-seg"></span></div>
      <div id="tiles"></div>
      <section><h3>Snowfall by day and night</h3>
        <div class="chart" id="period-chart" style="height:260px"><p class="hint">Loading chart…</p></div>
        <p class="note" id="period-note"></p></section>
      <section id="ex-sec"><h3>Chance of at least…</h3>
        <div class="seg" role="group" aria-label="Window" id="ex-win"><button type="button" class="on" data-w="24h" aria-pressed="true">24 h</button><button type="button" data-w="48h" aria-pressed="false">48 h</button><button type="button" data-w="72h" aria-pressed="false">72 h</button></div>
        <div id="ex-chart" class="heat-box"><p class="hint">Loading…</p></div>
        <p class="note" id="ex-note"></p></section>
      <section><h3>Snow level vs the ${isStation ? "station" : "mountain"}</h3>
        <div class="chart" id="sl-chart" style="height:260px"><p class="hint">Loading chart…</p></div>
        <p class="note" id="sl-note"></p></section>
      <section><h3>Hour by hour <span class="h3sub" id="hbh-sub"></span></h3><p class="note" id="ridge-note"></p>
        <div class="chart" id="t-chart" style="height:220px"><p class="hint">Loading chart…</p></div>
        <div class="chart" id="w-chart" style="height:220px"><p class="hint">Loading chart…</p></div>
        <div class="chart" id="p-chart" style="height:220px"><p class="hint">Loading chart…</p></div>
        <p class="note" id="met-note"></p></section>`
      : `<p class="hint">No point forecast is available for this site yet.</p>`}
      <section id="afd"></section>
      <section><h3>Recent observations</h3><div id="nohrsc-obs"></div><div id="obs"></div></section>
      ${isStation ? "" : `<section><h3>Avalanche danger</h3>${avalanche(a.avalanche, avyR.status === "fulfilled" ? avyR.value : null)}</section>`}
      <section><h3>More</h3>
        ${isStation
          ? `<p>NWS point forecast: <a href="${nwsLink(a)}" target="_blank" rel="noopener">this site</a> ·
               <a href="index.html#v=depth_in&map=11/${a.lat}/${a.lon}&s=${encodeURIComponent(a.triplet).replace(/%3A/gi, ":")}">Map</a> ·
               <a href="https://wcc.sc.egov.usda.gov/nwcc/site?sitenum=${encodeURIComponent(a.triplet.split(":")[0])}" target="_blank" rel="noopener">NRCS station page</a></p>`
          : `<p>NWS point forecast: <a href="${nwsLink(a.summit)}" target="_blank" rel="noopener">summit</a> ·
               <a href="${nwsLink(a.base)}" target="_blank" rel="noopener">base</a>
               ${a.url ? ` · <a href="${esc(safeUrl(a.url))}" target="_blank" rel="noopener">Area website</a>` : ""}
               · <a href="index.html#map=12/${a.summit.lat}/${a.summit.lon}&s=area:${encodeURIComponent(a.id)}">Map</a></p>
             <h4>Nearby SNOTEL</h4><ul>${stationRows(a.nearest.snotel, "snotel")}</ul>
             <h4>Nearby airports</h4><ul>${stationRows(a.nearest.asos, "asos")}</ul>`}
      </section>`;

    wireAlertDetails(main);
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
    if (src) {
      const drawNumbers = () => {
        const d = doc(), keys = keysOf(d);
        if (!keys.includes(pt)) pt = keys[0];
        const stale = (Date.now() - new Date(d.issued)) / 3.6e6 > (src === "nws" ? 12 : 18);
        $("headline").innerHTML = headline(d, keys);
        $("fresh").className = `fresh${stale ? " stale" : ""}`;
        $("fresh").textContent = `${src === "nws" ? "NWS forecast (NDFD) issued" : "NBM"} ${localFmt(d.issued, tz,
          { weekday: "short", hour: "numeric", timeZoneName: "short" })}${src === "nws" ? "" : " run"} · ${ago(d.issued)}${stale ? " — out of date" : ""}`;
        $("elev-seg").innerHTML = keys.length > 1 ? `<span class="seg" role="group" aria-label="Elevation">${keys.map((k) =>
          `<button type="button" data-pt="${k}" class="${k === pt ? "on" : ""}" aria-pressed="${k === pt}">${POINT_LABEL[k]} ${ft(d.points[k].elev_ft)}</button>`).join("")}</span>` : "";
        $("elev-seg").querySelectorAll("button").forEach((btn) => btn.addEventListener("click", () => {
          pt = btn.dataset.pt; drawNumbers(); drawCharts();
        }));
        $("tiles").innerHTML = tiles(d, pt, d.points[pt].elev_ft);
        const dayLocal = d.points[pt].periods.find((p) => p.is_day)?.local || "about 5 AM–5 PM";
        $("period-note").textContent = src === "nws"
          ? `NWS forecast for the 2.5 km grid cell (elev. ${ft(d.points[pt].grid_elev_ft)}), shown as issued: snowfall to 72 h already includes the forecasters' rain/snow decisions. Days are 12Z–00Z (${dayLocal}).`
          : `Bars: NBM deterministic (most likely; they add up to the totals). Whiskers: NBM's own snowfall percentiles (10–90%). Only when the newest NBM run lacks them does a "derived range (fallback)" appear (25–75% of precipitation × snow ratio × chance of snow). NBM calibrates these separately, so a bar can sit outside its whisker. Days are 12Z–00Z (${dayLocal}); night bars are lighter and unlabelled.${d.points[pt].periods.some((p) => p.extended) ? " Hatched bars = extended outlook (derived range)." : ""}`;
        $("ex-sec").hidden = src === "nws" || !d.points[pt].exceed || !Object.keys(d.points[pt].exceed).length;
        $("ex-note").innerHTML = `NBM's own chance of at least each amount for the 2.5 km grid cell around the ${POINT_LABEL[pt].toLowerCase()}, in ${exWin.replace("h", " h")} windows from about 5 AM (12Z); columns are labelled with the day the window starts (hover for exact times). Separate from the most-likely bars, so they can disagree. NBM only. <a href="about.html#probabilities">How they work →</a>`;
        $("hbh-sub").textContent = `next ${Math.round(HOURS_DETAIL / 24 * 2) / 2} days · times ${tzName(tz)}`;
        $("sl-note").textContent = `Below the line precipitation falls as rain. The line is solid where precipitation is likely (≥ 20% chance) and dotted where it is not; the orange band is NBM's 10–90% range${src === "nws" ? "" : " (as far as NBM provides it, about 10 days)"}. Times ${tzName(tz)}.`;
        $("met-note").textContent = src === "nws"
          ? `NWS forecast for the 2.5 km grid cell (elev. ${ft(d.points[pt].grid_elev_ft)}), as issued — not adjusted to this elevation. Snow in 6-hour amounts, shown as an hourly rate. Days 4–10: see the day/night bars above.`
          : "Temperatures adjusted from the 2.5-km NBM grid to each elevation (6.5 °C/km). Snow: hourly to 36 h, then 6-hour amounts, both shown as a rate (in per hour) so they compare. Ridge-top wind: HRRR, then RRFS. Days 4–10: see the day/night bars above.";
      };
      // Each chart draws when it comes near the viewport (SnowCharts.lazy), one per task, so
      // Plotly only loads once a chart is about to be seen.
      const drawCharts = () => {
        const d = doc(), keys = keysOf(d);
        const withPlotly = (f) => () => Promise.all([loadPlotly(), isStation ? null : loadRidge()]).then(([, ridge]) => f(ridge));
        if (!isStation) loadRidge().then((ridge) => {
          const rs = ridgeSummary(ridge, a.id);
          $("ridge-note").innerHTML = rs ? `<b>Ridge-top wind</b>, next 24 h: up to <b>${rs.mph} mph</b> from ${compass(rs.dir)}
            (${esc(rs.model || "")}, free air at summit height; exposed ridges). NBM's 10 m wind runs lower on exposed summits.
            <a href="about.html#ridge-wind">Why →</a>` : "";
        });
        C.lazy($("period-chart"), withPlotly(() => periodChart($("period-chart"), d, pt, tz)));
        if (!$("ex-sec").hidden) C.lazy($("ex-chart"), () => exceedTable($("ex-chart"), d, pt, tz));
        C.lazy($("sl-chart"), withPlotly(() => snowLevelChart($("sl-chart"), d, keys, tz)));
        C.lazy($("t-chart"), withPlotly(() => tempChart($("t-chart"), d, keys, tz)));
        C.lazy($("w-chart"), withPlotly((ridge) => windChart($("w-chart"), d, pt, keys, ridge, a.id, tz)));
        C.lazy($("p-chart"), withPlotly(() => snowRateChart($("p-chart"), d, pt, tz)));
        return Promise.resolve();
      };
      $("ex-win")?.querySelectorAll("button").forEach((btn) => btn.addEventListener("click", () => {
        exWin = btn.dataset.w;
        $("ex-win").querySelectorAll("button").forEach((x) => { x.classList.toggle("on", x === btn); x.setAttribute("aria-pressed", String(x === btn)); });
        drawNumbers(); drawCharts();
      }));
      drawNumbers();     // plain HTML first; charts after the library arrives
      main.querySelectorAll("[data-src]").forEach((btn) => btn.addEventListener("click", () => {
        src = btn.dataset.src;
        main.querySelectorAll("[data-src]").forEach((x) => { x.classList.toggle("on", x === btn); x.setAttribute("aria-pressed", String(x === btn)); });
        drawNumbers(); drawCharts();
      }));
      requestAnimationFrame(() => drawCharts());
      loadPlotly().catch((e) => {
        main.querySelectorAll(".chart .hint").forEach((h) => { h.textContent = `Charts unavailable: ${e.message}`; });
      });
    }
    if (!isStation) nohrscObs($("nohrsc-obs"), a, tz);
    recentObs($("obs"), a);
    afdSection($("afd"), a, a.nws?.wfo || a.nws?.summit?.wfo || a.nws?.base?.wfo, tz);
  }

  window.addEventListener("hashchange", () => { window.scrollTo(0, 0); render(); });
  render();
})();
