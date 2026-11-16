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
