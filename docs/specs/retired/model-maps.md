# Spec: Model maps (low maintenance until Track 3 / M6)

> Read only when touching models.html, model-map CI or the interactive layer system.
> Part of Snow-Wx docs v1.0 (Nov 15 2026). Index and priorities: `PLAN.md`.
> Section numbers (§) are kept from the original single plan so cross-references still work.

---

### 5.4 Model maps (low maintenance until Track 3)
- `h500`/`t700` removed from HRRR/RRFS (GFS/ECMWF keep them).
- **Interactive tab (M6, last):** regrid once to Web Mercator (EPSG:3857, ~2–3 km),
  compact value-encoded PNGs, client-side colorizing as a Leaflet overlay,
  hover/tap readout, ski-area/station markers on top; replaces the six
  per-domain PNG sets (expected net size reduction). Must be 3857.
- **Synoptic charts tab:** static GFS (and ECMWF) PNG viewer with pan/zoom.
- Snow-level legend note: "≈ wet-bulb 0 °C height"; evaluate NWS Western Region
  convention (0.5 °C wet-bulb).
- **Hosting note:** thousands of frames are the most likely violation of static-host
  file-count limits (§5.10) — serve them from object storage.
