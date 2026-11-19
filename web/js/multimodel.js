// Precipitation by model (M7, docs/specs/multi-model.md): pure functions for the area page (area.js draws the chart).
// Data: data/multimodel.json (pipeline/models/multimodel.py: HRRR / RRFS / GFS run-total liquid precipitation in inches at the summit, each
// cumulative since its OWN init, with the model's terrain height there) and the NBM series from the area's points file.
// Nothing here sums percentiles; series are cumulative liquid amounts aligned to a common start by linear interpolation.
// eslint-disable-next-line no-unused-vars
const MultiModel = (() => {
  const ms = (iso) => Date.parse(iso);
  const HOUR = 3.6e6;

  /** value of the piecewise-linear series (xs ascending, ys with nulls) at x, or null outside the non-null range */
  function interpAt(xs, ys, x) {
    let prev = null;
    for (let i = 0; i < xs.length; i++) {
      if (ys[i] === null || ys[i] === undefined) continue;
      if (xs[i] === x) return ys[i];
      if (xs[i] > x) return prev && prev[0] <= x ? prev[1] + (ys[i] - prev[1]) * (x - prev[0]) / (xs[i] - prev[0]) : null;
      prev = [xs[i], ys[i]];
    }
    return null;
  }

  /** liquid since t0 for a cumulative-since-init series; mirrors pipeline/models/multimodel.py `rebase` (tested against it) */
  function rebase(initMs, hours, q, t0Ms) {
    const xs = hours.map((h) => initMs + h * HOUR);
    const base = interpAt(xs, q, t0Ms);
    if (base === null) return null;
    return q.map((v) => (v === null || v === undefined ? null : Math.round((v - base) * 1000) / 1000));
  }

  /** NBM cumulative liquid and snow (in) at the end of each precipitation window of the points file, from 0 at the issue time */
  function nbmCumulative(precip, initMs) {
    const x = [initMs], liquid = [0], snow = [0];
    let l = 0, s = 0;
    (precip?.end || []).forEach((e, i) => {
      l += precip.qpf_in[i] ?? 0; s += precip.snow_in[i] ?? 0;
      x.push(ms(e)); liquid.push(Math.round(l * 1000) / 1000); snow.push(Math.round(s * 1000) / 1000);
    });
    return { x, liquid, snow };
  }

  /**
   * opts: {doc (multimodel.json), areaId, nbm: {initMs, precip, times: [iso], ratio: [..], psnow: [..]}, mode: "liquid" | "snow"}
   * -> {t0, series: [{key, label, x: [ms], y: [in], z (model terrain ft) | null, init}], agreement}
   * mode "snow" converts each model's liquid increments with NBM's median snow ratio and NBM's chance of snow at the point
   * ("inches assume NBM SLR"); the NBM line is NBM's own expected snowfall.
   */
  function build({ doc, areaId, nbm, mode = "liquid" }) {
    const liquid = buildOne({ doc, areaId, nbm, mode: "liquid" });
    if (mode !== "snow") return liquid;
    return { ...liquid, series: buildOne({ doc, areaId, nbm, mode: "snow" }).series };        // the badge always comes from the liquid series
  }
  function buildOne({ doc, areaId, nbm, mode }) {
    const nb = nbmCumulative(nbm.precip, nbm.initMs);
    const per = [];
    for (const m of doc?.models || []) {
      const a = doc.areas?.[areaId]?.[m.model];
      if (a) per.push({ key: m.model, label: m.label, initMs: ms(m.init), hours: m.hours, q: a.q, z: a.z ?? null });
    }
    const t0 = Math.max(nbm.initMs, ...per.map((p) => p.initMs));
    const tms = (nbm.times || []).map(ms);
    const at = (arr, t) => { // nearest-in-time value of an hourly/3-hourly NBM series
      let best = null, bd = Infinity;
      tms.forEach((x, i) => { const d = Math.abs(x - t); if (d < bd && arr?.[i] !== null && arr?.[i] !== undefined) { bd = d; best = arr[i]; } });
      return best;
    };
    const series = [];
    // NBM
    const nbmY = mode === "snow" ? nb.snow : nb.liquid;
    const b0 = interpAt(nb.x, nbmY, t0);
    if (b0 !== null) {
      const xs = nb.x.filter((x) => x >= t0), ys = nb.x.map((x, i) => [x, nbmY[i]]).filter(([x]) => x >= t0).map(([, y]) => Math.round((y - b0) * 1000) / 1000);
      const first = nb.x[0] >= t0 ? [] : [[t0, 0]];
      series.push({ key: "nbm", label: "NBM", x: [...first.map((p) => p[0]), ...xs], y: [...first.map((p) => p[1]), ...ys], z: null, init: nbm.initMs });
    }
    for (const p of per) {
      const r = rebase(p.initMs, p.hours, p.q, t0);
      if (!r) continue;
      const pts = p.hours.map((h, i) => [p.initMs + h * HOUR, r[i]]).filter(([x, y]) => x >= t0 && y !== null);
      if (!pts.length) continue;
      if (pts[0][0] > t0) pts.unshift([t0, 0]);
      let ys = pts.map((q) => q[1]);
      if (mode === "snow") {                                   // liquid increments x NBM median ratio x NBM chance of snow
        let cum = 0;
        ys = pts.map(([x, y], i) => {
          if (i === 0) return 0;
          const mid = (x + pts[i - 1][0]) / 2, d = Math.max(0, y - pts[i - 1][1]);
          cum += d * (at(nbm.ratio, mid) ?? 0) * (at(nbm.psnow, mid) ?? 0);      // both series are required (the page disables the toggle without them)
          return Math.round(cum * 100) / 100;
        });
      }
      series.push({ key: p.key, label: p.label, x: pts.map((q) => q[0]), y: ys, z: p.z, init: p.initMs });
    }
    return { t0, series, agreement: mode === "liquid" ? agreement(series, t0) : null };
  }

  /** value of a built series at t0 + h hours (null if the series does not reach it) */
  const valueAt = (s, t0, h) => interpAt(s.x, s.y, t0 + h * HOUR);

  /**
   * Agreement badge (a HEURISTIC until verified; formula on about.html): over the longest window H in {72, 48, 36, 24, 12, 6} h after the common
   * start that at least 3 models reach, the share of models whose liquid total is within +-25% of the median total (or within 0.10 in when the
   * median is small). share >= 80% -> High, >= 66% -> Medium, else Low (dev17: was 75 / 50; with four sources 3 of 4 made 78% of areas High); a window where every model is under 0.10 in is "High (dry)".
   * Always computed from LIQUID amounts so the toggle does not change it.
   */
  function agreement(series, t0) {
    const liquid = series;
    for (const H of [72, 48, 36, 24, 12, 6]) {
      const totals = liquid.map((s) => [s.label, valueAt(s, t0, H)]).filter(([, v]) => v !== null);
      if (totals.length < 3) continue;
      const vals = totals.map((t) => t[1]).sort((a, b) => a - b);
      const med = vals.length % 2 ? vals[(vals.length - 1) / 2] : (vals[vals.length / 2 - 1] + vals[vals.length / 2]) / 2;
      if (vals.every((v) => v < 0.1)) return { H, n: totals.length, within: totals.length, median: med, label: "High", dry: true, totals };
      const tol = Math.max(0.25 * med, 0.1);
      const within = totals.filter(([, v]) => Math.abs(v - med) <= tol).length;
      const share = within / totals.length;
      return { H, n: totals.length, within, median: med, label: share >= 0.8 ? "High" : share >= 0.66 ? "Medium" : "Low", dry: false, totals };
    }
    return null;
  }

  return { interpAt, rebase, nbmCumulative, build, valueAt, agreement };
})();
