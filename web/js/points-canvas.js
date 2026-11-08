// Canvas layer for many small point symbols (SNOTEL value boxes, ASOS wind barbs,
// ski-area triangles). One <canvas> instead of ~1,500 DOM markers: pan and zoom
// move a single element, and label decluttering is computed once per zoom level
// (in projected pixels, so panning never recomputes it).
//
// Items: { group, lat, lon, prio, draw(ctx, x, y, full), box(full) -> [x0,y0,x1,y1]
//          relative to the point, labelBox -> same (null = no label to declutter),
//          hit -> [x0,y0,x1,y1], title, onClick() }
// Groups can be toggled independently (see PointsCanvas.toggleLayer).

/* global L */
const PointsCanvas = L.Layer.extend({
  options: { pane: "markerPane", padding: 0.3, lowZoom: 7, cell: 64 },

  initialize(options) {
    L.setOptions(this, options);
    this._groups = {};        // name -> items
    this._visible = {};       // name -> bool
    this._order = [];         // draw order (bottom first)
    this._layout = new Map(); // zoom -> Map(item -> full?)
    this._frame = null;
  },

  // ---- data
  setGroup(name, items, { order } = {}) {
    this._groups[name] = items;
    if (!(name in this._visible)) this._visible[name] = true;
    if (!this._order.includes(name)) this._order.splice(order ?? this._order.length, 0, name);
    this.invalidate();
  },
  setVisible(name, on) { this._visible[name] = on; this.invalidate(); },
  isVisible(name) { return !!this._visible[name]; },
  invalidate() { this._layout.clear(); this.redraw(); },
  redraw() {
    if (!this._map || this._frame) return;
    this._frame = requestAnimationFrame(() => { this._frame = null; this._draw(); });
  },

  // A thin layer for L.control.layers that toggles one group of this canvas.
  toggleLayer(name) {
    const owner = this;
    const T = L.Layer.extend({
      onAdd() { owner.setVisible(name, true); },
      onRemove() { owner.setVisible(name, false); },
    });
    return new T();
  },

  // ---- Leaflet plumbing (mirrors L.Renderer: padded canvas, zoom-animated)
  onAdd(map) {
    const c = (this._canvas = L.DomUtil.create("canvas", "points-canvas leaflet-zoom-animated"));
    c.style.pointerEvents = "none";
    this.getPane().appendChild(c);
    this._ctx = c.getContext("2d");
    const box = map.getContainer();
    this._onClick = (e) => this._click(e);
    this._onMove = (e) => this._hover(e);
    box.addEventListener("click", this._onClick, true);   // capture: beats the avalanche polygons below
    box.addEventListener("mousemove", this._onMove, { passive: true });
    this._reset();
  },
  onRemove(map) {
    const box = map.getContainer();
    box.removeEventListener("click", this._onClick, true);
    box.removeEventListener("mousemove", this._onMove);
    L.DomUtil.remove(this._canvas);
    if (this._tip) map.closeTooltip(this._tip);
  },
  getEvents() {
    const ev = { viewreset: this._reset, zoom: this._onZoom, moveend: this._reset, resize: this._reset };
    if (this._map && this._map._zoomAnimated) ev.zoomanim = this._onAnimZoom;
    return ev;
  },
  _onAnimZoom(e) { this._updateTransform(e.center, e.zoom); },
  _onZoom() { this._updateTransform(this._map.getCenter(), this._map.getZoom()); },
  _updateTransform(center, zoom) {
    const map = this._map, scale = map.getZoomScale(zoom, this._zoom);
    const viewHalf = map.getSize().multiplyBy(0.5 + this.options.padding);
    const cur = map.project(this._center, zoom);
    const offset = viewHalf.multiplyBy(-scale).add(cur).subtract(map._getNewPixelOrigin(center, zoom));
    L.DomUtil.setTransform(this._canvas, offset, scale);
  },
  _reset() {
    const map = this._map, p = this.options.padding, size = map.getSize();
    const min = map.containerPointToLayerPoint(size.multiplyBy(-p)).round();
    this._bounds = L.bounds(min, min.add(size.multiplyBy(1 + 2 * p)).round());
    this._center = map.getCenter();
    this._zoom = map.getZoom();
    const s = this._bounds.getSize(), dpr = window.devicePixelRatio || 1;
    L.DomUtil.setPosition(this._canvas, min);
    this._canvas.width = Math.round(s.x * dpr);
    this._canvas.height = Math.round(s.y * dpr);
    this._canvas.style.width = `${s.x}px`;
    this._canvas.style.height = `${s.y}px`;
    this._dpr = dpr;
    this._draw();
  },

  // ---- layout: projected positions + declutter, cached per zoom
  _proj(it, z) {
    if (it._z !== z) { const p = this._map.project([it.lat, it.lon], z); it._x = p.x; it._y = p.y; it._z = z; }
  },
  _items() {
    const out = [];
    for (const g of this._order) if (this._visible[g]) for (const it of this._groups[g] || []) out.push(it);
    return out;
  },
  _layoutFor(z) {
    if (this._layout.has(z)) return this._layout.get(z);
    const items = this._items();
    for (const it of items) this._proj(it, z);
    const full = new Map();
    if (z < this.options.lowZoom) {
      for (const it of items) full.set(it, false);
    } else {
      const cell = this.options.cell, grid = new Map();
      const hits = (a, b) => a[0] < b[2] && b[0] < a[2] && a[1] < b[3] && b[1] < a[3];
      const labelled = items.filter((it) => it.labelBox).sort((a, b) => b.prio() - a.prio());
      for (const it of labelled) {
        const r = it.labelBox, bx = [it._x + r[0], it._y + r[1], it._x + r[2], it._y + r[3]];
        const keys = [];
        for (let cx = Math.floor(bx[0] / cell); cx <= Math.floor(bx[2] / cell); cx++)
          for (let cy = Math.floor(bx[1] / cell); cy <= Math.floor(bx[3] / cell); cy++) keys.push(`${cx},${cy}`);
        const blocked = keys.some((k) => (grid.get(k) || []).some((b) => hits(bx, b)));
        full.set(it, !blocked);
        if (!blocked) for (const k of keys) (grid.get(k) || grid.set(k, []).get(k)).push(bx);
      }
      for (const it of items) if (!full.has(it)) full.set(it, true);
    }
    this._layout.set(z, full);
    return full;
  },

  _draw() {
    if (!this._map || !this._bounds) return;
    const ctx = this._ctx, z = this._map.getZoom(), dpr = this._dpr;
    const origin = this._map.getPixelOrigin().add(this._bounds.min);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, this._canvas.width, this._canvas.height);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const full = this._layoutFor(z);
    const s = this._bounds.getSize(), m = 40;
    // dots first, then full labels, then items that always draw on top (z: 2)
    const items = this._items();
    // positions are cached per item for one zoom; the layout cache may be for a zoom
    // visited earlier, so re-project here (no-op when the zoom is unchanged)
    for (const it of items) this._proj(it, z);
    const pass = (pred) => {
      for (const it of items) {
        if (!pred(it)) continue;
        const x = it._x - origin.x, y = it._y - origin.y;
        if (x < -m || y < -m || x > s.x + m || y > s.y + m) continue;
        it.draw(ctx, x, y, full.get(it), z);
      }
    };
    pass((it) => !it.top && !full.get(it));
    pass((it) => !it.top && full.get(it));
    pass((it) => it.top);
    this._drawn = { origin, full, z };
  },

  // ---- interaction
  _pick(ev) {
    if (!this._drawn) return null;
    const map = this._map, cp = map.mouseEventToContainerPoint(ev);
    const pt = map.containerPointToLayerPoint(cp).add(map.getPixelOrigin());
    const items = this._items(), { full, z } = this._drawn;
    // topmost first: reverse draw order
    const order = [...items.filter((it) => it.top), ...items.filter((it) => !it.top && full.get(it)),
                   ...items.filter((it) => !it.top && !full.get(it))];
    for (let i = 0; i < order.length; i++) {
      const it = order[i];
      if (it._z !== z) continue;
      const h = it.hit(full.get(it), z);
      if (pt.x >= it._x + h[0] && pt.x <= it._x + h[2] && pt.y >= it._y + h[1] && pt.y <= it._y + h[3]) return it;
    }
    return null;
  },
  _click(e) {
    const map = this._map;
    if (map.dragging && map.dragging.moved && map.dragging.moved()) return;
    if (e.target.closest && e.target.closest(".leaflet-control, .leaflet-popup")) return;
    const it = this._pick(e);
    if (!it) return;
    e.stopPropagation();
    e.preventDefault();
    it.onClick();
  },
  _hover(e) {
    if (this._hoverFrame) return;
    this._hoverFrame = requestAnimationFrame(() => {
      this._hoverFrame = null;
      if (e.target.closest && e.target.closest(".leaflet-control, .leaflet-popup")) return;
      const it = this._pick(e), box = this._map.getContainer();
      box.classList.toggle("points-hover", !!it);
      if (it === this._hovered) return;
      this._hovered = it;
      if (!it) { if (this._tip) this._map.closeTooltip(this._tip); return; }
      this._tip = this._tip || L.tooltip({ direction: "top", offset: [0, -10], opacity: 0.95 });
      this._tip.setLatLng([it.lat, it.lon]).setContent(it.title);
      this._map.openTooltip(this._tip);
    });
  },
});
