// Powder Finder (finder.html): every ski area ranked by forecast snowfall, or by the
// chance of at least X inches. Plain HTML list first (fast on phones); Leaflet map and
// the probability table (data/points/exceed_summary.json) load only when needed.
// Data: data/points/summary.json (NBM), data/ndfd/summary.json (NWS),
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
  const SKI_THR = { "24h": [4, 6, 8, 12, 18, 24], "48h": [4, 6, 8, 12, 18, 24, 30, 36], "72h": [4, 6, 8, 12, 18, 24, 30, 36, 48] };
  const SEPARATE = "Chances come from NBM's probabilistic guidance, calibrated separately from NBM's most-likely amount; " +
    "the two can disagree.";
  const fmt = (v) => (v === null || v === undefined ? "–" : v < 0.5 ? (v < 0.05 ? "0" : "<1") : `${Math.round(v)}`);
  const kft = (v) => `${(v / 1000).toFixed(1)}k`;

  // ---- state: a shared URL wins, then the visitor's last choice, then 72 h summit
  const q = new URLSearchParams(location.hash.slice(1));
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(PREF_KEY)) || {}; } catch { saved = {}; }
  const pick = (k, def) => q.get(k) ?? saved[k] ?? def;
  const st = { m: pick("m", "amount"), w: pick("w", "72h"), e: pick("e", "summit"), src: pick("src", "nbm"),
               state: pick("st", ""), region: pick("r", ""), sort: pick("sort", "snow"), fav: pick("fav", "0") === "1",
               pw: pick("pw", "24h"), px: Number(pick("px", "6")), pd: Number(pick("pd", "0")) };
  const writeHash = () => {
    const p = new URLSearchParams({ m: st.m, e: st.e });
    if (st.m === "prob") { p.set("pw", st.pw); p.set("px", String(st.px)); p.set("pd", String(st.pd)); }
    else { p.set("w", st.w); p.set("src", st.src); p.set("sort", st.sort); }
    if (st.state) p.set("st", st.state);
    if (st.region) p.set("r", st.region);
    if (st.fav) p.set("fav", "1");
    history.replaceState(null, "", `#${p}`);
    try {
      localStorage.setItem(PREF_KEY, JSON.stringify({ m: st.m, w: st.w, e: st.e, src: st.src, st: st.state, r: st.region,
        sort: st.sort, fav: st.fav ? "1" : "0", pw: st.pw, px: String(st.px), pd: String(st.pd) }));
    } catch { /* private mode */ }
  };

  let nbm = null, nws = null, obs = null, alerts = {}, exceed = null, exceedP = null, rows = [];

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

  function buildRows() {
    const nwsBy = new Map((nws?.areas || []).map((r) => [r.id, r]));
    rows = (nbm?.areas || []).map((a) => {
      const src = st.m === "amount" && st.src === "nws" ? nwsBy.get(a.id) : a;
      const t = src?.[st.e]?.[st.w] || null;               // [mean, lo, hi, pop]
      const o = obs?.areas?.[a.id]?.[st.e]?.sf24 ?? null;
      const sl = src?.snowlvl_min_72h_ft ?? null;
      let prob = null, pmean = null;
      if (st.m === "prob" && exceed) {
        const w = pwin(), k = w ? w.thr.indexOf(st.px) : -1;
        const tbl = exceed.areas?.[a.id]?.[st.e]?.[st.pw];
        prob = k >= 0 && tbl && tbl[st.pd] ? tbl[st.pd][k] : null;
        pmean = exceed.areas?.[a.id]?.[st.e]?.mean?.[st.pw]?.[st.pd] ?? null;
      }
      return { a, snow: t ? t[0] : null, lo: t ? t[1] : null, hi: t ? t[2] : null, pop: t && t.length > 3 ? t[3] : null,
               obs: o, sl, slVsBase: sl === null ? null : sl - a.elev.base, gust: src?.gust_max_72h_mph ?? null,
               prob, pmean, alerts: alerts[a.id] || [] };
    });
  }

  function renderControls() {
    const prob = st.m === "prob";
    segment($("mode"), [["amount", "Most likely"], ["prob", "Chance of"]], "m", async () => {
      if (st.m === "prob") await ensureExceed();
      update();
    });
    $("win").hidden = prob; $("pwin").hidden = !prob; $("thr").hidden = !prob; $("pday-wrap").hidden = !prob;
    $("sort-wrap").hidden = prob; $("src-note").hidden = !prob;
    segment($("win"), WINDOWS.map(([v, l]) => [v, l, st.src === "nws" && (v === "7d" || v === "10d")]), "w", update);
    segment($("elev"), [["summit", "Summit"], ["base", "Base"]], "e", update);
    segment($("src"), [["nbm", "NBM"], ["nws", "NWS", !nws || prob, prob ? "Chances are NBM-only: the NWS forecast has no probabilistic snowfall" : ""]], "src", () => {
      if (st.src === "nws" && (st.w === "7d" || st.w === "10d")) st.w = "72h";
      update();
    });
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
    const fav = favs(), prob = st.m === "prob";
    const list = rows.filter((r) => (!st.state || r.a.state === st.state) && (!st.region || r.a.region === st.region)
      && (!st.fav || fav.has(r.a.id)));
    const val = (x) => (x === null || x === undefined ? -1 : x);
    const by = prob ? (x, y) => val(y.prob) - val(x.prob) || val(y.pmean) - val(x.pmean) : {
      snow: (x, y) => val(y.snow) - val(x.snow) || val(y.hi) - val(x.hi),
      obs: (x, y) => val(y.obs) - val(x.obs),
      sl: (x, y) => (x.slVsBase ?? 1e9) - (y.slVsBase ?? 1e9),
      name: (x, y) => x.a.name.localeCompare(y.a.name),
    }[st.sort];
    list.sort((x, y) => (fav.has(y.a.id) - fav.has(x.a.id)) || by(x, y) || x.a.name.localeCompare(y.a.name));
    $("snow-head").innerHTML = prob ? `% chance ≥ ${st.px}" <a class="info" href="about.html#probabilities" title="${esc(SEPARATE)}" aria-label="How the chances work">ⓘ</a>`
      : `${WINDOWS.find(([v]) => v === st.w)[1]} snow`;
    $("rows").innerHTML = list.length ? list.map((r) => {
      const c = prob ? colorFor(PROB, r.prob) || "#f4f6f8" : colorFor(SNOWFALL, r.snow) || "#f4f6f8";
      const main = prob ? `<b>${r.prob === null ? "–" : `${r.prob}%`}</b>${r.pmean === null ? "" : `<small>most likely ${fmt(r.pmean)}"</small>`}`
        : `<b>${fmt(r.snow)}"</b>${r.hi === null || r.hi === undefined ? "" : `<small>${fmt(r.lo)}–${fmt(r.hi)}</small>`}`;
      const dry = r.pop !== null && r.pop < 20;
      const slTxt = r.sl === null || dry ? `<span class="hint" title="${dry ? "little precipitation expected" : ""}">–</span>`
        : r.slVsBase <= 0 ? `<span class="tobase">to base</span>` : `+${kft(r.slVsBase)}`;
      const badge = r.alerts.length ? `<span class="alert-badge ${esc(r.alerts[0].level)}" title="${esc(r.alerts.map((x) => x.event).join(", "))}">${esc(r.alerts[0].short || "Alert")}</span>` : "";
      return `<div class="frow" role="listitem">
        <button type="button" class="star${fav.has(r.a.id) ? " on" : ""}" data-id="${esc(r.a.id)}" aria-pressed="${fav.has(r.a.id)}"
          title="Favorite">${fav.has(r.a.id) ? "★" : "☆"}<span class="sr"> favorite ${esc(r.a.name)}</span></button>
        <span class="who"><a href="area.html#${encodeURIComponent(r.a.id)}">${esc(r.a.name)}</a>${badge}
          <small>${esc(r.a.region)}, ${esc(r.a.state)}</small></span>
        <span class="num snow"><i class="sw" style="background:${c}"></i>${main}</span>
        <span class="details">
          <span class="num" data-label="Obs 24 h">${r.obs === null ? "–" : `${fmt(r.obs)}"`}</span>
          <span class="num" data-label="Snow level" title="${r.sl === null ? "" : `lowest snow level in 72 h: ${Math.round(r.sl).toLocaleString()} ft`}">${slTxt}</span>
          <span class="num" data-label="Gust">${r.gust === null ? "–" : `${Math.round(r.gust)}`}<small> mph</small></span>
          ${(() => { const m = ridgeMax(r.a.id); return `<span class="num" data-label="Ridge">${m ? `${m[0]}<small> mph ${COMPASS[Math.round(m[1] / 22.5) % 16]}</small>` : "–<small> mph</small>"}</span>`; })()}
        </span>
      </div>`;
    }).join("") : `<p class="hint">No ski areas match these filters.</p>`;
    $("legend-note").textContent = prob
      ? `Chance of at least ${st.px}" of snow in ${st.pw.replace("h", " h")} (${dayLabel(st.pd).replace("Next: ", "")}) at the ${st.e}, from NBM's ` +
        `probabilistic guidance for the 2.5 km grid cell. ${SEPARATE} Small number: NBM's most-likely ${st.w.replace("h", " h").replace("d", " d")} amount.`
      : `Most likely snowfall at the ${st.e} (${st.src === "nws" ? "NWS forecast, 2.5 km grid cell" : "NBM"})` +
        `${st.src === "nws" ? "" : "; small numbers: NBM 10–90%"}. Obs 24 h: NOHRSC snowfall analysis. Snow level: lowest in the next 72 h vs the base ` +
        `("–" when the chance of precipitation is under 20 %). Gust: highest summit gust in 72 h (NBM). Ridge: highest ridge-top wind at summit height in the window ` +
        `(HRRR, then RRFS; to 84 h). ★ favorites list first.`;
    $("rows").querySelectorAll(".star").forEach((b) => b.addEventListener("click", () => {
      const s = favs(); s.has(b.dataset.id) ? s.delete(b.dataset.id) : s.add(b.dataset.id); saveFavs(s); render();
    }));
    drawMap(list);
  }

  function update() { buildRows(); render(); }

  // ridge-top wind (HRRR then RRFS, to 84 h): highest in the chosen window, loaded after first paint
  let ridge = null;
  const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  function ridgeMax(id) {
    const r = ridge?.areas?.[id];
    if (!r) return null;
    let a, b;
    if (st.m === "prob") {
      const w = pwin();
      if (!w?.start[st.pd]) return null;
      a = new Date(w.start[st.pd]).getTime(); b = new Date(w.end[st.pd]).getTime();
    } else {
      a = new Date(nbm.issued).getTime(); b = a + { "24h": 24, "72h": 72, "7d": 168, "10d": 240 }[st.w] * 3.6e6;
    }
    let best = null, covered = false;
    ridge.valid.forEach((t, i) => {
      const x = new Date(t).getTime();
      if (x > a && x <= b) {
        covered = true;
        if (r.mph[i] !== null && (!best || r.mph[i] > best[0])) best = [r.mph[i], r.dir[i]];
      }
    });
    return covered ? best : null;
  }

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
    css.rel = "stylesheet"; css.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
    document.head.appendChild(css);
    const s = document.createElement("script");
    s.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"; s.async = true;
    s.onload = () => resolve(window.L); s.onerror = () => reject(new Error("map failed to load"));
    document.head.appendChild(s);
  }));
  function drawMap(list) {
    if (!map) return;
    layer.clearLayers();
    const fitKey = `${st.state}|${st.region}|${st.fav}`;
    if (fitKey !== lastFit && list.length) {
      lastFit = fitKey;
      map.fitBounds(L.latLngBounds(list.map((r) => [r.a.lat, r.a.lon])).pad(0.15), { maxZoom: 9 });
    }
    const prob = st.m === "prob";
    for (const r of [...list].reverse()) {
      const c = prob ? colorFor(PROB, r.prob) || "#f4f6f8" : colorFor(SNOWFALL, r.snow) || "#f4f6f8";
      const txt = prob ? `${r.prob ?? "–"}% chance ≥ ${st.px}"` : `${fmt(r.snow)}"`;
      L.circleMarker([r.a.lat, r.a.lon], { radius: r.a.major ? 7 : 5, color: "#1b2a4a", weight: 1, fillColor: c, fillOpacity: 0.95 })
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
    const [a, b, c, d] = await Promise.allSettled([getJSON("data/points/summary.json"), getJSON("data/ndfd/summary.json"),
      getJSON("data/nohrsc/ski.json"), getJSON("data/alerts/index.json")]);
    if (a.status !== "fulfilled") { $("rows").innerHTML = `<p>Forecasts are not available yet.</p>`; $("fresh").textContent = ""; return; }
    nbm = a.value; nws = b.status === "fulfilled" ? b.value : null; obs = c.status === "fulfilled" ? c.value : null;
    alerts = d.status === "fulfilled" ? d.value.areas || {} : {};
    const states = [...new Set(nbm.areas.map((x) => x.state))].sort();
    const regions = [...new Set(nbm.areas.map((x) => x.region))].sort();
    $("state").innerHTML = `<option value="">All</option>${states.map((x) => `<option${x === st.state ? " selected" : ""}>${esc(x)}</option>`).join("")}`;
    $("region").innerHTML = `<option value="">All</option>${regions.map((x) => `<option${x === st.region ? " selected" : ""}>${esc(x)}</option>`).join("")}`;
    $("sort").value = st.sort; $("favonly").checked = st.fav;
    $("state").addEventListener("change", (e) => { st.state = e.target.value; render(); });
    $("region").addEventListener("change", (e) => { st.region = e.target.value; render(); });
    $("sort").addEventListener("change", (e) => { st.sort = e.target.value; render(); });
    $("favonly").addEventListener("change", (e) => { st.fav = e.target.checked; render(); });
    $("pday").addEventListener("change", (e) => { st.pd = Number(e.target.value); update(); });
    const when = (iso) => new Date(iso).toLocaleString([], { weekday: "short", hour: "numeric", timeZoneName: "short" });
    $("fresh").textContent = `NBM ${when(nbm.issued)} run${nws ? ` · NWS issued ${when(nws.issued)}` : ""}${obs?.snowfall_end ? ` · observed to ${when(obs.snowfall_end)}` : ""}`;
    if (st.m === "prob") await ensureExceed();
    update();
    getJSON("data/ridge.json").then((x) => { ridge = x; render(); }).catch(() => {});
    (window.requestIdleCallback || ((f) => setTimeout(f, 300)))(initMap, { timeout: 1500 });
  }
  load();
})();
