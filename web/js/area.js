// Ski-area page (area.html#<id>). M1 stub: catalog facts, links, nearby stations,
// current avalanche danger. The NBM point forecast arrives in M2/M3.

(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const ft = (v) => (v === null || v === undefined ? "–" : `${Math.round(v).toLocaleString()} ft`);
  const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");
  const getJSON = async (path) => {
    const r = await fetch(path, { cache: "no-cache" });
    if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
    return r.json();
  };

  function stationRows(list, kind) {
    if (!list?.length) return `<li class="hint">None within range</li>`;
    return list.map((s) => {
      const href = kind === "snotel" ? `index.html#v=depth_in&s=${encodeURIComponent(s.id).replace(/%3A/gi, ":")}`
                                     : `index.html#s=asos:${encodeURIComponent(s.id)}`;
      const dz = s.dz_base_ft === undefined ? "" : ` · ${s.dz_base_ft > 0 ? "+" : ""}${s.dz_base_ft.toLocaleString()} ft vs base`;
      return `<li><a href="${href}">${esc(s.name)}</a> <span class="hint">${s.dist_km} km · ${ft(s.elev_ft)}${dz}</span></li>`;
    }).join("");
  }

  function avalanche(a, fc) {
    if (!a) return `<p class="hint">Outside the avalanche-center forecast zones.</p>`;
    const f = (fc?.features || []).find((x) => x.properties.zone_id === a.zone_id);
    if (!f) return `<p>${esc(a.zone)}</p>`;
    const p = f.properties;
    return `<p><span class="danger-chip${p.expired ? " expired" : ""}" style="background:${esc(p.color)}">${esc(p.danger)}</span>
      ${esc(p.name)}${p.expired ? " <span class=\"hint\">(expired)</span>" : ""}</p>
      <a href="${esc(safeUrl(p.link))}" target="_blank" rel="noopener">Read the full forecast →</a>`;
  }

  async function render() {
    const id = decodeURIComponent(location.hash.replace(/^#/, ""));
    const main = $("area");
    let cat;
    try { cat = await getJSON("data/ski_areas.json"); } catch (e) {
      main.innerHTML = `<p>Ski-area catalog not available (${esc(e.message)}).</p>`; return;
    }
    const a = cat.areas.find((x) => x.id === id);
    if (!a) {
      main.innerHTML = `<h2>Ski areas</h2><ul class="area-list">${cat.areas.map((x) =>
        `<li><a href="#${encodeURIComponent(x.id)}">${esc(x.name)}</a> <span class="hint">${esc(x.region)}, ${esc(x.state)}</span></li>`).join("")}</ul>`;
      document.title = "Snow-Wx · Ski areas";
      return;
    }
    document.title = `Snow-Wx · ${a.name}`;
    let avy = null;
    try { avy = await getJSON("data/avalanche.geojson"); } catch { /* optional */ }
    const nwsLink = (p) => `https://forecast.weather.gov/MapClick.php?lat=${p.lat}&lon=${p.lon}`;
    main.innerHTML = `
      <h2>${esc(a.name)} <span class="hint">${esc(a.region)}, ${esc(a.state)}</span></h2>
      <div class="facts">
        <div><span class="label">Summit</span><strong>${ft(a.summit.elev_ft)}</strong></div>
        <div><span class="label">Base</span><strong>${ft(a.base.elev_ft)}</strong></div>
        <div><span class="label">Vertical</span><strong>${ft(a.vertical_ft)}</strong></div>
        <div><span class="label">Lifts</span><strong>${a.lifts}</strong></div>
      </div>
      <section><h3>Forecast</h3>
        <p class="hint">NBM point forecast for base and summit is coming soon.</p>
        <p>NWS point forecast: <a href="${nwsLink(a.summit)}" target="_blank" rel="noopener">summit</a> ·
           <a href="${nwsLink(a.base)}" target="_blank" rel="noopener">base</a></p>
      </section>
      <section><h3>Avalanche danger</h3>${avalanche(a.avalanche, avy)}</section>
      <section><h3>Nearby SNOTEL</h3><ul>${stationRows(a.nearest.snotel, "snotel")}</ul></section>
      <section><h3>Nearby airports (ASOS)</h3><ul>${stationRows(a.nearest.asos, "asos")}</ul></section>
      <p>${a.url ? `<a href="${esc(safeUrl(a.url))}" target="_blank" rel="noopener">Area website</a> · ` : ""}
         <a href="index.html#map=12/${a.summit.lat}/${a.summit.lon}&s=area:${encodeURIComponent(a.id)}">Show on map</a></p>`;
  }

  window.addEventListener("hashchange", render);
  render();
})();
