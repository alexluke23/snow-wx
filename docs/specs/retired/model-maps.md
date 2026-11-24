---
status: retired
owner: team
last_reviewed: 2026-11-23
read_when: history only
---

# Spec: Model maps (low maintenance until Track 3 / M6)

> **RETIRED Nov 23 2026** (team decision; `docs/DECISIONS.md`). The Models page, map-frame rendering, M6 interactive layers and the synoptic-charts tab are removed or cancelled. **Not retired:** the HRRR/RRFS/GFS/ECMWF/GEFS point sampling that feeds the plumes (`docs/specs/multi-model.md`). Kept for history only.

> Read only when touching models.html, model-map CI or the interactive layer system.
> Part of Snow-Wx docs v1.0 (Nov 15 2026). Index and priorities: `docs/PLAN.md`; doc map `docs/INDEX.md`.
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
