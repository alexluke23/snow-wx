// Shared chart theme and helpers (PLAN.md §6-B). Plain script defining SnowCharts; used by
// area.js (forecast charts) and app.js (SNOTEL panel). Plotly itself is loaded lazily by
// the pages; nothing here touches Plotly until plot() is called.
//
// Standards implemented here:
// - 13 px ticks (12 px under 480 px wide), horizontal 13.5 px axis titles at the top left
//   of each panel with units; no rotated titles; one shared left/right margin.
// - Time axes in the place's local time (Plotly has no time zones: times are converted to
//   local wall-clock strings), weekday + date ticks at local noon, faint midnight lines,
//   subtle night shading (18-06 local); the time zone is stated once by the page.
// - Okabe-Ito colours; summit solid, base dashed; direct labels at line ends.
// - No drag/zoom (pages scroll on touch), unified tap tooltips, explicit container heights
//   (Plotly's responsive resize otherwise shrinks charts to their CSS min-height).
// - summary() = visible one-sentence summary + aria-label; tableToggle() = "View as table".
// - heatTable() for probabilities; lazy() draws a chart when it nears the viewport.

/* global Plotly */
// eslint-disable-next-line no-unused-vars
const SnowCharts = (() => {
  const OI = { orange: "#E69F00", sky: "#56B4E9", green: "#009E73", yellow: "#F0E442", blue: "#0072B2",
    vermillion: "#D55E00", purple: "#CC79A7", black: "#000000" };
  const INK = "#1d2733", MUTED = "#4a5666", GRID = "#e3e8ef", DAYLINE = "#b9c3cf", NIGHT = "rgba(40,60,100,0.055)";
  const FAMILY = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif";
  const small = () => window.matchMedia?.("(max-width: 480px)").matches;
  const font = (size, color = INK) => ({ family: FAMILY, size, color });
  const tick = () => (small() ? 12 : 13);
  const MARGIN = { l: 44, r: 16, t: 30, b: 34 };
  const CONFIG = { displayModeBar: false, responsive: true, scrollZoom: false, doubleClick: false, showTips: false };

  // ---------------------------------------------------------------- time (local wall clock)
  const fmts = new Map();
  function parts(ms, tz) {
    let f = fmts.get(tz);
    if (!f) {
      f = new Intl.DateTimeFormat("en-US", { timeZone: tz, hourCycle: "h23", year: "numeric", month: "2-digit",
        day: "2-digit", hour: "2-digit", minute: "2-digit", weekday: "short" });
      fmts.set(tz, f);
    }
    const o = {};
    for (const p of f.formatToParts(new Date(ms))) o[p.type] = p.value;
    return o;
  }
  /** ISO/ms -> "YYYY-MM-DD HH:MM" in tz (what Plotly date axes display). */
  function wall(t, tz) {
    const p = parts(typeof t === "number" ? t : new Date(t).getTime(), tz);
    return `${p.year}-${p.month}-${p.day} ${p.hour === "24" ? "00" : p.hour}:${p.minute}`;
  }
  const dayName = (dateStr, twoLine = false) => {   // "2026-11-09" -> "Mon 9" (or "Mon<br>9")
    const d = new Date(`${dateStr}T12:00:00Z`);
    return `${d.toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" })}${twoLine ? "<br>" : " "}${d.getUTCDate()}`;
  };
  /** Day labels on two lines when a day gets less than ~56 px (never skip days). */
  const narrow = (widthPx, nDays) => !!widthPx && nDays > 0 && widthPx / nDays < 56;
  const addDays = (dateStr, n) => {
    const d = new Date(`${dateStr}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + n);
    return d.toISOString().slice(0, 10);
  };

  /** x axis + day/night shapes for a local-time range [w0, w1] ("YYYY-MM-DD HH:MM"). */
  function timeAxis(w0, w1, widthPx) {
    const d0 = w0.slice(0, 10), d1 = w1.slice(0, 10);
    const days = [];
    for (let d = d0; d <= d1; d = addDays(d, 1)) days.push(d);
    const inRange = days.filter((d) => `${d} 12:00` >= w0 && `${d} 12:00` <= w1);
    // every day while a day gets >= 28 px (two-line labels below 56 px), else every other day; never rotated
    const step = widthPx && inRange.length && widthPx / inRange.length < 28 ? 2 : 1;
    const ticks = inRange.filter((d, i) => i % step === 0);
    const two = !!widthPx && widthPx / inRange.length * step < 56;
    const shapes = [];
    for (const d of days) {
      const mid = `${d} 00:00`;
      if (mid > w0 && mid < w1) shapes.push({ type: "line", xref: "x", yref: "paper", x0: mid, x1: mid, y0: 0, y1: 1,
        line: { color: DAYLINE, width: 1 }, layer: "below" });
      shapes.push({ type: "rect", xref: "x", yref: "paper", x0: `${d} 18:00`, x1: `${addDays(d, 1)} 06:00`, y0: 0, y1: 1,
        fillcolor: NIGHT, line: { width: 0 }, layer: "below" });
    }
    if (days.length) shapes.push({ type: "rect", xref: "x", yref: "paper", x0: `${addDays(d0, -1)} 18:00`, x1: `${d0} 06:00`,
      y0: 0, y1: 1, fillcolor: NIGHT, line: { width: 0 }, layer: "below" });
    return {
      axis: { type: "date", range: [w0, w1], fixedrange: true, showgrid: false, tickvals: ticks.map((d) => `${d} 12:00`),
        ticktext: ticks.map((d) => dayName(d, two)), tickangle: 0, tickfont: font(tick(), INK), ticks: "", zeroline: false, linecolor: GRID,
        showline: true },
      shapes,
      b: two ? 46 : MARGIN.b,               // bottom margin for one- or two-line day labels
    };
  }

  // ---------------------------------------------------------------- layout pieces
  const yaxis = (extra = {}) => ({ fixedrange: true, gridcolor: GRID, zeroline: false, tickfont: font(tick(), MUTED),
    automargin: false, ...extra });
  /** Horizontal axis title at the panel's top left, e.g. "Snow (in)". */
  const axisTitle = (text, side = "left") => ({ xref: "paper", yref: "paper", x: side === "left" ? 0 : 1,
    xanchor: side === "left" ? "left" : "right", xshift: side === "left" ? -MARGIN.l + 2 : 0, y: 1, yanchor: "bottom",
    yshift: 6, text, showarrow: false, font: font(13.5, INK) });
  /** Labelled horizontal reference line (32 °F, base/summit elevation, zero). */
  function refLine(y, label, { color = MUTED, dash = "dash", width = 1.2, where = "right", yref = "y", xref = "paper" } = {}) {
    return {
      shape: { type: "line", xref, x0: 0, x1: 1, yref, y0: y, y1: y, line: { color, width, dash } },
      ann: { xref, x: where === "right" ? 1 : 0, xanchor: where === "right" ? "right" : "left", yref, y, yanchor: "bottom",
        text: label, showarrow: false, font: font(12, color), bgcolor: "rgba(255,255,255,0.85)", borderpad: 1 },
    };
  }
  /** Label for a vertical marker line, inside the top of the plot (clear of the axis title). */
  const markLabel = (x, text, color = MUTED) => ({ x, xref: "x", yref: "paper", y: 1, yanchor: "top", xanchor: "left",
    xshift: 3, yshift: -2, text, showarrow: false, font: font(12, color), bgcolor: "rgba(255,255,255,0.85)" });
  /** Direct label just right of a trace's last non-null point. */
  function endLabel(xs, ys, text, color, { yref = "y", yshift = 0 } = {}) {
    for (let i = ys.length - 1; i >= 0; i--) {
      if (ys[i] !== null && ys[i] !== undefined) {
        return { x: xs[i], y: ys[i], xref: "x", yref, xanchor: "left", xshift: 5, yshift, text, showarrow: false,
          font: font(12, color), bgcolor: "rgba(255,255,255,0.75)" };
      }
    }
    return null;
  }
  /** Several end labels, nudged apart vertically so none overlap (fix 6). yrange must be the
   *  y axis range actually used and plotHeight the plot area height in px. */
  function endLabels(items, { yrange, plotHeight, gap = 15 }) {
    const [y0, y1] = yrange, k = plotHeight / ((y1 - y0) || 1);
    const L = items.map((it) => {
      const a = endLabel(it.xs, it.ys, it.text, it.color, { yref: it.yref || "y" });
      return a ? { a, base: (a.y - y0) * k, px: (a.y - y0) * k } : null;
    }).filter(Boolean).sort((p, q) => p.px - q.px);
    for (let i = 1; i < L.length; i++) L[i].px = Math.max(L[i].px, L[i - 1].px + gap);
    const over = L.length ? L[L.length - 1].px - (plotHeight - 7) : 0;      // keep inside the plot
    if (over > 0) {
      L[L.length - 1].px -= over;
      for (let i = L.length - 2; i >= 0; i--) L[i].px = Math.min(L[i].px, L[i + 1].px - gap);
    }
    return L.map((l) => ({ ...l.a, yanchor: "middle", yshift: l.px - l.base }));
  }
  /** Padded [min, max] of the finite values in several arrays (explicit ranges keep labels exact). */
  function extent(arrays, { zero = false, pad = 0.06, min = null } = {}) {
    const v = arrays.flat().filter((x) => x !== null && x !== undefined && Number.isFinite(x));
    if (!v.length) return [0, 1];
    let lo = zero ? 0 : Math.min(...v), hi = Math.max(...v);
    if (min !== null) hi = Math.max(hi, lo + min);
    const p = (hi - lo || 1) * pad;
    return [zero ? 0 : lo - p, hi + p];
  }
  const plotH = (lay) => lay.height - lay.margin.t - lay.margin.b;

  function layout(height, extra = {}) {
    return { height, margin: { ...MARGIN, ...(extra.margin || {}) }, font: font(tick()), paper_bgcolor: "#fff",
      plot_bgcolor: "#fff", showlegend: false, hovermode: "x unified", dragmode: false, hoverdistance: 40,
      hoverlabel: { font: font(13), bgcolor: "#fff", bordercolor: "#9aa6b5" }, ...extra,
      ...(extra.margin ? { margin: { ...MARGIN, ...extra.margin } } : {}) };
  }

  /** Draw with an explicit container height so responsive resizes never squash the chart. */
  function plot(el, traces, lay) {
    el.style.height = `${lay.height}px`;
    el.querySelector(":scope > .hint")?.remove();
    return Plotly.react(el, traces, lay, CONFIG);
  }

  // ---------------------------------------------------------------- accessibility
  /** One-sentence summary above the chart, also its aria-label. */
  function summary(el, text) {
    let p = el.previousElementSibling;
    if (!p || !p.classList.contains("chart-sum")) {
      p = document.createElement("p");
      p.className = "chart-sum";
      el.before(p);
    }
    p.textContent = text;
    el.setAttribute("role", "img");
    el.setAttribute("aria-label", text);
  }
  const escHtml = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  /** "View as table" after the chart; the table is built when opened. */
  function tableToggle(el, caption, columns, rows) {
    let d = el.nextElementSibling;
    if (!d || !d.classList.contains("chart-table")) {
      d = document.createElement("details");
      d.className = "chart-table";
      d.innerHTML = "<summary>View as table</summary><div class=\"tbl-wrap\"></div>";
      el.after(d);
      d.addEventListener("toggle", () => { if (d.open) d._build?.(); });
    }
    d._build = () => {
      d.querySelector(".tbl-wrap").innerHTML = `<table><caption>${escHtml(caption)}</caption><thead><tr>${columns.map((c) =>
        `<th scope="col">${escHtml(c)}</th>`).join("")}</tr></thead><tbody>${rows.map((r) =>
        `<tr>${r.map((v, i) => (i === 0 ? `<th scope="row">${escHtml(v)}</th>` : `<td>${escHtml(v ?? "–")}</td>`)).join("")}</tr>`).join("")}</tbody></table>`;
    };
    if (d.open) d._build();
  }

  // ---------------------------------------------------------------- colour helpers
  const lum = (hex) => {
    const n = parseInt(hex.slice(1, 7), 16);
    const ch = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
    return 0.2126 * ch[0] + 0.7152 * ch[1] + 0.0722 * ch[2];
  };
  /** Text colour (#111 or #fff) with the higher WCAG contrast on this background. */
  const textOn = (hex) => {
    const L = lum(hex);
    return (L + 0.05) / (lum("#111111") + 0.05) >= (1.05) / (L + 0.05) ? "#111" : "#fff";
  };

  /** Probability heat table: rows = thresholds, columns = windows, % in every cell. */
  function heatTable(el, { caption, rowLabels, colLabels, colTitles, values, palette }) {
    const cell = (v) => {
      if (v === null || v === undefined) return `<td class="na">–</td>`;
      let i = 0;
      while (i < palette.bins.length && v >= palette.bins[i]) i++;
      const bg = palette.colors[i];
      return `<td style="background:${bg};color:${textOn(bg)}">${v}%</td>`;
    };
    el.querySelector(":scope > .hint")?.remove();
    el.style.height = "";
    el.innerHTML = `<div class="tbl-wrap heat"><table><caption class="sr">${escHtml(caption)}</caption>
      <thead><tr><th scope="col">At least</th>${colLabels.map((c, j) => `<th scope="col"${colTitles ? ` title="${escHtml(colTitles[j])}"` : ""}>${c}</th>`).join("")}</tr></thead>
      <tbody>${rowLabels.map((r, i) => `<tr><th scope="row">${escHtml(r)}</th>${values[i].map(cell).join("")}</tr>`).join("")}</tbody>
    </table></div>`;
  }

  // ---------------------------------------------------------------- lazy drawing
  let io = null;
  const pending = new Map();
  /** Run draw() now if el has been on screen before, else when it comes within ~300 px. */
  function lazy(el, draw) {
    if (el.dataset.seen === "1" || !("IntersectionObserver" in window)) { el.dataset.seen = "1"; return draw(); }
    pending.set(el, draw);
    io ||= new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (!e.isIntersecting) continue;
        io.unobserve(e.target);
        e.target.dataset.seen = "1";
        const f = pending.get(e.target);
        pending.delete(e.target);
        Promise.resolve().then(f).catch((err) => console.warn("chart:", err));
      }
    }, { rootMargin: "300px 0px" });
    io.observe(el);
    return null;
  }

  return { OI, INK, MUTED, GRID, font, tick, MARGIN, CONFIG, wall, dayName, narrow, markLabel, endLabels, extent, plotH, timeAxis, yaxis, axisTitle, refLine, endLabel,
    layout, plot, summary, tableToggle, heatTable, textOn, lazy, small };
})();
