// Freshness of a model run (dev22 Part 4). Pure, no DOM; plain script defining `Freshness` (tests: tests/test_freshness_js.py, frozen clocks).
//
// Three states, judged against WHEN THE NEXT RUN IS DUE, never against a fixed age:
//   latest       no newer run is due yet (now < init + period + lag): this is the newest run that can exist.
//   late         a newer run is due (it should be on the mirror) but we are still inside the grace window that our scheduled fetches need to deliver it.
//   out-of-date  a newer run should exist and we failed to get it (now >= due + grace).
// `lag` = how long after its nominal time a cycle is complete on the mirror (MEASURED from S3 Last-Modified of the last file of 17 cycles, Nov 12-20 2026: ECMWF ENS +7.75 h,
// HRES +7.57 h, GEFS +5.5 to +5.65 h); `grace` covers the retry attempts and GitHub's late or dropped cron events (see docs/specs/multi-model.md).
const Freshness = (() => {
  const HOUR = 3.6e6;
  const SOURCES = {
    ecmwf: { name: "ECMWF", periodH: 12, lagH: 7.75, graceH: 3 },        // IFS HRES, IFS ENS and AIFS ride on the same 00Z / 12Z cycle
    gefs: { name: "GEFS", periodH: 12, lagH: 5.65, graceH: 3 },
  };
  /** -> {state, dueMs (when the next run is/was due), pastDue (how many cycles should be newer than this run)} */
  function state(initMs, nowMs, src) {
    const s = typeof src === "string" ? SOURCES[src] : src;
    const due = initMs + (s.periodH + s.lagH) * HOUR;
    if (!(nowMs >= due)) return { state: "latest", dueMs: due, pastDue: 0 };
    const pastDue = 1 + Math.floor((nowMs - due) / (s.periodH * HOUR));
    return { state: nowMs < due + s.graceH * HOUR ? "late" : "out-of-date", dueMs: due, pastDue };
  }
  const utc = (ms) => `${new Date(ms).toISOString().slice(11, 16)} UTC`;
  /** the words for the badge / footer; `localFmt` (optional) renders a local time for the due moment */
  function words(st, { init, label = "run", localFmt } = {}) {
    const at = (localFmt ? `${localFmt(st.dueMs)} (${utc(st.dueMs)})` : utc(st.dueMs));
    if (st.state === "latest") return { text: `latest ${label}`, long: `Latest ${label}; the next one is expected at about ${at}.`, cls: "ok" };
    if (st.state === "late") return { text: `late: newer ${label} expected about ${at}, not yet available here`, long: `A newer ${label} was due at about ${at} and is not available here yet (we keep trying for a few hours).`, cls: "late" };
    return { text: `out of date: a newer ${label} should exist (due about ${at})`, long: `Out of date: a newer ${label} should exist (due at about ${at}${st.pastDue > 1 ? `, ${st.pastDue} cycles ago` : ""}) and we have not received it.`, cls: "stale" };
  }
  return { SOURCES, state, words, utc };
})();
