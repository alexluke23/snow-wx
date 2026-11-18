# Spec: Offline-first PWA (W4)

> Read when working on manifest, service worker, offline UX or install flow.
> Part of Snow-Wx docs v1.0 (Nov 15 2026). Index and priorities: `PLAN.md`.
> Section numbers (§) are kept from the original single plan so cross-references still work.

---

### 5.8 Offline-first PWA (W4) — *new, from Gemini #2*
- **Files:** `manifest.json` (name, icons 192/512 incl. maskable, `display:
  standalone`, theme color, `start_url` = "My mountains"), `sw.js`, install
  coach mark.
- **Caching:** precache the app shell; **stale-while-revalidate** for
  `summary.json` and each favorite's `points/<id>.json` + latest obs; cache a
  custom/trimmed Plotly bundle (default Plotly is large — measure).
- **Offline UX (safety-critical):** banner "Offline — data from 5:12 AM (3 h
  41 m old)"; amber > 6 h; red > 24 h with "Check the avalanche center forecast
  when you have signal". Never present stale data as current.
- **"Save for offline"**: prefetch favorites (cap ~5 free / more for supporters
  is fine) with a storage estimate. Budget ≤ 25 MB for 5 favorites.
- **iOS notes:** web push works only for sites **installed to the Home Screen**
  (iOS 16.4+, Safari), so the install funnel doubles as the alerts funnel;
  storage and background behavior are less forgiving than Android — test on real
  devices.
- **Basemaps offline:** don't bulk-prefetch third-party tiles (provider terms);
  offline view shows charts/tables with a simple static fallback.
- **Ordering:** after W1 — moving origins later strands installed users.
- **Acceptance:** installable (Lighthouse); airplane-mode test on iOS Safari and
  Android Chrome loads a favorite's page with charts and the staleness banner;
  update prompt works.

---

### W4 build (dev15) — BUILD ONLY, never enabled before W1
- **Flag:** config `pwa.enabled` (default **false**), `pwa.kill`, `pwa.version` (salt). `python -m pipeline pwa --out build` (`pipeline/pwa.py`) is a
  no-op while disabled: it writes nothing and changes no page. Enabling is a W1-cutover task (installed users are stranded if the origin changes).
  Origin/scope come from `site.origin` / `site.base_path`; nothing is hard-coded (test: no origin in `sw.js`).
- **Files when enabled:** `manifest.json` (start_url = `<base>/mine.html?source=pwa` "My mountains", scope = base path, standalone, icons 192/512 + maskable
  512 + apple-touch 180 generated with Pillow), `sw.js` (from `pipeline/pwa_sw.js`), `icons/`, and per page: manifest link, theme colour, `window.SNOWWX_PWA`
  config and `js/pwa.js` (inert without that config).
- **Caches:** `snowwx-shell-<hash>` (versioned precache of our html/css/js + Leaflet, ~0.6 MB; the version is a hash of those files, old versions are deleted on
  activate), `snowwx-data-v1` (stale-while-revalidate: summary.json, ski_areas/rec/snotel_points, alerts + avalanche indexes, `snotel.geojson`, and ONLY the
  favorites' `points/<id>.json` + `ndfd/<id>.json`; `meta.json` is network-first so the freshness clock is honest), `snowwx-lib-v1` (the Plotly basic bundle
  from cdn.plot.ly, 1.07 MB raw / 355 KB gzip, CORS, cache-first). Map tiles and any other third-party URL are never touched.
- **Staleness banner (`js/pwa.js`):** age of `meta.json` `generated_at`. Offline: "Offline — data from Tue 6:09 PM (1 h 30 min old)." (blue); > 6 h amber
  "It may be out of date."; > 24 h red "…check the avalanche center forecast when you have signal."; offline with no saved clock: red "treat everything as out of date".
  Online data older than 6 h also shows the banner. Never green, never "current".
- **Save for offline (My mountains):** button + estimate + "Clear offline data"; first 5 favorites (free cap); measured: 1 favorite ≈ 1.7 MB incl. the Plotly
  bundle, 5 favorites ≈ 2–3 MB, far under the 25 MB budget.
- **Update flow:** new `sw.js` (new version hash) installs and WAITS; pages show "A new version is available — Reload"; the button posts SKIP_WAITING; the page reloads on
  `controllerchange`. **Kill switch:** (a) `pwa.kill: true` in config → the build emits ONLY a worker that unregisters itself, clears every `snowwx-*` cache and reloads
  the page; (b) `?nopwa` on any URL does the same for one browser. Test: `tools/browser_check.py --only pwa` (install, save, CDP offline run of My mountains and a
  favorite's page with 7 charts, banner levels, kill switch).
- **Real-device tests still to do (owner), once W1 is live and the flag is on in a preview:** iPhone Safari (iOS 16.4+): Add to Home Screen, open offline in airplane mode,
  banner + charts; storage eviction after a week unused; Android Chrome: install prompt appears, installed app opens My mountains, airplane-mode favorite page; update prompt after a
  deploy; kill switch via `pwa.kill`; Lighthouse "installable" in Chrome DevTools (Lighthouse 12 no longer has a PWA category).
