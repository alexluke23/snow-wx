// Offline-first PWA client (W4, docs/specs/pwa.md). INERT unless `python -m pipeline pwa` injected window.SNOWWX_PWA (config pwa.enabled,
// default false; never enable before the W1 domain move). Registers the service worker, shows the staleness banner (amber > 6 h, red
// > 24 h), the update prompt, the install coach and "Save for offline" on My mountains. Plain script, no dependencies; localStorage only
// for per-viewer conveniences (coach dismissed). Kill switch: add ?nopwa to any URL, or set config pwa.kill (build emits a self-removing worker).
(() => {
  const cfg = window.SNOWWX_PWA;
  if (!cfg) return;
  const LIMIT_MB = 25, FREE_FAVS = 5, AMBER_H = 6, RED_H = 24;
  const el = (tag, attrs = {}, text = "") => { const n = document.createElement(tag); Object.assign(n, attrs); if (text) n.textContent = text; return n; };
  const store = { get: (k) => { try { return localStorage.getItem(k); } catch { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } } };
  const favorites = () => { try { return JSON.parse(localStorage.getItem("snowwx.favorites")) || []; } catch { return []; } };
  const fmtAge = (h) => (h < 1 ? `${Math.max(1, Math.round(h * 60))} min` : h < 48 ? `${Math.floor(h)} h ${Math.round((h % 1) * 60)} min` : `${Math.round(h / 24)} days`);
  const fmtTime = (d) => d.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });

  // ---- kill switch (client side): ?nopwa unregisters everything and reloads without it
  if (/[?&]nopwa\b/.test(location.search)) {
    (async () => {
      for (const r of (await navigator.serviceWorker?.getRegistrations?.()) || []) await r.unregister();
      for (const k of (await window.caches?.keys?.()) || []) if (k.startsWith("snowwx-")) await caches.delete(k);
      location.replace(location.pathname + location.hash);
    })();
    return;
  }

  // ---- staleness banner: never present stale data as current
  const banner = el("div", { id: "pwa-banner", role: "status" });
  banner.hidden = true;
  async function updateBanner() {
    let generated = null;
    try {
      const r = await fetch(`${cfg.base}/data/meta.json`, { cache: "no-cache" });
      if (r.ok && !(await r.clone().json()).offline) generated = new Date((await r.json()).generated_at);
    } catch { /* offline */ }
    const offline = !navigator.onLine || generated === null;
    if (!generated) {                                          // offline and the SW has no cached meta: say so
      const c = await (window.caches ? caches.match(`${location.origin}${cfg.base}/data/meta.json`) : null);
      if (c) try { generated = new Date((await c.json()).generated_at); } catch { /* ignore */ }
    }
    const age = generated && !Number.isNaN(generated.getTime()) ? (Date.now() - generated.getTime()) / 3.6e6 : null;
    if (age === null) {
      if (!offline) { banner.hidden = true; return; }
      banner.className = "red";
      banner.textContent = "Offline — there is no saved forecast time, so treat everything on this page as out of date. Check the avalanche center forecast when you have signal.";
    } else if (age > AMBER_H || offline) {
      const lvl = age > RED_H ? "red" : age > AMBER_H ? "amber" : "info";
      banner.className = lvl;
      banner.textContent = `${offline ? "Offline — data" : "Data"} from ${fmtTime(generated)} (${fmtAge(age)} old).` +
        (age > RED_H ? " This is out of date: check the avalanche center forecast when you have signal." : age > AMBER_H ? " It may be out of date." : "");
    } else { banner.hidden = true; return; }
    banner.hidden = false;
  }
  document.addEventListener("DOMContentLoaded", () => { document.body.prepend(banner); updateBanner(); });
  addEventListener("online", updateBanner); addEventListener("offline", updateBanner);
  setInterval(updateBanner, 10 * 60 * 1000);

  if (!("serviceWorker" in navigator)) return;

  // ---- registration + update flow
  let reg = null;
  const updateBar = el("div", { id: "pwa-update", role: "status" });
  updateBar.hidden = true;
  const showUpdate = (w) => {
    updateBar.replaceChildren(el("span", {}, "A new version of Snow-Wx is available. "), Object.assign(el("button", { type: "button" }, "Reload"), {
      onclick: () => w.postMessage({ type: "SKIP_WAITING" }) }));
    updateBar.hidden = false;
    document.body.append(updateBar);
  };
  navigator.serviceWorker.register(cfg.sw, { scope: cfg.scope }).then((r) => {
    reg = r;
    if (r.waiting && navigator.serviceWorker.controller) showUpdate(r.waiting);
    r.addEventListener("updatefound", () => {
      const w = r.installing;
      w?.addEventListener("statechange", () => { if (w.state === "installed" && navigator.serviceWorker.controller) showUpdate(w); });
    });
    syncFavorites();
  }).catch((e) => console.warn("pwa: registration failed", e));
  let reloading = false;
  navigator.serviceWorker.addEventListener("controllerchange", () => { if (!reloading) { reloading = true; location.reload(); } });

  const toWorker = async (msg) => { const r = reg || await navigator.serviceWorker.ready; (r.active || navigator.serviceWorker.controller)?.postMessage(msg); };
  const syncFavorites = () => toWorker({ type: "FAVORITES", ids: favorites().slice(0, 50) });
  addEventListener("storage", (e) => { if (e.key === "snowwx.favorites") syncFavorites(); });

  // ---- "Save for offline" on My mountains (<= 5 favorites free; budget 25 MB)
  navigator.serviceWorker.addEventListener("message", (e) => {
    if (e.data?.type !== "PREFETCHED") return;
    const n = document.getElementById("pwa-save-note");
    if (n) n.textContent = `Saved ${e.data.count} favorite${e.data.count === 1 ? "" : "s"} for offline: ${(e.data.bytes / 1e6).toFixed(1)} MB of ${LIMIT_MB} MB budget. Basemap tiles are not saved.`;
  });
  function mineUi() {
    const host = document.getElementById("fresh");
    if (!host || document.getElementById("pwa-save")) return;
    const box = el("div", { id: "pwa-save", className: "pwa-save" });
    const btn = Object.assign(el("button", { type: "button" }, "Save for offline"), { onclick: async () => {
      const ids = favorites().slice(0, FREE_FAVS);
      const note = document.getElementById("pwa-save-note");
      if (!ids.length) { note.textContent = "Add a favorite first (the ☆ star on any forecast page)."; return; }
      const est = navigator.storage?.estimate ? await navigator.storage.estimate() : null;
      note.textContent = `Saving ${ids.length} favorite${ids.length === 1 ? "" : "s"}${favorites().length > FREE_FAVS ? ` (the first ${FREE_FAVS}; offline saving is capped at ${FREE_FAVS})` : ""}` +
        `${est ? `, about ${(ids.length * 0.1 + 0.4).toFixed(1)} MB; ${(((est.quota || 0) - (est.usage || 0)) / 1e6).toFixed(0)} MB free on this device` : ""}…`;
      toWorker({ type: "PREFETCH", ids });
    } });
    const clr = Object.assign(el("button", { type: "button", className: "link" }, "Clear offline data"), { onclick: () => { toWorker({ type: "CLEAR" }); document.getElementById("pwa-save-note").textContent = "Offline data cleared."; } });
    box.append(btn, clr, el("p", { id: "pwa-save-note", className: "hint" }, "Keeps your favorites' forecasts and the charts library on this device so they open without a signal."));
    host.after(box);
  }
  document.addEventListener("DOMContentLoaded", () => { if (/mine\.html$/.test(location.pathname)) { mineUi(); new MutationObserver(mineUi).observe(document.body, { childList: true, subtree: true }); } });

  // ---- install coach
  let deferred = null;
  const coach = el("div", { id: "pwa-coach", role: "region" });
  coach.setAttribute("aria-label", "Install Snow-Wx");
  coach.hidden = true;
  const showCoach = (text, withButton) => {
    if (store.get("snowwx.pwa.coach")) return;
    coach.replaceChildren(el("span", {}, text));
    if (withButton) coach.append(Object.assign(el("button", { type: "button" }, "Install"), { onclick: async () => { deferred.prompt(); await deferred.userChoice; coach.hidden = true; } }));
    coach.append(Object.assign(el("button", { type: "button", className: "link" }, "Not now"), { onclick: () => { store.set("snowwx.pwa.coach", String(Date.now())); coach.hidden = true; } }));
    coach.hidden = false;
    document.body.append(coach);
  };
  addEventListener("appinstalled", () => { if (window.snowwxTrack) snowwxTrack("install", { where: "pwa" }); });
  addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferred = e; showCoach("Install Snow-Wx to open your mountains from the home screen, even offline.", true); });
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) && !navigator.standalone;
  if (ios) document.addEventListener("DOMContentLoaded", () => showCoach("To install on iPhone/iPad: tap Share, then “Add to Home Screen”.", false));
})();
