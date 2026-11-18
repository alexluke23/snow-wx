// Daily Snow summary helpers shared by the area page, Finder and My mountains (W3, docs/specs/daily-summaries.md §5.7).
// The stored summary (points file / summary.json) never contains alerts: an ACTIVE winter-relevant NWS alert (from the live
// alerts/index.json) outranks every stored summary and is applied here, client-side (owner Nov 17).
// eslint-disable-next-line no-unused-vars
const SnowSummary = (() => {
  const active = (refs) => (refs || []).filter((r) => r.relevant !== false && (!r.ends || new Date(r.ends).getTime() > Date.now()));
  /** {tag, sentence, bullets, ...} with the alert tag on top when an active relevant alert exists; the stored headline then becomes a bullet. */
  function withAlerts(sm, refs) {
    const act = active(refs);
    if (!act.length) return sm || null;
    const names = [...new Set(act.map((r) => r.event))].join(", ");
    return { ...(sm || {}), tag: "Alert active", alert: true, confidence: sm?.confidence || "high",
      sentence: `NWS alert in effect: ${names}. See the alert and your local avalanche center.`,
      bullets: [...(sm?.sentence ? [sm.sentence] : []), ...(sm?.bullets || [])].slice(0, 3) };
  }
  return { active, withAlerts };
})();
