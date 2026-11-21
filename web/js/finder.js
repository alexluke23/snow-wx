// Powder Finder (finder.html): every ski area ranked by forecast snowfall, or by the
// chance of at least X inches. Plain HTML list first (fast on phones); Leaflet map and
// the probability table (data/points/exceed_summary.json) load only when needed.
// Data: data/points/summary.json (NBM),
//       data/nohrsc/ski.json (observed 24 h), data/alerts/index.json (NWS alerts).

(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const getJSON = async (p) => { const r = await fetch(p, { cache: "no-cache" }); if (!r.ok) throw new Error(p); return r.json(); };
  const FAV_KEY = "snowwx.favorites", PREF_KEY = "snowwx.finder";
  const favs = () => { try { return new Set(JSON.parse(localStorage.getItem(FAV_KEY)) || []); } catch { return new Set(); } };
  const saveFavs = (s) => { try { localStorage.setItem(FAV_KEY, JSON.stringify([...s])); } catch { /* private mode */ } };
  const WINDOWS = [["24h", "24 h"], ["72h", "72 h"], ["7d", "7 d"], ["10d", "10 d"]];
  const PWINDOWS = [["24h", "24 h"], ["48h", "48 h"], ["72h", "72 h"]];
  // skier-relevant thresholds (inches) shown as chips when NBM provides them
  const SKI_THR = { "24h": [2, 4, 6, 8, 12, 18, 24], "48h": [2, 4, 6, 8, 12, 18, 24, 30, 36], "72h": [4, 6, 8, 12, 18, 24, 30, 36, 48] };   // 2": NBM-native for 24/48 h only
  const SEPARATE = "Chances come from NBM's probabilistic guidance, calibrated separately from NBM's expected amount; " +
    "the two can disagree.";
  const fmt = (v) => (v === null || v === undefined ? "–" : v < 0.5 ? (v < 0.05 ? "0" : "<1") : `${Math.round(v)}`);
  const kft = (v) => `${(v / 1000).toFixed(1)}k`;

  // ---- state: a shared URL wins, then the visitor's last choice, then 72 h summit
  const q = new URLSearchParams(location.hash.slice(1));
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(PREF_KEY)) || {}; } catch { saved = {}; }
  const pick = (k, def) => q.get(k) ?? saved[k] ?? def;
  const st = { m: pick("m", "amount"), w: pick("w", "72h"), e: pick("e", "summit"),
               state: pick("st", ""), region: pick("r", ""), sort: pick("sort", "snow"), fav: pick("fav", "0") === "1",
               pw: pick("pw", "24h"), px: Number(pick("px", "6")), pd: Number(pick("pd", "0")), t: pick("t", "ski"),
               ty: pick("ty", "0") === "1", dir: pick("dir", "") };
  const ROW_CAP = 200;
  let showAll = false;                                   // reset whenever a filter changes (see update())
  const TYPE_SHORT = { dense: "Dense", medium: "Medium", blower: "Blower" };
  const TYPE_LONG = { dense: `Dense (< ${POWDER_Q.dense_below}:1)`, medium: `Medium (${POWDER_Q.dense_below}–${POWDER_Q.blower_at}:1)`, blower: `Blower (≥ ${POWDER_Q.blower_at}:1)` };
  // Sno-Parks (kind "snopark") reuse the ski-area fields: summit = high terrain, base = trailhead
  const isRec = (a) => a.kind === "snopark";
  const ELEV_LABEL = { ski: ["Summit", "Base"], snopark: ["High terrain", "Trailhead"], all: ["Summit / high terrain", "Base / trailhead"] };
  const TYPE_WORD = { ski: "ski areas", snopark: "Sno-Parks and winter recreation sites", all: "ski areas and Sno-Parks" };
  const writeHash = () => {
    const p = new URLSearchParams({ t: st.t, m: st.m, e: st.e });
    if (st.m === "prob") { p.set("pw", st.pw); p.set("px", String(st.px)); p.set("pd", String(st.pd)); }
    else { p.set("w", st.w); p.set("sort", st.sort); }
    if (st.state) p.set("st", st.state);
    if (st.region) p.set("r", st.region);
    if (st.fav) p.set("fav", "1");
    if (st.ty) p.set("ty", "1");
    if (st.dir) p.set("dir", st.dir);
    history.replaceState(null, "", `#${p}`);
    try {
      localStorage.setItem(PREF_KEY, JSON.stringify({ m: st.m, w: st.w, e: st.e, st: st.state, r: st.region,
        sort: st.sort, dir: st.dir, fav: st.fav ? "1" : "0", pw: st.pw, px: String(st.px), pd: String(st.pd), t: st.t, ty: st.ty ? "1" : "0" }));
    } catch { /* private mode */ }
  };

  let nbm = null, obs = null, alerts = {}, exceed = null, exceedP = null, rows = [];

  function segment(el, items, key, onChange, cast = String) {
    el.innerHTML = items.map(([v, label, disabled, title]) =>
      `<button type="button" data-v="${v}" class="${String(st[key]) === String(v) ? "on" : ""}" aria-pressed="${String(st[key]) === String(v)}"
        ${disabled ? "disabled" : ""}${title ? ` title="${esc(title)}"` : ""}>${label}</button>`).join("");
    el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { st[key] = cast(b.dataset.v); onChange(); }));
  }

  // ---- probability mode: windows, thresholds, days
  const pwin = () => exceed?.windows?.[st.pw];
  const chips = () => (pwin()?.thr || []).filter((t) => SKI_THR[st.pw].includes(t));
  const dayLabel = (i) => {
    const w = pwin(); if (!w || !w.start[i]) return "";
    const opt = { weekday: "short", hour: "numeric" };
    const a = new Date(w.start[i]).toLocaleString([], opt), b = new Date(w.end[i]).toLocaleString([], opt);
    return `${i === 0 ? "Next: " : ""}${a} → ${b}`;
  };

  // ---- linked state / region menus (dev13 item 1)
  const DEFAULT_DIR = { snow: "desc", obs: "desc", sl: "asc", name: "asc" };
  const effectiveDir = () => (st.dir === "asc" || st.dir === "desc" ? st.dir : DEFAULT_DIR[st.sort] || "desc");
  const typeFavOk = (r, fav) => (st.t === "all" || (st.t === "snopark") === isRec(r.a)) && (!st.fav || fav.has(r.a.id));
  let regionOrder = null;
  /** Regions north to south (mean latitude of their places, ties by name); states alphabetical. */
  function computeOrder() {
    const acc = new Map();
    for (const a of nbm.areas) {
      const x = acc.get(a.region) || { lat: 0, n: 0 };
      x.lat += a.lat; x.n += 1; acc.set(a.region, x);
    }
    regionOrder = [...acc.entries()].map(([r, x]) => [r, x.lat / x.n]).sort((p, q) => q[1] - p[1] || p[0].localeCompare(q[0])).map(([r]) => r);
  }
  function syncFilterMenus(fav) {
    if (!nbm || !$("state") || !$("region")) return;
    if (!regionOrder) computeOrder();
    const base = rows.filter((r) => typeFavOk(r, fav));
    const count = (pred, key) => { const m = new Map(); for (const r of base) if (pred(r)) m.set(r.a[key], (m.get(r.a[key]) || 0) + 1); return m; };
    const byState = count((r) => !st.region || r.a.region === st.region, "state");       // counts respect the OTHER filter
    const byRegion = count((r) => !st.state || r.a.state === st.state, "region");
    // a choice that no longer exists under the other filter resets to All (never an empty list by accident)
    if (st.state && !byState.get(st.state)) st.state = "";
    if (st.region && !byRegion.get(st.region)) st.region = "";
    const total = (m) => [...m.values()].reduce((a, b) => a + b, 0);
    const fill = (id, names, m, current, label) => {
      $(id).innerHTML = `<option value="">All (${total(m)})</option>` + names.map((n) => {
        const c = m.get(n) || 0;
        return `<option value="${esc(n)}"${n === current ? " selected" : ""}${c || n === current ? "" : " disabled"}>${esc(n)} (${c})</option>`;
      }).join("");
      $(id).value = current;
    };
    const states = [...new Set(nbm.areas.map((x) => x.state))].sort();
    fill("state", states, byState, st.state, "All states");
    fill("region", regionOrder, byRegion, st.region, "All regions");
  }

  function buildRows() {
    rows = (nbm?.areas || []).map((a) => {
      const src = a;
      const t = src?.[st.e]?.[st.w] || null;               // [mean, lo, hi, pop %, lowest wet snow level]
      const o = obs?.areas?.[a.id]?.[st.e]?.sf24 ?? null;
      // snow level and chance of precip for the window on screen (B3): the amount window,
      // or in "Chance of" mode the selected probability window
      let pop = t && t.length > 3 ? t[3] : null;
      let sl = t && t.length > 4 ? t[4] : (src?.snowlvl_min_72h_ft ?? null);   // older files: 72 h
      let prob = null, pmean = null;
      if (st.m === "prob" && exceed) {
        const w = pwin(), k = w ? w.thr.indexOf(st.px) : -1;
        const ea = exceed.areas?.[a.id]?.[st.e];
        const tbl = ea?.[st.pw];
        prob = k >= 0 && tbl && tbl[st.pd] ? tbl[st.pd][k] : null;
        pmean = ea?.mean?.[st.pw]?.[st.pd] ?? null;
        if (ea?.pop) { pop = ea.pop[st.pw]?.[st.pd] ?? null; sl = ea.sl?.[st.pw]?.[st.pd] ?? null; }
      }
      // 7/10-day ranges were sums of NBM windows (owner Nov 16: dropped); only native 24/48/72 h ranges are shown
      // Ranges only from ONE native NBM window (t[6]): 7/10-day ranges and composite ones (percentiles of
      // several windows added) are never shown; expected total only (owner Nov 16)
      const nat = !!(t && t.length > 6 && t[6] === true) && st.w !== "7d" && st.w !== "10d";
      return { a, snow: t ? t[0] : null, lo: t && nat && t.length > 8 ? t[7] : null, hi: t && nat && t.length > 8 ? t[8] : null,   // "likely" = native NBM p25/p75 (owner Nov 17)
               pop, stype: t && t.length > 5 ? t[5] : null, sm: a.sm || null,
               obs: o, sl, slVsBase: sl === null ? null : sl - a.elev.base, gust: src?.gust_max_72h_mph ?? null,
               prob, pmean, alerts: alerts[a.id] || [] };
    });
  }

  function renderControls() {
    const prob = st.m === "prob";
    segment($("mode"), [["amount", "Expected"], ["prob", "Chance of"]], "m", async () => {
      if (st.m === "prob") await ensureExceed();
      update();
    });
    $("win").hidden = prob; $("pwin").hidden = !prob; $("thr").hidden = !prob; $("pday-wrap").hidden = !prob;
    $("sort-wrap").hidden = prob;
    segment($("win"), WINDOWS.map(([v, l]) => [v, l]), "w", update);
    segment($("type"), [["ski", "Ski areas"], ["snopark", "Sno-Parks"], ["all", "All"]], "t", update);
    segment($("elev"), [["summit", ELEV_LABEL[st.t][0]], ["base", ELEV_LABEL[st.t][1]]], "e", update);
    if (prob) {
      segment($("pwin"), PWINDOWS, "pw", () => {
        if (!chips().includes(st.px)) st.px = chips()[Math.min(1, chips().length - 1)] || 6;
        if (st.pd >= (pwin()?.start.length || 1)) st.pd = 0;
        update();
      });
      segment($("thr"), chips().map((t) => [t, `${t}"`]), "px", update, Number);
      const w = pwin();
      $("pday").innerHTML = (w?.start || []).map((s, i) => `<option value="${i}"${i === st.pd ? " selected" : ""}>${esc(dayLabel(i))}</option>`).join("");
    }
  }

  function render() {
    writeHash();
    renderControls();
    document.querySelector(".finder-list").classList.toggle("with-type", st.ty);   // optional Snow type column
    document.querySelector(".fhead .col-type").hidden = !st.ty;
    const fav = favs(), prob = st.m === "prob";
    syncFilterMenus(fav);                                     // linked state/region menus with counts (dev13 item 1)
    const list = rows.filter((r) => typeFavOk(r, fav)
      && (!st.state || r.a.state === st.state) && (!st.region || r.a.region === st.region));
    const val = (x) => (x === null || x === undefined ? -1 : x);
    const by = prob ? (x, y) => val(y.prob) - val(x.prob) || val(y.pmean) - val(x.pmean) : {
      snow: (x, y) => val(y.snow) - val(x.snow) || val(y.hi) - val(x.hi),
      obs: (x, y) => val(y.obs) - val(x.obs),
      sl: (x, y) => (x.slVsBase ?? 1e9) - (y.slVsBase ?? 1e9),
      name: (x, y) => x.a.name.localeCompare(y.a.name),
    }[st.sort];
    // Deterministic: favorites first, then the chosen column in the chosen direction, ties by name (A-Z). The order
    // depends only on the sort controls, never on which state/region is selected.
    const flip = !prob && effectiveDir() !== DEFAULT_DIR[st.sort] ? -1 : 1;
    list.sort((x, y) => (fav.has(y.a.id) - fav.has(x.a.id)) || flip * (by(x, y) || 0) || x.a.name.localeCompare(y.a.name));
    const dirBtn = $("sort-dir");
    if (dirBtn) {
      const d = effectiveDir();
      dirBtn.textContent = d === "desc" ? "↓" : "↑";
      dirBtn.setAttribute("aria-label", `Sort direction: ${d === "desc" ? "descending (highest first)" : "ascending (lowest first)"}. Activate to reverse.`);
      dirBtn.setAttribute("title", d === "desc" ? "Highest first (tap to reverse)" : "Lowest first (tap to reverse)");
    }
    $("snow-head").innerHTML = prob ? `% chance ≥ ${st.px}" <a class="info" href="about.html#probabilities" title="${esc(SEPARATE)}" aria-label="How the chances work">ⓘ</a>`
      : `${WINDOWS.find(([v]) => v === st.w)[1]} expected ${expectedInfo()}`;
    // long lists (all 447 Sno-Parks): draw the first ROW_CAP rows, the rest on demand (a 450-row DOM costs ~700 ms of main-thread time on phones)
    const shownList = showAll ? list : list.slice(0, ROW_CAP);
    $("rows").innerHTML = list.length ? shownList.map((r) => {
      const c = prob ? colorFor(PROB, r.prob) || "#f4f6f8" : colorFor(SNOWFALL, r.snow) || "#f4f6f8";
      const main = prob ? `<b>${r.prob === null ? "–" : `${r.prob}%`}</b>${r.pmean === null ? "" : `<small>expected ${fmt(r.pmean)}"</small>`}`
        : `<b>${fmt(r.snow)}"</b>${r.hi === null || r.hi === undefined ? "" : `<small title="${LIKELY_TIP}">${fmt(r.lo)}–${fmt(r.hi)}</small>`}`;
      // precipitation likely in the window: chance of precip >= 20 %, or (Chance of mode)
      // the selected snowfall chance itself >= 20 %
      const wet = (r.pop !== null && r.pop >= 20) || (r.prob !== null && r.prob >= 20);
      const dry = !wet && (r.pop !== null || r.prob !== null);
      const slTxt = r.sl === null || dry
        ? `<span class="hint" title="${dry ? "little precipitation expected in this window" : "no snow level while precipitation is likely"}">–</span>`
        : r.slVsBase <= 0 ? `<span class="tobase">to base</span>` : `+${kft(r.slVsBase)}`;
      const sm = SnowSummary.withAlerts(r.sm ? { tag: r.sm[0], sentence: r.sm[1] } : null, r.alerts);   // client-side alert tag (§5.7)
      const smHtml = sm ? `<small class="sm${sm.alert ? " alert" : ""}" title="${esc(sm.sentence)}"><b>${esc(sm.tag)}</b></small>` : "";
      const badge = r.alerts.length ? `<span class="alert-badge ${esc(r.alerts[0].level)}" title="${esc(r.alerts.map((x) => x.event).join(", "))}">${esc(r.alerts[0].short || "Alert")}</span>` : "";
      return `<div class="frow" role="listitem">
        <button type="button" class="star${fav.has(r.a.id) ? " on" : ""}" data-id="${esc(r.a.id)}" aria-pressed="${fav.has(r.a.id)}"
          title="Favorite">${fav.has(r.a.id) ? "★" : "☆"}<span class="sr"> favorite ${esc(r.a.name)}</span></button>
        <span class="who">${isRec(r.a) ? `<i class="kind-sp" title="${esc(r.a.type_label || "Sno-Park")}" aria-hidden="true">P</i>` : ""}<a href="area.html#${encodeURIComponent(r.a.id)}">${esc(r.a.name)}</a>${badge}
          <small>${isRec(r.a) ? `${esc(r.a.type_label || "Sno-Park")} · ` : ""}${esc(r.a.region)}, ${esc(r.a.state)}</small>${smHtml}</span>
        <span class="num snow"><i class="sw" style="background:${c}"></i>${main}</span>
        <span class="details">
          <span class="num" data-label="Obs 24 h">${r.obs === null ? "–" : `${fmt(r.obs)}"`}</span>
          <span class="num" data-label="Snow level" title="${r.sl === null || dry ? "" : `lowest snow level while precipitation is likely in this window: ${Math.round(r.sl).toLocaleString()} ft`}">${slTxt}</span>
          <span class="num" data-label="Gust">${r.gust === null ? "–" : `${Math.round(r.gust)}`}<small> mph</small></span>
          ${st.ty ? `<span class="num" data-label="Snow type" title="${r.stype ? esc(TYPE_LONG[r.stype]) + " — " : ""}heuristic from NBM's snow ratio">${r.stype ? esc(TYPE_SHORT[r.stype]) : "–"}</span>` : ""}
        </span>
      </div>`;
    }).join("") : `<p class="hint">No ${TYPE_WORD[st.t]} match these filters.</p>`;
    $("rows-more").innerHTML = shownList.length < list.length ? `<button type="button" id="show-all">Show all ${list.length} (showing ${shownList.length})</button>` : "";   // outside the role=list container
    $("show-all")?.addEventListener("click", () => { showAll = true; render(); });
    $("snow-legend-box").innerHTML = prob ? "" : snowLegendHtml(Math.max(0, ...list.map((r) => r.hi ?? r.snow ?? 0)), { minTop: 12 });
    $("legend-note").textContent = prob
      ? `Chance of at least ${st.px}" of snow in ${st.pw.replace("h", " h")} (${dayLabel(st.pd).replace("Next: ", "")}) at the ${st.e}, from NBM's ` +
        `probabilistic guidance for the 2.5 km grid cell. ${SEPARATE} Small number: NBM's expected amount in the same window (about a 1-in-3 chance of reaching it). ` +
        `Snow level: lowest while precipitation is likely in that window.`
      : `Expected snowfall at the ${st.e} (NBM)` +
        `${st.w === "7d" || st.w === "10d" ? "; expected total only beyond 72 h (no range)" : "; small numbers: the likely range (the middle half of NBM's outcomes: about a 1-in-4 chance of more or less) where NBM gives it for the whole window"}. Obs 24 h: NOHRSC snowfall analysis. Snow level: lowest while precipitation is likely in the window, vs the base ` +
        `("–" when the chance of precipitation is under 20 %). Gust: highest summit gust in 72 h (NBM). ★ favorites list first.`;
    $("rows").querySelectorAll(".star").forEach((b) => b.addEventListener("click", () => {
      const s = favs(); if (s.has(b.dataset.id)) s.delete(b.dataset.id); else { s.add(b.dataset.id); if (window.snowwxTrack) snowwxTrack("favorite_added", { where: "finder" }); } saveFavs(s); render();
    }));
    drawMap(list);
  }

  function update() { showAll = false; buildRows(); render(); }

  async function ensureExceed() {
    if (exceed) return;
    exceedP = exceedP || getJSON("data/points/exceed_summary.json").catch(() => null);
    exceed = await exceedP;
    if (!exceed) st.m = "amount";
    else if (!chips().includes(st.px)) st.px = chips()[1] || chips()[0] || 6;
  }

  // ---- map (Leaflet loads after the list is on screen)
  let map = null, layer = null, leafletP = null, lastFit = "";
  const loadLeaflet = () => (leafletP ||= new Promise((resolve, reject) => {
    const css = document.createElement("link");
    css.rel = "stylesheet"; css.href = "vendor/leaflet-1.9.4/leaflet.css";
    document.head.appendChild(css);
    const s = document.createElement("script");
    s.src = "vendor/leaflet-1.9.4/leaflet.js"; s.async = true;
    s.onload = () => resolve(window.L); s.onerror = () => reject(new Error("map failed to load"));
    document.head.appendChild(s);
  }));
  // Sno-Park symbol: the same 11 px rounded square as before, but drawn on the map's canvas like the ski-area dots. 447 DOM markers (divIcon + tooltip + popup each)
  // cost ~400 ms of main-thread time on a throttled phone (Lighthouse 86 -> 98, dev19). Not keyboard-focusable before either (the list beside the map is the keyboard path).
  let SquareMarker = null;
  function squareMarker(latlng, opts) {
    SquareMarker ||= L.CircleMarker.extend({
      _updatePath() {
        const rd = this._renderer;
        if (!rd._drawing || this._empty()) return;
        const p = this._point, h = this._radius, ctx = rd._ctx;
        ctx.beginPath();
        if (ctx.roundRect) ctx.roundRect(p.x - h, p.y - h, 2 * h, 2 * h, 2); else ctx.rect(p.x - h, p.y - h, 2 * h, 2 * h);
        rd._fillStroke(ctx, this);
      },
    });
    return new SquareMarker(latlng, opts);
  }
  function drawMap(list) {
    if (!map) return;
    layer.clearLayers();
    const fitKey = `${st.state}|${st.region}|${st.fav}|${st.t}`;
    if (fitKey !== lastFit && list.length) {
      lastFit = fitKey;
      map.fitBounds(L.latLngBounds(list.map((r) => [r.a.lat, r.a.lon])).pad(0.15), { maxZoom: 9 });
    }
    const prob = st.m === "prob";
    for (const r of [...list].reverse()) {
      const c = prob ? colorFor(PROB, r.prob) || "#f4f6f8" : colorFor(SNOWFALL, r.snow) || "#f4f6f8";
      if (!isRec(r.a)) {                        // white halo under each dot so it stands off the base map (S10)
        L.circleMarker([r.a.lat, r.a.lon], { radius: (r.a.major ? 7 : 5) + 1.5, stroke: true, color: "#fff", opacity: 0.85, weight: 3,
          fill: false, interactive: false }).addTo(layer);
      }
      const txt = prob ? `${r.prob ?? "–"}% chance ≥ ${st.px}"${r.pmean === null ? "" : ` (expected ${fmt(r.pmean)}")`}` : `expected ${fmt(r.snow)}"${r.hi === null || r.hi === undefined ? "" : ` (${fmt(r.lo)}–${fmt(r.hi)}")`}`;
      (isRec(r.a)
        ? squareMarker([r.a.lat, r.a.lon], { radius: 5.5, color: "#14202e", weight: 1.4, fillColor: c, fillOpacity: 1 })
        : L.circleMarker([r.a.lat, r.a.lon], { radius: r.a.major ? 7 : 5, color: "#14202e", weight: 1.4, fillColor: c, fillOpacity: 1 }))
        .bindTooltip(`${esc(r.a.name)}: ${txt}`, { direction: "top" })
        .bindPopup(`<strong>${esc(r.a.name)}</strong><br>${txt}<br><a href="area.html#${encodeURIComponent(r.a.id)}">Forecast →</a>`)
        .addTo(layer);
    }
  }
  async function initMap() {
    try { await loadLeaflet(); } catch { $("fmap").innerHTML = `<p class="hint">Map unavailable.</p>`; return; }
    map = L.map("fmap", { preferCanvas: true, zoomControl: true, attributionControl: true }).setView([41.5, -113], 5);
    snowBasemaps(map);                        // shaded relief, overzoom + fallback (basemap.js)
    layer = L.layerGroup().addTo(map);
    render();
  }

  async function load() {
    const [a, c, d] = await Promise.allSettled([getJSON("data/points/summary.json"),
      getJSON("data/nohrsc/ski.json"), getJSON("data/alerts/index.json")]);
    if (a.status !== "fulfilled") { $("rows").innerHTML = `<p>Forecasts are not available yet.</p>`; $("fresh").textContent = ""; return; }
    nbm = a.value; obs = c.status === "fulfilled" ? c.value : null;
    alerts = d.status === "fulfilled" ? d.value.areas || {} : {};
    $("sort").value = st.sort; $("favonly").checked = st.fav;
    $("state").addEventListener("change", (e) => { st.state = e.target.value; render(); });
    $("region").addEventListener("change", (e) => { st.region = e.target.value; render(); });
    $("sort").addEventListener("change", (e) => { st.sort = e.target.value; st.dir = ""; render(); });   // new column: its default direction
    $("sort-dir").addEventListener("click", () => { st.dir = effectiveDir() === "desc" ? "asc" : "desc"; render(); });
    $("favonly").addEventListener("change", (e) => { st.fav = e.target.checked; render(); });
    $("stype").checked = st.ty;
    $("stype").addEventListener("change", (e) => { st.ty = e.target.checked; render(); });
    $("pday").addEventListener("change", (e) => { st.pd = Number(e.target.value); update(); });
    const when = (iso) => new Date(iso).toLocaleString([], { weekday: "short", hour: "numeric", timeZoneName: "short" });
    $("fresh").textContent = `NBM ${when(nbm.issued)} run${obs?.snowfall_end ? ` · observed to ${when(obs.snowfall_end)}` : ""}`;
    if (st.m === "prob") await ensureExceed();
    update();
    // Safari has no requestIdleCallback: setTimeout fallback (dev21; never call the function detached from window)
    if (typeof window.requestIdleCallback === "function") window.requestIdleCallback(initMap, { timeout: 1500 }); else setTimeout(initMap, 300);
  }
  load();
})();
