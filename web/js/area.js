// Ski-area page (area.html#<id>): NBM point forecast for base and summit, snow
// level vs the mountain, hourly meteogram, nearest SNOTEL, avalanche danger.
// Numbers render as plain HTML first; Plotly loads afterwards for the charts.
// Amounts are NBM means (bars add up to totals); ranges are 10th–90th percentile.

(() => {
  "use strict";
  const PLOTLY_URL = "vendor/plotly-2.35.2/plotly-basic.min.js";      // self-hosted (dev19), version in the folder name
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ft = (v) => (v === null || v === undefined ? "–" : `${Math.round(v).toLocaleString()} ft`);
  const CAM_TYPE = { resort: "resort site", dot: "road cameras, state DOT", avalanche_center: "avalanche center", usfs: "US Forest Service" };
  /** the Webcams row: up to 3 plain outbound links to the PROVIDER's own page. No iframe, no <img>, no embed: the pictures stay on the provider's site. */
  function webcamRow(list) {
    if (!Array.isArray(list) || !list.length) return "";
    const links = list.slice(0, 3).filter((c) => /^https:\/\//i.test(c?.url || "")).map((c) =>
      `<a href="${esc(c.url)}" target="_blank" rel="noopener noreferrer" aria-label="${esc(c.label)} (opens ${esc(c.host)} in a new tab)">${esc(c.label)} ↗</a>`
      + ` <span class="hint">${esc(CAM_TYPE[c.type] || "")}</span>`);
    return links.length ? `<p class="webcams"><b>Webcams</b> <span class="hint">(these open the provider's own site)</span>: ${links.join(" · ")}</p>` : "";
  }
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
  // The library is 355 KB gzip from OUR host since dev19. It is started when the browser is idle after the page's own load, so it does not compete with the page's first
  // data requests and the headline paint (the charts below are placeholders of fixed height until it arrives).
  const whenIdle = (f) => {
    const run = () => (typeof window.requestIdleCallback === "function" ? window.requestIdleCallback(f, { timeout: 1200 }) : setTimeout(f, 150));
    if (document.readyState === "complete") run(); else window.addEventListener("load", run, { once: true });
  };
  const loadPlotly = () => (plotlyPromise ||= new Promise((resolve, reject) => {
    if (window.Plotly) return resolve(window.Plotly);
    whenIdle(() => {
      const s = document.createElement("script");
      s.src = PLOTLY_URL; s.async = true;
      s.onload = () => resolve(window.Plotly); s.onerror = () => reject(new Error("chart library failed to load"));
      document.head.appendChild(s);
    });
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
  // Range wording (owner Nov 17): "likely X–Y in" = NBM's own p25-p75 of ONE native window (snow_q1/snow_q3, only when t.native);
  // otherwise the expected amount alone. The 10-90 % (snow_lo/hi) stays in the files for other uses, never inline text.
  const likely = (t) => (t && t.native === true && t.snow_q1 != null && t.snow_q3 != null ? [t.snow_q1, t.snow_q3] : null);
  const outside = (t) => { const r = likely(t); return !!r && t.snow_in !== null && (t.snow_in < r[0] - 0.05 || t.snow_in > r[1] + 0.05); };
  const SEPARATE = "NBM's expected amount (its deterministic forecast) and its probabilistic forecasts are calibrated separately, " +
    "so the expected amount can fall outside the range.";

  function headline(fc, keys) {
    const pt = keys[0], s = fc.points[pt].totals["72h"];
    if (!s) return "";
    const where = keys.length > 1 ? ` at the ${POINT_LABEL[pt].toLowerCase()}` : "";
    let txt;
    const rng = (t) => { const r = likely(t); return r ? ` (likely ${range(r[0], r[1])})` : ""; };
    if ((likely(s)?.[1] ?? s.snow_in ?? 0) < 0.5) {
      txt = `No significant snow in the next 72 hours${where}.`;
    } else {
      txt = `Next 72 h${where}: expected <strong>${inches(s.snow_in)} in</strong> ${expectedInfo()}` +
            `<span class="rng">${rng(s)}${likely(s) ? " " + likelyInfo() : ""}</span>.`;
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

  /** "Report a bad summary" mailto with the place, rule ids and the text prefilled (W3 quality loop, docs/specs/daily-summaries.md). */
  const summaryReport = (sm) => `<span data-mailto-wrap hidden>· <a ${SiteConfig.attrs("Snow-Wx: bad summary",
    `Place: ${document.title.replace("Snow-Wx · ", "")}
Page: ${location.href}
Tag: ${sm.tag}
Rules: ${(sm.rule_ids || []).join(", ")}
Text: ${sm.sentence}

What was wrong (and what happened):
`)}>Report a bad summary</a></span>`;

  /** "Report a bust" (W5): prefilled e-mail with place, date, issue time and what was forecast; hidden when no feedback address is configured. */
  function bustLink(d, a, keys, tz) {
    const today = new Date().toLocaleDateString("en-CA", { timeZone: tz });
    const t = d.points[keys[0]]?.totals || {};
    const fc = ["24h", "72h"].filter((k) => t[k]).map((k) => `${k}: expected ${inches(t[k].snow_in)} in${likely(t[k]) ? `, likely ${range(...likely(t[k]))}` : ""}`).join("; ");
    const body = `Place: ${a.name}
Page: ${location.href}
Date of the miss: ${today}
Forecast issued: ${d.issued}
Forecast (${POINT_LABEL[keys[0]]}): ${fc}

What actually happened (snow measured/seen, where, photos or links welcome):
`;
    return `<span data-mailto-wrap hidden>Forecast missed badly? <a ${SiteConfig.attrs(`Snow-Wx bust report: ${a.name} ${today}`, body)}>Report a bust</a> (busts are published, not hidden).</span>`;
  }

  /** W7 wind-exposure flag (Phase A, docs/specs/wind-exposure.md): INFORMATIONAL, never an avalanche rating. Only drawn when the point file carries
   *  `wind_exposure`, which the pipeline writes only while config wind_exposure.enabled is true (it is false). All text is escaped. */
  function windExposure(wx, a, ratings, tz) {
    if (!wx || !wx.flag) return "";
    const zone = a?.avalanche ? ratings?.[String(a.avalanche.zone_id)] : null;
    const link = zone?.link ? `<a href="${esc(safeUrl(zone.link))}" target="_blank" rel="noopener" data-track="avalanche_click">Read the avalanche forecast for this zone →</a>`
      : `<a href="https://avalanche.org/" target="_blank" rel="noopener" data-track="avalanche_click">Find your avalanche center's forecast →</a>`;
    const when = wx.start && wx.end ? ` <span class="hint">${esc(localDT(wx.start, tz))} to ${esc(localDT(wx.end, tz))}</span>` : "";
    return `<aside class="wind-flag" aria-label="Wind transport potential"><p><b>${esc(wx.title)}</b>${when}</p><p>${esc(wx.text)}</p>
      <p class="hint"><b>${esc(wx.disclaimer)}</b> ${esc(wx.caveat)} ${link} <a href="about.html#wind-exposure">How this flag works</a></p></aside>`;
  }

  /** Daily Snow summary (W3: pipeline/summary.py, rules in config/summary_rules.yml): deterministic, hedged, never an LLM. */
  function summaryCard(sm) {
    if (!sm || !sm.sentence) return "";
    if (sm.alert) return `<p class="summary-line"><b class="summary-tag alert">${esc(sm.tag)}</b> ${esc(sm.sentence)}</p>
      ${sm.bullets?.length ? `<ul class="summary-bullets">${sm.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : ""}
      <p class="hint summary-note">Active NWS alerts always come first. <a href="about.html#daily-summary">How the summary works →</a> ${summaryReport(sm)}</p>`;
    const conf = { high: "", medium: " · medium confidence (no native NBM window for part of the forecast)", low: " · low confidence (NBM ranges unavailable)" }[sm.confidence] || "";
    return `<p class="summary-line"><b class="summary-tag">${esc(sm.tag)}</b> ${esc(sm.sentence)}</p>
      ${sm.bullets?.length ? `<ul class="summary-bullets">${sm.bullets.map((b) => `<li>${esc(b)}</li>`).join("")}</ul>` : ""}
      <p class="hint summary-note">Automatic summary from the numbers below (rules, not a person)${esc(conf)}. <a href="about.html#daily-summary">How it works →</a> ${summaryReport(sm)}</p>`;
  }

  function tiles(fc, pt, elev) {
    const P = fc.points[pt];
    const cell = (name, label) => {
      let t = P.totals[name];
      if (!t) return "";
      const c = colorFor(SNOWFALL, t.snow_in) || "#f4f6f8";
      // ranges only from ONE native NBM window (t.native); 7/10-day and composite ones: expected total only (owner Nov 16)
      const long = name === "7d" || name === "10d" || (t.snow_hi != null && t.native !== true);
      if (long) { t = { ...t, snow_lo: null, snow_hi: null, snow_q1: null, snow_q3: null }; }
      const lk = likely(t);
      const note = outside(t) ? ` <a class="info" href="about.html#nbm" title="${esc(SEPARATE)}" aria-label="Why the ranges can disagree">ⓘ</a>` : "";
      return `<div class="tile${t.extended ? " ext" : ""}"><span class="label">${label}</span>
        <span class="swatch${snowPale(c) ? " pale" : ""}" style="background:${c}"></span><strong>${inches(t.snow_in)}<small> in</small></strong>
        <span class="rng">${long ? "expected total only (no native NBM range)" : P.raw ? "NWS: amount only, no range" : !lk ? "expected amount only" : `likely ${range(lk[0], lk[1])} ${likelyInfo()}${note}`}</span>
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
  // 2" is NBM's own >2" exceedance field for 24 h and 48 h windows only; the 72 h row shows "n/a" with a tooltip (never derived, never blank)
  const EX_THR = { "24h": [2, 4, 6, 8, 12, 18, 24], "48h": [2, 4, 6, 8, 12, 18, 24, 36], "72h": [2, 4, 6, 8, 12, 18, 24, 36, 48] };
  let exWin = "24h";
  function exceedTable(el, fc, pt, tz) {
    const ex = fc.points[pt].exceed?.[exWin];
    if (!ex || !ex.end?.length) { el.innerHTML = `<p class="hint">No NBM chances for this window.</p>`; return; }
    const want = EX_THR[exWin].filter((t) => ex.thr.includes(t) || t === 2);      // 2" has no 72 h field: shown as n/a, never blank
    const day = (iso) => C.wall(iso, tz).slice(0, 10);
    const lastDay = (iso) => C.wall(new Date(iso).getTime() - 3.6e6, tz).slice(0, 10);   // window end at ~5 AM -> day before
    const cols = ex.start.map((s0, i) => (exWin === "24h" ? C.dayName(day(s0), true)
      : `${C.dayName(day(s0))}<br>–${C.dayName(lastDay(ex.end[i])).split(" ")[0]}`));
    const titles = ex.start.map((s0, i) => `${localDT(s0, tz)} → ${localDT(ex.end[i], tz)}`);
    const values = want.map((t) => ex.p.map((row) => (ex.thr.indexOf(t) < 0 ? null : row[ex.thr.indexOf(t)])));
    const naRows = Object.fromEntries(want.map((t, i) => [i, ex.thr.indexOf(t) < 0 ? "NBM publishes this for 24 h and 48 h only" : null]).filter(([, v]) => v));
    C.heatTable(el, { caption: `Chance (%) of at least each amount in ${exWin.replace("h", "-hour")} windows`,
      rowLabels: want.map((t) => `${t}"`), colLabels: cols, colTitles: titles, values, palette: PROB, naRows });
    // summary: the largest amount with a >= 30 % chance somewhere, else the best chance of the smallest
    let best = null;
    want.forEach((t, i) => values[i].forEach((v, j) => {
      if (v !== null && v >= 30 && (!best || t > best.t || (t === best.t && v > best.v))) best = { t, v, j };
    }));
    const first = values.findIndex((_, i) => !naRows[i]);
    const w0 = values[first] ? Math.max(...values[first].map((v) => v ?? 0)) : 0;
    const j0 = values[first] ? values[first].indexOf(w0) : 0;
    const txt = best
      ? `Best odds: ${best.v}% for at least ${best.t} in, ${titles[best.j]}.`
      : w0 > 0 ? `Low odds: at most ${w0}% chance of ${want[first]} in or more in any ${exWin.replace("h", "-hour")} window (${titles[j0]}).`
        : `No meaningful chance of ${want[first]} in or more in any ${exWin.replace("h", "-hour")} window.`;
    C.summary(el, txt);
    el.removeAttribute("role");               // a real table: keep its own semantics
  }

  // ---- Snowfall by day (owner S11) ----
  // 12Z-12Z days (~4-5 AM local). NBM view: a floating bar from NBM's own 25th to 75th percentile for
  // that 24-h window (the "likely" middle half), coloured by its median with the NWS snowfall colours,
  // labelled "low–high″". Percentiles come only from one native NBM window, never added together, so
  // a short first day or a day past the percentile data shows the expected amount instead (hatched
  // grey).
  const hasV = (v) => v !== null && v !== undefined;
  const H = (n) => (C.small() ? Math.round(n * 0.86) : n);          // chart heights: ~14% shorter at phone width (placeholders use the same value)
  const how = (anchor) => `<a class="how" href="about.html#${anchor}">How it works →</a>`;       // every chart module links its About section (tests: every anchor exists)
  const MUTED_IN = 0.5;                     // likely high below ~0.5 in: muted, no colour
  function dayRange(d) {                    // "6–12″", "1–3″", "<1″", "4″"
    const lo = Math.round(d.snow_p25), hi = Math.round(d.snow_p75);
    if (d.snow_p75 < MUTED_IN) return "0″";
    if (hi <= 1 && lo === 0) return "<1″";
    return lo === hi ? `${hi}″` : `${lo}–${hi}″`;
  }
  const dayAmount = (v) => (!hasV(v) ? "–" : v < 0.5 ? (v < 0.05 ? "0″" : "<1″") : `${Math.round(v)}″`);
  function dayWords(d) {
    if (hasV(d.snow_p25) && hasV(d.snow_p75)) {
      return d.snow_p75 < MUTED_IN ? "Little or no snow likely (NBM's middle half of outcomes is under ½ in)"
        : `Likely ${dayRange(d).replace("″", "")} in — the middle half of NBM's outcomes`;
    }
    return d.partial ? `Partial day (${d.hours} h) — expected amount, no range: ${plain(d.snow_in)} in`
      : `No NBM range for this day — expected amount: ${plain(d.snow_in)} in`;
  }
  /** takeaway (visible, <= 2 lines on a phone); `long` = the full sentence kept as the chart's aria text */
  function daySummary(fc, pt, long = false) {
    const days = fc.points[pt].days || [];
    const tot = fc.points[pt].totals || {};
    const total = tot["10d"] || tot["7d"] || tot["72h"];
    const key = (d) => (!hasV(d.snow_p75) ? d.snow_in ?? 0 : d.snow_p75);
    const big = days.reduce((b, d) => (key(d) > (b ? key(b) : 0) ? d : b), null);
    const span = tot["10d"] ? "10 days" : tot["7d"] ? "7 days" : "72 hours";
    const part = long && days.length && days[0].partial && !hasV(days[0].snow_p75) ? ` First day: partial day — expected amount ${dayAmount(days[0].snow_in)}, no range.` : "";
    const totTxt = total && hasV(total.snow_in) ? ` Expected total over ${span}: ${inches(total.snow_in)} in.` : "";
    if (!big || key(big) < MUTED_IN) return `Little or no snow on any day in the next ${days.length} days.${totTxt}${part}`;
    if (!long) return `Snowiest: ${big.label}, ${hasV(big.snow_p75) ? `likely ${dayRange(big).replace("″", "")}` : `expected ${inches(big.snow_in)}`} in.${totTxt}`;
    return `Snowiest day: ${big.label} (${big.local}) — ${hasV(big.snow_p75) ? `likely ${dayRange(big).replace("″", "")} in` : `expected ${inches(big.snow_in)} in`}.${totTxt}${part}`;
  }
  function periodChart(el, fc, pt, tz) {
    const days = fc.points[pt].days || [];
    if (!days.length) { el.innerHTML = `<p class="hint">No daily snowfall data in this forecast file yet.</p>`; return false; }
    const x = days.map((d, i) => i);
    const ranged = days.map((d) => hasV(d.snow_p25) && hasV(d.snow_p75));
    const muted = days.map((d, i) => (ranged[i] ? d.snow_p75 < MUTED_IN : (d.snow_in ?? 0) < MUTED_IN));
    // bar geometry: NBM = p25..p75 (at least 0.25 in tall so a narrow range stays visible); NWS and
    // days without a native range = 0..amount
    const minH = 0.25;
    const base = days.map((d, i) => (muted[i] ? null : ranged[i] ? d.snow_p25 : 0));
    const top = days.map((d, i) => (muted[i] ? null : ranged[i] ? Math.max(d.snow_p75, d.snow_p25 + minH) : d.snow_in));
    const colorOf = (d, i) => (!ranged[i] ? "#c9ced6"
      : colorFor(SNOWFALL, ranged[i] ? (hasV(d.snow_p50) ? d.snow_p50 : (d.snow_p25 + d.snow_p75) / 2) : d.snow_in) || "#ffffff");
    const colors = days.map(colorOf);
    const text = days.map((d, i) => (ranged[i] ? dayRange(d) : muted[i] ? dayAmount(d.snow_in) : `~${dayAmount(d.snow_in)}`));
    const hover = days.map((d, i) => `<b>${esc(d.label)}</b> (${esc(d.local)})<br>${esc(dayWords(d))}` +
      (ranged[i] && hasV(d.snow_p50) && !muted[i] ? `<br>Median ${plain(d.snow_p50)} in` : "") +
      `<br>Liquid ${d.qpf_in ?? "–"} in${hasV(d.pop) ? ` · chance of precip ${Math.round(d.pop * 100)}%` : ""}`);
    const ymax = Math.max(1, ...top.map((v) => v ?? 0));
    const labels = days.map((d, i) => ({ x: i, y: muted[i] ? 0 : top[i], yanchor: "bottom", yshift: 3, text: text[i], showarrow: false,
      font: C.font(12, muted[i] || !ranged[i] ? C.MUTED : C.INK) }));
    const two = C.narrow(el.clientWidth - C.MARGIN.l - C.MARGIN.r, days.length);
    C.plot(el, [
      { type: "bar", x, base, y: top.map((t, i) => (t === null ? null : t - base[i])), width: 0.62, hovertext: hover, hoverinfo: "text",
        marker: { color: colors, line: { color: "rgba(20,32,46,0.55)", width: 1 },
          pattern: { shape: days.map((d, i) => (!ranged[i] ? "/" : "")), fgcolor: "rgba(30,40,60,0.45)", size: 6, solidity: 0.2 } } },
      // invisible full-height hover targets so muted days still answer a tap
      { type: "bar", x, y: days.map(() => ymax * 1.1), width: 0.9, marker: { color: "rgba(0,0,0,0)" }, hovertext: hover, hoverinfo: "text" },
    ], C.layout(H(260), { hovermode: "closest", barmode: "overlay", bargap: 0.2, margin: { b: two ? 46 : C.MARGIN.b },
      annotations: [C.axisTitle("Likely snow (in), 25–75%"), ...labels],
      yaxis: C.yaxis({ rangemode: "tozero", range: [0, ymax * 1.22] }),
      xaxis: { fixedrange: true, tickfont: C.font(C.tick()), tickvals: x, tickangle: 0, ticks: "", range: [-0.6, days.length - 0.4],
               ticktext: days.map((d) => C.dayName(C.wall(d.start, tz).slice(0, 10), two)) } }));
    C.summary(el, daySummary(fc, pt), daySummary(fc, pt, true));
    el.parentElement.querySelector(".snow-legend")?.remove();      // so tableToggle finds its own toggle again
    C.tableToggle(el, `Snowfall by day (${POINT_LABEL[pt].toLowerCase()})`,
      ["Day", "Local time", "Likely (25–75%)", "Median (in)", "Expected (in)", "Chance of precip"],
      days.map((d, i) => [d.label, d.local, ranged[i] ? dayRange(d) : "–", ranged[i] ? plain(d.snow_p50) : "–", plain(d.snow_in),
        hasV(d.pop) ? `${Math.round(d.pop * 100)}%` : "–"]));
    // colour legend directly under the chart (before the table toggle)
    el.insertAdjacentHTML("afterend", snowLegendHtml(ymax, { minTop: 18, cls: "chart-legend", partial: days.some((d, i) => !ranged[i] && d.partial) }));
    return days.some((d, i) => !ranged[i]);
  }

  /** Accumulated snow (owner S11): NBM's expected snowfall piling up, one bar per day on the same
   *  12Z-12Z days as "Snowfall by day", each labelled with the running total. No probabilistic
   *  ranges here. The chart ends exactly at the 10-day total's horizon (a short last step when that
   *  falls mid-day), so its last bar equals the "Next 10 days" amount. */
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
  function accumSummary(fc, pt) {
    const { steps, tot, span } = accumSteps(fc, pt);
    const final = tot && hasV(tot.snow_in) ? tot.snow_in : steps.length ? steps[steps.length - 1].run : 0;
    if (final < 0.5) return `Little or no snow expected over the next ${span}.`;
    const big = steps.reduce((b, x) => (x.add > (b ? b.add : 0) ? x : b), null);
    return `Expected total over the next ${span}: ${inches(final)} in` +
      (big && big.add >= 0.5 ? `, most on ${big.d.label} (+${inches(big.add)} in).` : ".");
  }
  function accumChart(el, fc, pt, tz) {
    const { steps } = accumSteps(fc, pt);
    if (!steps.length) { el.innerHTML = `<p class="hint">No daily snowfall data in this forecast file yet.</p>`; return; }
    const x = steps.map((s, i) => i);
    const y = steps.map((s) => Math.round(s.run * 10) / 10);
    const endTxt = (s) => new Date(s.end).toLocaleString([], { weekday: "short", hour: "numeric", timeZone: tz });
    const hover = steps.map((s) => `<b>By ${esc(endTxt(s))}</b>: ${plain(s.run)} in expected` +
      `<br>${esc(s.d.label)}${s.cut ? ` (to ${esc(endTxt(s))}, end of the 10-day total)` : ""}: +${plain(s.add)} in`);
    const ymax = Math.max(1, ...y);
    const labels = steps.map((s, i) => ({ x: i, y: y[i], yanchor: "bottom", yshift: 3, showarrow: false,
      text: y[i] < 0.5 ? "0″" : `${Math.round(y[i])}″`, font: C.font(12, y[i] < 0.5 ? C.MUTED : C.INK) }));
    const two = C.narrow(el.clientWidth - C.MARGIN.l - C.MARGIN.r, steps.length);
    const colors = y.map((v) => colorFor(SNOWFALL, v) || "#ffffff");
    C.plot(el, [
      { type: "bar", x, y, width: steps.map((s) => (s.cut ? 0.36 : 0.62)), hovertext: hover, hoverinfo: "text",
        marker: { color: colors, line: { color: "rgba(20,32,46,0.55)", width: 1 } } },
    ], C.layout(H(240), { hovermode: "closest", bargap: 0.2, margin: { b: two ? 46 : C.MARGIN.b },
      annotations: [C.axisTitle("Expected running total (in)"), ...labels],
      yaxis: C.yaxis({ rangemode: "tozero", range: [0, ymax * 1.2] }),
      xaxis: { fixedrange: true, tickfont: C.font(C.tick()), tickvals: x, tickangle: 0, ticks: "", range: [-0.6, steps.length - 0.4],
               ticktext: steps.map((s) => C.dayName(C.wall(s.d.start, tz).slice(0, 10), two) + (s.cut && !two ? "*" : "")) } }));
    C.summary(el, accumSummary(fc, pt));
    C.tableToggle(el, `Accumulated snow (${POINT_LABEL[pt].toLowerCase()})`,
      ["Day", "Until", `That day (in)`, `Running total (in)`],
      steps.map((s) => [s.d.label, endTxt(s), plain(s.add), plain(s.run)]));
  }

  /** Snow ratio + powder quality in ONE panel (dev13 item 4, redesigned dev14 F3). NBM's snow-to-liquid ratio (SNOWLR):
   *  the median (p50) and the "likely" 25-75 % band, both from the SAME percentile series over the whole forecast. Thresholds
   *  of the ONE powder-quality definition (Dense < 10:1, Medium 10-15, Blower >= 15; config powder_quality, colors.js
   *  POWDER_Q) are thin dashed lines with direct labels at the right edge; the band is a single translucent Okabe-Ito blue (not
   *  used by the thresholds). Where the series is undefined (a place with no snow forecast at all) nothing is plotted and the
   *  gap is labelled "no snow forecast". Wind-affected markers where summit gusts reach POWDER_Q.wind_gust_mph while it snows.
   *  A documented heuristic, never an accuracy claim or an avalanche rating. */
  const POWDER_WIND_MPH = POWDER_Q.wind_gust_mph;
  const powderClass = (r) => (r === null || r === undefined ? null : r < POWDER_Q.dense_below ? "Dense" : r < POWDER_Q.blower_at ? "Medium" : "Blower");
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
  /** runs of consecutive indices where `defined` is false, as [first, last] */
  function gaps(defined) {
    const out = []; let a = -1;
    defined.forEach((d, i) => { if (!d && a < 0) a = i; if ((d || i === defined.length - 1) && a >= 0) { out.push([a, d ? i - 1 : i]); a = -1; } });
    return out;
  }
  function slrChart(el, fc, pt, tz) {
    const P = fc.points[pt], s = P.series, xs = fc.times.map((x) => C.wall(x, tz));
    const pos = (arr) => (arr || fc.times.map(() => null)).map((v) => (v ? v : null));     // 0 / null = undefined: never plotted as a value
    const hasPct = (s.slr_p50 || []).some(Boolean);
    const raw50 = pos(hasPct ? s.slr_p50 : s.slr), raw25 = pos(s.slr_p25), raw75 = pos(s.slr_p75);
    // dev22: a snow ratio means something only while precipitation is likely (chance >= 20 %, the same rule as the snow-level chart). The median line and the
    // likely band are drawn ONLY inside contiguous runs of that mask: one closed polygon per run, one colour, never bridged or interpolated across a dry gap.
    const chance = precipChance(fc, pt);
    const mask = raw50.map((v, i) => v !== null && (chance[i] ?? 0) >= WET);
    const p50 = raw50.map((v, i) => (mask[i] ? v : null));
    const bandAt = (i) => mask[i] && raw25[i] !== null && raw75[i] !== null;
    const p25 = raw25.map((v, i) => (mask[i] ? v : null)), p75 = raw75.map((v, i) => (mask[i] ? v : null));
    const band = hasPct && fc.times.some((_, i) => bandAt(i));
    const bad = Segments.outside(p25, p50, p75, mask);                                      // data is never altered: counted and logged only
    window.snowwx = window.snowwx || {};
    window.snowwx.slr = { outside: bad.length, masked: mask.filter(Boolean).length, runs: Segments.runs(mask).length };
    if (bad.length) console.debug(`snow ratio: median outside the likely range at ${bad.length} time(s), data unchanged`);
    const snowing = snowingMask(fc, pt);
    const windy = fc.times.map((_, i) => (snowing[i] && (s.gust_mph?.[i] ?? 0) >= POWDER_WIND_MPH && mask[i] ? i : null)).filter((v) => v !== null);
    const ymax = Math.max(24, ...p75.filter(Boolean).map((v) => v + 3), ...p50.filter(Boolean).map((v) => v + 3));
    const small = C.small();
    const rMargin = small ? 84 : 124;
    const ax = C.timeAxis(xs[0], xs[xs.length - 1], el.clientWidth - C.MARGIN.l - rMargin);
    const shapes = [...ax.shapes], annotations = [C.axisTitle(small ? "Snow ratio (snow : water)" : "Snow ratio (inches of snow per inch of water)")];
    // thresholds: thin dashed lines + direct labels in the right margin (never over the data)
    const LINE = "#5b6572";
    for (const y of [POWDER_Q.dense_below, POWDER_Q.blower_at]) {
      shapes.push({ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y", y0: y, y1: y, line: { color: LINE, width: 1, dash: "dash" }, layer: "below" });
    }
    const lab = (y, text) => annotations.push({ xref: "paper", x: 1, xshift: 5, xanchor: "left", yref: "y", y, yanchor: "middle", showarrow: false,
      text, font: C.font(12, "#1f2937"), align: "left" });
    lab(POWDER_Q.blower_at + (ymax - POWDER_Q.blower_at) * 0.45, small ? `<b>Blower</b> ≥${POWDER_Q.blower_at}` : `<b>Blower</b> ≥ ${POWDER_Q.blower_at}:1`);
    lab((POWDER_Q.dense_below + POWDER_Q.blower_at) / 2, small ? `<b>Medium</b>` : `<b>Medium</b> ${POWDER_Q.dense_below}–${POWDER_Q.blower_at}:1`);
    lab(POWDER_Q.dense_below / 2, small ? `<b>Dense</b> <${POWDER_Q.dense_below}` : `<b>Dense</b> < ${POWDER_Q.dense_below}:1`);
    const ms = (w) => Date.parse(`${w.replace(" ", "T")}:00Z`);
    // hatched "dry - ratio not shown" strips in the gaps (the partial-day hatch): one bar per gap, spanning from the middle of the last drawn step to the middle of the next
    const gapsR = Segments.gapRuns(mask);
    const mid = (i, k) => (i < 0 || k >= xs.length ? null : (ms(xs[i]) + ms(xs[k])) / 2);
    const dry = gapsR.map(([a, b]) => {
      const x0 = a > 0 ? mid(a - 1, a) : ms(xs[a]), x1 = b + 1 < xs.length ? mid(b, b + 1) : ms(xs[b]);
      return { c: (x0 + x1) / 2, w: Math.max(x1 - x0, 3.6e6) };
    });
    const traces = [];
    if (dry.length) traces.push({ type: "bar", x: dry.map((d) => d.c), y: dry.map(() => ymax), width: dry.map((d) => d.w), meta: { kind: "slr-dry" }, hoverinfo: "text",
      hovertext: dry.map(() => "Dry: precipitation not likely (under 20% chance), so no snow ratio is shown"), showlegend: false,
      marker: { color: "rgba(201,206,214,0.35)", line: { width: 0 }, pattern: { shape: "/", fgcolor: "rgba(30,40,60,0.28)", size: 6, solidity: 0.2 } } });
    // one closed polygon per run of the band
    for (const r of Segments.runs(fc.times.map((_, i) => bandAt(i)))) {
      if (r[1] === r[0]) continue;                                                     // a single point: marker + vertical range below
      const poly = Segments.polygon(xs, p25, p75, r);
      traces.push({ x: poly.x, y: poly.y, mode: "lines", fill: "toself", line: { width: 0 }, fillcolor: "rgba(0,114,178,0.22)", hoverinfo: "skip", meta: { kind: "slr-band", run: r } });
    }
    // ONE median line, solid, broken (null) between runs
    traces.push({ x: xs, y: p50, mode: "lines", line: { color: "#111827", width: 2.6 }, connectgaps: false, meta: { kind: "slr-line" },
      customdata: p25.map((v, i) => [v, p75[i], powderClass(p50[i])]),
      hovertemplate: band ? "median %{y:.0f}:1 (%{customdata[2]}) · likely %{customdata[0]:.0f}–%{customdata[1]:.0f}:1<extra></extra>" : "ratio %{y:.0f}:1 (%{customdata[2]})<extra></extra>" });
    // isolated single points: a marker with its own vertical range
    const lone = Segments.runs(mask).filter(([a, b]) => a === b).map(([a]) => a);
    if (lone.length) traces.push({ x: lone.map((i) => xs[i]), y: lone.map((i) => p50[i]), mode: "markers", meta: { kind: "slr-point" },
      marker: { size: 7, color: "#111827" }, hovertemplate: "ratio %{y:.0f}:1<extra></extra>",
      error_y: { type: "data", symmetric: false, array: lone.map((i) => (bandAt(i) ? p75[i] - p50[i] : 0)), arrayminus: lone.map((i) => (bandAt(i) ? p50[i] - p25[i] : 0)),
        color: "rgba(0,114,178,0.55)", thickness: 3, width: 0 } });
    if (windy.length) {
      traces.push({ x: windy.map((i) => xs[i]), y: windy.map(() => ymax * 0.93), mode: "markers", hovertemplate: `wind-affected: summit gusts ${POWDER_WIND_MPH} mph or more while snowing<extra></extra>`,
        marker: { symbol: "diamond", size: 9, color: C.OI.vermillion, line: { color: "#111827", width: 1 } } });
      annotations.push({ xref: "paper", x: 1, xanchor: "right", yref: "paper", y: 1, yanchor: "bottom", yshift: 4, showarrow: false,
        text: small ? "◆ wind-affected" : `◆ wind-affected (gusts ≥ ${POWDER_WIND_MPH} mph while snowing)`, font: C.font(12, "#7a2e00") });
    }
    if (!mask.some(Boolean)) annotations.push({ xref: "paper", x: 0.5, yref: "paper", y: 0.5, showarrow: false, text: "no precipitation likely: snow ratio not shown", font: C.font(12, C.MUTED) });
    C.plot(el, traces, C.layout(H(280), { margin: { r: rMargin, b: ax.b }, showlegend: false, shapes, annotations, xaxis: ax.axis,
      yaxis: C.yaxis({ range: [0, ymax] }), barmode: "overlay" }));
    // takeaway (visible) and the full sentence (aria): the median while precipitation is likely, with the heuristic class and the likely range
    const idx = fc.times.map((_, i) => i).filter((i) => mask[i]);
    let short, full;
    if (!idx.length) {
      short = full = raw50.some(Boolean) ? "No precipitation is likely in this period, so no snow ratio is shown."
        : "No snow ratio is available for this place in this period.";
    } else {
      const m = idx.map((i) => p50[i]), lo = Math.round(Math.min(...m)), hi = Math.round(Math.max(...m));
      const c1 = powderClass(Math.min(...m)), c2 = powderClass(Math.max(...m));
      const rng = band ? `${Math.round(Math.min(...idx.map((i) => p25[i] ?? p50[i])))}–${Math.round(Math.max(...idx.map((i) => p75[i] ?? p50[i])))}:1` : "";
      short = `Median ratio while precipitation is likely: ${lo === hi ? `${lo}:1` : `${lo}–${hi}:1`} (${c1 === c2 ? c1 : `${c1} to ${c2}`})${rng ? `, likely ${rng}` : ""}.`;
      full = `While precipitation is likely (at least a 20% chance) the median snow ratio is about ${lo === hi ? `${lo}:1` : `${lo}–${hi}:1`} (${c1 === c2 ? `${c1} class` : `${c1} to ${c2} class`})${rng ? `, likely ${rng}` : ""}; powder quality is a documented heuristic, not an accuracy claim.`;
    }
    C.summary(el, short, full);
    C.tableToggle(el, "Snow ratio and powder quality over time (documented heuristic); a dash means precipitation is not likely, so no ratio is shown",
      ["Time", "Median ratio", "Likely low (25%)", "Likely high (75%)", "Powder quality", "Chance of precip", "Snowing", "Wind-affected"],
      fc.times.map((x, i) => [localDT(x, tz), p50[i] ? `${Math.round(p50[i])}:1` : "–", band && p25[i] ? `${Math.round(p25[i])}:1` : "–", band && p75[i] ? `${Math.round(p75[i])}:1` : "–",
        powderClass(p50[i]) || "–", chance[i] === null || chance[i] === undefined ? "–" : `${Math.round(chance[i] * 100)}%`, snowing[i] ? "yes" : "no",
        snowing[i] && (s.gust_mph?.[i] ?? 0) >= POWDER_WIND_MPH ? "yes" : "no"]));
    C.legend(el, [["line", "median"], ["band", "likely range", "rgba(0,114,178,0.35)"], ["hatch", "dry: ratio not shown", "#8a94a3"], ["dashed", "classes (heuristic)", "#5b6572"]]);
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

  // ---- Precipitation by model (M7; js/multimodel.js, data/multimodel.json): liquid-equivalent, cumulative, one line per model.
  const MM_STYLE = { nbm: { color: "#111827", width: 3.2, dash: "solid" }, hrrr: { color: C.OI.vermillion, width: 2, dash: "solid" },
    rrfs: { color: C.OI.blue, width: 2, dash: "solid" }, gfs: { color: C.OI.green, width: 2, dash: "dash" }, ecmwf: { color: C.OI.purple, width: 2, dash: "dashdot" },
    aifs: { color: "#8a6100", width: 2, dash: "dot" } };          // dev20: ECMWF AIFS (AI model, experimental): dotted dark ochre (5.3:1 on white), never in the badge by default
  let mmDoc, mmMode = "liquid", mmView = "models", ensSrc = "ecmwf";                // view / source = per visit only (not stored)
  // dev21: model chips show/hide lines (view only: the agreement badge, summary and View-as-table always use EVERY model). Default: all models on wide
  // screens; at phone width NBM, HRRR, GFS and ECMWF (RRFS sits close to HRRR, AIFS is experimental). The choice is kept for the visit (sessionStorage).
  const MM_CHIP = { nbm: "NBM", hrrr: "HRRR", rrfs: "RRFS", gfs: "GFS", ecmwf: "ECMWF", aifs: "AIFS (AI)" };
  const MM_PHONE_OFF = ["rrfs", "aifs"], MM_KEY = "snowwx.mmHidden";
  let mmHidden = null;
  const mmHiddenSet = () => {
    if (mmHidden) return mmHidden;
    let stored = null;
    try { stored = JSON.parse(sessionStorage.getItem(MM_KEY)); } catch { /* storage blocked: default set */ }
    mmHidden = new Set(Array.isArray(stored) ? stored : (window.matchMedia?.("(max-width: 700px)").matches ? MM_PHONE_OFF : []));
    return mmHidden;
  };
  const saveHidden = () => { try { sessionStorage.setItem(MM_KEY, JSON.stringify([...mmHidden])); } catch { /* private mode: kept in memory only */ } };
  function mmChips(series, redraw) {
    const box = $("mm-chips");
    if (!box) return;
    const hid = mmHiddenSet();
    const swatch = (k) => { const st = MM_STYLE[k]; const da = { dash: "6 3", dashdot: "6 2 1.5 2", dot: "1.5 2.5" }[st.dash] || "";
      return `<svg width="22" height="10" aria-hidden="true" focusable="false"><line x1="1" y1="5" x2="21" y2="5" stroke="${st.color}" stroke-width="${Math.min(3, st.width + 0.5)}" ${da ? `stroke-dasharray="${da}"` : ""}/></svg>`; };
    box.innerHTML = series.map((s) => `<button type="button" class="mm-chip" data-k="${s.key}" aria-pressed="${!hid.has(s.key)}" title="${hid.has(s.key) ? "Show" : "Hide"} ${esc(s.label)}">${swatch(s.key)}${esc(MM_CHIP[s.key] || s.label)}</button>`).join("");
    box.hidden = false;
    box.querySelectorAll("button").forEach((btn) => btn.addEventListener("click", () => {
      const k = btn.dataset.k, on = !hid.has(k);
      if (on && series.filter((s) => !hid.has(s.key)).length <= 1) { $("mm-announce").textContent = "At least one model stays on the chart."; return; }
      if (on) hid.add(k); else hid.delete(k);
      saveHidden();
      $("mm-announce").textContent = `${MM_CHIP[k] || k} ${on ? "hidden" : "shown"}.`;
      redraw();
    }));
  }
  // ECMWF open data: the one-line credit under every ECMWF panel (the full "adapted" statement and Terms of Use link are in About and on the Sources page)
  const ECMWF_CREDIT = `Contains ECMWF open data, <a href="https://creativecommons.org/licenses/by/4.0/" target="_blank" rel="noopener">CC BY 4.0</a>, adapted`;
  const plumeList = () => mmDoc?.plumes ?? ((mmDoc?.models || []).some((m) => m.model === "ecmwf" && m.plume) ? ["ecmwf"] : []);   // ensemble plumes published with this build
  const hasPlume = () => plumeList().length > 0;
  /** the two ensemble sources (ECMWF live; GEFS built behind gefs.enabled): the same chart code reads either plume file */
  const ENS_SRC = {
    ecmwf: { short: "ECMWF", label: "ECMWF IFS ENS", path: "models/ecmwf/plume/", head: "ECMWF ensemble" },
    gefs: { short: "GEFS", label: "NOAA GEFS", path: "models/gefs/plume/", head: "GEFS ensemble" },
  };
  async function modelChart(el, fc, tz) {
    const sec = $("mm-sec"), P = fc.points.summit;
    if (typeof MultiModel === "undefined" || typeof Ensemble === "undefined") {           // a helper script failed to load: say so, never throw
      chartMsg(el, `<p class="hint">The model comparison could not be loaded. Reload the page to try again.</p>`); return;
    }
    if (mmDoc === undefined) mmDoc = await getJSON("data/multimodel.json").catch(() => null);
    if (!mmDoc?.areas?.[fc.id] || !P) {
      chartMsg(el, `<p class="hint">The model comparison is not available for this area yet (it needs a recent HRRR, RRFS or GFS run).</p>`);
      $("mm-badge").textContent = "";
      return;
    }
    const viewBox = $("mm-view");                                                    // the Models / Ensemble toggle exists only when ECMWF data were published
    if (viewBox) viewBox.hidden = !hasPlume();
    if (!hasPlume()) mmView = "models";
    if (hasPlume() && !plumeList().includes(ensSrc)) ensSrc = plumeList()[0];
    const srcBox = $("ens-src");                                                     // ECMWF | GEFS: only in the Ensemble view and only when both are published
    if (srcBox) srcBox.hidden = !(mmView === "ens" && plumeList().length > 1);
    if ($("mm-chips")) $("mm-chips").hidden = mmView === "ens";
    if (mmView === "ens") return ensembleChart(el, fc, tz);
    const nbm = { initMs: Date.parse(fc.issued), precip: P.precip, times: fc.times, ratio: P.series.slr_p50 || P.series.slr, psnow: P.series.p_snow };
    // the snow conversion needs NBM's ratio and chance of snow: without them the toggle is disabled (never a silent 10:1 / all-snow guess)
    const snowOk = (nbm.ratio || []).some((v) => v) && (nbm.psnow || []).some((v) => v !== null && v !== undefined);
    const snowBtn = document.querySelector("#mm-mode [data-m=snow]");
    if (snowBtn) { snowBtn.disabled = !snowOk; snowBtn.title = snowOk ? "" : "NBM's snow ratio / chance of snow are not available for this point"; }
    if (!snowOk && mmMode === "snow") mmMode = "liquid";
    const r = MultiModel.build({ doc: mmDoc, areaId: fc.id, nbm, mode: mmMode });
    if (r.series.length < 2) { chartMsg(el, `<p class="hint">Only one source covers the next hours here, so there is nothing to compare yet.</p>`); return; }
    const unit = mmMode === "snow" ? "in of snow" : "in of liquid";
    const xs = (s) => s.x.map((t) => C.wall(t, tz));
    mmChips(r.series, () => modelChart(el, fc, tz));
    const hid = mmHiddenSet();
    if (r.series.every((s) => hid.has(s.key))) hid.delete(r.series[0].key);                 // never an empty chart
    const vis = r.series.filter((s) => !hid.has(s.key));
    const traces = vis.map((s) => ({ x: xs(s), y: s.y, mode: "lines+markers", name: s.label, line: { color: MM_STYLE[s.key].color, width: MM_STYLE[s.key].width, dash: MM_STYLE[s.key].dash },
      marker: { size: s.key === "nbm" ? 3 : 4, color: MM_STYLE[s.key].color }, customdata: s.y.map(() => (s.z === null ? (s.key === "nbm" ? "NBM 2.5 km grid, adjusted to the summit" : `${s.label}: 0.25° grid, not elevation-adjusted`) : `${s.label} terrain ${s.z.toLocaleString()} ft`)),
      hovertemplate: `${s.label}: %{y:.2f} ${unit}<br>%{customdata} vs summit ${Math.round(P.elev_ft).toLocaleString()} ft<extra></extra>` }));
    const allX = r.series.flatMap((s) => s.x), x0 = C.wall(r.t0, tz), x1 = C.wall(Math.max(...allX), tz);      // the time axis spans every model (hiding one never rescales time)
    const ymax = Math.max(0.5, ...vis.flatMap((s) => s.y.filter((v) => v !== null))) * 1.08;
    const ax = C.timeAxis(x0, x1, el.clientWidth - C.MARGIN.l - 56);
    const labels = C.endLabels(vis.map((s) => ({ xs: xs(s), ys: s.y, text: MM_CHIP[s.key] || s.label, color: MM_STYLE[s.key].color })), { yrange: [0, ymax], plotHeight: 240 - C.MARGIN.t - ax.b, gap: 20 });   // label boxes are ~19 px tall (12 px text + background); browser check mmchips measures them
    C.plot(el, traces, C.layout(240, { margin: { r: 56, b: ax.b }, showlegend: false, shapes: ax.shapes, annotations: [C.axisTitle(mmMode === "snow" ? "Snow (in), at NBM's ratio" : "Liquid precipitation (in)"), ...labels],
      xaxis: ax.axis, yaxis: C.yaxis({ range: [0, ymax] }) }));
    const ag = r.agreement;
    $("mm-badge").innerHTML = ag ? (ag.dry
      ? `<b class="mm-dry">${ag.text}</b> <span class="hint">(all ${ag.n} models under 0.20 in over the next ${ag.H} h; a heuristic)</span>`
      : `Model agreement: <b class="mm-${ag.label.toLowerCase()}">${ag.label}</b> <span class="hint">(${ag.within} of ${ag.n} models within ±25% of the median, next ${ag.H} h; a heuristic)</span>`) + `
      <a class="info" href="about.html#precip-by-model" title="Share of models within ±25% of the median total (High ≥ 80%, Medium ≥ 66%): a heuristic, not an accuracy claim." aria-label="How model agreement works">ⓘ</a>`
      : `<span class="hint">Model agreement needs at least three models over the same hours.</span>`;
    const fmt = (v) => (v === null || v === undefined ? "–" : v.toFixed(2));
    const mmFull = (ag ? `Next ${ag.H} h at the summit, ${mmMode === "snow" ? "snow at NBM's ratio" : "liquid precipitation"}: ${ag.totals.map(([l]) => `${l} ${fmt(MultiModel.valueAt(r.series.find((s) => s.label === l), r.t0, ag.H))} in`).join(", ")}; ${ag.dry ? "little precipitation is expected (every model under 0.20 in)" : `model agreement is ${ag.label.toLowerCase()}`} (a heuristic).`
      : `Precipitation by model: ${r.series.map((s) => s.label).join(", ")}.`);
    const tots = ag ? ag.totals.map(([l]) => MultiModel.valueAt(r.series.find((s) => s.label === l), r.t0, ag.H)).filter((v) => v !== null) : [];
    C.summary(el, ag && tots.length ? `Next ${ag.H} h at the summit: ${fmt(Math.min(...tots))}–${fmt(Math.max(...tots))} in of ${mmMode === "snow" ? "snow" : "liquid"} across the models.` : mmFull, mmFull);
    const grid = []; for (let h = 0; h <= 240; h += 6) if (r.series.some((s) => MultiModel.valueAt(s, r.t0, h) !== null)) grid.push(h);
    C.tableToggle(el, `Cumulative ${unit} since ${localDT(new Date(r.t0).toISOString(), tz)}, by model`, ["Time", ...r.series.map((s) => s.label)],
      grid.map((h) => [localDT(new Date(r.t0 + h * 3.6e6).toISOString(), tz), ...r.series.map((s) => fmt(MultiModel.valueAt(s, r.t0, h)))]));
    const ecm = r.series.some((s) => s.key === "ecmwf" || s.key === "aifs"), aif = r.series.find((s) => s.key === "aifs");
    const ecS = r.series.find((s) => s.key === "ecmwf") || aif, ecFr = ecS && ecS.init ? Freshness.state(ecS.init, Date.now(), "ecmwf") : null;
    const ecW = ecFr && ecFr.state !== "latest" ? Freshness.words(ecFr, { label: "ECMWF run" }) : null;
    $("mm-note").innerHTML = `Cumulative from ${esc(localDT(new Date(r.t0).toISOString(), tz))} · NOAA/NWS NBM, HRRR, RRFS, GFS${ecm ? ` · ${ECMWF_CREDIT}` : ""}${ecW ? ` · <b class="fr-${ecFr.state}" title="${esc(ecW.long)}">${esc(ecW.text)}</b>` : ""}${aif ? ` · AIFS (AI) is experimental${aif.badge ? "" : ", not in the agreement rating"}` : ""} · ${how("precip-by-model")}`;
  }


  // ---- ECMWF IFS ENS plume (dev17): the second view of the panel; models/ecmwf/plume/<area>.json is fetched ONLY when this view is selected
  const ensDocs = new Map();
  /** replace a chart with a message: purge the Plotly state first, or a later Plotly.react would draw into a DOM that no longer exists (blank chart) */
  const chartMsg = (el, html) => { try { window.Plotly?.purge(el); } catch { /* no plot yet */ } el.innerHTML = html; };
  async function ensembleChart(el, fc, tz) {
    const P = fc.points.summit, badge = $("mm-badge"), note = $("mm-note");
    const S = ENS_SRC[ensSrc] || ENS_SRC.ecmwf;
    if (!el.data) el.innerHTML = `<p class="hint">Loading the ${S.short} ensemble…</p>`;
    const dkey = `${ensSrc}:${fc.id}`;
    if (!ensDocs.has(dkey)) ensDocs.set(dkey, getJSON(`${S.path}${encodeURIComponent(fc.id)}.json`).catch(() => null));
    const doc = await ensDocs.get(dkey);
    if (!doc || !doc.hours?.length) {
      chartMsg(el, `<p class="hint">The ${S.short} ensemble is not available for this area yet.</p>`); badge.textContent = ""; return;
    }
    const nbmRatio = P.series.slr_p50 || P.series.slr || [];
    const snowOk = nbmRatio.some((v) => v);
    const snowBtn = document.querySelector("#mm-mode [data-m=snow]");
    if (snowBtn) { snowBtn.disabled = !snowOk; snowBtn.title = snowOk ? "" : "NBM's snow ratio is not available for this point"; }
    if (!snowOk && mmMode === "snow") mmMode = "liquid";
    const issued = Date.parse(fc.issued), init = Date.parse(doc.init);
    const t0 = Math.max(issued, init);
    const b = Ensemble.build(doc, { mode: mmMode, t0Ms: t0, ratio: nbmRatio, ratioTimes: (fc.times || []).map((x) => Date.parse(x)) });
    if (!b.members.length || b.x.length < 3) { chartMsg(el, `<p class="hint">The ${S.short} run does not cover the hours after the common start yet.</p>`); return; }
    const st = Ensemble.summarize(b);
    // dev22: freshness is judged against when the NEXT run is due (js/freshness.js): latest / late / out of date; only "out of date" greys the plume
    const fr = Freshness.state(init, Date.now(), ensSrc === "gefs" ? "gefs" : "ecmwf"), sk = { stale: fr.state === "out-of-date", ageH: (Date.now() - init) / 3.6e6 };
    const frWords = Freshness.words(fr, { label: "run" });
    const col = (k) => st.map((s) => s[k]);
    const xs = b.x.map((t) => C.wall(t, tz));
    const ink = sk.stale ? "#7a8594" : C.INK, blue = sk.stale ? "#9aa3ad" : C.OI.blue;
    // ALL members as ONE faint multi-segment trace (null breaks between members): fast on phones
    const fx = [], fy = [];
    b.members.forEach((m) => { m.forEach((v, i) => { fx.push(xs[i]); fy.push(v); }); fx.push(null); fy.push(null); });      // a missing step is a null y: the line breaks there
    const unit = mmMode === "snow" ? "in of snow" : "in of liquid";
    const gapHours = (doc.steps_missing || []).slice().sort((x, y) => x - y);
    const gapNote = gapHours.length ? ` ${gapHours.length} forecast step${gapHours.length === 1 ? "" : "s"} (${gapHours.slice(0, 6).map((h) => `+${h} h`).join(", ")}${gapHours.length > 6 ? ", …" : ""}) could not be fetched from the mirror and ${gapHours.length === 1 ? "is" : "are"} drawn as gaps, never interpolated.` : "";
    const terrain = doc.z_ft ? `${S.short} terrain ${doc.z_ft.toLocaleString()} ft (0.25° grid) vs summit ${Math.round(P.elev_ft).toLocaleString()} ft` : `${S.short} 0.25° grid, not elevation-adjusted`;
    const traces = [
      { x: fx, y: fy, mode: "lines", line: { color: sk.stale ? "rgba(120,130,140,0.18)" : "rgba(0,114,178,0.13)", width: 1 }, hoverinfo: "skip", connectgaps: false, name: "members" },
      { x: xs, y: col("p90"), mode: "lines", line: { width: 0 }, hoverinfo: "skip" },
      { x: xs, y: col("p10"), mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: sk.stale ? "rgba(120,130,140,0.14)" : "rgba(86,180,233,0.22)", hoverinfo: "skip", name: "10–90%" },
      { x: xs, y: col("p75"), mode: "lines", line: { width: 0 }, hoverinfo: "skip" },
      { x: xs, y: col("p25"), mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: sk.stale ? "rgba(120,130,140,0.26)" : "rgba(0,114,178,0.28)", hoverinfo: "skip", name: "25–75%" },
      { x: xs, y: col("p50"), mode: "lines", name: "Median", line: { color: ink, width: 3 }, customdata: st.map((s) => [s.p25, s.p75, s.p10, s.p90, s.n]),
        hovertemplate: `Median %{y:.2f} ${unit}<br>25–75%: %{customdata[0]:.2f}–%{customdata[1]:.2f} · 10–90%: %{customdata[2]:.2f}–%{customdata[3]:.2f}<br>%{customdata[4]} members<br>${terrain}<extra></extra>` },
      { x: xs, y: col("mean"), mode: "lines", name: "Mean", line: { color: blue, width: 2, dash: "dot" }, hovertemplate: `Mean %{y:.2f} ${unit}<extra></extra>` },
    ];
    if (b.hres) traces.push({ x: xs, y: b.hres, mode: "lines", name: "HRES", line: { color: C.OI.purple, width: 2, dash: "dash" }, connectgaps: false, hovertemplate: `HRES: ECMWF's single high-resolution (deterministic) run, a reference line, not a member %{y:.2f} ${unit}<extra></extra>` });
    const ymax = Math.max(0.3, ...st.map((s) => s.p90 ?? 0), ...b.members.map((m) => Math.max(0, ...m.filter((v) => v !== null)))) * 1.06;
    const ax = C.timeAxis(C.wall(b.x[0], tz), C.wall(b.x[b.x.length - 1], tz), el.clientWidth - C.MARGIN.l - 62);
    const last = (arr) => arr.length - 1 - [...arr].reverse().findIndex((v) => v !== null && v !== undefined);
    const lbl = [["90%", col("p90"), blue], ["Median", col("p50"), ink], ["10%", col("p10"), blue]];
    if (b.hres) lbl.push(["HRES (single run)", b.hres, C.OI.purple]);
    const labels = C.endLabels(lbl.map(([text, ys, color]) => ({ xs, ys, text, color })), { yrange: [0, ymax], plotHeight: 230 - C.MARGIN.t - ax.b + 34 });
    const shapes = [...ax.shapes];
    const annotations = [C.axisTitle(mmMode === "snow" ? "Snow (in), at NBM's ratio" : "Liquid precipitation (in)"), ...labels];
    if (sk.stale) annotations.push({ xref: "paper", yref: "paper", x: 0.5, y: 0.92, showarrow: false, text: `Out of date: a newer run should exist (this run started ${Math.round(sk.ageH)} h ago)`, font: C.font(13, "#8a1c10") });
    C.plot(el, traces, C.layout(240, { margin: { r: 62, b: ax.b }, showlegend: false, shapes, annotations, xaxis: ax.axis, yaxis: C.yaxis({ range: [0, ymax] }) }));
    // headline (also the aria-label), the 72 h mark when the run reaches it
    const lastH = Math.round((b.x[b.x.length - 1] - b.t0) / 3.6e6), H = Math.min(72, lastH);
    const endMs = b.t0 + H * 3.6e6;
    const thr = mmMode === "snow" ? 6 : 1;
    const sentence = Ensemble.headline(b, st, { mode: mmMode, h: H, thr, weekday: localFmt(new Date(endMs).toISOString(), tz, { weekday: "short" }), label: S.head });
    C.summary(el, Ensemble.headline(b, st, { mode: mmMode, h: H, thr, weekday: localFmt(new Date(endMs).toISOString(), tz, { weekday: "short" }), label: S.head, short: true }), sentence);
    const fmtT = (ms) => localDT(new Date(ms).toISOString(), tz);
    C.tableToggle(el, `${S.head}, cumulative ${unit} since ${fmtT(b.t0)}: percentiles across ${b.n} members, then the number of members at or above each amount`,
      ["Time", "10%", "25%", "Median", "75%", "90%", "Mean", "HRES"], Ensemble.tableRows(b, st, { mode: mmMode, fmtTime: fmtT, thresholds: mmMode === "snow" ? [2, 6, 12] : [0.5, 1, 2] }));
    badge.innerHTML = `${S.label} <b>${new Date(doc.init).toISOString().slice(11, 13)}Z</b> run, started ${esc(localDT(doc.init, tz))} · ${doc.n_members} ${ensSrc === "gefs" ? "members (the control run plus the perturbed members)" : `perturbed members${doc.control_member ? " plus the control run" : ""}`} · <b class="mm-${fr.state === "latest" ? "high" : fr.state === "late" ? "medium" : "low"}" title="${esc(frWords.long)}">${esc(frWords.text)}</b>
      <span class="hint">(faint = members · bands 25–75%, 10–90% · median, mean${b.hres ? " · dashed purple = HRES, a single deterministic run drawn as a reference, not a member" : ""})</span>`;
    const gapShort = gapHours.length ? ` · ${gapNote.trim().replace(/\.$/, "")}` : "";                    // names the missing steps: a data-quality label that stays
    note.innerHTML = ensSrc === "gefs"
      ? `NOAA/NCEP GEFS via NOAA Open Data Dissemination (public domain) · run started ${esc(fmtT(Date.parse(doc.init)))}${mmMode === "snow" ? " · snow is an ESTIMATE (water equivalent × snow share × NBM's ratio)" : ""}${gapShort} · ${how("ensemble")}`
      : `${ECMWF_CREDIT} · <a href="https://apps.ecmwf.int/datasets/licences/general/" target="_blank" rel="noopener">terms</a> · run started ${esc(fmtT(Date.parse(doc.init)))}${gapShort} · ${how("ensemble")}`;
  }

  /** M9 verification panel ("How did forecasts do here?"), BUILT BEHIND config verification_ui.enabled (meta.json): flag off = the section stays hidden and nothing is fetched.
   *  Below the minimum (days AND pairs) it says "Collecting data: X of 14 days" and shows no numbers. Observation = SNOTEL 24-h depth change, a lower bound of snowfall. */
  async function verification(a, isRec) {
    const sec = $("verif-sec");
    if (!sec || isRec || typeof VerificationUI === "undefined") return;
    const meta = await getJSON("data/meta.json").catch(() => null);
    if (!meta?.verification_ui?.enabled) return;
    const near = a.nearest?.snotel?.[0];
    const proxy = !a.triplet && !String(a.id || "").startsWith("snotel-");
    sec.hidden = false;
    const body = $("verif-body");
    if (!near) { body.innerHTML = `<p class="hint">No SNOTEL site is near enough to compare with.</p>`; return; }
    const index = await getJSON(`${VerificationUI.BASE}verification.json`).catch(() => null);
    if (!index) { body.innerHTML = `<p class="hint">Verification results are not available yet.</p>`; return; }
    const st = VerificationUI.status(index, near.id);
    if (st.state !== "ready") { body.innerHTML = `<p class="collecting" role="status">${esc(VerificationUI.collecting(st))}</p>`; return; }
    const doc = await getJSON(`${VerificationUI.BASE}verification/${encodeURIComponent(near.id.replace(/:/g, "_"))}.json`).catch(() => null);
    if (!doc) { body.innerHTML = `<p class="hint">Results for this site could not be loaded.</p>`; return; }
    const where = { name: near.name, proxy, distKm: near.dist_km ?? null, dz: near.dz_base_ft ?? null };
    body.innerHTML = `<div class="chart" id="verif-chart" style="height:240px"><p class="hint">Loading chart…</p></div>
      <div class="tbl-wrap"><table class="st-tbl"><caption class="sr">Forecast verification at ${esc(near.name)}</caption><thead><tr>${VerificationUI.METRIC_COLS.map((c) => `<th scope="col">${esc(c)}</th>`).join("")}</tr></thead>
        <tbody>${VerificationUI.metricRows(doc).map((r) => `<tr><th scope="row">${esc(r[0])}</th>${r.slice(1).map((v) => `<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
      <ul class="caveats">${VerificationUI.caveats(doc, where, index).map((t) => `<li>${esc(t)}</li>`).join("")}</ul>
      <p class="hint">A heuristic first look, not an accuracy rating: <a href="about.html#scorecard">how this is measured</a>.</p>`;
    C.lazy($("verif-chart"), () => loadPlotly().then(() => verifyChart($("verif-chart"), doc, where, index)));
  }

  function verifyChart(el, doc, where, index) {
    const d = doc.daily, num = (arr) => arr.filter((v) => v !== null && v !== undefined);
    const ymax = Math.max(0.5, ...d.obs, ...num(d.nbm), ...num(d.ndfd)) * 1.12;
    const traces = [
      { type: "bar", x: d.dates, y: d.obs, name: "Observed (SNOTEL depth gain)", marker: { color: "#aab4bf" }, hovertemplate: "Observed %{y:.2f} in<extra></extra>" },
      { type: "scatter", mode: "markers", x: d.dates, y: d.nbm, name: "NBM expected", marker: { color: C.OI.blue, size: 8, symbol: "circle" }, hovertemplate: "NBM %{y:.2f} in<extra></extra>" },
      { type: "scatter", mode: "markers", x: d.dates, y: d.ndfd, name: "NWS (NDFD)", marker: { color: C.OI.orange, size: 8, symbol: "diamond" }, hovertemplate: "NWS %{y:.2f} in<extra></extra>" },
    ];
    C.plot(el, traces, C.layout(250, { margin: { t: 40 }, showlegend: true, legend: { orientation: "h", x: 0, y: 1.16, font: C.font(C.tick(), C.INK) }, bargap: 0.35,
      annotations: [C.axisTitle("24-h snow (in), one window per day (12Z to 12Z)")], xaxis: { type: "date", tickformat: "%b %-d", fixedrange: true, tickfont: C.font(C.tick(), C.INK), showgrid: false },
      yaxis: C.yaxis({ range: [0, ymax] }) }));
    C.summary(el, VerificationUI.sentence(doc, where));
    C.tableToggle(el, `Observed and forecast 24-hour snow (in) at ${where.name}`, ["Window end (12Z)", "Observed", "NBM expected", "NWS (NDFD)"], VerificationUI.dailyRows(doc));
  }

  function snowLevelChart(el, fc, keys, tz) {
    const s = fc.points[keys[0]].series, t = fc.times;
    const xs = t.map((x) => C.wall(x, tz));
    // "likely" band = NBM p25-p75 (owner Nov 17) and the median from the SAME percentile series; older files (no p25/p75)
    // fall back to p10-p90, labelled as such. Where NBM has no snow level at all the gap is labelled, never blank.
    const has25 = (s.snowlvl_p25 || []).some((v) => v !== null) && (s.snowlvl_p75 || []).some((v) => v !== null);
    const lo_s = has25 ? s.snowlvl_p25 : s.snowlvl_p10, hi_s = has25 ? s.snowlvl_p75 : s.snowlvl_p90;
    const med = (s.snowlvl_p50 || []).some((v) => v !== null) ? s.snowlvl_p50 : s.snowlvl_ft;
    const bandName = has25 ? "likely range" : "10–90% range";
    let nb = 0;                                  // the band: as long as NBM has the percentiles
    while (nb < t.length && lo_s[nb] !== null && hi_s[nb] !== null) nb++;
    const chance = precipChance(fc, keys[0]);
    const wet = med.map((v, i) => ((chance[i] ?? 0) >= WET ? v : null));
    const lines = keys.map((k) => [POINT_LABEL[k], fc.points[k].elev_ft, k === "summit" || k === "point" ? C.INK : "#7a4e12",
      k === "base" ? "dash" : "solid"]);
    const elevs = keys.map((k) => fc.points[k].elev_ft);
    const minBase = Math.min(...elevs);
    const allV = [...med, ...lo_s.slice(0, nb)].filter((v) => v !== null);
    const lo = Math.max(0, Math.min(minBase - 2500, ...allV) - 500), top = Math.max(...elevs, ...allV.slice(0, 400)) + 1500;
    const ax = C.timeAxis(xs[0], xs[xs.length - 1], el.clientWidth - C.MARGIN.l - C.MARGIN.r);
    const traces = [
      { x: xs.slice(0, nb), y: hi_s.slice(0, nb), mode: "lines", line: { width: 0 }, hoverinfo: "skip" },
      { x: xs.slice(0, nb), y: lo_s.slice(0, nb), mode: "lines", line: { width: 0 }, fill: "tonexty",
        fillcolor: "rgba(230,159,0,0.28)", name: bandName, hoverinfo: "skip" },
      { x: xs, y: med, mode: "lines", line: { color: "#5b6572", width: 2, dash: "dot" }, name: "Snow level (median)", connectgaps: false,
        customdata: xs.map((_, i) => [lo_s[i], hi_s[i]]),
        hovertemplate: `Median snow level %{y:,.0f} ft (${bandName} %{customdata[0]:,.0f}–%{customdata[1]:,.0f})<extra></extra>` },
      { x: xs, y: wet, mode: "lines", line: { color: "#9a5300", width: 2.8 }, connectgaps: false, hoverinfo: "skip" },
    ];
    const shapes = [...ax.shapes, { type: "rect", xref: "paper", x0: 0, x1: 1, y0: lo, y1: minBase,
      fillcolor: "rgba(0,114,178,0.10)", line: { width: 0 }, layer: "below" }];
    const annotations = [C.axisTitle("Snow level (ft)")];
    for (const [a, b] of gaps(med.map((v) => v !== null))) {      // NBM has no snow level here: say so
      shapes.push({ type: "rect", xref: "x", yref: "paper", x0: xs[a], x1: b + 1 < xs.length ? xs[b + 1] : xs[b], y0: 0, y1: 1, fillcolor: "rgba(120,130,140,0.12)", line: { width: 0 }, layer: "below" });
      if (b - a >= 4) annotations.push({ xref: "x", x: xs[Math.floor((a + b) / 2)], yref: "paper", y: 0.5, showarrow: false, text: "no snow-level forecast", font: C.font(12, C.MUTED) });
    }
    for (const [lab, y, c, dash] of lines) {
      const r = C.refLine(y, `${lab} ${ft(y)}`, { color: c, dash, width: 1.6, where: "left" });
      shapes.push(r.shape); annotations.push(r.ann);
    }
    annotations.push({ xref: "paper", x: 0.99, y: lo, yanchor: "bottom", xanchor: "right", yshift: 3, showarrow: false,
      font: C.font(12, "#0b4f80"), text: `Line in the blue zone = snow to the ${keys.includes("base") ? "base" : "station"}` });
    if (nb > 1) annotations.push({ x: xs[Math.min(nb - 1, Math.floor(nb * 0.85))], y: hi_s[Math.min(nb - 1, Math.floor(nb * 0.85))],
      xref: "x", yref: "y", yanchor: "bottom", showarrow: false, text: bandName, font: C.font(12, "#8a4b00"), yshift: 2 });
    C.plot(el, traces, C.layout(H(260), { shapes, annotations, xaxis: ax.axis, margin: { b: ax.b },
      yaxis: C.yaxis({ range: [lo, top], tickformat: ",.0f" }) }));
    // summary: lowest snow level while precipitation is likely, vs base/summit
    let wi = -1;
    wet.forEach((v, i) => { if (v !== null && (wi < 0 || v < wet[wi])) wi = i; });
    const base = keys.includes("base") ? fc.points.base.elev_ft : fc.points[keys[0]].elev_ft;
    const rel = (v) => (v <= base ? `below the ${keys.includes("base") ? "base" : "station"} (${ft(base)})`
      : keys.includes("summit") && v >= fc.points.summit.elev_ft ? `above the summit (${ft(fc.points.summit.elev_ft)})` : "between base and summit");
    const vals = med.filter((v) => v !== null);
    C.summary(el, wi >= 0
      ? `Lowest snow level while precipitation is likely: ${ft(wet[wi])} (${localDT(t[wi], tz)}), ${rel(wet[wi])}.`
      : vals.length ? `Little precipitation expected; snow level ${ft(Math.min(...vals))} to ${ft(Math.max(...vals))}.` : "No snow-level forecast.");
    C.tableToggle(el, "Snow level (ft MSL), NBM", ["Time", "Median snow level (ft)", has25 ? "Likely low (25%)" : "Low (10%)", has25 ? "Likely high (75%)" : "High (90%)", "Chance of precip"],
      t.map((x, i) => [localDT(x, tz), plain(med[i]), plain(lo_s[i]), plain(hi_s[i]),
        chance[i] === null || chance[i] === undefined ? "–" : `${Math.round(chance[i] * 100)}%`]));
    C.legend(el, [["line", "median, precip. likely", "#9a5300"], ["dotted", "precip. not likely", "#5b6572"], ["band", bandName, "rgba(230,159,0,0.4)"], ["#cfe6f5", "blue zone = snow to base"]]);
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
    const lay = C.layout(H(220), { margin: { r: 70, b: ax.b }, shapes: [...ax.shapes, ext.shape, r32.shape], xaxis: ax.axis });
    const yr = C.extent([...keys.map((k) => P[k].series.t_f), [32], ...(wc ? [wc] : [])], { min: 10 });
    lay.yaxis = C.yaxis({ dtick: 10, range: yr });
    lay.annotations = [C.axisTitle(rec ? "Temperature and wind chill (°F)" : "Temperature (°F)"), r32.ann, ext.ann,
      ...C.endLabels([...keys.map((k) => ({ xs, ys: P[k].series.t_f, text: POINT_LABEL[k], color: PT_STYLE[k].color })),
        ...(wc ? [{ xs, ys: wc, text: "Wind chill", color: "#9c3d78" }] : [])], { yrange: yr, plotHeight: C.plotH(lay) })];
    C.plot(el, traces, lay);
    const rng = (k) => rangeOf(P[k].series.t_f.slice(0, D.n));
    const later = rangeOf(P[keys[0]].series.t_f.slice(D.n));
    const tShort = keys.map((k) => { const r = rng(k); return r ? `${POINT_LABEL[k]} ${r[0]} to ${r[1]} °F` : ""; }).filter(Boolean).join(", ") + (keys.some((k) => (rng(k)?.[1] ?? 99) < 32) ? "; staying below freezing" : "") + ".";
    C.summary(el, tShort, keys.map((k) => { const r = rng(k); return r ? `${POINT_LABEL[k]} ${r[0]} to ${r[1]} °F` : ""; }).filter(Boolean).join(", ") +
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
    const lay = C.layout(H(220), { margin: { r: 70, b: ax.b }, shapes, xaxis: ax.axis });
    const yr = C.extent(allY, { zero: true, min: 10 });
    lay.yaxis = C.yaxis({ range: yr });
    lay.annotations = [...annotations, ...C.endLabels(ends, { yrange: yr, plotHeight: C.plotH(lay) })].filter(Boolean);
    C.plot(el, traces, lay);
    const mx = (a, i0 = 0, i1 = D.n) => Math.max(0, ...a.slice(i0, i1).filter((v) => v !== null));
    const lateG = D.N > D.n ? mx(s.gust_mph, D.n, D.N) : null;
    C.summary(el, `${POINT_LABEL[wk]} wind up to ${mx(s.wind_mph)} mph, gusts to ${mx(s.gust_mph)} mph.`,
      `${POINT_LABEL[wk]} wind up to ${mx(s.wind_mph)} mph, gusts to ${mx(s.gust_mph)} mph in the next ${Math.round(HOURS_DETAIL / 24 * 2) / 2} days` +
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
    C.layout(H(220), { margin: { r: 70, b: ax.b }, bargap: 0, shapes, annotations, xaxis: ax.axis,
      yaxis: C.yaxis({ rangemode: "tozero", tickformat: ".2~f", range: [0, Math.max(0.1, ...rate.filter((v) => v !== null)) * 1.15] }) }));
    let bi = -1;
    rate.forEach((v, j) => { if (v !== null && (bi < 0 || v > rate[bi])) bi = j; });
    const total = keep.reduce((a, i) => a + (pr.snow_in[i] ?? 0), 0);
    const rFull = bi >= 0 && rate[bi] >= 0.05
      ? `Heaviest snow about ${rate[bi].toFixed(2)} in per hour (${text[bi].split(":")[0]}); about ${inches(total)} in in the next ${Math.round(HOURS_DETAIL / 24 * 2) / 2} days (expected).`
      : `Little or no snow in the next ${Math.round(HOURS_DETAIL / 24 * 2) / 2} days (expected ${inches(total)} in).`;
    C.summary(el, bi >= 0 && rate[bi] >= 0.05 ? `Heaviest: about ${rate[bi].toFixed(2)} in per hour, ${text[bi].split(":")[0]}.` : rFull, rFull);
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

  /** Storm total (observed, W-tracker dev15): snow over a selectable window from the nearest SNOTEL station (snow depth change and SWE change from
   *  its hourly series) and the NOHRSC National Snowfall Analysis at the summit/base (24/48/72 h windows only; NOHRSC publishes no 7-day product).
   *  A depth change includes compaction: it is NOT snowfall (owner Nov 16). A stale SNOTEL copy older than the window shows "–", never an old value as current. */
  async function stormTotal(host, a, depthSeries, sweSeries, info, st) {
    const WINS = [["24h", 24], ["48h", 48], ["72h", 72], ["7d", 168]];
    let win = "72h", nohrsc = null;
    try { nohrsc = (await getJSON("data/nohrsc/ski.json")).areas?.[a.id] || null; } catch { /* optional */ }
    const change = (arr, h) => {
      let i = arr.length - 1;
      while (i >= 0 && (arr[i] === null || arr[i] === undefined)) i--;
      return i >= h && arr[i - h] !== null && arr[i - h] !== undefined ? arr[i] - arr[i - h] : null;
    };
    const sw = (v) => `<i class="sw${v !== null && snowPale(colorFor(SNOWFALL, v) || "#fff") ? " pale" : ""}" style="background:${v !== null && v > 0 ? colorFor(SNOWFALL, v) || "#f4f6f8" : "#f4f6f8"}"></i>`;
    const fmt = (v, d = 0, sign = true) => (v === null || v === undefined ? "–" : `${sign && v > 0 ? "+" : ""}${v.toFixed(d)}"`);
    function render() {
      const h = Object.fromEntries(WINS)[win];
      const closed = info.state === "stale" && (info.ageH ?? 0) > h;            // the stale copy is older than the window
      const dep = closed ? null : change(depthSeries, h), swe = closed ? null : change(sweSeries, h);
      const key = h === 24 ? "sf24" : h === 48 ? "sf48" : h === 72 ? "sf72" : null;
      const nrow = (k) => (nohrsc?.[k] && key ? `<tr><th scope="row">NOHRSC snowfall analysis, ${POINT_LABEL[k].toLowerCase()}</th><td>${sw(nohrsc[k][key])}${fmt(nohrsc[k][key], 1, false)}</td></tr>` : "");
      host.innerHTML = `<h4>Storm total (observed)</h4>
        <span class="seg" role="group" aria-label="Storm-total window">${WINS.map(([n]) => `<button type="button" data-w="${n}" class="${n === win ? "on" : ""}" aria-pressed="${n === win}">${n === "7d" ? "7 days" : n.replace("h", " h")}</button>`).join("")}</span>
        <table class="metrics"><tbody>
          <tr><th scope="row">${esc(st.name)} SNOTEL: snow depth change</th><td>${sw(dep)}${fmt(dep)}</td></tr>
          <tr><th scope="row">${esc(st.name)} SNOTEL: SWE change</th><td>${fmt(swe, 1)}</td></tr>
          ${nrow("summit")}${nrow("base")}
        </tbody></table>
        <p class="note src">${closed ? `The SNOTEL copy is ${Math.round(info.ageH)} h old, older than this window, so no change is shown. ` : ""}Depth change is <b>not snowfall</b> (compaction)${key ? "" : "; NOHRSC publishes snowfall for 24–72 h only"} · USDA NRCS SNOTEL${key ? ", NOAA/NWS NOHRSC" : ""} · ${how("recent-observations")}</p>`;
      host.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { win = b.dataset.w; render(); }));
    }
    render();
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
    $("obs-chart").insertAdjacentHTML("beforebegin", `<div id="storm" class="storm"></div>`);
    stormTotal($("storm"), a, series, d.WTEQ || [], info, st);
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
      <p class="note src">NOAA/NWS NOHRSC snowfall analysis to ${esc(when(js.snowfall_end))} · depth and SWE: SNODAS, ${esc(when(js.snodas_valid))} · ${how("recent-observations")}</p>`;
  }

  function avalanche(a, ratings) {
    if (!a) return `<p class="hint">Outside the avalanche-center forecast zones.</p>`;
    const p = ratings?.[String(a.zone_id)];
    if (!p) return `<p>${esc(a.zone)}</p>`;
    return `<p><span class="danger-chip${p.expired ? " expired" : ""}" style="background:${esc(p.color)}">${esc(p.danger)}</span>
      ${esc(p.name)}${p.expired ? ` <span class="hint">(expired)</span>` : ""}</p>
      <a href="${esc(safeUrl(p.link))}" target="_blank" rel="noopener" data-track="avalanche_click">Read the full forecast →</a>`;
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
    const [fcR, avyR, alR, camR] = await Promise.allSettled([
      id ? getJSON(`data/points/${encodeURIComponent(id)}.json`) : Promise.reject(new Error("no id")),
      isStation ? Promise.resolve(null) : getJSON("data/avalanche_ratings.json"),
      getJSON("data/alerts/index.json"),
      isStation ? Promise.resolve(null) : getJSON("data/webcams.json")]);              // webcam LINKS only (config/webcams.yml); no images are ever loaded from those sites
    const nbm = fcR.status === "fulfilled" ? fcR.value : null;
    const alertRefs = alR.status === "fulfilled" ? (isStation ? alR.value.points : alR.value.areas)?.[id] || [] : [];   // client-side alert tag (§5.7)
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
    const src = nbm ? "nbm" : null;
    const doc = () => nbm;
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
      ${src ? `<div id="summary-card" class="summary-card" aria-live="polite"></div>
      <p class="headline" id="headline"></p>
      <p class="fresh" id="fresh"></p>
      <p class="hint bust" id="bust"></p>
      <div class="sec-head seg-row"><span id="elev-seg"></span></div>
      <div id="tiles"></div>
      <section id="sec-period"><h3>Snowfall by day</h3>
        <div class="chart" id="period-chart" style="height:${H(260)}px"><p class="hint">Loading chart…</p></div>
        <p class="note src" id="period-note"></p></section>
      <section id="sec-acc"><h3>Accumulated snow</h3>
        <div class="chart" id="acc-chart" style="height:${H(240)}px"><p class="hint">Loading chart…</p></div>
        <p class="note src" id="acc-note"></p></section>
      <section id="sec-slr"><h3>Snow ratio and powder quality <a class="info" href="about.html#snow-ratio" title="Powder quality is a documented heuristic from NBM's snow-to-liquid ratio, not an accuracy claim or an avalanche rating." aria-label="How powder quality works">ⓘ</a></h3>
        <div class="chart" id="slr-chart" style="height:${H(280)}px"><p class="hint">Loading chart…</p></div>
        <p class="note src" id="slr-note"></p></section></section>
      <section id="ex-sec"><h3>Chance of at least…</h3>
        <div class="seg" role="group" aria-label="Window" id="ex-win"><button type="button" class="on" data-w="24h" aria-pressed="true">24 h</button><button type="button" data-w="48h" aria-pressed="false">48 h</button><button type="button" data-w="72h" aria-pressed="false">72 h</button></div>
        <div id="ex-chart" class="heat-box"><p class="hint">Loading…</p></div>
        <p class="note src" id="ex-note"></p></section>
      <section id="sec-sl"><h3>Snow level vs the ${isStation ? "station" : isRec ? "trailhead and high terrain" : "mountain"}</h3>
        <div class="chart" id="sl-chart" style="height:${H(260)}px"><p class="hint">Loading chart…</p></div>
        <p class="note src" id="sl-note"></p></section>
      ${isStation || isRec ? "" : `<section id="mm-sec"><h3>Precipitation by model <a class="info" href="about.html#precip-by-model" title="Cumulative precipitation at the summit from each model, in liquid-equivalent inches (or snow at NBM's ratio)." aria-label="About the model comparison">ⓘ</a></h3>
        <p class="mm-badge" id="mm-badge" aria-live="polite"></p>
        <span class="seg mm-view" id="mm-view" role="group" aria-label="View" hidden><button type="button" data-v="models" class="on" aria-pressed="true">Models</button><button type="button" data-v="ens" aria-pressed="false">Ensemble</button></span>
        <span class="seg mm-view" id="ens-src" role="group" aria-label="Ensemble source" hidden><button type="button" data-s="ecmwf" class="on" aria-pressed="true">ECMWF ENS</button><button type="button" data-s="gefs" aria-pressed="false">NOAA GEFS</button></span>
        <span class="sr" id="mm-announce" role="status" aria-live="polite"></span>
        <span class="seg" id="mm-mode" role="group" aria-label="Units"><button type="button" data-m="liquid" class="on" aria-pressed="true">Liquid (in)</button><button type="button" data-m="snow" aria-pressed="false">Snow (in)</button></span>
        <div class="mm-chips" id="mm-chips" role="group" aria-label="Models on the chart (the agreement rating and the table always use every model)"></div>
        <div class="chart" id="mm-chart" style="height:240px"><p class="hint">Loading chart…</p></div>
        <p class="note src" id="mm-note"></p></section>`}
      <section id="sec-hbh"><h3>Hour by hour <span class="h3sub" id="hbh-sub"></span></h3>
        <div class="chart" id="t-chart" style="height:${H(220)}px"><p class="hint">Loading chart…</p></div>
        <div class="chart" id="w-chart" style="height:${H(220)}px"><p class="hint">Loading chart…</p></div>
        <div class="chart" id="p-chart" style="height:${H(220)}px"><p class="hint">Loading chart…</p></div>
        <p class="note src" id="met-note"></p></section>`
      : `<p class="hint">No point forecast is available for this site yet.</p>`}
      <section id="afd"></section>
      <section><h3>Recent observations</h3><div id="nohrsc-obs"></div><div id="obs"></div></section>
      ${isRec ? "" : `<section id="verif-sec" hidden><h3>How did forecasts do here? <a class="info" href="about.html#scorecard" title="Forecasts versus SNOTEL snow-depth change, shown only after enough days of data." aria-label="How forecast verification works">ⓘ</a></h3><div id="verif-body"></div></section>`}
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
             ${webcamRow(camR.status === "fulfilled" ? camR.value?.[a.id] : null)}
             <h4>Nearby SNOTEL</h4><ul>${stationRows(a.nearest.snotel, "snotel")}</ul>
             <h4>Nearby airports</h4><ul>${stationRows(a.nearest.asos, "asos")}</ul>`}
      </section>`;

    wireAlertDetails(main);
    verification(a, isRec);
    $("fav").addEventListener("click", (e) => {
      const list = favs(), on = !list.includes(a.id);
      setFavs(on ? [...list, a.id] : list.filter((x) => x !== a.id));
      if (on && window.snowwxTrack) snowwxTrack("favorite_added", { where: "area", kind: isStation ? "snotel" : isRec ? "snopark" : "ski" });
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
          $("rk-wc-where").textContent = best ? `${POINT_LABEL[best.k].toLowerCase()}, ${localDT(best.iso, tz)} (NBM)` : "";
        }
        if (!keys.includes(pt)) pt = keys[0];
        const stale = (Date.now() - new Date(d.issued)) / 3.6e6 > 18;
        $("headline").innerHTML = headline(d, keys);
        $("summary-card").innerHTML = summaryCard(SnowSummary.withAlerts(d.summary, alertRefs)) + windExposure(d.wind_exposure, a, avyR.status === "fulfilled" ? avyR.value : null, tz);
        $("bust").innerHTML = bustLink(d, a, keys, tz);
        $("fresh").className = `fresh${stale ? " stale" : ""}`;
        $("fresh").textContent = `NBM ${localFmt(d.issued, tz,
          { weekday: "short", hour: "numeric", timeZoneName: "short" })} run · ${ago(d.issued)}${stale ? " — out of date" : ""}`;
        $("elev-seg").innerHTML = keys.length > 1 ? `<span class="seg" role="group" aria-label="Elevation">${keys.map((k) =>
          `<button type="button" data-pt="${k}" class="${k === pt ? "on" : ""}" aria-pressed="${k === pt}">${POINT_LABEL[k]} ${ft(d.points[k].elev_ft)}</button>`).join("")}</span>` : "";
        $("elev-seg").querySelectorAll("button").forEach((btn) => btn.addEventListener("click", () => {
          pt = btn.dataset.pt; drawNumbers(); drawCharts();
        }));
        $("tiles").innerHTML = tiles(d, pt, d.points[pt].elev_ft);
        // dev22: every module ends with ONE source/issue-time line and a "How it works" link; the explanations live in About ("Reading the charts")
        const issuedTxt = localFmt(d.issued, tz, { weekday: "short", hour: "numeric", timeZoneName: "short" });
        const srcLine = (anchor, extra = "") => `NBM, ${issuedTxt} run${extra ? ` · ${extra}` : ""} · ${how(anchor)}`;
        $("period-note").innerHTML = srcLine("snowfall-by-day");
        if ($("acc-note")) $("acc-note").innerHTML = srcLine("accumulated-snow");
        if ($("slr-note")) $("slr-note").innerHTML = srcLine("snow-ratio");
        $("ex-sec").hidden = !d.points[pt].exceed || !Object.keys(d.points[pt].exceed).length;
        $("ex-note").innerHTML = srcLine("chance-of", "NBM only");
        $("hbh-sub").textContent = `hourly ${Math.round(HOURS_DETAIL / 24 * 2) / 2} days, then 6-hourly · times ${tzName(tz)}`;
        $("sl-note").innerHTML = srcLine("snow-level", `times ${tzName(tz)}`);
        $("met-note").innerHTML = srcLine("hour-by-hour", `times ${tzName(tz)}`);
      };
      // Each chart draws when it comes near the viewport (SnowCharts.lazy), one per task, so
      // Plotly only loads once a chart is about to be seen.
      const drawCharts = () => {
        const d = doc(), keys = keysOf(d);
        const withPlotly = (f) => () => loadPlotly().then(() => f());
        // explanation only: the numbers live in the wind panel's summary (one source, fix 5)
        C.summary($("period-chart"), daySummary(d, pt), daySummary(d, pt, true));     // text first (LCP), chart when near view
        C.lazy($("period-chart"), withPlotly(() => periodChart($("period-chart"), d, pt, tz)));
        if ($("acc-chart")) {
          C.summary($("acc-chart"), accumSummary(d, pt));
          C.lazy($("acc-chart"), withPlotly(() => accumChart($("acc-chart"), d, pt, tz)));
        }
        if ($("slr-chart")) C.lazy($("slr-chart"), withPlotly(() => slrChart($("slr-chart"), d, pt, tz)));
        if (!$("ex-sec").hidden) C.lazy($("ex-chart"), () => exceedTable($("ex-chart"), d, pt, tz));
        C.lazy($("sl-chart"), withPlotly(() => snowLevelChart($("sl-chart"), d, keys, tz)));
        if ($("mm-chart")) C.lazy($("mm-chart"), withPlotly(() => modelChart($("mm-chart"), d, tz)));
        C.lazy($("t-chart"), withPlotly(() => tempChart($("t-chart"), d, keys, tz)));
        C.lazy($("w-chart"), withPlotly(() => windChart($("w-chart"), d, pt, keys, tz)));
        C.lazy($("p-chart"), withPlotly(() => snowRateChart($("p-chart"), d, pt, tz)));
        return Promise.resolve();
      };
      $("mm-view")?.querySelectorAll("button").forEach((btn) => btn.addEventListener("click", () => {
        mmView = btn.dataset.v;
        $("mm-view").querySelectorAll("button").forEach((x) => { x.classList.toggle("on", x === btn); x.setAttribute("aria-pressed", String(x === btn)); });
        $("mm-announce").textContent = mmView === "ens" ? "Showing the ECMWF ensemble plume." : "Showing the model comparison.";
        modelChart($("mm-chart"), doc(), tz);
      }));
      $("ens-src")?.querySelectorAll("button").forEach((btn) => btn.addEventListener("click", () => {
        ensSrc = btn.dataset.s;
        $("ens-src").querySelectorAll("button").forEach((x) => { x.classList.toggle("on", x === btn); x.setAttribute("aria-pressed", String(x === btn)); });
        $("mm-announce").textContent = `Showing the ${(ENS_SRC[ensSrc] || ENS_SRC.ecmwf).short} ensemble plume.`;
        modelChart($("mm-chart"), doc(), tz);
      }));
      $("mm-mode")?.querySelectorAll("button").forEach((btn) => btn.addEventListener("click", () => {
        if (btn.disabled) return;
        mmMode = btn.dataset.m;
        $("mm-mode").querySelectorAll("button").forEach((x) => { x.classList.toggle("on", x === btn); x.setAttribute("aria-pressed", String(x === btn)); });
        modelChart($("mm-chart"), doc(), tz);
      }));
      $("ex-win")?.querySelectorAll("button").forEach((btn) => btn.addEventListener("click", () => {
        exWin = btn.dataset.w;
        $("ex-win").querySelectorAll("button").forEach((x) => { x.classList.toggle("on", x === btn); x.setAttribute("aria-pressed", String(x === btn)); });
        drawNumbers(); drawCharts();
      }));
      drawNumbers();     // plain HTML first; charts after the library arrives
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
