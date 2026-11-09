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
function snowBasemaps(map, { initial = "Shaded relief (USGS)", maxZoom = 17, onSwitch, deferReference = false } = {}) {
  window.snowwx = window.snowwx || {};
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

  // Reference layer (roads, towns, state lines, peaks; js/basemap-ref.js, owner pick S10) in its own
  // pane above the base tiles and below overlays/markers. The group exists right away so the layer
  // control can list it; the MapLibre layer is loaded into it after the first paint. It goes with the
  // shaded relief only: Topo and Imagery carry their own labels, so it is hidden there (and comes
  // back with the relief unless the visitor turned it off).
  map.createPane("reference");
  map.getPane("reference").style.zIndex = 250;
  map.getPane("reference").style.pointerEvents = "none";
  const REF = "Roads, towns & peaks";
  const reference = L.layerGroup();
  const refState = (window.snowwx.reference = { state: "pending", group: reference });
  let refWanted = true, auto = false;
  const refFits = (name) => name === "Shaded relief (USGS)";
  map.on("overlayadd overlayremove", (e) => { if (e.layer === reference && !auto) refWanted = e.type === "overlayadd"; });
  const syncRef = () => {
    auto = true;
    if (refWanted && refFits(current)) reference.addTo(map); else map.removeLayer(reference);
    auto = false;
  };
  let refStarted = false;
  function loadReference() {
    if (refStarted) return;
    refStarted = true;
    const s = document.createElement("script");
    s.src = "js/basemap-ref.js"; s.async = true;
    s.onload = () => snowReferenceLayer("reference")          // eslint-disable-line no-undef
      .then((gl) => {
        reference.addLayer(gl);
        refState.state = "ready"; refState.layer = gl;
        gl.getMaplibreMap?.().once("idle", () => { refState.state = "idle"; });
      })
      .catch((err) => { refState.state = "failed"; console.debug("basemap: reference layer unavailable", err); });
    s.onerror = () => { refState.state = "failed"; };
    document.head.appendChild(s);
  }
  // MapLibre (~210 KB gz; parsing it is one 100-500 ms main-thread task on a throttled phone) starts
  // right after the page's own data and markers are drawn (the page calls api.loadReference(); window
  // load when deferReference is off), once the visible relief tiles have arrived (its downloads would
  // otherwise slow the relief, the page's largest paint) and the browser is idle, but no later than
  // REF_CAP_MS. Owner decision S10: orientation matters more than a few Lighthouse points.
  const REF_CAP_MS = 2000;
  let refScheduled = false;
  function scheduleReference() {
    if (refScheduled) return;
    refScheduled = true;
    const t0 = Date.now();
    let fired = false;
    const go = () => {
      if (fired) return;
      fired = true;
      const left = Math.max(0, REF_CAP_MS - (Date.now() - t0));
      if ("requestIdleCallback" in window && left > 0) requestIdleCallback(loadReference, { timeout: left });
      else loadReference();
    };
    const base = layers[current];
    if (base && base._loading) base.once("load", go); else go();
    setTimeout(go, REF_CAP_MS);
  }
  if (!deferReference) {
    if (document.readyState === "complete") scheduleReference(); else window.addEventListener("load", scheduleReference, { once: true });
  } else {
    setTimeout(scheduleReference, 8000);        // safety net if the page never calls loadReference()
  }

  map.on("baselayerchange", (e) => {           // the user picked one in the layer control
    current = e.name in layers ? e.name : current;
    if (current) stats[current].recent = [];
    syncRef();
  });
  use(initial in layers ? initial : DEFS[0].name);
  syncRef();
  // re-measure when the map box changes size (layout shifts, sticky panels, browser zoom):
  // otherwise Leaflet keeps loading tiles for the old size and the rest stays grey
  if ("ResizeObserver" in window) {
    let raf = 0;
    new ResizeObserver(() => { cancelAnimationFrame(raf); raf = requestAnimationFrame(() => map.invalidateSize({ pan: false })); })
      .observe(map.getContainer());
  }
  // compact credits on phones (CSS: 2 lines); the first tap expands them, links work once open
  const attr = map.attributionControl?.getContainer();
  if (attr) {
    attr.classList.add("compact");
    attr.setAttribute("title", "Map credits (tap to show all)");
    attr.addEventListener("click", (e) => {
      if (!attr.classList.contains("open") && window.matchMedia("(max-width: 600px)").matches) { attr.classList.add("open"); e.preventDefault(); }
    }, true);
  }
  const api = { layers, overlays: { [REF]: reference }, use, current: () => current, loadReference: scheduleReference };
  window.snowwx.basemap = api;            // test handle (tools/browser_check.py)
  return api;
}
