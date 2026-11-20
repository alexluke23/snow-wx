// Cookieless analytics abstraction (PLAN W5, dev18 Part 2c). SWITCHED OFF: config `analytics.enabled: false`. The owner chooses the provider; nothing here picks one.
//
// This file is NOT loaded at all while analytics is off: js/site-config.js (already on every page) reads `analytics` from data/meta.json and only injects this script
// when `enabled` is true, a provider is set AND the visitor has not opted out. So with the default config the site makes ZERO analytics requests (not even for this file).
//
// Rules (also on the privacy page): no cookies (nothing here reads or writes cookies or browser storage), no fingerprinting (no device or browser probing), no personal data
// (events carry only a name from a fixed list and a "where" label), Do Not Track and Global Privacy Control are honoured (an opted-out visitor gets nothing injected).
//
// Providers (config analytics.provider): "plausible" (script + data-domain = site_id), "goatcounter" (site_id = the code in CODE.goatcounter.com, or a full /count URL),
// "cloudflare" (Web Analytics beacon, site_id = the beacon token; it has NO custom events, so events are ignored for it). `script_url` overrides the provider's script
// address (self-hosting). Events (PLAN W5): favorite_added, install, signup, alert_created, avalanche_click, table_view.
// Any element with data-track="<event>" fires that event when clicked (avalanche-center links, "view as table").
// eslint-disable-next-line no-unused-vars
const SnowWxAnalytics = (() => {
  const EVENTS = ["favorite_added", "install", "signup", "alert_created", "avalanche_click", "table_view"];
  const WHERE = ["area", "finder", "mine", "map", "pwa", "about"];
  const KIND = ["ski", "snotel", "snopark"];
  const PROVIDERS = {
    plausible: { script: "https://plausible.io/js/script.js", attrs: (id) => ({ "data-domain": id, defer: "" }), events: true },
    goatcounter: { script: "https://gc.zgo.at/count.js", attrs: (id) => ({ "data-goatcounter": /^https:\/\//.test(id) ? id : `https://${id}.goatcounter.com/count`, async: "" }), events: true },
    cloudflare: { script: "https://static.cloudflareinsights.com/beacon.min.js", attrs: (id) => ({ "data-cf-beacon": JSON.stringify({ token: id }), defer: "" }), events: false },
  };

  /** Do Not Track / Global Privacy Control: true = the visitor opted out, so nothing is loaded and nothing is sent */
  function optedOut(nav = typeof navigator !== "undefined" ? navigator : {}, win = typeof window !== "undefined" ? window : {}) {
    return nav.doNotTrack === "1" || nav.doNotTrack === "yes" || win.doNotTrack === "1" || nav.msDoNotTrack === "1" || nav.globalPrivacyControl === true;
  }

  /** only a fixed vocabulary leaves the page: an allowed `where` / `kind` label, nothing else (no ids, no names, no text) */
  function sanitize(props) {
    const out = {};
    if (props && WHERE.includes(props.where)) out.where = props.where;
    if (props && KIND.includes(props.kind)) out.kind = props.kind;
    return out;
  }

  /** the script element to add for a config, or null when analytics must not run (disabled, no/unknown provider, no site id, opted out, non-https script) */
  function plan(cfg, nav, win) {
    if (!cfg || cfg.enabled !== true) return null;
    const p = PROVIDERS[cfg.provider];
    if (!p || !cfg.site_id || optedOut(nav, win)) return null;
    const src = cfg.script_url || p.script;
    if (!/^https:\/\//.test(src)) return null;
    return { src, attrs: p.attrs(String(cfg.site_id)), events: p.events, provider: cfg.provider };
  }

  let active = null, ready = false;
  const pending = [];

  function send(name, props) {
    if (!active || !active.events || !EVENTS.includes(name)) return false;
    const pr = sanitize(props);
    try {
      if (active.provider === "plausible") { window.plausible = window.plausible || function () { (window.plausible.q = window.plausible.q || []).push(arguments); }; window.plausible(name, Object.keys(pr).length ? { props: pr } : undefined); return true; }
      if (active.provider === "goatcounter") { if (window.goatcounter && window.goatcounter.count) { window.goatcounter.count({ path: `event/${name}${pr.where ? `/${pr.where}` : ""}`, title: name, event: true }); return true; } return false; }
    } catch { /* analytics must never break the page */ }
    return false;
  }

  /** start with a config (from meta.json) and the events queued so far; returns true when a provider script was injected */
  function init(cfg, queued = []) {
    const p = plan(cfg);
    if (!p) { active = null; return false; }
    active = p;
    const s = document.createElement("script");
    s.src = p.src;
    for (const [k, v] of Object.entries(p.attrs)) s.setAttribute(k, v);
    s.referrerPolicy = "strict-origin-when-cross-origin";
    s.addEventListener("load", () => { ready = true; for (const [n, pr] of pending.splice(0)) send(n, pr); });
    document.head.appendChild(s);
    for (const [n, pr] of queued) track(n, pr);
    document.addEventListener("click", (e) => {
      const el = e.target && e.target.closest ? e.target.closest("[data-track]") : null;
      if (el) track(el.getAttribute("data-track"), { where: document.body.dataset.where || undefined });
    }, { capture: true });
    return true;
  }

  function track(name, props) {
    if (!active) return false;
    if (!ready && active.provider === "goatcounter") { if (EVENTS.includes(name) && pending.length < 30) pending.push([name, props]); return false; }
    return send(name, props);
  }

  return { EVENTS, PROVIDERS, optedOut, sanitize, plan, init, track, active: () => active };
})();
