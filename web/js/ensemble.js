// ECMWF IFS ENS plume for the "Precipitation by model" panel (dev17, docs/specs/multi-model.md): pure functions; area.js draws the chart.
// Data: models/ecmwf/plume/<area>.json (pipeline/ecmwf.py), loaded ONLY when the Ensemble view is selected: per member the run-total precipitation `tp` and snowfall
// water equivalent `sf` in 0.1 mm integers at 6-hour steps from the run start (null = member message missing), plus the HRES run ("hres_tp").
// Statistics: each member is one complete scenario. Totals are accumulated per member and aligned to the common start PER MEMBER (linear interpolation of that
// member's own cumulative series, js/multimodel.js interpAt); quantiles are then taken ACROSS members at each time (linear / Hyndman-Fan type 7, the same method
// as pipeline/ecmwf.py `quantiles`). No NBM percentile is read, summed, scaled or interpolated here.
/* global MultiModel */
// eslint-disable-next-line no-unused-vars
const Ensemble = (() => {
  const HOUR = 3.6e6, MM_IN = 25.4, TENTH = 0.1;
  const toIn = (tenthsMm) => (tenthsMm === null || tenthsMm === undefined ? null : (tenthsMm * TENTH) / MM_IN);

  /** quantile q (0-100) of an ascending array, linear interpolation between order statistics (numpy default; type 7) */
  function quantile(sorted, q) {
    const n = sorted.length;
    if (!n) return null;
    const pos = ((n - 1) * q) / 100, lo = Math.floor(pos), hi = Math.ceil(pos);
    return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
  }

  /** {p10, p25, p50, p75, p90, mean, n} of the non-null values (n = valid members) */
  function stats(values) {
    const v = values.filter((x) => x !== null && x !== undefined && Number.isFinite(x)).sort((a, b) => a - b);
    return { p10: quantile(v, 10), p25: quantile(v, 25), p50: quantile(v, 50), p75: quantile(v, 75), p90: quantile(v, 90),
      mean: v.length ? v.reduce((s, x) => s + x, 0) / v.length : null, n: v.length };
  }

  /** members still at or above `thr` (in) and the number of valid members */
  function share(values, thr) {
    const v = values.filter((x) => x !== null && x !== undefined && Number.isFinite(x));
    return { k: v.filter((x) => x >= thr - 1e-9).length, n: v.length };
  }

  /**
   * doc: a data/ecmwf/<area>.json; mode "liquid" (tp, inches of liquid) or "snow" (sf, snowfall water equivalent x NBM's median snow ratio);
   * t0Ms: common start; ratio/ratioTimes: NBM's median snow ratio series (snow mode only; the caller disables snow mode when it is missing).
   * -> {x: [ms], members: [[in per x]], hres: [in per x] | null, t0}; the series start at t0 (0 there) and are never negative.
   */
  function build(doc, { mode = "liquid", t0Ms, ratio = [], ratioTimes = [] }) {
    const initMs = Date.parse(doc.init);
    const xs = doc.hours.map((h) => initMs + h * HOUR);
    const field = mode === "snow" ? doc.sf : doc.tp;
    const n = doc.n_members;
    const ratioAt = (t) => {
      let best = null, bd = Infinity;
      ratioTimes.forEach((ms, i) => { const d = Math.abs(ms - t); if (d < bd && ratio[i]) { bd = d; best = ratio[i]; } });
      return best ?? 0;
    };
    const rebased = (cumTenths) => {                              // one cumulative series (0.1 mm) -> inches since t0, or null
      const cum = cumTenths.map(toIn);
      const base = MultiModel.interpAt(xs, cum, t0Ms);
      if (base === null) return null;
      const pts = xs.map((x, i) => [x, cum[i] === null ? null : Math.max(0, cum[i] - base)]).filter(([x, y]) => x >= t0Ms && y !== null);
      if (!pts.length) return null;
      if (pts[0][0] > t0Ms) pts.unshift([t0Ms, 0]);
      if (mode === "snow") {                                      // sf is already snow: water-equivalent increments x NBM's ratio
        let acc = 0;
        return pts.map(([x, y], i) => { if (i === 0) return [x, 0]; acc += Math.max(0, y - pts[i - 1][1]) * ratioAt((x + pts[i - 1][0]) / 2); return [x, acc]; });
      }
      return pts;
    };
    const grid = new Map();                                       // x (ms) -> column index
    const per = [];
    for (let k = 0; k < n; k++) per.push(rebased(field.map((row) => row[k])));
    const hres = doc[mode === "snow" ? "hres_sf" : "hres_tp"] ? rebased(doc[mode === "snow" ? "hres_sf" : "hres_tp"]) : null;
    const allX = [...new Set([...per.flatMap((p) => (p ? p.map((q) => q[0]) : [])), ...(hres ? hres.map((q) => q[0]) : [])])].sort((a, b) => a - b);
    allX.forEach((x, i) => grid.set(x, i));
    const col = (p) => { if (!p) return null; const out = new Array(allX.length).fill(null); p.forEach(([x, y]) => { out[grid.get(x)] = y; }); return out; };
    return { x: allX, members: per.map(col).filter(Boolean), hres: col(hres), t0: t0Ms, n };
  }

  /** per-x statistics of a build() result */
  function summarize(b) {
    return b.x.map((_, i) => stats(b.members.map((m) => m[i])));
  }

  /** value of a per-x series at t0 + h hours (exact grid hit or linear between neighbours), null outside */
  const at = (b, series, h) => MultiModel.interpAt(b.x, series, b.t0 + h * HOUR);

  /** headline sentence (also the chart's aria-label). h = the window end used (hours after the common start). */
  function headline(b, st, { mode, h, thr, weekday }) {
    const i = b.x.findIndex((x) => x >= b.t0 + h * HOUR - 1);
    if (i < 0) return "ECMWF ensemble: not enough forecast hours after the common start.";
    const s = st[i], vals = b.members.map((m) => m[i]);
    const f = (v) => (v === null ? "–" : v.toFixed(2));
    const unit = mode === "snow" ? "in of snow at NBM's ratio" : "in of liquid precipitation";
    const sh = share(vals, thr);
    return `ECMWF ensemble (${s.n} members): median ${f(s.p50)} ${unit} by ${weekday}; 25–75% ${f(s.p25)}–${f(s.p75)}; ${sh.k} of ${sh.n} members above ${thr} in.`;
  }

  /** table rows: percentiles at 24 h marks, then the member-share rows ("N of n members") */
  function tableRows(b, st, { mode, fmtTime, windows = [24, 72, 168], thresholds }) {
    const f = (v) => (v === null || v === undefined ? "–" : v.toFixed(2));
    const rows = [];
    for (let h = 24; h <= 240; h += 24) {
      const i = b.x.findIndex((x) => Math.abs(x - (b.t0 + h * HOUR)) < HOUR / 2);
      if (i < 0) continue;
      const s = st[i];
      rows.push([`+${h} h · ${fmtTime(b.x[i])}`, f(s.p10), f(s.p25), f(s.p50), f(s.p75), f(s.p90), f(s.mean), f(b.hres ? b.hres[i] : null)]);
    }
    for (const h of windows) {
      const i = b.x.findIndex((x) => Math.abs(x - (b.t0 + h * HOUR)) < HOUR / 2);
      if (i < 0) continue;
      const vals = b.members.map((m) => m[i]);
      for (const thr of thresholds) { const sh = share(vals, thr); rows.push([`+${h} h: at least ${thr} in`, `${sh.k} of ${sh.n} members`, "", "", "", "", "", ""]); }
    }
    return rows;
  }

  /** age of the run in hours and whether it is stale (older than staleHours) */
  const staleness = (doc, nowMs, staleHours = 24) => { const age = (nowMs - Date.parse(doc.init)) / HOUR; return { ageH: age, stale: age > staleHours }; };

  return { quantile, stats, share, build, summarize, at, headline, tableRows, staleness, toIn };
})();
