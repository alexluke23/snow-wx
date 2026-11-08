// Value-encoded raster overlays (PLAN.md §5.4) for the obs map: NOHRSC snowfall
// analysis and SNODAS SWE / depth / 24-h SWE change.
// Each layer is a PNG on an EPSG:3857 grid whose pixels encode values
// (code = R*256 + G, value = offset + scale*code, alpha 0 = no data). The browser
// decodes it once, colourizes it with the site palettes and reads exact values
// under the cursor.

/* global L, colorFor, SNOWFALL, SNOTEL_VARS */
// eslint-disable-next-line no-unused-vars
function SnowOverlays(map, { panel, onChange, base = "data/nohrsc/" } = {}) {
  const R = 6378137;
  const mercX = (lon) => (R * lon * Math.PI) / 180;
  const mercY = (lat) => R * Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const palette = (key) => (key === "SNOWFALL" ? SNOWFALL : SNOTEL_VARS[key]);

  map.createPane("analysis");
  map.getPane("analysis").style.zIndex = 350;        // above tiles, below avalanche zones and stations
  map.getPane("analysis").style.pointerEvents = "none";

  // The colourized layer is drawn onto a canvas the size of the map view, redrawn after
  // every move/zoom with only the visible part of the source. (An L.ImageOverlay sizes its
  // element to the whole overlay: ~270,000 x 285,000 px at zoom 14 for the western US,
  // beyond GPU texture limits, so real browsers dropped the layers and showed the grey
  // map background. Fix 1, Nov 8.) Nearest-neighbour scaling shows the true data cells.
  const ViewOverlay = L.Layer.extend({
    options: { pane: "analysis", opacity: 0.75 },
    initialize(source, bounds, options) {
      this._src = source; this._llb = L.latLngBounds(bounds); L.setOptions(this, options);
    },
    onAdd() {
      const c = (this._canvas = L.DomUtil.create("canvas", "leaflet-layer view-overlay leaflet-zoom-animated"));
      c.style.pointerEvents = "none";
      this.getPane().appendChild(c);
      this.setOpacity(this.options.opacity);
      this._reset();
    },
    onRemove() { L.DomUtil.remove(this._canvas); this._canvas = null; },
    getEvents() {
      return { moveend: this._reset, viewreset: this._reset, resize: this._reset, zoomanim: this._animateZoom };
    },
    setOpacity(o) { this.options.opacity = o; if (this._canvas) this._canvas.style.opacity = o; return this; },
    elementSize() { return this._canvas ? [this._canvas.offsetWidth, this._canvas.offsetHeight] : null; },   // tests
    _animateZoom(e) {     // scale the current picture while Leaflet animates, like L.Renderer
      const map = this._map, scale = map.getZoomScale(e.zoom, this._zoom);
      L.DomUtil.setTransform(this._canvas, map._latLngToNewLayerPoint(this._nw, e.zoom, e.center), scale);
    },
    _reset() {
      const map = this._map, c = this._canvas;
      if (!map || !c) return;
      const size = map.getSize(), dpr = window.devicePixelRatio || 1;
      this._zoom = map.getZoom();
      this._nw = map.containerPointToLatLng([0, 0]);
      L.DomUtil.setPosition(c, map.containerPointToLayerPoint([0, 0]));
      c.width = Math.max(1, Math.round(size.x * dpr)); c.height = Math.max(1, Math.round(size.y * dpr));
      c.style.width = `${size.x}px`; c.style.height = `${size.y}px`;
      const ctx = c.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.imageSmoothingEnabled = false;
      ctx.clearRect(0, 0, size.x, size.y);
      // the source is a regular EPSG:3857 grid, so it maps linearly onto container pixels
      const a = map.latLngToContainerPoint(this._llb.getNorthWest()), b = map.latLngToContainerPoint(this._llb.getSouthEast());
      const W = this._src.width, H = this._src.height, kx = (b.x - a.x) / W, ky = (b.y - a.y) / H;
      const sx0 = Math.max(0, Math.floor(-a.x / kx)), sy0 = Math.max(0, Math.floor(-a.y / ky));
      const sx1 = Math.min(W, Math.ceil((size.x - a.x) / kx)), sy1 = Math.min(H, Math.ceil((size.y - a.y) / ky));
      if (sx1 <= sx0 || sy1 <= sy0) return;
      ctx.drawImage(this._src, sx0, sy0, sx1 - sx0, sy1 - sy0, a.x + sx0 * kx, a.y + sy0 * ky, (sx1 - sx0) * kx, (sy1 - sy0) * ky);
    },
  });

  let index = null, active = null, overlay = null, opacity = 0.75;
  const cache = new Map();   // id -> {values, w, h, canvas}

  async function decodeLayer(l) {
    if (cache.has(l.id)) return cache.get(l.id);
    const blob = await (await fetch(`${base}${l.file}?v=${encodeURIComponent(index.key)}`)).blob();
    const bmp = await createImageBitmap(blob, { premultiplyAlpha: "none", colorSpaceConversion: "none" });
    const w = bmp.width, h = bmp.height;
    const work = document.createElement("canvas");
    work.width = w; work.height = h;
    const ctx = work.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(bmp, 0, 0);
    const px = ctx.getImageData(0, 0, w, h).data;
    const values = new Float32Array(w * h);
    for (let i = 0, j = 0; i < values.length; i++, j += 4) {
      values[i] = px[j + 3] === 0 ? NaN : l.offset + l.scale * (px[j] * 256 + px[j + 1]);
    }
    // colourize once: bins -> RGBA lookup
    const spec = palette(l.palette);
    const rgb = spec.colors.map((c) => [parseInt(c.slice(1, 3), 16), parseInt(c.slice(3, 5), 16), parseInt(c.slice(5, 7), 16)]);
    const out = ctx.createImageData(w, h), o = out.data;
    for (let i = 0, j = 0; i < values.length; i++, j += 4) {
      const v = values[i];
      if (Number.isNaN(v) || (l.clear_below !== undefined && v < l.clear_below)
          || (l.clear_between && v > l.clear_between[0] && v < l.clear_between[1])) continue;
      let b = 0;
      while (b < spec.bins.length && v >= spec.bins[b]) b++;
      const c = rgb[b];
      o[j] = c[0]; o[j + 1] = c[1]; o[j + 2] = c[2]; o[j + 3] = 255;
    }
    const canvas = document.createElement("canvas");
    canvas.width = w; canvas.height = h;
    canvas.getContext("2d").putImageData(out, 0, 0);
    const rec = { values, w, h, canvas };
    cache.set(l.id, rec);
    return rec;
  }

  function legend(l) {
    const spec = palette(l.palette);
    const items = spec.colors.map((c, i) => {
      const lo = i === 0 ? null : spec.bins[i - 1], hi = i < spec.bins.length ? spec.bins[i] : null;
      const txt = lo === null ? `< ${hi}` : hi === null ? `≥ ${lo}` : `${lo}`;
      return `<div class="sw" style="background:${c};color:${textOn(c)}">${txt}</div>`;
    });
    return `<div class="legend">${items.join("")}</div>`;
  }

  const fmtValid = (iso) => new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "numeric", timeZoneName: "short" });

  function renderPanel() {
    if (!panel) return;
    const opts = (index?.layers || []).map((l) => `<option value="${esc(l.id)}"${l.id === active ? " selected" : ""}>${esc(l.label)}</option>`);
    const l = index?.layers.find((x) => x.id === active);
    panel.innerHTML = `
      <label for="overlay-select" class="label">Snow analysis overlay</label>
      <select id="overlay-select"><option value="">None</option>${opts.join("")}</select>
      ${l ? `<div class="overlay-meta">
          ${legend(l)}
          <p class="hint">${esc(l.units)} · ${l.id.startsWith("sf") ? "ending" : "valid"} ${esc(fmtValid(l.valid))} · ${esc(l.source)}</p>
          <label class="opacity">Opacity <input id="overlay-opacity" type="range" min="0.2" max="1" step="0.05" value="${opacity}"></label>
          <p id="overlay-readout" class="readout" aria-live="polite">Hover or tap the map for a value.</p>
        </div>` : ""}
      <p class="hint credit">${index ? `Source: ${esc(index.attribution)}` : "No snow analysis available yet."}</p>`;
    panel.querySelector("#overlay-select").addEventListener("change", (e) => set(e.target.value || null));
    panel.querySelector("#overlay-opacity")?.addEventListener("input", (e) => {
      opacity = Number(e.target.value); overlay?.setOpacity(opacity);
    });
  }

  function readout(latlng) {
    const el = panel?.querySelector("#overlay-readout");
    const l = index?.layers.find((x) => x.id === active), rec = l && cache.get(l.id);
    if (!el || !rec) return;
    const x = Math.floor((mercX(latlng.lng) - l.x0) / l.res), y = Math.floor((l.y0 - mercY(latlng.lat)) / l.res);
    const v = x >= 0 && y >= 0 && x < rec.w && y < rec.h ? rec.values[y * rec.w + x] : NaN;
    const d = l.scale >= 0.5 ? 0 : l.scale >= 0.1 ? 1 : 2;
    el.textContent = Number.isNaN(v) ? "No data here."
      : `${l.label.split(" (")[0]}: ${v > 1000 ? "glacier / permanent snow" : `${v.toFixed(d)} ${l.units}`}`;
  }
  map.on("mousemove click", (e) => { if (active) readout(e.latlng); });

  async function set(id) {
    if (overlay) { map.removeLayer(overlay); overlay = null; }
    active = id && index?.layers.some((l) => l.id === id) ? id : null;
    renderPanel();
    onChange?.(active);
    if (!active) return;
    const l = index.layers.find((x) => x.id === active);
    const el = panel?.querySelector("#overlay-readout");
    if (el) el.textContent = "Loading…";
    try {
      const rec = await decodeLayer(l);
      if (active !== l.id) return;          // switched while loading
      overlay = new ViewOverlay(rec.canvas, l.bounds, { pane: "analysis", opacity });
      overlay.addTo(map);
      if (el) el.textContent = "Hover or tap the map for a value.";
    } catch (e) {
      if (el) el.textContent = `Overlay unavailable (${e.message}).`;
    }
  }

  async function load(initial) {
    try {
      index = await (await fetch(`${base}index.json?v=${Date.now()}`)).json();
    } catch {
      index = null;
    }
    renderPanel();
    if (initial) await set(initial);
    return index;
  }

  return { load, set, current: () => active, layer: () => overlay };
}
