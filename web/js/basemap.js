// Base maps that never go blank (PLAN.md §6-C). Shared by the obs map and Powder Finder.
// - maxNativeZoom per provider + overzoom: past a provider's last tile level the last
//   tiles are scaled up instead of disappearing (a layer's maxZoom used to blank the map).
// - Automatic fallback: when the active base map keeps failing (tile errors with few
//   successes), switch to the next provider and say so in a small note; the layer
//   control follows. Providers and terms: USGS The National Map (public domain).
//   OpenTopoMap was removed in S10 (owner decision).
// - Debug: window.snowwx.tiles holds per-provider counts; console.debug on every switch.
// Plain script: it only touches Leaflet (global L) when snowBasemaps() is called, so it
// can load before a lazily loaded Leaflet.

/* global L */
// Tile layer that fills holes in a tile cache from the nearest ancestor tile (up to 3 levels up),
// scaled with CSS. USGSShadedReliefOnly has no z9 tiles anywhere and gaps at z10-11 (checked
// 8 Nov 2026: Mt Hood 404 at z9-11, Alta/Colorado at z9), which used to trip the provider
// fallback. A tile counts as an error (tileerror -> fallback) only when no ancestor loads either.
const SNOW_EMPTY_TILE = "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7";
// eslint-disable-next-line no-unused-vars
function snowTileLayer(url, opts) {
  const Layer = L.TileLayer.extend({
    createTile(coords, done) {
      const tile = L.TileLayer.prototype.createTile.call(this, coords, done);
      tile._snowCoords = coords;
      return tile;
    },
    _tileOnError(done, tile, e) {
      const c = tile._snowCoords, k = (tile._snowUp || 0) + 1;
      if (!c || k > 3 || c.z - k < 0 || tile.src === SNOW_EMPTY_TILE) {
        L.TileLayer.prototype._tileOnError.call(this, done, tile, e); return;
      }
      tile._snowUp = k;
      const pc = { x: c.x >> k, y: c.y >> k, z: c.z - k }, n = 1 << k;
      const size = this.getTileSize().x;
      const src = this.getTileUrl(Object.assign(L.point(pc.x, pc.y), { z: pc.z }));
      const probe = new Image();
      probe.onload = () => {
        tile.style.background = `url("${src}") ${-(c.x - pc.x * n) * size}px ${-(c.y - pc.y * n) * size}px / ${size * n}px ${size * n}px no-repeat`;
        tile.src = SNOW_EMPTY_TILE;          // fires load -> done(); counted as a tile that loaded
        this.fire("tileholefill", { coords: c, up: k });
      };
      probe.onerror = () => this._tileOnError(done, tile, e);
      probe.src = src;
    },
    getTileUrl(coords) {                   // the ancestor lookup passes z explicitly
      if (coords.z !== undefined && coords.z !== this._getZoomForUrl()) {
        const d = { s: this._getSubdomain(coords), x: coords.x, y: coords.y, z: coords.z };
        return L.Util.template(this._url, L.Util.extend(d, this.options));
      }
      return L.TileLayer.prototype.getTileUrl.call(this, coords);
    },
  });
  return new Layer(url, opts);
}

// eslint-disable-next-line no-unused-vars
function snowBasemaps(map, { initial = "Shaded relief (USGS)", maxZoom = 17, onSwitch } = {}) {
  // Design spike (S10 step 3): ?bm=1|2|3 shows a candidate design instead (js/basemap-proto.js).
  const proto = new URLSearchParams(location.search).get("bm");
  if (["1", "2", "3"].includes(proto)) {
    window.snowwx = window.snowwx || {};
    window.snowwx.map = window.snowwx.map || map;
    const s = document.createElement("script");
    s.src = "js/basemap-proto.js";
    s.onload = () => snowBasemapProto(map, proto);      // eslint-disable-line no-undef
    document.head.appendChild(s);
    const api = { layers: {}, use() {}, current: () => `proto ${proto}` };
    window.snowwx.basemap = api;
    return api;
  }
  const USGS = "https://basemap.nationalmap.gov/arcgis/rest/services";
  const NM = '<a href="https://www.usgs.gov/programs/national-geospatial-program/national-map">USGS</a>';
  const DEFS = [
    { name: "Shaded relief (USGS)", url: `${USGS}/USGSShadedReliefOnly/MapServer/tile/{z}/{y}/{x}`, native: 16, attribution: `Relief: ${NM}` },
    { name: "Topo (USGS)", url: `${USGS}/USGSTopo/MapServer/tile/{z}/{y}/{x}`, native: 16, attribution: `Topo: ${NM}` },
    { name: "Imagery + topo (USGS)", url: `${USGS}/USGSImageryTopo/MapServer/tile/{z}/{y}/{x}`, native: 16, attribution: `Imagery: ${NM}` },
  ];
  // where to go when a provider fails (never back to one that already failed)
  const NEXT = { "Shaded relief (USGS)": ["Topo (USGS)", "Imagery + topo (USGS)"], "Topo (USGS)": ["Shaded relief (USGS)", "Imagery + topo (USGS)"],
    "Imagery + topo (USGS)": ["Topo (USGS)", "Shaded relief (USGS)"] };
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
    const layer = snowTileLayer(d.url, { attribution: d.attribution, maxNativeZoom: d.native, maxZoom,
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
