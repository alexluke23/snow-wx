// Pure helpers for charts whose values mean something only in stretches (dev22: the snow-ratio chart is drawn only where precipitation is likely).
// Plain script defining `Segments`; no DOM, tested with Node (tests/test_segments_js.py).
const Segments = (() => {
  /** contiguous runs of truthy values in `mask` as [first, last] index pairs (inclusive); a single point is a run [i, i] */
  function runs(mask) {
    const out = [];
    let a = -1;
    for (let i = 0; i < mask.length; i++) {
      if (mask[i] && a < 0) a = i;
      if (a >= 0 && (!mask[i] || i === mask.length - 1)) { out.push([a, mask[i] ? i : i - 1]); a = -1; }
    }
    return out;
  }
  /** the complement: contiguous runs where `mask` is falsy */
  const gapRuns = (mask) => runs(mask.map((m) => !m));
  /** ONE closed polygon for the band over run [a, b]: along `hi` forward, back along `lo`. Never reaches outside the run (so nothing is bridged). */
  function polygon(xs, lo, hi, [a, b]) {
    const x = xs.slice(a, b + 1), top = hi.slice(a, b + 1), bot = lo.slice(a, b + 1);
    return { x: [...x, ...x.slice().reverse()], y: [...top, ...bot.slice().reverse()] };
  }
  /** indices inside the mask where the median falls outside the likely range (data is never altered; the chart logs the count) */
  function outside(p25, p50, p75, mask) {
    const bad = [];
    for (let i = 0; i < p50.length; i++) {
      if (mask[i] && p25[i] !== null && p25[i] !== undefined && p75[i] !== null && p75[i] !== undefined && p50[i] !== null && p50[i] !== undefined
        && (p50[i] < p25[i] || p50[i] > p75[i])) bad.push(i);
    }
    return bad;
  }
  return { runs, gapRuns, polygon, outside };
})();
