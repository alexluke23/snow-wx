"""NBM snow forecast overlays for the obs map (PLAN.md Track 2 item 7).

Expected snowfall (24 h, 72 h, 7 d) and the chance of >= 4 / 6 / 12 in (24 h and 72 h) for
the NBM grid, as value-encoded EPSG:3857 PNG layers (pipeline/layers.py, the NOHRSC layer
format) in <points out>/layers/ + index.json. Windows are the first ones ending at 12Z (about
4-5 AM in the West), like the area pages' "Chance of" table. Values are NBM's own fields for
the 2.5 km grid (not elevation-adjusted). Run at the end of the points job (fail-soft).
"""

from __future__ import annotations

import logging
import math
from datetime import timedelta
from pathlib import Path

import numpy as np

from .. import layers as L
from ..common import utcnow, write_json
from .inventory import parse_idx

log = logging.getLogger("snow-wx.nbm")
M_TO_IN = 39.3701
THRESH = {4: ">0.1016", 6: ">0.1524", 12: ">0.3048"}     # NBM thresholds in metres
ATTRIBUTION = "NOAA/NWS National Blend of Models (NBM), 2.5 km grid"


def layer_specs() -> list[dict]:
    snow = {"group": "Forecast", "palette": "SNOWFALL", "scale": 0.1, "offset": 0.0, "units": "in", "clear_below": 0.1}
    prob = {"group": "Forecast", "palette": "PROB", "scale": 1.0, "offset": 0.0, "units": "%", "clear_below": 5}
    out = [{"id": "nbm24", "label": "Expected snowfall, 24 h (NBM forecast)", "hours": 24, "kind": "det", **snow},
           {"id": "nbm72", "label": "Expected snowfall, 72 h (NBM forecast)", "hours": 72, "kind": "det", **snow},
           {"id": "nbm7d", "label": "Expected snowfall, 7 days (NBM forecast)", "hours": 168, "kind": "det7", **snow}]
    for h in (24, 72):
        for t in (4, 6, 12):
            out.append({"id": f"nbmp{h}_{t}", "label": f'Chance of ≥ {t}" in {h} h (NBM forecast)', "hours": h,
                        "kind": "prob", "thr": THRESH[t], **prob})
    return out


def first_end(cycle_hour: int, hours: int, earliest: int) -> int:
    """First forecast hour >= earliest + hours whose valid time is 12Z (window end)."""
    h = earliest + hours
    while (cycle_hour + h) % 24 != 12:
        h += 1
    return h


def plan(cycle_hour: int, specs: list[dict], earliest: int = 5) -> dict[int, list[tuple]]:
    """{file hour: [(key, hours, kind, value)]}: messages to fetch for every layer."""
    need: dict[int, list[tuple]] = {}
    e24 = first_end(cycle_hour, 24, earliest)
    for s in specs:
        if s["kind"] == "det7":
            for d in range(7):
                need.setdefault(e24 + 24 * d, []).append((f"det24_{d}", 24, "det", None))
            continue
        e = first_end(cycle_hour, s["hours"], earliest)
        key = s["id"]
        need.setdefault(e, []).append((key, s["hours"], s["kind"], s.get("thr")))
    return need


def full_field(blob: bytes) -> np.ndarray:
    """Whole NBM message -> (ny, nx) array, south row first, alternating rows unscrambled."""
    import eccodes
    h = eccodes.codes_new_from_message(blob)
    try:
        nx, ny = eccodes.codes_get(h, "Nx"), eccodes.codes_get(h, "Ny")
        alt = bool(eccodes.codes_get(h, "alternativeRowScanning"))
        eccodes.codes_set(h, "missingValue", 9.999e20)
        a = eccodes.codes_get_values(h).reshape(ny, nx).astype("float32")
    finally:
        eccodes.codes_release(h)
    if alt:
        a[1::2] = a[1::2, ::-1].copy()
    a[a > 9e20] = np.nan
    return a


def target_index(grid: dict, target: L.TargetGrid) -> tuple[np.ndarray, np.ndarray]:
    """(j, i) NBM indices for every target pixel (-1 outside the NBM grid)."""
    from ..catalog import nbm_proj
    p = nbm_proj(grid)
    x0, y0 = p(grid["lon1"], grid["lat1"])
    lon, lat = np.meshgrid(target.center_lons(), target.center_lats())
    x, y = p(lon, lat)
    i = np.rint((x - x0) / grid["dx"]).astype(int)
    j = np.rint((y - y0) / grid["dy"]).astype(int)
    ok = (i >= 0) & (i < grid["nx"]) & (j >= 0) & (j < grid["ny"])
    return np.where(ok, j, -1), np.where(ok, i, -1)


def regrid(a: np.ndarray, jj: np.ndarray, ii: np.ndarray) -> np.ndarray:
    out = a[np.clip(jj, 0, None), np.clip(ii, 0, None)].astype("float32")
    out[(jj < 0) | (ii < 0)] = np.nan
    return out


def build_layers(session, cycle, out: Path, grid: dict, bbox, res_m: float = 2500.0) -> dict | None:
    """Fetch, regrid, encode; writes out/<id>.png + out/index.json. Returns the index."""
    from .run import _get, url
    if cycle.hour not in (1, 7, 13, 19):
        log.info("NBM layers: %02dZ cycle has no 24/72-h snowfall fields; skipped", cycle.hour)
        return None
    specs = layer_specs()
    need = plan(cycle.hour, specs)
    fields: dict[str, np.ndarray] = {}
    for fh, wants in sorted(need.items()):
        r = _get(session, url(cycle, "core", fh) + ".idx")
        if r is None:
            log.warning("NBM layers: no idx for f%03d", fh)
            continue
        msgs = parse_idx(r.text)
        for key, hours, kind, value in wants:
            m = next((m for m in msgs if m.var == "ASNOW" and m.level == "surface" and m.end == fh and m.start is not None
                      and m.end - m.start == hours and m.kind == ("det" if kind in ("det", "det7") else "prob")
                      and (value is None or m.value == value) and m.length), None)
            if m is None:
                log.warning("NBM layers: %s not in f%03d", key, fh)
                continue
            blob = _get(session, url(cycle, "core", fh), {"Range": f"bytes={m.offset}-{m.offset + m.length - 1}"}).content
            a = full_field(blob)
            fields[key] = a * M_TO_IN if kind in ("det", "det7") else a
    days = [fields.get(f"det24_{d}") for d in range(7)]
    if all(x is not None for x in days):
        fields["nbm7d"] = np.sum(days, axis=0)
    target = L.TargetGrid.from_bbox(*bbox, res=res_m)
    jj, ii = target_index(grid, target)
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    layers = []
    e24 = first_end(cycle.hour, 24, 5)
    for s in specs:
        a = fields.get(s["id"])
        if a is None:
            continue
        e = e24 + 24 * 6 if s["kind"] == "det7" else first_end(cycle.hour, s["hours"], 5)
        end = cycle + timedelta(hours=e)
        start = end - timedelta(hours=s["hours"])
        rg = regrid(a, jj, ii)
        png = L.png_bytes(L.encode(rg, s["scale"], s["offset"]))
        (out / f"{s['id']}.png").write_bytes(png)
        finite = rg[np.isfinite(rg)]
        layers.append({k: v for k, v in s.items() if k not in ("hours", "kind", "thr")} | {
            "start": start.strftime("%Y-%m-%dT%H:%MZ"), "valid": end.strftime("%Y-%m-%dT%H:%MZ"),
            "cycle": cycle.strftime("%Y%m%d%H"), "source": f"NBM {cycle:%H}Z {cycle:%d %b}", "file": f"{s['id']}.png",
            "bytes": len(png), "max": round(float(finite.max()), 1) if finite.size else None, **target.meta()})
    idx = {"key": cycle.strftime("%Y%m%d%H"), "generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
           "attribution": ATTRIBUTION, "group": "Forecast", "layers": layers}
    write_json(out / "index.json", idx, ndigits=6)
    log.info("NBM layers %s: %d layers, %.1f MB (%s)", idx["key"], len(layers), sum(x["bytes"] for x in layers) / 1e6,
             ", ".join(f"{x['id']} {x['bytes'] // 1024} KB" for x in layers))
    return idx
