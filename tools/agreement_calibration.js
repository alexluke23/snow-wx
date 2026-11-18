// Agreement-badge distribution across all areas (dev17 Part 0e, docs/specs/multi-model.md). Runs the page's own web/js/multimodel.js over build/data/multimodel.json
// (or env CALIB_FILE) and build/data/points/*.json. Usage: SCRATCH=outdir node tools/agreement_calibration.js <label> [path-to-multimodel.js]
const fs = require("fs"), vm = require("vm"), path = require("path");
const ROOT = path.resolve(__dirname, "..");
const variant = process.argv[2] || "current";
const src = fs.readFileSync(process.argv[3] ? process.argv[3] : path.join(ROOT, "web/js/multimodel.js"), "utf8");
const ctx = {}; vm.createContext(ctx); vm.runInContext(src + "\nthis.MultiModel = MultiModel;", ctx);
const MM = ctx.MultiModel;
const doc = JSON.parse(fs.readFileSync(path.join(process.env.CALIB_FILE || (ROOT + "/build/data/multimodel.json")), "utf8"));
const ski = JSON.parse(fs.readFileSync(path.join(ROOT, "build/data/ski_areas.json"), "utf8")).areas;
const summit = Object.fromEntries(ski.map((a) => [a.id, a.summit.elev_ft]));
console.log("models:", doc.models.map((m) => `${m.label} ${m.init} f${m.hours[m.hours.length - 1]}`).join(" | "), "areas:", Object.keys(doc.areas).length);
const out = { High: 0, Medium: 0, Low: 0, none: 0, dry: 0 };
const rows = [];
for (const id of Object.keys(doc.areas)) {
  const f = path.join(ROOT, "build/data/points", id + ".json");
  if (!fs.existsSync(f)) { out.none++; continue; }
  const d = JSON.parse(fs.readFileSync(f, "utf8")), P = d.points.summit;
  const nbm = { initMs: Date.parse(d.issued), precip: P.precip, times: d.times, ratio: P.series.slr_p50 || P.series.slr, psnow: P.series.p_snow };
  const r = MM.build({ doc, areaId: id, nbm, mode: "liquid" });
  const ag = r.agreement;
  if (!ag) { out.none++; continue; }
  out[ag.label]++; if (ag.dry) out.dry++;
  const gaps = {};
  for (const m of doc.models) { const a = doc.areas[id][m.model]; if (a && a.z != null) gaps[m.label] = Math.round(a.z - summit[id]); }
  const maxGap = Math.max(0, ...Object.values(gaps).map(Math.abs));
  rows.push({ id, label: ag.label, dry: ag.dry, H: ag.H, n: ag.n, within: ag.within, median: ag.median, gaps, maxGap, totals: ag.totals });
}
const n = rows.length;
console.log(`[${variant}] areas scored ${n}, no badge ${out.none}`);
console.log(`High ${out.High} (${(100 * out.High / n).toFixed(0)}%)  Medium ${out.Medium} (${(100 * out.Medium / n).toFixed(0)}%)  Low ${out.Low} (${(100 * out.Low / n).toFixed(0)}%)   all-dry ${out.dry}`);
const wet = rows.filter((r) => !r.dry);
console.log(`wet areas ${wet.length}: High ${wet.filter((r) => r.label === "High").length} Medium ${wet.filter((r) => r.label === "Medium").length} Low ${wet.filter((r) => r.label === "Low").length}`);
const byH = {}; rows.forEach((r) => { byH[r.H] = (byH[r.H] || 0) + 1; }); console.log("window H used:", JSON.stringify(byH));
const bucket = (g) => (g < 500 ? "<500" : g < 1500 ? "500-1500" : g < 3000 ? "1500-3000" : ">=3000");
const tb = {};
for (const r of wet) { const b = bucket(r.maxGap); tb[b] = tb[b] || { High: 0, Medium: 0, Low: 0 }; tb[b][r.label]++; }
console.log("wet areas by largest |model terrain - summit| gap (ft):", JSON.stringify(tb));
// per model: terrain gap and how often it is the outlier (the only one outside tolerance)
const outl = {}, gapAbs = {};
for (const r of wet) {
  const tol = Math.max(0.25 * r.median, 0.1);
  for (const [l, v] of r.totals) { outl[l] = outl[l] || [0, 0]; outl[l][1]++; if (Math.abs(v - r.median) > tol) outl[l][0]++; (gapAbs[l] = gapAbs[l] || []).push(Math.abs(r.gaps[l] ?? 0)); }
}
for (const l of Object.keys(outl)) { const g = gapAbs[l].sort((a, b) => a - b); console.log(`  ${l}: outside tolerance in ${outl[l][0]} of ${outl[l][1]} wet areas; |terrain gap| median ${g[Math.floor(g.length / 2)]} ft, p90 ${g[Math.floor(g.length * 0.9)]} ft`); }
// does the terrain gap drive Low? correlation between label and the GFS/HRRR gap among wet areas
const lowGap = wet.filter((r) => r.label === "Low").map((r) => r.maxGap).sort((a, b) => a - b), hiGap = wet.filter((r) => r.label === "High").map((r) => r.maxGap).sort((a, b) => a - b);
const med = (a) => (a.length ? a[Math.floor(a.length / 2)] : null);
console.log(`median max gap: Low ${med(lowGap)} ft (n=${lowGap.length}), High ${med(hiGap)} ft (n=${hiGap.length})`);
fs.writeFileSync(path.join(process.env.SCRATCH || ".", `calib_${variant}.json`), JSON.stringify(rows));
// terrain effect: per model-area, outside-tolerance rate by |terrain gap| bucket (wet areas only)
{
  const b = { "<1000": [0, 0], "1000-2000": [0, 0], "2000-3000": [0, 0], ">=3000": [0, 0] };
  for (const r of wet) {
    const tol = Math.max(0.25 * r.median, 0.1);
    for (const [l, v] of r.totals) {
      if (l === "NBM") continue; const g = Math.abs(r.gaps[l] ?? 0), k = g < 1000 ? "<1000" : g < 2000 ? "1000-2000" : g < 3000 ? "2000-3000" : ">=3000";
      b[k][1]++; if (Math.abs(v - r.median) > tol) b[k][0]++;
    }
  }
  console.log("model-area pairs outside tolerance by |terrain gap| (ft):", Object.entries(b).map(([k, [o, n]]) => `${k}: ${o}/${n} (${n ? (100 * o / n).toFixed(0) : 0}%)`).join("  "));
  const lows = wet.filter((r) => r.label === "Low");
  let gapOut = 0;
  for (const r of lows) { const tol = Math.max(0.25 * r.median, 0.1); const outs = r.totals.filter(([, v]) => Math.abs(v - r.median) > tol).map(([l]) => l).filter((l) => l !== "NBM"); if (outs.some((l) => Math.abs(r.gaps[l] ?? 0) > 2000)) gapOut++; }
  console.log(`Low areas where a model outside tolerance sits > 2000 ft from the summit: ${gapOut} of ${lows.length}`);
}
