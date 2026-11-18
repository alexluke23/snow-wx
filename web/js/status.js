// Public data-status page (status.html, W5): reads data/meta.json (per-source status + the monitoring limits written by the
// pipeline). Plain script, no dependencies, no cookies or storage. Mirrors pipeline/monitor.py `evaluate` (failures + age).
(() => {
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const NAMES = { snotel: "SNOTEL snow observations", asos: "Airport weather stations (ASOS/AWOS)", alerts: "NWS alerts", afd: "NWS forecast discussions",
    avalanche: "Avalanche danger ratings", hazards: "NWS winter hazards layer", points: "NBM point forecasts (ski areas, Sno-Parks, SNOTEL)",
    ndfd: "NWS official forecast (NDFD)", models: "Model maps (HRRR, RRFS, GFS)", nohrsc: "NOHRSC snowfall analysis" };
  const ORDER = ["points", "ndfd", "snotel", "asos", "alerts", "hazards", "avalanche", "afd", "models", "nohrsc"];
  const hoursSince = (iso, now) => { const t = Date.parse(iso || ""); return Number.isFinite(t) ? Math.max(0, (now - t) / 3.6e6) : null; };
  const ageText = (h) => (h === null ? "–" : h < 1 ? "under 1 h" : h < 48 ? `${Math.round(h)} h` : `${Math.round(h / 24)} days`);
  const when = (iso) => { const d = new Date(iso); return Number.isNaN(d.getTime()) ? "–" : d.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", timeZoneName: "short" }); };

  /** {state: ok | late | none, why} for one source, with the same rules as the monitor. */
  function judge(e, lim, now) {
    if (!e || typeof e !== "object") return { state: "none", why: "no status reported yet" };
    const why = [];
    const fails = Number(e.consecutive_failures || 0);
    if (lim?.max_failures && fails >= lim.max_failures) why.push(`failed ${fails} runs in a row (limit ${lim.max_failures})`);
    const ref = e.last_success_at || (e.ok ? e.at : null);
    const age = hoursSince(ref, now);
    if (age !== null && lim?.max_age_hours && age > lim.max_age_hours) why.push(`last success ${ageText(age)} ago (limit ${lim.max_age_hours} h)`);
    if (e.unavailable) why.push(`unavailable${e.last_observed ? ` since ${when(e.last_observed)}` : ""}`);
    else if (e.stale) why.push(`showing the last good copy, ${ageText(e.age_h ?? null)} old`);
    if (e.ok === false && !e.last_success_at && !why.length) why.push(e.error ? `missing: ${e.error}` : "no data");
    return { state: why.length ? "late" : lim ? "ok" : "nolimit", why: why.join("; "), age, ref };       // no limit known: shown, never called OK
  }

  function render(meta) {
    const now = Date.now();
    const lims = meta.monitoring?.sources || {};
    const src = meta.sources || {};
    const names = [...ORDER.filter((n) => n in src || n in lims), ...Object.keys(src).filter((n) => !ORDER.includes(n))];
    const g = hoursSince(meta.generated_at, now);
    const banner = $("st-banner");
    if (g === null || g > 3) {
      banner.hidden = false;
      banner.textContent = g === null ? "This status file has no timestamp, so it cannot be trusted."
        : `This status file is ${ageText(g)} old: the site itself may not have updated recently (GitHub's schedule is best-effort).`;
    }
    const rows = names.map((n) => {
      const e = src[n], lim = lims[n], j = judge(e, lim, now);
      const label = { ok: "✓ OK", late: "⚠ Late", none: "– Not reported", nolimit: "• Reported" }[j.state];
      const limit = lim ? [lim.max_failures ? `${lim.max_failures} failed runs` : "", lim.max_age_hours ? `${lim.max_age_hours} h` : ""].filter(Boolean).join(" or ") : "–";
      const outage = e?.outage_since && !e.unavailable ? `outage since ${when(e.outage_since)}` : "";
      const detail = [e?.detail || (e?.count != null ? `${e.count} ${e.unit || "items"}` : ""), j.why, outage].filter(Boolean).join(" · ");
      return `<tr class="st-${j.state}"><th scope="row">${esc(NAMES[n] || n)}</th><td data-label="Status"><b class="st-badge">${label}</b></td>
        <td data-label="Last success">${j.ref ? esc(when(j.ref)) : "–"}</td><td data-label="Age">${esc(ageText(j.age ?? null))}</td><td data-label="Limit">${esc(limit)}</td><td data-label="Detail">${esc(detail) || "–"}</td></tr>`;
    });
    $("st-table").innerHTML = `<div class="tbl-wrap"><table class="st-tbl"><caption class="sr">Last successful update and health of each data source</caption>
      <thead><tr><th scope="col">Source</th><th scope="col">Status</th><th scope="col">Last success</th><th scope="col">Age</th><th scope="col">Limit</th><th scope="col">Detail</th></tr></thead>
      <tbody>${rows.join("")}</tbody></table></div>`;
    const bad = names.filter((n) => judge(src[n], lims[n], now).state === "late").length;
    $("st-foot").textContent = `Status file written ${when(meta.generated_at)} (${ageText(g)} ago). ${bad ? `${bad} source${bad === 1 ? "" : "s"} late.` : (names.some((n) => judge(src[n], lims[n], now).state === "nolimit") ? "Limits are not published in this status file yet, so ages are shown without a verdict." : "All reported sources are inside their limits.")}`;
  }

  fetch("data/meta.json", { cache: "no-cache" })
    .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
    .then(render)
    .catch((e) => {
      $("st-table").innerHTML = `<p class="snotel-note" role="status">The status file (data/meta.json) could not be read (${esc(e.message)}). The site may be updating or temporarily unavailable; try again in a few minutes.</p>`;
    });
})();
