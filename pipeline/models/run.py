"""Model-map run orchestration.

  1. pick the newest complete cycle (or skip if it is already published)
  2. download frames (threads, a few ahead) and derive map fields in order
     (accumulations need the previous frame), saving one .npz per frame
  3. render PNGs in a process pool as frames become ready
  4. write <out>/<model>/index.json and drop older cycles
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from concurrent.futures import Future, ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..common import REPO_ROOT, utcnow, write_json
from . import derive as d
from .config import FIELD_INFO, QPF_WINDOWS, expand_fhours, field_domains, field_fhours
from .fetch import (Grid, candidate_cycles, cycle_complete, decode, download_frame,
                    latest_cycle, needed_vars, var_catalog)

log = logging.getLogger("snow-wx.models")


# ---------------------------------------------------------------- derivation (pure)

@dataclass
class RunState:
    """What carries over between frames: run totals and snowfall sums."""
    totals: dict[int, np.ndarray] = field(default_factory=dict)   # QPF since init, in
    prev_f: int | None = None
    snow10: np.ndarray | None = None
    snowku: np.ndarray | None = None


def _level_heights(raw: dict, levels: list[int]) -> dict[int, np.ndarray]:
    """Heights for every level; fills a missing level (HRRR has no 925 mb HGT) in ln p."""
    z = {p: raw[f"gh{p}"] for p in levels if f"gh{p}" in raw}
    for p in levels:
        if p in z:
            continue
        lower = [q for q in z if q > p]
        upper = [q for q in z if q < p]
        if lower and upper:
            lo, hi = min(lower), max(upper)
            z[p] = d.height_lnp(z[lo], lo, z[hi], hi, p)
    return z


def derive_frame(raw: dict[str, np.ndarray], grid: Grid, mcfg: dict, fields: list[str],
                 f: int, state: RunState) -> dict[str, np.ndarray]:
    """Map-ready arrays (US units unless noted) for forecast hour f.

    Must be called for frames in increasing f; `state` is updated in place.
    """
    out: dict[str, np.ndarray] = {}
    levels = sorted(mcfg["levels"], reverse=True)
    want = set(fields)
    shape = grid.lat.shape
    if "orog" in raw:
        out["orog_ft"] = d.m_to_ft(raw["orog"])

    # --- precipitation since init (all windows come from differencing these)
    if any(x.startswith("qpf") for x in want) or "snow" in want or "snowlevel" in want:
        if f == 0:
            total = np.zeros(shape, np.float32)
        elif "apcp" in raw:
            total = d.mm_to_in(raw["apcp"])
        else:
            raise KeyError(f"f{f:03d}: no run-total APCP")
        state.totals[f] = total
        for name, n in QPF_WINDOWS.items():
            if name in want:
                q = d.qpf_window(state.totals, f, n)
                if q is not None:
                    out[name] = q
        if "qpf_total" in want and f > 0:
            out["qpf_total"] = total

    # --- snowfall: 10:1 and Kuchera, accumulated step by step
    if "snow" in want:
        if state.prev_f is not None and f > state.prev_f:
            dq = np.maximum(total - state.totals[state.prev_f], 0.0)
            frz = d.frozen_fraction(raw.get("cpofp"), raw.get("csnow"))
            z = _level_heights(raw, levels)
            tmax = d.column_tmax(raw["t2m"], {p: raw[f"t{p}"] for p in levels if f"t{p}" in raw},
                                 raw["sp"], z, raw.get("orog"))
            slr = d.kuchera_slr(tmax)
            state.snow10 = d.accumulate(state.snow10, dq * frz * 10.0)
            state.snowku = d.accumulate(state.snowku, dq * frz * slr)
        if f > 0 and state.snow10 is not None:
            out["snow10"] = state.snow10
            out["snowku"] = state.snowku

    # --- snow level (wet-bulb zero height) and freezing level
    if "snowlevel" in want:
        z = _level_heights(raw, levels)
        t2c = d.k_to_c(raw["t2m"])
        tw_sfc = d.wetbulb_stull(t2c, d.rh_from_dewpoint(t2c, d.k_to_c(raw["d2m"])))
        prof = []
        for p in levels:
            if f"t{p}" not in raw or p not in z:
                continue
            tc = d.k_to_c(raw[f"t{p}"])
            if f"dpt{p}" in raw:
                rh = d.rh_from_dewpoint(tc, d.k_to_c(raw[f"dpt{p}"]))
            elif f"rh{p}" in raw:
                rh = raw[f"rh{p}"]
            else:
                continue
            prof.append((p, z[p], d.wetbulb_stull(tc, rh)))
        wbz = d.wetbulb_zero_height(raw["orog"], tw_sfc, prof, raw["sp"])
        if "hgt0c" in raw:
            # Tw <= T, so the wet-bulb zero can't sit above the lowest 0 °C level; coarse
            # pressure levels (850 -> 700 mb is ~5000 ft) can interpolate past it.
            wbz = d.cap_at(wbz, raw["hgt0c"])
        out["snowlevel_ft"] = d.m_to_ft(wbz)
        out["snow_at_sfc"] = (tw_sfc <= 0.0).astype(np.float32)
        if "fzl_top" in raw:
            fz_sigma = 15_000.0 / max(grid.dx_m, 1.0)
            out["fzl_ft"] = d.smooth(d.m_to_ft(raw["fzl_top"]), fz_sigma)
        if state.prev_f is not None and f in state.totals:   # precip falling in the last step
            step = state.totals[f] - state.totals[state.prev_f]
            out["precip_now"] = (step >= 0.01).astype(np.float32)

    # --- upper air
    sigma = float(mcfg.get("smooth_km", 0) or 0) * 1000.0 / max(grid.dx_m, 1.0)
    if "h500" in want:
        out["h500_dam"] = d.smooth(raw["gh500"] / 10.0, sigma)
        if "absv500" in raw:
            vort = raw["absv500"]
        else:
            vort = d.absolute_vorticity(raw["u500"], raw["v500"], grid.lat, grid.dx_m, grid.dy_m)
        out["vort500"] = d.smooth(vort * 1e5, sigma)
    if "t700" in want:
        out["t700_c"] = d.smooth(d.k_to_c(raw["t700"]), sigma / 3)
        out["h700_dam"] = d.smooth(raw["gh700"] / 10.0, sigma)
        out["u700_kt"] = d.ms_to_kt(raw["u700"])
        out["v700_kt"] = d.ms_to_kt(raw["v700"])

    # --- surface
    if "t2m" in want:
        out["t2m_f"] = d.k_to_f(raw["t2m"])
    if "gust" in want:
        out["gust_kt"] = d.ms_to_kt(raw["gust"])

    state.prev_f = f
    return {k: np.asarray(v, dtype=np.float32) for k, v in out.items()}


# ---------------------------------------------------------------- orchestration

def models_out_dir(out: Path, model: str) -> Path:
    return Path(out) / model


def _cache_dir(cfg: dict) -> Path:
    p = Path(cfg.get("cache_dir", "data_cache/herbie"))
    return p if p.is_absolute() else REPO_ROOT / p


def _github_output(path: str | None, **kv) -> None:
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        for k, v in kv.items():
            f.write(f"{k}={v}\n")


def run_model(cfg: dict, model: str, out: Path, *, fhours: list[int] | None = None,
              domains: list[str] | None = None, fields: list[str] | None = None,
              cycle: datetime | None = None, published: str | None = None,
              workers: int | None = None, keep_grib: bool = False,
              github_output: str | None = None, now: datetime | None = None) -> int:
    """Produce maps for the newest complete cycle of one model. Returns an exit code.

    Exit 0 with nothing written when the newest cycle equals `published`
    (or no cycle is complete yet) so scheduled runs can no-op cleanly.
    """
    t_start = time.time()
    mcfg = dict(cfg["models"][model])
    fh = sorted(fhours) if fhours else expand_fhours(mcfg["fhours"])
    use_fields = list(fields) if fields else list(mcfg["fields"])
    cache = _cache_dir(cfg) / model
    cache.mkdir(parents=True, exist_ok=True)

    if cycle is None:
        cands = candidate_cycles(now or utcnow(), mcfg["cycles"])
        cycle = latest_cycle(cands, lambda c: cycle_complete(mcfg, c, max(fh), cache))
        if cycle is None:
            log.warning("%s: no complete cycle in the last 36 h", model)
            _github_output(github_output, new="false")
            return 0
    cid = cycle.strftime("%Y%m%d%H")
    if published and published == cid:
        log.info("%s: newest complete cycle %s is already published; nothing new", model, cid)
        _github_output(github_output, new="false", cycle=cid)
        return 0
    log.info("%s: cycle %s, %d frames, fields %s", model, cid, len(fh), ",".join(use_fields))

    from .plot import map_lonlat_bounds
    extent = map_lonlat_bounds([cfg["domains"][dname]["extent"] for dname in mcfg["domains"]])
    doms_by_field = {f: [x for x in field_domains(cfg, model, f) if not domains or x in domains]
                     for f in use_fields}
    fh_by_field = {f: set(field_fhours(f, fh)) for f in use_fields}

    model_dir = models_out_dir(out, model)
    run_dir = model_dir / cid
    if run_dir.exists():
        shutil.rmtree(run_dir)
    work = cache / f"frames_{cid}"
    work.mkdir(parents=True, exist_ok=True)

    catalog = var_catalog(mcfg["levels"])
    names = needed_vars(mcfg, use_fields)
    state = RunState()
    grid: Grid | None = None
    grid_path = work / "grid.npz"
    results: list[dict] = []
    failed_frames: list[int] = []
    plot_futures: list[Future] = []
    meta = {"model": model, "label": mcfg["label"], "cycle": cycle.replace(tzinfo=timezone.utc),
            "attribution": mcfg.get("attribution", ""), "image": cfg.get("image", {}),
            "domains": cfg["domains"]}

    from .plot import ensure_basemap_data, render_task
    ensure_basemap_data()   # download Natural Earth once, before workers race for it

    n_workers = workers or max(1, min(os.cpu_count() or 2, 8) - 1)
    t_fetch = 0.0
    with ThreadPoolExecutor(max_workers=4) as dl, \
            ProcessPoolExecutor(max_workers=n_workers) as pool:
        downloads = {f: dl.submit(download_frame, mcfg, catalog, names, cycle, f, cache) for f in fh}
        for f in fh:
            t0 = time.time()
            try:
                paths = downloads[f].result()
                raw, grid = decode(paths, catalog, names, extent, grid)
                if not keep_grib:
                    for p in paths:
                        p.unlink(missing_ok=True)
                arrays = derive_frame(raw, grid, mcfg, use_fields, f, state)
            except Exception as exc:
                # Later accumulations continue from the last good frame (state.prev_f).
                log.warning("%s f%03d failed: %s", model, f, exc)
                failed_frames.append(f)
                continue
            finally:
                t_fetch += time.time() - t0
            if not grid_path.exists():
                np.savez(grid_path, lat=grid.lat, lon=grid.lon,
                         crs=json.dumps(grid.crs), uv_rel=grid.uv_grid_relative)
            frame_path = work / f"f{f:03d}.npz"
            np.savez(frame_path, **arrays)
            for dom in cfg["domains"]:
                todo = [fld for fld in use_fields if f in fh_by_field[fld] and dom in doms_by_field[fld]]
                if todo:
                    plot_futures.append(pool.submit(render_task, str(grid_path), str(frame_path), dom,
                                                    todo, f, str(run_dir), meta))
        for fut in plot_futures:
            try:
                results.extend(fut.result())
            except Exception as exc:
                log.warning("%s plot task failed: %s", model, exc)

    shutil.rmtree(work, ignore_errors=True)
    ok = [r for r in results if r.get("ok")]
    bad = [r for r in results if not r.get("ok")]
    for r in bad[:10]:
        log.warning("plot %s %s f%03d: %s", r["field"], r["domain"], r["f"], r.get("error"))
    if not ok:
        log.error("%s: no images produced", model)
        return 1

    index = build_index(cfg, model, cycle, ok)
    index["seconds"] = round(time.time() - t_start, 1)
    index["failed_frames"] = failed_frames
    write_json(model_dir / "index.json", index)
    for old in model_dir.iterdir():   # keep only this cycle
        if old.is_dir() and old.name != cid:
            shutil.rmtree(old, ignore_errors=True)
    mb = sum(r["bytes"] for r in ok) / 1e6
    log.info("%s %s: %d images, %.1f MB, %d plot errors, %d failed frames; fetch+derive %.0f s, "
             "total %.0f s", model, cid, len(ok), mb, len(bad), len(failed_frames), t_fetch,
             time.time() - t_start)
    _github_output(github_output, new="true", cycle=cid)
    return 0


def build_index(cfg: dict, model: str, cycle: datetime, ok: list[dict]) -> dict:
    """Index JSON the viewer reads: fields, domains and forecast hours that exist."""
    mcfg = cfg["models"][model]
    cid = cycle.strftime("%Y%m%d%H")
    fields: dict[str, dict] = {}
    for r in ok:
        e = fields.setdefault(r["field"], {"domains": set(), "fhours": set()})
        e["domains"].add(r["domain"])
        e["fhours"].add(r["f"])
    order = list(cfg["domains"])
    return {
        "model": model,
        "label": mcfg["label"],
        "cycle": cid,
        "init": cycle.strftime("%Y-%m-%dT%H:00Z"),
        "generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "attribution": mcfg.get("attribution", ""),
        "path": f"{cid}/{{field}}/{{domain}}/f{{fhour}}.png",
        "domains": {k: {"label": v["label"]} for k, v in cfg["domains"].items()},
        "fields": {
            name: {**FIELD_INFO[name],
                   "domains": sorted(fields[name]["domains"], key=order.index),
                   "fhours": sorted(fields[name]["fhours"])}
            for name in mcfg["fields"] if name in fields
        },
        "images": len(ok),
        "bytes": sum(r["bytes"] for r in ok),
    }
