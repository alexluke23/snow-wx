// Site settings the pages need from config/settings.yml, delivered through data/meta.json (`site`): today only the feedback
// address (site.feedback_email). NO e-mail address is hard-coded in any page or script: every mailto link is written as
//   <a data-mailto data-subject="..." data-body="..." hidden>   (optionally inside <span data-mailto-wrap hidden>)
// and this script fills in the href once the address is known. No address configured = those links stay hidden.
// Plain script, no dependencies, no storage.
// eslint-disable-next-line no-unused-vars
const SiteConfig = (() => {
  let cfg = null;
  // meta.json is loaded from the site base path = the folder above this script (js/site-config.js), i.e. config site.base_path:
  // nested pages (W2: /ski/<state>/<id>/) include the script as "<base_path>/js/site-config.js", so the URL stays right there.
  const BASE = (() => { try { return new URL("../", document.currentScript.src).href; } catch { return ""; } })();
  const load = () => (cfg ||= fetch(`${BASE}data/meta.json`, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : {})).then((m) => m.site || {}).catch(() => ({})));
  const wire = async (root = document) => {
    const links = [...root.querySelectorAll("a[data-mailto]")].filter((a) => !a.dataset.wired);
    if (!links.length) return;
    const email = String((await load()).feedback_email || "").trim();
    for (const a of links) {
      a.dataset.wired = "1";
      if (!email) continue;                                  // not configured: hidden, never a default address
      const q = [];
      if (a.dataset.subject) q.push(`subject=${encodeURIComponent(a.dataset.subject)}`);
      if (a.dataset.body) q.push(`body=${encodeURIComponent(a.dataset.body)}`);
      a.href = `mailto:${email}${q.length ? `?${q.join("&")}` : ""}`;
      a.hidden = false;
      const wrap = a.closest("[data-mailto-wrap]");
      if (wrap) wrap.hidden = false;
    }
  };
  /** a page that already fetched meta.json (the obs map) hands it over: no second request */
  const provide = (meta) => { cfg = Promise.resolve((meta && meta.site) || {}); };
  const idle = (fn) => ("requestIdleCallback" in window ? requestIdleCallback(fn, { timeout: 4000 }) : setTimeout(fn, 1500));
  const start = () => {
    idle(() => wire());                                      // never competes with the first paint
    if (document.getElementById("map")) return;              // the obs map adds no mailto links after load: no observer there
    let timer = 0;                                           // debounced: page scripts add many nodes in bursts
    new MutationObserver(() => { clearTimeout(timer); timer = setTimeout(() => wire(), 200); }).observe(document.body, { childList: true, subtree: true });
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start); else start();
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  /** attribute string for a link that becomes a mailto once the address is known: `<a ${SiteConfig.attrs(subject, body)}>text</a>` */
  const attrs = (subject, body = "") => `data-mailto data-subject="${esc(subject)}" data-body="${esc(body)}" hidden`;
  return { load, wire, attrs, provide, feedbackEmail: async () => String((await load()).feedback_email || "").trim() };
})();
