// Reference layer over the shaded relief (owner pick S10, design 3): a minimal, low-contrast
// OpenStreetMap layer drawn by MapLibre GL from OpenFreeMap vector tiles. Faint major roads
// (primary/secondary from z8, minor from z11), dashed state lines, national-park outlines,
// state names (z5-8), haloed city/town/village names, named peaks with elevation in feet (z11+).
// Loaded lazily by basemap.js after the map's first paint; if WebGL or the tiles are not
// available the relief simply shows on its own.
// Terms (checked Nov 8 2026): OpenFreeMap = no API key, no usage limits, commercial use OK;
// attribution "OpenFreeMap © OpenMapTiles Data © OpenStreetMap contributors" (data ODbL).
// MapLibre GL JS = BSD-3-Clause; maplibre-gl-leaflet = ISC. Both vendored in web/vendor/.

/* global L */
// eslint-disable-next-line no-unused-vars
async function snowReferenceLayer(pane) {
  const load = (src) => new Promise((ok, bad) => {
    const s = document.createElement("script");
    s.src = src; s.async = true; s.onload = ok; s.onerror = () => bad(new Error(`failed: ${src}`));
    document.head.appendChild(s);
  });
  const css = document.createElement("link");
  css.rel = "stylesheet"; css.href = "vendor/maplibre-gl-4.7.1/maplibre-gl.css";
  document.head.appendChild(css);
  if (!window.maplibregl) await load("vendor/maplibre-gl-4.7.1/maplibre-gl.js");
  if (!L.maplibreGL) await load("vendor/maplibre-gl-leaflet-0.0.22/leaflet-maplibre-gl.js");

  const OFM = "https://tiles.openfreemap.org";
  const halo = { "text-halo-color": "rgba(255,255,255,0.92)", "text-halo-width": 1.6 };
  const style = {
    version: 8,
    glyphs: `${OFM}/fonts/{fontstack}/{range}.pbf`,
    sources: { omt: { type: "vector", url: `${OFM}/planet` } },
    layers: [
      { id: "parks", type: "line", source: "omt", "source-layer": "park", minzoom: 7,
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
      { id: "places", type: "symbol", source: "omt", "source-layer": "place", minzoom: 5,
        filter: ["in", ["get", "class"], ["literal", ["city", "town", "village"]]],
        layout: { "text-field": ["get", "name"],
          "text-font": ["match", ["get", "class"], "city", ["literal", ["Noto Sans Bold"]], ["literal", ["Noto Sans Regular"]]],
          "text-size": ["interpolate", ["linear"], ["zoom"], 5, ["match", ["get", "class"], "city", 12, 10.5], 10, 13],
          "symbol-sort-key": ["match", ["get", "class"], "city", 0, "town", 1, 2] },
        paint: { "text-color": "#2f3742", ...halo,
          // cities from z5, towns from z8, villages from z11
          "text-opacity": ["step", ["zoom"], ["match", ["get", "class"], "city", 1, 0], 8,
            ["match", ["get", "class"], "village", 0, 1], 11, 1] } },
    ],
  };
  return L.maplibreGL({ style, pane, interactive: false,
    attribution: '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> © <a href="https://www.openmaptiles.org/" target="_blank" rel="noopener">OpenMapTiles</a> Data © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>' });
}
