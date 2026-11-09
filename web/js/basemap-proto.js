// Basemap design spike (S10 step 3): three candidate designs behind ?bm=1|2|3 on the obs map and
// Powder Finder. NOT the production basemap until the owner picks one.
//  1 = USGS shaded relief + USGS Topo faded (grayscale, ~40 %): roads/towns/boundaries faintly
//  2 = USGS shaded relief + USGS carto reference (transportation, govunits) as transparent PNGs
//      from the dynamic MapServer /export (public domain, no key; server-rendered per tile)
//  3 = USGS shaded relief + OpenFreeMap OSM vector tiles (no key, commercial OK, ODbL) drawn by
//      MapLibre GL with a minimal low-contrast style: major roads, state lines, national forests,
//      places with halos, peaks at high zoom

/* global L */
// eslint-disable-next-line no-unused-vars
async function snowBasemapProto(map, design) {
  const USGS = "https://basemap.nationalmap.gov/arcgis/rest/services";
  map.createPane("reference");
  map.getPane("reference").style.zIndex = 250;          // above base tiles, below overlays/markers
  map.getPane("reference").style.pointerEvents = "none";
  const relief = snowTileLayer(`${USGS}/USGSShadedReliefOnly/MapServer/tile/{z}/{y}/{x}`,   // eslint-disable-line no-undef
    { maxNativeZoom: 16, maxZoom: 17, attribution: "Relief: USGS" }).addTo(map);
  if (design === "1") {
    L.tileLayer(`${USGS}/USGSTopo/MapServer/tile/{z}/{y}/{x}`, { maxNativeZoom: 16, maxZoom: 17, opacity: 0.42,
      className: "topo-faded", pane: "reference", attribution: "Topo: USGS" }).addTo(map);
  } else if (design === "2") {
    const Dyn = L.TileLayer.extend({
      getTileUrl(c) {
        const R = 6378137 * Math.PI, n = 2 ** c.z, size = (2 * R) / n;
        const x0 = -R + c.x * size, y1 = R - c.y * size;
        return `${this._url}/export?bbox=${x0},${y1 - size},${x0 + size},${y1}&bboxSR=3857&imageSR=3857&size=256,256` +
          `&format=png32&transparent=true&dpi=96&f=image${this.options.layers ? `&layers=${this.options.layers}` : ""}`;
      },
    });
    const C = "https://carto.nationalmap.gov/arcgis/rest/services";
    new Dyn(`${C}/govunits/MapServer`, { pane: "reference", opacity: 0.3, maxZoom: 17, attribution: "Boundaries: USGS",
      layers: "show:31" }).addTo(map);                  // national forests (faint)
    new Dyn(`${C}/govunits/MapServer`, { pane: "reference", opacity: 0.7, maxZoom: 17,
      layers: "show:4,21,22" }).addTo(map);             // state lines + town labels
    new Dyn(`${C}/transportation/MapServer`, { pane: "reference", opacity: 0.75, maxZoom: 17, attribution: "Roads: USGS",
      layers: "show:8,9,16,17,29,30" }).addTo(map);    // major roads + interstate/US route labels
  } else if (design === "3") {
    const load = (src) => new Promise((ok, bad) => { const s = document.createElement("script"); s.src = src; s.onload = ok; s.onerror = bad; document.head.appendChild(s); });
    const css = document.createElement("link"); css.rel = "stylesheet"; css.href = "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css";
    document.head.appendChild(css);
    await load("https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js");
    await load("https://unpkg.com/@maplibre/maplibre-gl-leaflet@0.0.22/leaflet-maplibre-gl.js");
    const halo = { "text-halo-color": "rgba(255,255,255,0.92)", "text-halo-width": 1.6 };
    const style = {
      version: 8,
      glyphs: "https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf",
      sources: { omt: { type: "vector", url: "https://tiles.openfreemap.org/planet" } },
      layers: [
        { id: "forest", type: "line", source: "omt", "source-layer": "park", minzoom: 7,
          filter: ["==", ["get", "class"], "national_park"],
          paint: { "line-color": "#3f7f4f", "line-opacity": 0.4, "line-width": 1 } },
        { id: "roads-major", type: "line", source: "omt", "source-layer": "transportation",
          filter: ["in", ["get", "class"], ["literal", ["motorway", "trunk"]]],
          paint: { "line-color": "#8c6a3f", "line-opacity": 0.55, "line-width": ["interpolate", ["linear"], ["zoom"], 5, 0.6, 9, 1.4, 13, 2.4] } },
        { id: "roads-primary", type: "line", source: "omt", "source-layer": "transportation", minzoom: 8,
          filter: ["in", ["get", "class"], ["literal", ["primary", "secondary"]]],
          paint: { "line-color": "#9a8466", "line-opacity": 0.45, "line-width": ["interpolate", ["linear"], ["zoom"], 8, 0.5, 13, 1.6] } },
        { id: "roads-minor", type: "line", source: "omt", "source-layer": "transportation", minzoom: 11,
          filter: ["in", ["get", "class"], ["literal", ["tertiary", "minor", "track"]]],
          paint: { "line-color": "#a89a86", "line-opacity": 0.4, "line-width": 0.7 } },
        { id: "states", type: "line", source: "omt", "source-layer": "boundary", filter: ["==", ["get", "admin_level"], 4],
          paint: { "line-color": "#4b5563", "line-opacity": 0.6, "line-width": 1, "line-dasharray": [3, 2] } },
        { id: "peaks", type: "symbol", source: "omt", "source-layer": "mountain_peak", minzoom: 11,
          layout: { "text-field": ["concat", ["get", "name"], "\n", ["to-string", ["round", ["*", ["get", "ele"], 3.28084]]], " ft"],
            "text-font": ["Noto Sans Italic"], "text-size": 11, "text-offset": [0, 0.6], "text-anchor": "top" },
          paint: { "text-color": "#5b4a36", ...halo } },
        { id: "state-names", type: "symbol", source: "omt", "source-layer": "place", minzoom: 4.5, maxzoom: 8,
          filter: ["==", ["get", "class"], "state"],
          layout: { "text-field": ["upcase", ["get", "name"]], "text-font": ["Noto Sans Regular"], "text-size": 11,
            "text-letter-spacing": 0.25 },
          paint: { "text-color": "#6b7280", ...halo } },
        { id: "places", type: "symbol", source: "omt", "source-layer": "place",
          filter: ["in", ["get", "class"], ["literal", ["city", "town", "village"]]],
          layout: { "text-field": ["get", "name"],
            "text-font": ["match", ["get", "class"], "city", ["literal", ["Noto Sans Bold"]], ["literal", ["Noto Sans Regular"]]],
            "text-size": ["interpolate", ["linear"], ["zoom"], 5, ["match", ["get", "class"], "city", 12, 10.5], 10, 13],
            "symbol-sort-key": ["match", ["get", "class"], "city", 0, "town", 1, 2] },
          minzoom: 5,
          paint: { "text-color": "#2f3742", ...halo, "text-opacity": ["step", ["zoom"], ["match", ["get", "class"], "city", 1, 0], 8,
            ["match", ["get", "class"], "village", 0, 1], 11, 1] } },
      ],
    };
    L.maplibreGL({ style, pane: "reference", interactive: false,
      attribution: '<a href="https://openfreemap.org">OpenFreeMap</a> © <a href="https://www.openmaptiles.org/">OpenMapTiles</a> Data © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>' }).addTo(map);
  }
  return relief;
}
