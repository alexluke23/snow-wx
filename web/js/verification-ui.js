// M9 verification panel (dev18 Part 3): "How did forecasts do here?" on the area page and the regional scorecard on about.html.
// BUILT BEHIND config verification_ui.enabled (default false, never enabled by a dev session): while the flag is off the pages show nothing and never fetch models/verify/verification*.json.
// Reads what the daily verification job writes (dev21: .github/workflows/verify.yml -> `pipeline verify-ci` -> verify-*.tar, which update-site extracts into build/models/verify/):
// models/verify/verification.json (counts per SNOTEL site + the scorecard) and, only for sites that meet the minimum
// (default >= 14 observation days AND >= 30 forecast/observation pairs, configurable), models/verify/verification/<site>.json (metrics + a daily series).
// Honest by construction: below the minimum it says "Collecting data: X of 14 days" and shows no numbers; the observation is the 24-h SNOTEL depth change, a LOWER BOUND of snowfall.
// Pure functions here (tested with Node); drawing helpers use the shared chart theme (js/charts/theme.js, DESIGN §6-B).
// eslint-disable-next-line no-unused-vars
const VerificationUI = (() => {
  const BASE = "models/verify/";            // dev21: where update-site extracts the verify product tar
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const f1 = (v) => (v === null || v === undefined ? "–" : (Math.round(v * 100) / 100).toFixed(2));
  const pct = (v) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`);

  /** {state: "none" | "collecting" | "ready", d, n} for one SNOTEL site from data/verification.json */
  function status(index, triplet) {
    const min = { days: index?.min_days ?? 14, pairs: index?.min_pairs ?? 30 };
    const st = index?.stations?.[triplet];
    if (!st) return { state: "none", d: 0, n: 0, min };
    return { state: st.ready ? "ready" : "collecting", d: st.d, n: st.n, min };
  }

  /** "Collecting data: 6 of 14 days" (+ the pairs when those are what is missing): shown instead of any result */
  function collecting(s) {
    const pairs = s.n < s.min.pairs ? `; ${s.n} of ${s.min.pairs} forecast pairs` : "";
    return `Collecting data: ${s.d} of ${s.min.days} days${pairs}. Results appear here once there are at least ${s.min.days} observation days and ${s.min.pairs} forecast pairs at this site.`;
  }

  const lead = (m, what) => {
    if (!m) return "";
    const dir = m.bias_in >= 0.005 ? `${f1(m.bias_in)} in above` : m.bias_in <= -0.005 ? `${f1(-m.bias_in)} in below` : "about equal to";
    const hit = m.events_1 ? `, and caught ${pct(m.hit_1)} of the ${m.events_1} days with at least 1 in` : "";
    return `${what} ran ${dir} the observed snow-depth gain on average (typical error ${f1(m.mae_in)} in)${hit}`;
  };

  /** the one-sentence summary above the chart (also its aria-label). `where`: {name, proxy: bool, distKm} */
  function sentence(doc, where) {
    const nbm = doc.metrics?.["NBM expected"];
    const place = where.proxy ? `${where.name} (the SNOTEL site nearest this ski area${where.distKm != null ? `, ${where.distKm} km away` : ""})` : where.name;
    return `At ${place}, over ${doc.d} days and ${doc.n} forecasts issued up to 48 h ahead: ${lead(nbm, "NBM's expected 24-h snowfall")}. Depth change is a lower bound of snowfall, so a small positive bias is expected.`;
  }

  /** table: one row per forecast source in the file (NBM only since dev23) (bias, MAE, hit rate for >= 1 in) */
  function metricRows(doc) {
    return Object.entries(doc.metrics || {}).map(([src, m]) => [src, String(m.n), f1(m.bias_in), f1(m.mae_in), m.events_1 ? `${pct(m.hit_1)} of ${m.events_1}` : "no day with 1 in or more"]);
  }
  const METRIC_COLS = ["Forecast", "Days scored", "Bias (in)", "Mean abs. error (in)", "Hit rate, 1 in or more"];

  /** the daily table behind the chart: observed vs NBM, 24-h snow in inches */
  function dailyRows(doc) {
    const d = doc.daily;
    return d.dates.map((day, i) => [day, f1(d.obs[i]), f1(d.nbm[i])]);
  }

  /** the caveats shown under every result (plain words, never an accuracy claim) */
  function caveats(doc, where, index) {
    const out = [
      "Observed snow is the 24-hour change in SNOTEL snow depth. That is a lower bound for snowfall (settling, melt and wind take snow away), so a forecast above it is not necessarily wrong.",
      `Sample size: ${doc.n} forecasts over ${doc.d} days at one site (${doc.span?.[0] ?? "?"} to ${doc.span?.[1] ?? "?"}); a few storms dominate, so treat these as a first look, not an accuracy rating.`,
    ];
    const ex = index?.outage_excluded;
    out.push(`Observations from the NRCS SNOTEL outage${ex ? ` (${String(ex[0]).slice(0, 10)} to ${String(ex[1]).slice(0, 10)})` : ""} and stale or patchy station reports are left out.`);
    if (where.proxy) out.push(`This is the nearest SNOTEL site${where.distKm != null ? ` (${where.distKm} km away${where.dz != null ? `, ${Math.abs(where.dz).toLocaleString()} ft ${where.dz >= 0 ? "higher" : "lower"} than the base` : ""})` : ""}, not the ski area itself.`);
    return out;
  }

  /** regional scorecard HTML for about.html (hidden until the minimum is met) */
  function scorecardHtml(index) {
    const sc = index?.scorecard;
    if (!sc) return `<p>No verification results have been published yet.</p>`;
    if (!sc.ready) return `<p><b>Collecting data:</b> ${sc.days} of ${index.min_days} days, ${sc.pairs} of ${index.min_pairs} forecast pairs. Results appear here once both minimums are met.</p>`;
    const rows = sc.rows.map((r) => `<tr><th scope="row">${esc(r.source)}</th><td>${r.n}</td><td>${f1(r.bias_in)}</td><td>${f1(r.mae_in)}</td><td>${r.events_1 ? `${pct(r.hit_1)} of ${r.events_1}` : "–"}</td></tr>`).join("");
    return `<p class="lead">All SNOTEL sites, ${index.span?.[0] ?? ""} to ${index.span?.[1] ?? ""} (${sc.days} days, ${sc.pairs} forecast pairs), forecasts issued up to 48 h before the 24-hour window ends.</p>
      <div class="tbl-wrap"><table class="st-tbl"><caption class="sr">Forecast verification against SNOTEL snow-depth change</caption>
        <thead><tr>${METRIC_COLS.map((c) => `<th scope="col">${esc(c)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div>`;
  }

  return { BASE, status, collecting, sentence, metricRows, METRIC_COLS, dailyRows, caveats, scorecardHtml, esc };
})();
