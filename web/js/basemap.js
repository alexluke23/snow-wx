// Base maps that never go blank (PLAN.md §6-C). Shared by the obs map and Powder Finder.
// - maxNativeZoom per provider + overzoom: past a provider's last tile level the last
//   tiles are scaled up instead of disappearing (a layer's maxZoom used to blank the map).
// - Automatic fallback: when the active base map keeps failing (tile errors with few
//   successes), switch to the next provider and say so in a small note; the layer
//   control follows. Providers and terms: USGS The National Map (public domain) and
//   OpenTopoMap (CC-BY-SA, already credited on about.html). No new providers.
// - Debug: window.snowwx.tiles holds per-provider counts; console.debug on every switch.
// Plain script: it only touches Leaflet (global L) when snowBasemaps() is called, so it
// can load before a lazily loaded Leaflet.

/* global L */
// eslint-disable-next-line no-unused-vars
function snowBasemaps(map, { initial = "Shaded relief (USGS)", maxZoom = 17, onSwitch } = {}) {
  const USGS = "https://basemap.nationalmap.gov/arcgis/rest/services";
  const NM = '<a href="https://www.usgs.gov/programs/national-geospatial-program/national-map">USGS</a>';
  const DEFS = [
    { name: "Shaded relief (USGS)", url: `${USGS}/USGSShadedReliefOnly/MapServer/tile/{z}/{y}/{x}`, native: 16, attribution: `Relief: ${NM}` },
    { name: "Topo (USGS)", url: `${USGS}/USGSTopo/MapServer/tile/{z}/{y}/{x}`, native: 16, attribution: `Topo: ${NM}` },
    { name: "Imagery + topo (USGS)", url: `${USGS}/USGSImageryTopo/MapServer/tile/{z}/{y}/{x}`, native: 16, attribution: `Imagery: ${NM}` },
    { name: "OpenTopoMap", url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png", native: 17,
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, SRTM | © <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)' },
  ];
  // where to go when a provider fails (never back to one that already failed)
  const NEXT = { "Shaded relief (USGS)": ["Topo (USGS)", "OpenTopoMap"], "Topo (USGS)": ["OpenTopoMap", "Shaded relief (USGS)"],
    "Imagery + topo (USGS)": ["Topo (USGS)", "OpenTopoMap"], OpenTopoMap: ["Topo (USGS)", "Shaded relief (USGS)"] };
  const ERR_MIN = 6;            // errors before judging a provider ...
  const WINDOW_MS = 20000;      // ... within this many seconds, with fewer successes than errors / 2

  window.snowwx = window.snowwx || {};
  window.snowwx.map = window.snowwx.map || map;          // debugging / test handle
  const stats = (window.snowwx.tiles = {});
  const layers = {};
  const failed = new Set();
  let current = null;
  let note = null;

  for (const d of DEFS) {
    const s = (stats[d.name] = { ok: 0, err: 0, recent: [] });
    const layer = L.tileLayer(d.url, { attribution: d.attribution, maxNativeZoom: d.native, maxZoom,
      subdomains: "abc", crossOrigin: false });
    layer.on("tileload", () => { s.ok++; s.recent.push([Date.now(), 1]); });
    layer.on("tileerror", () => { s.err++; s.recent.push([Date.now(), 0]); judge(d.name); });
    layers[d.name] = layer;
  }

  function judge(name) {
    // only the base layer that is on the map right now can trigger a switch; overlay
    // layers and base layers that were just switched away from never count
    if (name !== current || !layers[name]._map) return;
    const s = stats[name], now = Date.now();
    s.recent = s.recent.filter(([t]) => now - t < WINDOW_MS);
    const errs = s.recent.filter(([, ok]) => !ok).length, oks = s.recent.length - errs;
    if (errs >= ERR_MIN && oks < errs / 2) {
      failed.add(name);
      const next = (NEXT[name] || []).find((n) => !failed.has(n));
      console.debug("basemap: %s failing (%d errors, %d tiles in %ds) -> %s", name, errs, oks, WINDOW_MS / 1000, next || "none left");
      if (next) {
        use(next);
        showNote(`${name.replace(" (USGS)", "")} tiles are not loading — showing ${next}.`);
        onSwitch?.(next, name);
      }
    }
  }

  function showNote(text) {
    if (!note) {
      const C = L.Control.extend({ options: { position: "bottomleft" },
        onAdd() { const d = L.DomUtil.create("div", "basemap-note"); d.setAttribute("role", "status"); return d; } });
      note = new C().addTo(map);
    }
    note.getContainer().textContent = text;
  }

  function use(name) {
    if (!layers[name] || name === current) return;
    if (current) map.removeLayer(layers[current]);
    current = name;
    stats[name].recent = [];
    layers[name].addTo(map);
    layers[name].bringToBack();
  }

  map.on("baselayerchange", (e) => {           // the user picked one in the layer control
    current = e.name in layers ? e.name : current;
    if (current) stats[current].recent = [];
  });
  use(initial in layers ? initial : DEFS[0].name);
  // re-measure when the map box changes size (layout shifts, sticky panels, browser zoom):
  // otherwise Leaflet keeps loading tiles for the old size and the rest stays grey
  if ("ResizeObserver" in window) {
    let raf = 0;
    new ResizeObserver(() => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => map.invalidateSize({ pan: false })); })
      .observe(map.getContainer());
  }
  const api = { layers, use, current: () => current };
  window.snowwx.basemap = api;            // test handle (tools/browser_check.py)
  return api;
}
