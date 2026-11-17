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
  const SEPARATE = "NBM's expected amount (its deterministic forecast) and its probabilistic forecasts are calibrated separately, " +
    "so the expected amount can fall outside the range.";

  function headline(fc, keys) {
    const pt = keys[0], s = fc.points[pt].totals["72h"];
    if (!s) return "";
    const where = keys.length > 1 ? ` at the ${POINT_LABEL[pt].toLowerCase()}` : "";
    let txt;
    const rng = (t) => (t.snow_hi === null || t.snow_hi === undefined || t.native !== true ? "" : ` (${rangeName(t)} ${range(t.snow_lo, t.snow_hi)})`);
    if (((s.native === true ? s.snow_hi : null) ?? s.snow_in ?? 0) < 0.5) {
      txt = `No significant snow in the next 72 hours${where}.`;
    } else {
      txt = `Next 72 h${where}: expected <strong>${inches(s.snow_in)} in</strong> ${expectedInfo()}` +
            `<span class="rng">${rng(s)}</span>.`;
      const other = keys.find((k) => k !== pt);
      const b = other ? fc.points[other].totals["72h"] : null;
      if (b) txt += ` ${POINT_LABEL[other]}: ${inches(b.snow_in)} in${rng(b)}.`;
    }
    // rain vs snow by elevation, from the wet day/night periods in the first 72 h
    const wet = (k) => fc.points[k].periods.slice(0, 6).filter((p) => (p.qpf_in ?? 0) >= 0.05);
    const types = (k) => new Set(wet(k).map((p) => p.type));
    if (keys.includes("base")) {
      const bt = types("base"), st = types("summit");
      if ((bt.has("mostly rain") || bt.has("mixed")) && st.has("snow")) {
        const sl = wet("summit").map((p) => p.snowlvl_min_ft).filter((v) => v !== null);
        txt += ` <span class="mixnote">Rain or mixed at the ${POINT_LABEL.base.toLowerCase()}, snow ${POINT_LABEL.summit === "Summit" ? "up top" : "on the high terrain"}${sl.length ? ` (snow level down to ~${ft(Math.min(...sl))})` : ""}.</span>`;
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
      let t = P.totals[name];
      if (!t) return "";
      const c = colorFor(SNOWFALL, t.snow_in) || "#f4f6f8";
      // ranges only from ONE native NBM window (t.native); 7/10-day and composite ones: expected total only (owner Nov 16)
      const long = name === "7d" || name === "10d" || (t.snow_hi != null && t.native !== true);
      if (long) { t = { ...t, snow_lo: null, snow_hi: null }; }
      const note = outside(t) ? ` <a class="info" href="about.html#nbm" title="${esc(SEPARATE)}" aria-label="Why the ranges can disagree">ⓘ</a>` : "";
      return `<div class="tile${t.extended ? " ext" : ""}"><span class="label">${label}</span>
        <span class="swatch${snowPale(c) ? " pale" : ""}" style="background:${c}"></span><strong>${inches(t.snow_in)}<small> in</small></strong>
        <span class="rng">${long ? "expected total only (no native NBM range)" : t.snow_hi === null || t.snow_hi === undefined ? "NWS: no range" : `${rangeName(t)}: ${range(t.snow_lo, t.snow_hi)}${note}`}</span>
        <span class="rng liquid">${(t.qpf_in ?? 0).toFixed(2)} in liquid</span></div>`;
    };
    const head = P.raw
      ? `NWS forecast for the 2.5 km grid cell (elev. ${ft(P.grid_elev_ft)}) · ${POINT_LABEL[pt]} ${ft(elev)}`
      : `${POINT_LABEL[pt]} · ${ft(elev)} · expected snowfall (NBM) ${expectedInfo()}`;
    return `<p class="tiles-for">${head}</p>
      <div class="tiles">${cell("24h", "Next 24 h")}${cell("72h", "Next 72 h")}${cell("7d", "Next 7 days")}${cell("10d", "Next 10 days")}</div>`;
  }

  // ---------------------------------------------------------------- charts (shared theme: js/charts/theme.js)
  const C = SnowCharts;
  const PT_STYLE = { summit: { color: C.OI.blue, dash: "solid" }, base: { color: C.OI.vermillion, dash: "dash" },
    point: { color: C.OI.blue, dash: "solid" } };
  const HOURS_DETAIL = 84;            // "Hour by hour" detail (then 6-hourly to day 10)
  const tzName = (tz) => new Date().toLocaleTimeString("en-US", { timeZone: tz, timeZoneName: "short" }).split(" ").pop();
  const localDT = (iso, tz) => localFmt(iso, tz, { weekday: "short", hour: "numeric" });   // "Mon 5 PM"
  const f1 = (v) => (v === null || v === undefined ? null : Math.round(v * 10) / 10);
  const plain = (v) => (v === null || v === undefined ? "–" : String(v));

  // Chance of at least X inches per 24/48/72-h window (NBM probability fields): heat table
  // 2" is NBM's own >2" exceedance field for 24 h and 48 h windows only (NBM publishes none for 72 h: never derived)
  const EX_THR = { "24h": [2, 4, 6, 8, 12, 18, 24], "48h": [2, 4, 6, 8, 12, 18, 24, 36], "72h": [4, 6, 8, 12, 18, 24, 36, 48] };
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

  // ---- Snowfall by day (owner S11) ----
  // 12Z-12Z days (~4-5 AM local). NBM view: a floating bar from NBM's own 25th to 75th percentile for
  // that 24-h window (the "likely" middle half), coloured by its median with the NWS snowfall colours,
  // labelled "low–high″". Percentiles come only from one native NBM window, never added together, so
  // a short first day or a day past the percentile data shows the expected amount instead (hatched
  // grey). NWS view: NDFD's amounts, one solid bar per day.
  const hasV = (v) => v !== null && v !== undefined;
  const MUTED_IN = 0.5;                     // likely high below ~0.5 in: muted, no colour
  function dayRange(d) {                    // "6–12″", "1–3″", "<1″", "4″"
    const lo = Math.round(d.snow_p25), hi = Math.round(d.snow_p75);
    if (d.snow_p75 < MUTED_IN) return "0″";
    if (hi <= 1 && lo === 0) return "<1″";
    return lo === hi ? `${hi}″` : `${lo}–${hi}″`;
  }
  const dayAmount = (v) => (!hasV(v) ? "–" : v < 0.5 ? (v < 0.05 ? "0″" : "<1″") : `${Math.round(v)}″`);
  function dayWords(d, nws) {
    if (nws) return hasV(d.snow_in) ? `NWS forecast: ${d.snow_in < 0.05 ? "no snow" : `${plain(d.snow_in)} in`}` : "no forecast";
    if (hasV(d.snow_p25) && hasV(d.snow_p75)) {
      return d.snow_p75 < MUTED_IN ? "Little or no snow likely (NBM's middle half of outcomes is under ½ in)"
        : `Likely ${dayRange(d).replace("″", "")} in — the middle half of NBM's outcomes`;
    }
    return d.partial ? `Partial day (${d.hours} h) — expected amount, no range: ${plain(d.snow_in)} in`
      : `No NBM range for this day — expected amount: ${plain(d.snow_in)} in`;
  }
  function daySummary(fc, pt, nws) {
    const days = fc.points[pt].days || [];
    const tot = fc.points[pt].totals || {};
    const total = tot["10d"] || tot["7d"] || tot["72h"];
    const key = (d) => (nws || !hasV(d.snow_p75) ? d.snow_in ?? 0 : d.snow_p75);
    const big = days.reduce((b, d) => (key(d) > (b ? key(b) : 0) ? d : b), null);
    const span = tot["10d"] ? "10 days" : tot["7d"] ? "7 days" : "72 hours";
    const part = !nws && days.length && days[0].partial && !hasV(days[0].snow_p75) ? ` First day: partial day — expected amount ${dayAmount(days[0].snow_in)}, no range.` : "";
    const totTxt = total && hasV(total.snow_in) ? ` ${nws ? "NWS total" : "Expected total"} over ${span}: ${inches(total.snow_in)} in.` : "";
    if (!big || key(big) < MUTED_IN) return `Little or no snow on any day in the next ${days.length} days.${totTxt}${part}`;
    return `Snowiest day: ${big.label} (${big.local}) — ${nws ? `${inches(big.snow_in)} in (NWS)` : hasV(big.snow_p75)
      ? `likely ${dayRange(big).replace("″", "")} in` : `expected ${inches(big.snow_in)} in`}.${totTxt}${part}`;
  }
  function periodChart(el, fc, pt, tz, nws = false) {
    const days = fc.points[pt].days || [];
    if (!days.length) { el.innerHTML = `<p class="hint">No daily snowfall data in this forecast file yet.</p>`; return false; }
    const x = days.map((d, i) => i);
    const ranged = days.map((d) => !nws && hasV(d.snow_p25) && hasV(d.snow_p75));
    const muted = days.map((d, i) => (ranged[i] ? d.snow_p75 < MUTED_IN : (d.snow_in ?? 0) < MUTED_IN));
    // bar geometry: NBM = p25..p75 (at least 0.25 in tall so a narrow range stays visible); NWS and
    // days without a native range = 0..amount
    const minH = 0.25;
    const base = days.map((d, i) => (muted[i] ? null : ranged[i] ? d.snow_p25 : 0));
    const top = days.map((d, i) => (muted[i] ? null : ranged[i] ? Math.max(d.snow_p75, d.snow_p25 + minH) : d.snow_in));
    const colorOf = (d, i) => (!ranged[i] && !nws ? "#c9ced6"
      : colorFor(SNOWFALL, ranged[i] ? (hasV(d.snow_p50) ? d.snow_p50 : (d.snow_p25 + d.snow_p75) / 2) : d.snow_in) || "#ffffff");
    const colors = days.map(colorOf);
    const text = days.map((d, i) => (ranged[i] ? dayRange(d) : (nws || muted[i]) ? dayAmount(d.snow_in) : `~${dayAmount(d.snow_in)}`));
    const hover = days.map((d, i) => `<b>${esc(d.label)}</b> (${esc(d.local)})<br>${esc(dayWords(d, nws))}` +
      (ranged[i] && hasV(d.snow_p50) && !muted[i] ? `<br>Median ${plain(d.snow_p50)} in` : "") +
      `<br>Liquid ${d.qpf_in ?? "–"} in${hasV(d.pop) ? ` · chance of precip ${Math.round(d.pop * 100)}%` : ""}`);
    const ymax = Math.max(1, ...top.map((v) => v ?? 0));
    const labels = days.map((d, i) => ({ x: i, y: muted[i] ? 0 : top[i], yanchor: "bottom", yshift: 3, text: text[i], showarrow: false,
      font: C.font(12, muted[i] || (!ranged[i] && !nws) ? C.MUTED : C.INK) }));
    const two = C.narrow(el.clientWidth - C.MARGIN.l - C.MARGIN.r, days.length);
    C.plot(el, [
      { type: "bar", x, base, y: top.map((t, i) => (t === null ? null : t - base[i])), width: 0.62, hovertext: hover, hoverinfo: "text",
        marker: { color: colors, line: { color: "rgba(20,32,46,0.55)", width: 1 },
          pattern: { shape: days.map((d, i) => (!ranged[i] && !nws ? "/" : "")), fgcolor: "rgba(30,40,60,0.45)", size: 6, solidity: 0.2 } } },
      // invisible full-height hover targets so muted days still answer a tap
      { type: "bar", x, y: days.map(() => ymax * 1.1), width: 0.9, marker: { color: "rgba(0,0,0,0)" }, hovertext: hover, hoverinfo: "text" },
    ], C.layout(260, { hovermode: "closest", barmode: "overlay", bargap: 0.2, margin: { b: two ? 46 : C.MARGIN.b },
      annotations: [C.axisTitle(nws ? "Snow (in), NWS" : "Likely snow (in), 25–75%"), ...labels],
      yaxis: C.yaxis({ rangemode: "tozero", range: [0, ymax * 1.22] }),
      xaxis: { fixedrange: true, tickfont: C.font(C.tick()), tickvals: x, tickangle: 0, ticks: "", range: [-0.6, days.length - 0.4],
               ticktext: days.map((d) => C.dayName(C.wall(d.start, tz).slice(0, 10), two)) } }));
    C.summary(el, daySummary(fc, pt, nws));
    el.parentElement.querySelector(".snow-legend")?.remove();      // so tableToggle finds its own toggle again
    C.tableToggle(el, `Snowfall by day (${POINT_LABEL[pt].toLowerCase()})`,
      nws ? ["Day", "Local time", "NWS snow (in)", "Liquid (in)"]
        : ["Day", "Local time", "Likely (25–75%)", "Median (in)", "Expected (in)", "Chance of precip"],
      days.map((d, i) => (nws ? [d.label, d.local, plain(d.snow_in), d.qpf_in ?? "–"]
        : [d.label, d.local, ranged[i] ? dayRange(d) : "–", ranged[i] ? plain(d.snow_p50) : "–", plain(d.snow_in),
          hasV(d.pop) ? `${Math.round(d.pop * 100)}%` : "–"])));
    // colour legend directly under the chart (before the table toggle)
    el.insertAdjacentHTML("afterend", snowLegendHtml(ymax, { minTop: 18, cls: "chart-legend", partial: !nws && days.some((d, i) => !ranged[i] && d.partial) }));
    return days.some((d, i) => !ranged[i] && !nws);
  }

  /** Accumulated snow (owner S11): NBM's expected snowfall piling up, one bar per day on the same
   *  12Z-12Z days as "Snowfall by day", each labelled with the running total. No probabilistic
   *  ranges here. The chart ends exactly at the 10-day total's horizon (a short last step when that
   *  falls mid-day), so its last bar equals the "Next 10 days" amount. NWS view: NDFD's days (72 h). */
  function accumSteps(fc, pt) {
    const P = fc.points[pt], days = P.days || [], T = P.totals || {};
    const tot = T["10d"] || T["7d"] || T["72h"];
    const L = T["10d"] ? 240 : T["7d"] ? 168 : 72;
    const end = tot && tot.from ? new Date(tot.from).getTime() + L * 3.6e6 : Infinity;
    const steps = [];
    let run = 0;
    for (const d of days) {
      const e = new Date(d.end).getTime();
      if (e <= end) {
        run += d.snow_in ?? 0;
        steps.push({ d, add: d.snow_in ?? 0, run, end: d.end, cut: false });
      } else if (tot && hasV(tot.snow_in) && new Date(d.start).getTime() < end) {
        steps.push({ d, add: Math.max(0, tot.snow_in - run), run: tot.snow_in, end: new Date(end).toISOString(), cut: true });
        run = tot.snow_in;
        break;
      }
    }
    return { steps, tot, span: T["10d"] ? "10 days" : T["7d"] ? "7 days" : "72 hours" };
  }
  function accumSummary(fc, pt, nws) {
    const { steps, tot, span } = accumSteps(fc, pt);
    const final = tot && hasV(tot.snow_in) ? tot.snow_in : steps.length ? steps[steps.length - 1].run : 0;
    if (final < 0.5) return `Little or no snow expected over the next ${span}.`;
    const big = steps.reduce((b, x) => (x.add > (b ? b.add : 0) ? x : b), null);
    return `${nws ? "NWS total" : "Expected total"} over the next ${span}: ${inches(final)} in` +
      (big && big.add >= 0.5 ? `, most on ${big.d.label} (+${inches(big.add)} in).` : ".");
  }
  function accumChart(el, fc, pt, tz, nws = false) {
    const { steps } = accumSteps(fc, pt);
    if (!steps.length) { el.innerHTML = `<p class="hint">No daily snowfall data in this forecast file yet.</p>`; return; }
    const x = steps.map((s, i) => i);
    const y = steps.map((s) => Math.round(s.run * 10) / 10);
    const endTxt = (s) => new Date(s.end).toLocaleString([], { weekday: "short", hour: "numeric", timeZone: tz });
    const hover = steps.map((s) => `<b>By ${esc(endTxt(s))}</b>: ${plain(s.run)} in ${nws ? "(NWS)" : "expected"}` +
      `<br>${esc(s.d.label)}${s.cut ? ` (to ${esc(endTxt(s))}, end of the ${nws ? "forecast" : "10-day total"})` : ""}: +${plain(s.add)} in`);
    const ymax = Math.max(1, ...y);
    const labels = steps.map((s, i) => ({ x: i, y: y[i], yanchor: "bottom", yshift: 3, showarrow: false,
      text: y[i] < 0.5 ? "0″" : `${Math.round(y[i])}″`, font: C.font(12, y[i] < 0.5 ? C.MUTED : C.INK) }));
    const two = C.narrow(el.clientWidth - C.MARGIN.l - C.MARGIN.r, steps.length);
    const colors = y.map((v) => colorFor(SNOWFALL, v) || "#ffffff");
    C.plot(el, [
      { type: "bar", x, y, width: steps.map((s) => (s.cut ? 0.36 : 0.62)), hovertext: hover, hoverinfo: "text",
        marker: { color: colors, line: { color: "rgba(20,32,46,0.55)", width: 1 } } },
    ], C.layout(240, { hovermode: "closest", bargap: 0.2, margin: { b: two ? 46 : C.MARGIN.b },
      annotations: [C.axisTitle(nws ? "Running total (in), NWS" : "Expected running total (in)"), ...labels],
      yaxis: C.yaxis({ rangemode: "tozero", range: [0, ymax * 1.2] }),
      xaxis: { fixedrange: true, tickfont: C.font(C.tick()), tickvals: x, tickangle: 0, ticks: "", range: [-0.6, steps.length - 0.4],
               ticktext: steps.map((s) => C.dayName(C.wall(s.d.start, tz).slice(0, 10), two) + (s.cut && !two ? "*" : "")) } }));
    C.summary(el, accumSummary(fc, pt, nws));
    C.tableToggle(el, `Accumulated snow (${POINT_LABEL[pt].toLowerCase()})`,
      ["Day", "Until", `That day (in)`, `Running total (in)`],
      steps.map((s) => [s.d.label, endTxt(s), plain(s.add), plain(s.run)]));
  }

  /** Snow ratio + powder quality in ONE panel (dev13 item 4). NBM's snow-to-liquid ratio (SNOWLR): p50 line and
   *  p10-p90 band, drawn only where snow is falling (SNOWLR is ~0 otherwise). Background bands = the documented
   *  powder-quality heuristic (Dense < 10:1, Medium 10-15, Blower >= 15; PLAN §5.2, about.html#powder-quality);
   *  a marker where summit gusts exceed 30 mph while it snows ("wind-affected"). A heuristic, not an accuracy claim.
   *  Band colors are Okabe-Ito categories (never the NWS snowfall palette); every band is also labelled in text. */
  const POWDER = [["Dense", 0, 10, "#CC79A7"], ["Medium", 10, 15, "#009E73"], ["Blower", 15, Infinity, "#56B4E9"]];
  const POWDER_WIND_MPH = 30;
  function snowingMask(fc, pt) {
    // time i is "snowing" when the precipitation window containing it has snow (hourly to 36 h, then 6-hourly)
    const pr = fc.points[pt].precip;
    return fc.times.map((iso) => {
      const t = new Date(iso).getTime();
      for (let k = 0; k < pr.end.length; k++) {
        const e = new Date(pr.end[k]).getTime(), b = e - (pr.hours[k] || 1) * 3.6e6;
        if (t > b && t <= e) return (pr.snow_in[k] ?? 0) > 0;
      }
      return false;
    });
  }
  function slrChart(el, fc, pt, tz) {
    const P = fc.points[pt], s = P.series, xs = fc.times.map((x) => C.wall(x, tz));
    const snowing = snowingMask(fc, pt);
    const only = (arr) => arr.map((v, i) => (snowing[i] && v ? v : null));
    const p50 = only(s.slr), p10 = only(s.slr_p10 || []), p90 = only(s.slr_p90 || []);
    const windy = fc.times.map((_, i) => (snowing[i] && (s.gust_mph?.[i] ?? 0) > POWDER_WIND_MPH && p50[i] ? i : null)).filter((v) => v !== null);
    const ymax = Math.max(24, ...p90.filter(Boolean).map((v) => v + 3), ...p50.filter(Boolean).map((v) => v + 3));
    const ax = C.timeAxis(xs[0], xs[xs.length - 1], el.clientWidth - C.MARGIN.l - 20);
    const shapes = [...ax.shapes], annotations = [C.axisTitle(C.small() ? "Snow ratio (snow : water)" : "Snow ratio (inches of snow per inch of water)")];
    for (const [name, lo, hi, col] of POWDER) {
      const top = Math.min(hi, ymax);
      shapes.push({ type: "rect", xref: "paper", yref: "y", x0: 0, x1: 1, y0: lo, y1: top, fillcolor: col, opacity: 0.16,
        line: { width: 0 }, layer: "below" });
      annotations.push({ xref: "paper", x: 0.995, xanchor: "right", yref: "y", y: (lo + top) / 2, yanchor: "middle", showarrow: false,
        bgcolor: "rgba(255,255,255,0.8)", borderpad: 2,
        text: `<b>${name}</b> ${hi === Infinity ? `≥ ${lo}` : lo === 0 ? `< ${hi}` : `${lo}–${hi}`}:1`, font: C.font(12, "#1f2937") });
    }
    const hasSnow = p50.some(Boolean);
    const traces = [];
    if (p10.some(Boolean) && p90.some(Boolean)) {
      traces.push({ x: xs, y: p90, mode: "lines", line: { width: 0 }, hoverinfo: "skip", connectgaps: false },
        { x: xs, y: p10, mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: "rgba(31,41,55,0.22)", hoverinfo: "skip", connectgaps: false });
    }
    traces.push({ x: xs, y: p50, mode: "lines", line: { color: "#111827", width: 2.6 }, connectgaps: false,
      customdata: p10.map((v, i) => [v, p90[i]]), hovertemplate: "ratio %{y:.0f}:1 (10–90%: %{customdata[0]:.0f}–%{customdata[1]:.0f})<extra></extra>" });
    if (windy.length) {
      traces.push({ x: windy.map((i) => xs[i]), y: windy.map(() => ymax * 0.93), mode: "markers", hovertemplate: "wind-affected: summit gusts over 30 mph while snowing<extra></extra>",
        marker: { symbol: "diamond", size: 9, color: C.OI.vermillion, line: { color: "#111827", width: 1 } } });
      annotations.push({ xref: "paper", x: 1, xanchor: "right", yref: "paper", y: 1, yanchor: "bottom", yshift: 4, showarrow: false,
        text: C.small() ? "◆ wind-affected" : "◆ wind-affected (gusts > 30 mph while snowing)", font: C.font(12, "#7a2e00") });
    }
    if (!hasSnow) annotations.push({ xref: "paper", yref: "paper", x: 0.5, y: 0.5, showarrow: false, text: "No snow expected: no snow ratio", font: C.font(14, C.MUTED) });
    C.plot(el, traces, C.layout(280, { margin: { r: 20, b: ax.b }, showlegend: false, shapes, annotations, xaxis: ax.axis,
      yaxis: C.yaxis({ range: [0, ymax] }) }));
    const per = P.periods.filter((p) => p.powder);
    const label = (p) => `${p.label} ${Math.round(p.slr)}:1 ${p.powder.split(",")[0].toLowerCase()}${/wind/.test(p.powder) ? ", wind-affected" : ""}`;
    C.summary(el, per.length
      ? `Snow ratio and powder quality (a documented heuristic): ${per.slice(0, 4).map(label).join("; ")}${per.length > 4 ? "; …" : ""}.`
      : "No snow expected, so no snow ratio or powder quality.");
    C.tableToggle(el, "Snow ratio and powder quality by period (documented heuristic)",
      ["Period", "Snow ratio", "Powder quality", "Wind-affected", "Expected snow (in)"],
      P.periods.map((p) => [p.label, p.slr && p.powder ? `${Math.round(p.slr)}:1` : "–", p.powder ? p.powder.split(",")[0] : "–",
        p.powder ? (/wind/.test(p.powder) ? "yes" : "no") : "–", plain(p.snow_in)]));
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
  const WET = 0.2;
  /** NWS wind chill (°F) for T <= 50 °F and wind >= 3 mph, else the air temperature. */
  const windChill = (t, v) => (t === null || v === null || t === undefined || v === undefined ? null
    : t <= 50 && v >= 3 ? Math.round(35.74 + 0.6215 * t - 35.75 * v ** 0.16 + 0.4275 * t * v ** 0.16) : Math.round(t));     // "precipitation likely": same rule as Powder Finder and the pipeline

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

  const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  const compass = (d) => (d === null || d === undefined ? "" : COMPASS[Math.round(d / 22.5) % 16]);

  /** Index range of fc.times within the "hour by hour" window, plus its wall-clock bounds. */
  /** "Hour by hour" time frame: detail (hourly/3-hourly) to HOURS_DETAIL, then NBM's 6-hourly values to the
   *  end of the forecast (~day 10-11), lightly shaded and labelled "extended (6-hourly)" (owner S6/S7). */
  function detailWindow(fc, tz) {
    const t0 = new Date(fc.times[0]).getTime() - 3.6e6, t1 = t0 + (HOURS_DETAIL + 1) * 3.6e6;
    const idx = fc.times.map((x, i) => [i, new Date(x).getTime()]).filter(([, ms]) => ms <= t1).map(([i]) => i);
    const tEnd = new Date(fc.times[fc.times.length - 1]).getTime() + 3 * 3.6e6;
    return { t0, t1, tEnd, n: idx.length, N: fc.times.length, w0: C.wall(t0, tz), w1: C.wall(t1, tz), wEnd: C.wall(tEnd, tz) };
  }
  const extendedShade = (D, label = C.small() ? "6-hourly" : "extended (6-hourly)") => ({
    shape: { type: "rect", xref: "x", yref: "paper", x0: D.w1, x1: D.wEnd, y0: 0, y1: 1, fillcolor: "rgba(110,122,140,0.10)",
      line: { width: 0 }, layer: "below" },
    // right-aligned at the end of the axis, clear of the labels near the 3.5-day mark
    ann: { ...C.markLabel(D.wEnd, label), xanchor: "right", xshift: -3 },
  });
  const rangeOf = (a) => { const v = a.filter((x) => x !== null && x !== undefined); return v.length ? [Math.round(Math.min(...v)), Math.round(Math.max(...v))] : null; };

  function tempChart(el, fc, keys, tz) {
    const D = detailWindow(fc, tz), P = fc.points;
    const xs = fc.times.map((x) => C.wall(x, tz));
    const ax = C.timeAxis(D.w0, D.wEnd, el.clientWidth - C.MARGIN.l - 70);
    const ext = extendedShade(D);
    const traces = keys.map((k) => ({ x: xs, y: P[k].series.t_f, name: POINT_LABEL[k], mode: "lines",
      line: { color: PT_STYLE[k].color, width: 2.2, dash: PT_STYLE[k].dash }, hovertemplate: `${POINT_LABEL[k]} %{y:.0f} °F<extra></extra>` }));
    const rec = fc.area?.kind === "snopark";
    const wck = rec ? (keys.includes("summit") ? "summit" : keys[0]) : null;
    const wc = rec ? P[wck].series.t_f.map((t, i) => windChill(t, P[wck].series.wind_mph[i])) : null;
    if (rec) traces.push({ x: xs, y: wc, name: "Wind chill", mode: "lines", line: { color: C.OI.purple, width: 1.6, dash: "dot" },
      hovertemplate: `wind chill (${POINT_LABEL[wck].toLowerCase()}) %{y} °F<extra></extra>` });
    const r32 = C.refLine(32, "32 °F", { color: "#0b6e85", dash: "dot", where: "left" });
    const lay = C.layout(220, { margin: { r: 70, b: ax.b }, shapes: [...ax.shapes, ext.shape, r32.shape], xaxis: ax.axis });
    const yr = C.extent([...keys.map((k) => P[k].series.t_f), [32], ...(wc ? [wc] : [])], { min: 10 });
    lay.yaxis = C.yaxis({ dtick: 10, range: yr });
    lay.annotations = [C.axisTitle(rec ? "Temperature and wind chill (°F)" : "Temperature (°F)"), r32.ann, ext.ann,
      ...C.endLabels([...keys.map((k) => ({ xs, ys: P[k].series.t_f, text: POINT_LABEL[k], color: PT_STYLE[k].color })),
        ...(wc ? [{ xs, ys: wc, text: "Wind chill", color: "#9c3d78" }] : [])], { yrange: yr, plotHeight: C.plotH(lay) })];
    C.plot(el, traces, lay);
    const rng = (k) => rangeOf(P[k].series.t_f.slice(0, D.n));
    const later = rangeOf(P[keys[0]].series.t_f.slice(D.n));
    C.summary(el, keys.map((k) => { const r = rng(k); return r ? `${POINT_LABEL[k]} ${r[0]} to ${r[1]} °F` : ""; }).filter(Boolean).join(", ") +
      ` over the next ${Math.round(HOURS_DETAIL / 24 * 2) / 2} days${keys.some((k) => (rng(k)?.[1] ?? 99) < 32) ? ", staying below freezing" : ""}` +
      `${later ? `; later (6-hourly) ${POINT_LABEL[keys[0]].toLowerCase()} ${later[0]} to ${later[1]} °F` : ""}.` +
      (wc ? ` Coldest wind chill on the ${POINT_LABEL[wck].toLowerCase()}: ${Math.min(...wc.slice(0, D.n).filter((v) => v !== null))} °F in the next 3½ days.` : ""));
    C.tableToggle(el, "Temperature (°F) and sky cover", ["Time", ...keys.map((k) => `${POINT_LABEL[k]} °F`), "Sky cover"],
      fc.times.map((x, i) => [localDT(x, tz), ...keys.map((k) => plain(P[k].series.t_f[i])),
        P[keys[0]].series.sky[i] === null ? "–" : `${P[keys[0]].series.sky[i]}%`]));
  }

  function windChart(el, fc, pt, keys, tz) {
    const D = detailWindow(fc, tz), P = fc.points;
    const wk = keys.includes("summit") ? "summit" : pt;
    const s = P[wk].series;
    const xs = fc.times.map((x) => C.wall(x, tz));
    const ax = C.timeAxis(D.w0, D.wEnd, el.clientWidth - C.MARGIN.l - 70);
    const ext = extendedShade(D);
    const col = C.OI.blue;
    const traces = [
      { x: xs, y: s.wind_mph, name: "Wind", mode: "lines", line: { color: col, width: 2.2 },
        hovertemplate: `${POINT_LABEL[wk]} wind %{y} mph<extra></extra>` },
      { x: xs, y: s.gust_mph, name: "Gusts", mode: "lines", line: { color: col, width: 1.3, dash: "dot" },
        hovertemplate: "gusts %{y} mph<extra></extra>" },
    ];
    const annotations = [C.axisTitle(`Wind at the ${POINT_LABEL[wk].toLowerCase()} (mph)`), ext.ann];
    const ends = [{ xs, ys: s.wind_mph, text: "Wind", color: col }, { xs, ys: s.gust_mph, text: "Gusts", color: col }];
    const allY = [s.gust_mph, s.wind_mph];
    const shapes = [...ax.shapes, ext.shape];
    const lay = C.layout(220, { margin: { r: 70, b: ax.b }, shapes, xaxis: ax.axis });
    const yr = C.extent(allY, { zero: true, min: 10 });
    lay.yaxis = C.yaxis({ range: yr });
    lay.annotations = [...annotations, ...C.endLabels(ends, { yrange: yr, plotHeight: C.plotH(lay) })].filter(Boolean);
    C.plot(el, traces, lay);
    const mx = (a, i0 = 0, i1 = D.n) => Math.max(0, ...a.slice(i0, i1).filter((v) => v !== null));
    const lateG = D.N > D.n ? mx(s.gust_mph, D.n, D.N) : null;
    C.summary(el, `${POINT_LABEL[wk]} wind up to ${mx(s.wind_mph)} mph, gusts to ${mx(s.gust_mph)} mph in the next ${Math.round(HOURS_DETAIL / 24 * 2) / 2} days` +
      `${lateG !== null ? ` (later, 6-hourly: gusts to ${lateG} mph)` : ""} (NBM, 10 m wind).`);
    const rows = fc.times.map((x, i) => [localDT(x, tz), plain(s.wind_mph[i]), plain(s.gust_mph[i])]);
    C.tableToggle(el, "Wind (mph)", ["Time", "Wind", "Gusts"], rows);
  }

  function snowRateChart(el, fc, pt, tz) {
    const D = detailWindow(fc, tz), pr = fc.points[pt].precip;
    const keep = pr.end.map((e, i) => i).filter((i) => new Date(pr.end[i]).getTime() <= D.t1);
    const mid = keep.map((i) => C.wall(new Date(pr.end[i]).getTime() - pr.hours[i] * 1.8e6, tz));
    const rate = keep.map((i) => (pr.snow_in[i] === null ? null : f1(pr.snow_in[i] / pr.hours[i] * 10) / 10));
    const days = Math.round(HOURS_DETAIL / 24 * 2) / 2;
    const totalIn = keep.reduce((a, i) => a + (pr.snow_in[i] ?? 0), 0);
    if (totalIn < 0.05) {          // nothing to chart: one line instead of an empty panel (fix 9)
      if (el.data && window.Plotly) Plotly.purge(el);       // it may have held a chart before (base/summit switch)
      el.style.height = "";
      el.classList.add("chart-none");
      el.removeAttribute("role"); el.removeAttribute("aria-label");
      el.previousElementSibling?.classList.contains("chart-sum") && el.previousElementSibling.remove();
      el.nextElementSibling?.classList.contains("chart-table") && el.nextElementSibling.remove();
      const liq = keep.reduce((a, i) => a + (pr.qpf_in[i] ?? 0), 0);
      el.innerHTML = `<p class="none-line">No snow expected at the ${POINT_LABEL[pt].toLowerCase()} in the next ${days} days` +
        `${liq >= 0.05 ? ` (about ${liq.toFixed(2)} in of rain or mixed precipitation)` : ""}.</p>`;
      return;
    }
    el.classList.remove("chart-none");
    el.querySelector(":scope > .none-line")?.remove();
    const ax = C.timeAxis(D.w0, D.wEnd, el.clientWidth - C.MARGIN.l - 70);
    const ext = extendedShade(D, C.small() ? "later: bars ↑" : "later: day/night bars ↑");
    const hourly = keep.map((i) => pr.hours[i] === 1);
    const text = keep.map((i) => `${localDT(new Date(new Date(pr.end[i]).getTime() - pr.hours[i] * 3.6e6).toISOString(), tz)}–` +
      `${localFmt(pr.end[i], tz, { hour: "numeric" })}: ${plain(pr.snow_in[i])} in snow` +
      (pr.hours[i] > 1 ? ` in ${pr.hours[i]} h` : "") + ` · liquid ${plain(pr.qpf_in[i])} in` +
      (pr.pop?.[i] !== null && pr.pop?.[i] !== undefined ? ` · precip chance ${Math.round(pr.pop[i] * 100)}%` : ""));
    const k6 = hourly.indexOf(false);
    const annotations = [C.axisTitle("Snow rate (in per hour)"), ext.ann];
    const shapes = [...ax.shapes, ext.shape];
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
      ? `Heaviest snow about ${rate[bi].toFixed(2)} in per hour (${text[bi].split(":")[0]}); about ${inches(total)} in in the next ${Math.round(HOURS_DETAIL / 24 * 2) / 2} days (expected).`
      : `Little or no snow in the next ${Math.round(HOURS_DETAIL / 24 * 2) / 2} days (expected ${inches(total)} in).`);
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
    const info = snotelStatus(await getJSON("data/meta.json").catch(() => null));   // outage wording (snotel-status.js)
    try { d = await getJSON(`data/snotel/${st.id.replace(/:/g, "_")}.json`); } catch {
      el.innerHTML = `<p class="hint">${info.state === "unavailable" || info.state === "stale" ? esc(info.text) : `${esc(st.name)}: no recent data.`}</p>`; return;
    }
    // a stale copy (data service down) keeps its original times: say how old it is, never present it as current
    const staleNote = info.state === "stale" ? `<p class="snotel-note" role="status">${esc(info.text)}</p>` : "";
    const series = d.SNWD_med3 || d.SNWD;
    const last = (arr) => { for (let i = arr.length - 1; i >= 0; i--) if (arr[i] !== null) return [arr[i], i]; return [null, -1]; };
    const [depth, i] = last(series);
    const prev = i >= 72 ? series[i - 72] : null;
    const chg = depth !== null && prev !== null ? depth - prev : null;
    el.innerHTML = `${staleNote}<p><strong>${esc(st.name)}</strong> SNOTEL, ${ft(st.elev_ft)}${st.dist_km !== undefined ? ` (${st.dist_km} km away)` : ""}:
      snow depth <strong>${depth === null ? "–" : `${Math.round(depth)} in`}</strong>${chg === null ? "" :
      ` (${chg >= 0 ? "+" : ""}${Math.round(chg)} in in 72 h)`}.</p><div class="chart" id="obs-chart" style="height:220px"><p class="hint">Loading chart…</p></div>`;
    // SNOTEL times are the station's local standard time (wall clock already)
    const xs = d.times.map((t) => t.slice(0, 16));
    const swe = d.WTEQ || [];
    // two panels, each from 0 with its own axis (fix 7: on one axis SWE looked flat or missing)
    $("obs-chart").insertAdjacentHTML("afterend", `<div class="chart" id="obs-swe" style="height:190px"><p class="hint">Loading chart…</p></div>`);
    $("obs-chart").style.height = "200px";
    const panel = (el, ys, title, color, dash, fmt, minSpan) => {
      const ax = C.timeAxis(xs[0], xs[xs.length - 1], el.clientWidth - C.MARGIN.l - 30);
      const lay = C.layout(parseInt(el.style.height, 10), { margin: { r: 30, b: ax.b }, shapes: ax.shapes, xaxis: ax.axis });
      lay.yaxis = C.yaxis({ range: C.extent([ys], { zero: true, min: minSpan, pad: 0.1 }) });
      lay.annotations = [C.axisTitle(title)];
      C.plot(el, [{ x: xs, y: ys, mode: "lines", line: { color, width: 2.2, dash }, hovertemplate: `%{y:${fmt}} in<extra></extra>` }], lay);
    };
    C.lazy($("obs-chart"), () => loadPlotly().then(() => {
      panel($("obs-chart"), series, "Snow depth (in)", C.OI.blue, "solid", ".0f", 4);
      panel($("obs-swe"), swe, "Snow water equivalent (in)", "#00704f", "solid", ".1f", 1);
      const [sw] = last(swe);
      C.summary($("obs-chart"), `${st.name}: snow depth ${depth === null ? "unknown" : `${Math.round(depth)} in`}${chg === null ? "" : ` (${chg >= 0 ? "+" : ""}${Math.round(chg)} in in 72 h)`} (last 7 days, local standard time).`);
      C.summary($("obs-swe"), `Snow water equivalent ${sw === null ? "not reported" : `${sw.toFixed(1)} in`} at the last report.`);
      C.tableToggle($("obs-swe"), `${st.name} SNOTEL, hourly`, ["Time (local std.)", "Depth (in, 3-h median)", "SWE (in)"],
        xs.map((x, k) => [x, series[k] === null || series[k] === undefined ? "–" : Math.round(series[k]), swe[k] ?? "–"]).reverse());
    }));
  }

  // NOHRSC snowfall analysis + SNODAS at the area's base and summit (data/nohrsc/ski.json).
  async function nohrscObs(el, a, tz) {
    let js;
    try { js = await getJSON("data/nohrsc/ski.json"); } catch { return; }
    const r = js.areas?.[a.id];
    if (!r) return;
    if ($("rk-depth") && r.base) {             // Sno-Park key facts: SNODAS depth at the trailhead
      $("rk-depth").textContent = r.base.depth === null || r.base.depth === undefined ? "–" : `${Math.round(r.base.depth)}"`;
      if (js.snodas_valid) $("rk-depth").nextElementSibling.textContent = `SNODAS, ${localFmt(js.snodas_valid, tz, { weekday: "short", hour: "numeric" })}`;
    }
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
    const isRec = a.kind === "snopark";
    POINT_LABEL.summit = isRec ? "High terrain" : "Summit";
    POINT_LABEL.base = isRec ? "Trailhead" : "Base";
    const tz = a.tz || "America/Denver";
    let src = nbm ? "nbm" : nws ? "nws" : null;
    const doc = () => (src === "nws" ? nws : nbm);
    const keysOf = (d) => (d ? (isRec ? ["base", "summit"] : ["summit", "base", "point"]).filter((k) => d.points[k]) : []);
    let pt = keysOf(doc())[0];
    const isFav = favs().includes(a.id);
    const nwsLink = (p) => `https://forecast.weather.gov/MapClick.php?lat=${p.lat}&lon=${p.lon}`;
    const sub = isStation
      ? `SNOTEL ${esc(a.triplet)} · ${esc(a.state)} · ${ft(a.elev_ft)}`
      : isRec
        ? `${esc(a.type_label || "Sno-Park")} · ${esc(a.region)}, ${esc(a.state)} · Trailhead ${ft(a.base.elev_ft)} · High terrain ${ft(a.summit.elev_ft)} <span class="hint">(highest ground within 5 km)</span>`
        : `${esc(a.region)}, ${esc(a.state)} · Summit ${ft(a.summit.elev_ft)} · Base ${ft(a.base.elev_ft)} · ${ft(a.vertical_ft)} vertical`;
    const srcName = a.source === "osm" ? "OpenStreetMap" : "USDA Forest Service";
    const recFacts = isRec ? `<section class="rec-key" aria-label="Key facts">
        <div class="rk-avy"><span class="label">Avalanche danger</span>${avalanche(a.avalanche, avyR.status === "fulfilled" ? avyR.value : null)}
          <p class="hint">Snowmobilers and backcountry travellers: read the full avalanche forecast before you go.</p></div>
        <div class="rk-cells">
          <div><span class="label">Snow depth at the trailhead</span><b id="rk-depth">–</b><small>SNODAS analysis</small></div>
          <div><span class="label">Coldest wind chill, 24 h</span><b id="rk-wc">–</b><small id="rk-wc-where">NBM</small></div>
        </div>
        <ul class="rk-info">
          <li><b>Type:</b> ${esc(a.type_label || "Sno-Park")}</li>
          ${a.activities?.length ? `<li><b>Activities</b> (as listed by the source): ${esc(a.activities.join(", "))}</li>` : ""}
          <li><b>Permit:</b> ${a.permit ? esc(a.permit)
            : `Parking permits may be required — check ${a.permit_check?.url ? `<a href="${safeUrl(a.permit_check.url)}" target="_blank" rel="noopener">${esc(a.permit_check.name)}</a>` : "with the land manager"}.`}</li>
          ${a.agency ? `<li><b>Managed by:</b> ${esc(a.agency)}${a.url ? ` · <a href="${safeUrl(a.url)}" target="_blank" rel="noopener">site page</a>` : ""}</li>` : ""}
          <li><b>Source:</b> ${srcName}. Check conditions and closures with the land manager.</li>
        </ul></section>` : "";
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
      ${!isStation && a.nws && !a.nws.base && !a.nws.summit
        ? `<p class="note no-nws">NWS alerts not available for this location (it has no NWS forecast grid point).</p>`
        : alR.status === "fulfilled" ? alertBanner((isStation ? alR.value.points : alR.value.areas)?.[a.id], alR.value,
          nwsLink(isStation ? a : a.summit), tz) : ""}
      ${recFacts}
      ${src ? `<p class="headline" id="headline"></p>
      <p class="fresh" id="fresh"></p>
      <div class="sec-head seg-row">${srcSeg}<span id="elev-seg"></span></div>
      <div id="tiles"></div>
      <section><h3>Snowfall by day</h3>
        <div class="chart" id="period-chart" style="height:260px"><p class="hint">Loading chart…</p></div>
        <p class="note" id="period-note"></p></section>
      <section><h3>Accumulated snow</h3>
        <div class="chart" id="acc-chart" style="height:240px"><p class="hint">Loading chart…</p></div>
        <p class="note" id="acc-note"></p></section>
      <section><h3>Snow ratio and powder quality <a class="info" href="about.html#powder-quality" title="Powder quality is a documented heuristic from NBM's snow-to-liquid ratio (Dense below 10:1, Medium 10–15, Blower 15 and up; wind-affected when summit gusts exceed 30 mph while it snows). Not an accuracy claim or an avalanche rating." aria-label="How powder quality works">ⓘ</a></h3>
        <div class="chart" id="slr-chart" style="height:280px"><p class="hint">Loading chart…</p></div>
        <p class="note">NBM's forecast snow ratio (line = median, shading = 10–90%), drawn only while snow is falling. The colored bands are a <b>documented heuristic</b> for powder quality, not an accuracy claim. <a href="about.html#powder-quality">How it works →</a></p></section>
      <section id="ex-sec"><h3>Chance of at least…</h3>
        <div class="seg" role="group" aria-label="Window" id="ex-win"><button type="button" class="on" data-w="24h" aria-pressed="true">24 h</button><button type="button" data-w="48h" aria-pressed="false">48 h</button><button type="button" data-w="72h" aria-pressed="false">72 h</button></div>
        <div id="ex-chart" class="heat-box"><p class="hint">Loading…</p></div>
        <p class="note" id="ex-note"></p></section>
      <section><h3>Snow level vs the ${isStation ? "station" : isRec ? "trailhead and high terrain" : "mountain"}</h3>
        <div class="chart" id="sl-chart" style="height:260px"><p class="hint">Loading chart…</p></div>
        <p class="note" id="sl-note"></p></section>
      <section><h3>Hour by hour <span class="h3sub" id="hbh-sub"></span></h3>
        <div class="chart" id="t-chart" style="height:220px"><p class="hint">Loading chart…</p></div>
        <div class="chart" id="w-chart" style="height:220px"><p class="hint">Loading chart…</p></div>
        <div class="chart" id="p-chart" style="height:220px"><p class="hint">Loading chart…</p></div>
        <p class="note" id="met-note"></p></section>`
      : `<p class="hint">No point forecast is available for this site yet.</p>`}
      <section id="afd"></section>
      <section><h3>Recent observations</h3><div id="nohrsc-obs"></div><div id="obs"></div></section>
      ${isStation || isRec ? "" : `<section><h3>Avalanche danger</h3>${avalanche(a.avalanche, avyR.status === "fulfilled" ? avyR.value : null)}</section>`}
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
        if (isRec && $("rk-wc")) {               // coldest wind chill in the next 24 h, either point
          const t0 = Date.now(), t1 = t0 + 24 * 3.6e6;
          let best = null;
          for (const k of keys) {
            const se = d.points[k].series;
            d.times.forEach((iso, i) => {
              const ms = new Date(iso).getTime();
              const w = ms >= t0 - 3.6e6 && ms <= t1 ? windChill(se.t_f?.[i], se.wind_mph?.[i]) : null;
              if (w !== null && (!best || w < best.w)) best = { w, k, iso };
            });
          }
          $("rk-wc").textContent = best ? `${best.w} °F` : "–";
          $("rk-wc-where").textContent = best ? `${POINT_LABEL[best.k].toLowerCase()}, ${localDT(best.iso, tz)} (${src === "nws" ? "NWS" : "NBM"})` : "";
        }
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
        // "4 AM PST": when the 12Z-12Z days start locally (from the first whole day's label)
        const dayLocal = ((d.points[pt].days || []).find((x) => !x.partial)?.local || "Mon 5 AM").split(" – ")[0].replace(/^\S+ /, "")
          + ` ${tzName(tz)}`;
        $("period-note").innerHTML = src === "nws"
          ? `NWS forecast for the 2.5 km grid cell (elev. ${ft(d.points[pt].grid_elev_ft)}), shown as issued (snowfall to 72 h): one bar per day, coloured with the NWS snowfall colours. Days run from about ${dayLocal} to ${dayLocal}.`
          : `Each bar is NBM's <b>likely range</b> for that day: the middle half (25th–75th percentile) of its possible outcomes for the 24 hours from about ${dayLocal}, coloured by the median with the NWS snowfall colours. Greyed days: little or no snow likely. NBM gives these percentiles only for whole 24-hour windows, so a short first day${(d.points[pt].days || []).some((x) => !x.partial && x.snow_p25 === null) ? " and days past NBM's percentile data show" : " shows"} the expected amount instead (hatched grey). <a href="about.html#daily-snow">How it works →</a>`;
        if ($("acc-note")) $("acc-note").textContent = src === "nws"
          ? "The NWS forecast's snowfall added up day by day (to 72 hours), same days as the chart above."
          : "NBM's expected snowfall added up day by day, on the same days as the chart above; the label on each bar is the running total. "
            + "It ends where the 10-day total ends (a narrower last bar when that falls mid-day, marked *), so the last bar matches \"Next 10 days\". "
            + "Expected amounts only: NBM has no range for a running total.";
        $("ex-sec").hidden = src === "nws" || !d.points[pt].exceed || !Object.keys(d.points[pt].exceed).length;
        $("ex-note").innerHTML = `NBM's own chance of at least each amount for the 2.5 km grid cell around the ${POINT_LABEL[pt].toLowerCase()}, in ${exWin.replace("h", " h")} windows from about 5 AM (12Z); columns are labelled with the day the window starts (hover for exact times). Separate from the expected-amount bars, so they can disagree. NBM only. <a href="about.html#probabilities">How they work →</a>`;
        $("hbh-sub").textContent = `hourly ${Math.round(HOURS_DETAIL / 24 * 2) / 2} days, then 6-hourly · times ${tzName(tz)}`;
        $("sl-note").textContent = `Below the line precipitation falls as rain. The line is solid where precipitation is likely (≥ 20% chance) and dotted where it is not; the orange band is NBM's 10–90% range${src === "nws" ? "" : " (as far as NBM provides it, about 10 days)"}. Times ${tzName(tz)}.`;
        $("met-note").textContent = src === "nws"
          ? `NWS forecast for the 2.5 km grid cell (elev. ${ft(d.points[pt].grid_elev_ft)}), as issued — not adjusted to this elevation. Snow in 6-hour amounts, shown as an hourly rate. Days 4–10: see the day/night bars above.`
          : "Temperatures adjusted from the 2.5-km NBM grid to each elevation (6.5 °C/km). Snow: hourly to 36 h, then 6-hour amounts, both shown as a rate (in per hour) so they compare. After 3½ days (shaded) temperature and wind are NBM's 6-hourly values; snow after that: see the day/night bars above.";
      };
      // Each chart draws when it comes near the viewport (SnowCharts.lazy), one per task, so
      // Plotly only loads once a chart is about to be seen.
      const drawCharts = () => {
        const d = doc(), keys = keysOf(d);
        const withPlotly = (f) => () => loadPlotly().then(() => f());
        // explanation only: the numbers live in the wind panel's summary (one source, fix 5)
        C.summary($("period-chart"), daySummary(d, pt, src === "nws"));     // text first (LCP), chart when near view
        C.lazy($("period-chart"), withPlotly(() => periodChart($("period-chart"), d, pt, tz, src === "nws")));
        if ($("acc-chart")) {
          C.summary($("acc-chart"), accumSummary(d, pt, src === "nws"));
          C.lazy($("acc-chart"), withPlotly(() => accumChart($("acc-chart"), d, pt, tz, src === "nws")));
        }
        if ($("slr-chart")) C.lazy($("slr-chart"), withPlotly(() => slrChart($("slr-chart"), d, pt, tz)));
        if (!$("ex-sec").hidden) C.lazy($("ex-chart"), () => exceedTable($("ex-chart"), d, pt, tz));
        C.lazy($("sl-chart"), withPlotly(() => snowLevelChart($("sl-chart"), d, keys, tz)));
        C.lazy($("t-chart"), withPlotly(() => tempChart($("t-chart"), d, keys, tz)));
        C.lazy($("w-chart"), withPlotly(() => windChart($("w-chart"), d, pt, keys, tz)));
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
