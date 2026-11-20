// about.html scorecard (dev18 Part 3): shown only when data/meta.json says verification_ui.enabled (default false: the section stays hidden and nothing else is fetched).
(() => {
  const sec = document.getElementById("scorecard");
  if (!sec || typeof VerificationUI === "undefined") return;
  const BASE = (() => { try { return new URL("../", document.currentScript.src).href; } catch { return ""; } })();
  const get = (u) => fetch(`${BASE}${u}`, { cache: "no-cache" }).then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); });
  get("data/meta.json").catch(() => ({})).then(async (meta) => {
    if (!meta?.verification_ui?.enabled) return;
    sec.hidden = false;
    const body = document.getElementById("scorecard-body");
    try { body.innerHTML = VerificationUI.scorecardHtml(await get(`${VerificationUI.BASE}verification.json`)); } catch { body.innerHTML = `<p class="hint">Verification results are not available yet.</p>`; }
  });
})();
