// "My mountains" (mine.html): the visitor's favorites at a glance (PLAN.md Track 1 item 4).
// Favorites = localStorage "snowwx.favorites" (ski areas, Sno-Parks, SNOTEL sites; set with ☆ on
// any forecast page or in Powder Finder). Each card reads that place's NBM point file plus the
// shared alert and avalanche indexes: expected snow next 24/72 h with the NBM 10-90 % range,
// NBM's chance of >= 6" (first 24-h and 72-h windows ending ~5 AM), the lowest snow level while
// precipitation is likely in 72 h vs the base, alerts and avalanche danger.

/* global EXPECTED_TIP, expectedInfo, colorFor, SNOWFALL, PROB, textOn */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const FAV_KEY = "snowwx.favorites";
  const favs = () => { try { return JSON.parse(localStorage.getItem(FAV_KEY)) || []; } catch { return []; } };
  const setFavs = (list) => { try { localStorage.setItem(FAV_KEY, JSON.stringify(list)); } catch { /* private mode */ } };
  const getJSON = async (path) => {
    const r = await fetch(path, { cache: "no-cache" });
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  };
  const inches = (v) => (v === null || v === undefined ? "–" : v < 0.5 ? (v < 0.05 ? "0" : "<1") : `${Math.round(v)}`);
  const rng = (t) => (t?.snow_hi === null || t?.snow_hi === undefined ? "" : t.snow_hi < 0.5 ? "0–1" : `${Math.round(t.snow_lo ?? 0)}–${Math.max(1, Math.round(t.snow_hi))}`);
  const ft = (v) => (v === null || v === undefined ? "–" : `${Math.round(v).toLocaleString()} ft`);
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
  const dayFmt = (iso, tz) => new Date(iso).toLocaleString([], { weekday: "short", hour: "numeric", timeZone: tz });

  function emptyState() {
    $("fresh").textContent = "";
    $("cards").className = "mine-empty";
    $("cards").innerHTML = `
      <h3>No favorites yet</h3>
      <p>Tap the <b>☆</b> star on any ski area, Sno-Park or SNOTEL forecast page, or in <a href="finder.html">Powder Finder</a>,
        and it shows up here: expected snow for the next 24 and 72 hours, the chance of 6 inches or more, the snow level
        against the base, NWS alerts and avalanche danger — all on one screen.</p>
      <p>Find a place with the search box at the top of the page, or browse <a href="finder.html">Powder Finder</a>.</p>
      <p class="hint">Favorites are kept only in this browser (nothing is sent anywhere).</p>`;
  }

  function chance(ex, L, thr) {
    const w = ex?.[L];
    if (!w?.end?.length) return null;
    const k = w.thr.indexOf(thr);
    return k < 0 ? null : { p: w.p[0][k], start: w.start[0], end: w.end[0] };
  }

  function wetSnowLevel(pt) {         // lowest snow level while precip is likely (>= 20 %), first 72 h
    const per = (pt.periods || []).slice(0, 6).filter((p) => (p.pop ?? 0) >= 0.2 && p.snowlvl_min_ft !== null && p.snowlvl_min_ft !== undefined);
    return per.length ? Math.min(...per.map((p) => p.snowlvl_min_ft)) : null;
  }

  function card(id, d, alerts, avy) {
    const a = d.area || (d.station ? { name: d.station.name, kind: "snotel", region: d.station.state } : { name: id });
    const kind = d.station ? "snotel" : a.kind === "snopark" ? "snopark" : "ski";
    const keyPt = kind === "snotel" ? "point" : kind === "snopark" ? "base" : "summit";
    const other = kind === "ski" ? "base" : kind === "snopark" ? "summit" : null;
    const label = { summit: "Summit", base: kind === "snopark" ? "Trailhead" : "Base", point: "Station" };
    if (kind === "snopark") label.summit = "High terrain";
    const P = d.points[keyPt], O = other ? d.points[other] : null;
    const tz = d.tz || a.tz || "America/Denver";
    const t24 = P.totals["24h"], t72 = P.totals["72h"];
    const c24 = chance(P.exceed, "24h", 6), c72 = chance(P.exceed, "72h", 6);
    const sl = wetSnowLevel(P);
    const baseFt = kind === "snotel" ? P.elev_ft : (d.points.base || P).elev_ft;
    const slTxt = sl === null ? `<span class="hint">little precipitation expected</span>`
      : sl <= baseFt ? `<b class="tobase">to the ${kind === "snotel" ? "station" : label.base.toLowerCase()}</b> <span class="hint">(${ft(sl)})</span>`
      : `${ft(sl)} <span class="hint">(${(sl - baseFt).toLocaleString()} ft above the ${kind === "snotel" ? "station" : label.base.toLowerCase()})</span>`;
    const al = (alerts?.[kind === "snotel" ? "points" : "areas"]?.[id] || []);
    const alHtml = al.filter((x) => x.relevant !== false).map((x) => `<span class="alert-badge ${esc(x.level)}" title="${esc(x.event)}">${esc(x.short || x.event)}</span>`).join(" ")
      + (al.some((x) => x.relevant === false) ? ` <span class="hint">+${al.filter((x) => x.relevant === false).length} other</span>` : "");
    const z = a.avalanche, r = z && avy ? avy[String(z.zone_id)] : null;
    const avyHtml = kind === "snotel" ? "" : r
      ? `<a class="danger-chip${r.expired ? " expired" : ""}" style="background:${esc(r.color)};color:${textOn(r.color)}" href="${esc(safeUrl(r.link))}" target="_blank" rel="noopener"
          title="${esc(r.name)}${r.expired ? " (expired)" : ""}">${esc(r.danger)}</a>`
      : z ? `<span class="hint">${esc(z.zone)}</span>` : `<span class="hint">no avalanche forecast zone</span>`;
    const sw = (v) => `<i class="sw" style="background:${colorFor(SNOWFALL, v) || "#f4f6f8"}"></i>`;
    const pc = (c) => (c ? `<span class="pchip" style="background:${colorFor(PROB, c.p) || "#f4f6f8"};color:${textOn(colorFor(PROB, c.p) || "#f4f6f8")}">${c.p}%</span>` : "–");
    const sub = kind === "snotel" ? `SNOTEL · ${esc(d.station.state)} · ${ft(P.elev_ft)}` : `${esc(kind === "snopark" ? (a.type_label || "Sno-Park") : "Ski area")} · ${esc(a.region)}, ${esc(a.state)}`;
    return `<article class="mcard" data-id="${esc(id)}">
      <div class="mhead"><h3><a href="area.html#${encodeURIComponent(id)}">${esc(a.name)}</a></h3>
        <button type="button" class="unfav" data-id="${esc(id)}" aria-label="Remove ${esc(a.name)} from favorites" title="Remove from favorites">★</button>
        <p class="sub">${sub}</p>
        <div class="mtags">${alHtml}${avyHtml ? ` <span class="avy">Avalanche: ${avyHtml}</span>` : ""}</div></div>
      <div class="mgrid">
        <div><span class="lab">Next 24 h</span>${sw(t24?.snow_in)}<b>${inches(t24?.snow_in)}"</b><small>${rng(t24)}</small></div>
        <div><span class="lab">Next 72 h</span>${sw(t72?.snow_in)}<b>${inches(t72?.snow_in)}"</b><small>${rng(t72)}</small></div>
        <div><span class="lab">Chance ≥ 6", 24 h</span>${pc(c24)}<small>${c24 ? `${esc(dayFmt(c24.start, tz))} →` : ""}</small></div>
        <div><span class="lab">Chance ≥ 6", 72 h</span>${pc(c72)}<small>${c72 ? `to ${esc(dayFmt(c72.end, tz))}` : ""}</small></div>
      </div>
      <p class="mline"><span class="lab">Expected at the ${esc(label[keyPt].toLowerCase())}</span>${O ? ` · ${esc(label[other])} 72 h: ${inches(O.totals["72h"]?.snow_in)}"` : ""}
        · <span class="lab">Snow level</span> ${slTxt}</p>
    </article>`;
  }

  async function render() {
    const ids = favs();
    if (!ids.length) { emptyState(); return; }
    const [alR, avyR, ...docs] = await Promise.allSettled([getJSON("data/alerts/index.json"), getJSON("data/avalanche_ratings.json"),
      ...ids.map((id) => getJSON(`data/points/${encodeURIComponent(id)}.json`))]);
    const alerts = alR.status === "fulfilled" ? alR.value : null, avy = avyR.status === "fulfilled" ? avyR.value : null;
    const ok = docs.map((r, i) => [ids[i], r.status === "fulfilled" ? r.value : null]);
    const issued = ok.find(([, d]) => d)?.[1]?.issued;
    $("fresh").innerHTML = `${ids.length} favorite${ids.length === 1 ? "" : "s"}${issued ? ` · NBM ${new Date(issued).toLocaleString([], { weekday: "short", hour: "numeric", timeZoneName: "short" })} run` : ""}
      · amounts are <b>expected</b> ${expectedInfo()} with NBM's 10–90% range in small print`;
    $("cards").className = "mcards";
    $("cards").innerHTML = ok.map(([id, d]) => (d ? card(id, d, alerts, avy)
      : `<article class="mcard"><div class="mhead"><h3><a href="area.html#${encodeURIComponent(id)}">${esc(id)}</a></h3>
          <button type="button" class="unfav" data-id="${esc(id)}" aria-label="Remove from favorites">★</button></div>
          <p class="hint">No forecast available for this place right now.</p></article>`)).join("");
    $("cards").querySelectorAll(".unfav").forEach((b) => b.addEventListener("click", () => {
      setFavs(favs().filter((x) => x !== b.dataset.id));
      render();
    }));
  }

  // "Always open My mountains" (set from the obs-map banner); easy to turn off here (owner S9)
  function homePref() {
    let on = false;
    try { on = localStorage.getItem("snowwx.home") === "mine"; } catch { return; }
    const el = document.createElement("p");
    el.className = "home-pref";
    el.innerHTML = `<label><input type="checkbox" id="home-pref"${on ? " checked" : ""}> Open My mountains when I go to Snow-Wx's map directly</label>`;
    $("fresh").after(el);
    el.querySelector("input").addEventListener("change", (e) => {
      try { if (e.target.checked) localStorage.setItem("snowwx.home", "mine"); else localStorage.removeItem("snowwx.home"); } catch { /* ignore */ }
    });
  }

  if (typeof EXPECTED_TIP === "undefined") window.EXPECTED_TIP = "";
  render().then(() => { if (favs().length) homePref(); });
})();
