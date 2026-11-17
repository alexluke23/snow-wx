// SNOTEL outage wording, shared by the obs map and the area pages (fix-snotel). The pipeline writes the
// state into meta.json (sources.snotel): fresh, stale (previous good copy, ORIGINAL timestamps, younger than
// max_age_hours) or unavailable. Old values are never shown as current.
/* exported snotelStatus */
function snotelStatus(meta) {
  const s = meta && meta.sources && meta.sources.snotel;
  if (!s) return { state: "unknown", text: "" };
  const fmt = (iso) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? "" : d.toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "numeric", timeZoneName: "short" });
  };
  const day = (iso) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
  };
  if (s.ok && !s.carried_stale) return { state: "ok", text: "" };
  if (s.ok) return { state: "ok", text: `${s.carried_stale} SNOTEL stations could not be refreshed and show their last observation (greyed).` };
  const down = "The NRCS SNOTEL data service is not responding; forecasts and the other observations are unaffected.";
  if (s.stale) {
    const h = Math.max(1, Math.round(s.age_h));
    return { state: "stale", ageH: s.age_h,
      text: `SNOTEL observations are ${h} h old (last observed ${fmt(s.observed_through)}). ${down}` };
  }
  const since = s.last_observed || s.last_success_at || s.outage_since;
  return { state: "unavailable",
    text: `SNOTEL observations unavailable${since ? ` since ${day(since)}` : ""}. ${down}` };
}
