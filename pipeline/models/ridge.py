"""Ridge-top (free-air) wind at each ski area's summit from HRRR / RRFS pressure levels
(PLAN.md S4 item C). Pure functions plus the per-run sampler and the site-build merge.

Method: nearest model grid column to the summit; wind interpolated linearly in height
between the pressure levels that bracket the summit elevation (equivalent to the
summit's pressure level). A bracketing level whose height is below the model terrain
there (extrapolated "underground" values) is not used: the lowest level above the
model ground is taken instead. Grid-relative winds (Lambert grids) are rotated to
earth-relative with the cone constant, as wgrib2 does.

Outputs: <models>/<model>/ridge.json per run; `merge` -> build/data/ridge.json
(HRRR to 48 h, then RRFS to 84 h).
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from ..common import REPO_ROOT, utcnow, write_json

log = logging.getLogger("snow-wx.models")
MS_TO_MPH = 2.236936


def cone_constant(lat1: float, lat2: float) -> float:
    a, b = math.radians(lat1), math.radians(lat2)
    if abs(a - b) < 1e-9:
        return math.sin(a)
    return math.log(math.cos(a) / math.cos(b)) / math.log(math.tan(math.pi / 4 + b / 2) / math.tan(math.pi / 4 + a / 2))


def earth_relative(u, v, lon, crs: dict, grid_relative: bool):
    """Rotate grid-relative u/v on a Lambert grid to earth-relative (no-op otherwise)."""
    if not grid_relative or crs.get("kind") != "lcc":
        return u, v
    n = cone_constant(crs["lat1"], crs["lat2"])
    dlon = ((np.asarray(lon) - crs["lon0"] + 180.0) % 360.0) - 180.0
    ang = np.radians(n * dlon)
    c, s = np.cos(ang), np.sin(ang)
    return c * u + s * v, -s * u + c * v


def speed_dir(u, v):
    """(speed, meteorological direction the wind blows FROM, degrees)."""
    spd = math.hypot(u, v)
    return spd, (270.0 - math.degrees(math.atan2(v, u))) % 360.0


def nearest_index(lat: np.ndarray, lon: np.ndarray, pts: list[tuple[float, float]]) -> list[tuple[int, int] | None]:
    """Nearest grid cell (row, col) per (lat, lon); None if outside the cropped grid."""
    out = []
    coslat = np.cos(np.radians(lat))
    for la, lo in pts:
        d2 = (lat - la) ** 2 + ((lon - lo) * coslat) ** 2
        k = int(np.nanargmin(d2))
        r, c = np.unravel_index(k, lat.shape)
        out.append((int(r), int(c)) if d2[r, c] < 0.1 ** 2 else None)   # within ~10 km
    return out


def interp_wind(z_m: float, levels: list[tuple[float, float, float]], ground_m: float | None):
    """levels: [(height m, u, v)] any order -> (u, v) at height z_m, or None.
    Levels below the model ground are ignored; outside the profile -> nearest level."""
    prof = sorted((h, u, v) for h, u, v in levels
                  if all(np.isfinite(x) for x in (h, u, v)) and (ground_m is None or h >= ground_m))
    if not prof:
        return None
    if z_m <= prof[0][0]:
        return prof[0][1], prof[0][2]
    if z_m >= prof[-1][0]:
        return prof[-1][1], prof[-1][2]
    for (h0, u0, v0), (h1, u1, v1) in zip(prof, prof[1:]):
        if h0 <= z_m <= h1:
            w = (z_m - h0) / (h1 - h0) if h1 > h0 else 0.0
            return u0 + w * (u1 - u0), v0 + w * (v1 - v0)
    return None


def ridge_vars(mcfg: dict) -> list[str]:
    lv = (mcfg.get("ridge") or {}).get("levels") or []
    return sorted({f"{k}{p}" for p in lv for k in ("u", "v", "gh")} | {"orog"})


def load_summits(repo: Path = REPO_ROOT) -> list[dict]:
    cat = json.loads((repo / "data" / "ski_areas.json").read_text(encoding="utf-8"))
    return [{"id": a["id"], "lat": a["summit"]["lat"], "lon": a["summit"]["lon"],
             "elev_m": a["summit"]["elev_ft"] * 0.3048} for a in cat["areas"] if a.get("summit")]


class Sampler:
    """Collects summit winds frame by frame for one model run."""

    def __init__(self, mcfg: dict, summits: list[dict]):
        self.levels = list((mcfg.get("ridge") or {}).get("levels") or [])
        self.summits = summits
        self.idx = None
        self.hours: list[int] = []
        self.rows: list[list] = []

    def add(self, f: int, raw: dict, grid) -> None:
        if not self.levels:
            return
        if self.idx is None:
            self.idx = nearest_index(grid.lat, grid.lon, [(s["lat"], s["lon"]) for s in self.summits])
        row = []
        for s, ij in zip(self.summits, self.idx):
            if ij is None:
                row.append(None)
                continue
            r, c = ij
            prof = [(float(raw[f"gh{p}"][r, c]), float(raw[f"u{p}"][r, c]), float(raw[f"v{p}"][r, c]))
                    for p in self.levels if all(f"{k}{p}" in raw for k in ("gh", "u", "v"))]
            ground = float(raw["orog"][r, c]) if "orog" in raw else None
            uv = interp_wind(s["elev_m"], prof, ground)
            if uv is None:
                row.append(None)
                continue
            ue, ve = earth_relative(np.float64(uv[0]), np.float64(uv[1]), grid.lon[r, c], grid.crs, grid.uv_grid_relative)
            spd, dd = speed_dir(float(ue), float(ve))
            row.append([round(spd * MS_TO_MPH), int(round(dd)) % 360])
        self.hours.append(f)
        self.rows.append(row)

    def document(self, model: str, label: str, cycle: datetime) -> dict:
        order = sorted(range(len(self.hours)), key=lambda k: self.hours[k])
        hours = [self.hours[k] for k in order]
        areas = {}
        for j, s in enumerate(self.summits):
            vals = [self.rows[k][j] for k in order]
            if any(v is not None for v in vals):
                areas[s["id"]] = {"mph": [None if v is None else v[0] for v in vals],
                                  "dir": [None if v is None else v[1] for v in vals]}
        return {"model": model, "label": label, "cycle": cycle.strftime("%Y%m%d%H"),
                "init": cycle.strftime("%Y-%m-%dT%H:00Z"), "levels_mb": self.levels,
                "valid": [(cycle + timedelta(hours=h)).strftime("%Y-%m-%dT%H:%MZ") for h in hours],
                "hours": hours, "areas": areas}


def merge(models_dir: Path, out_path: Path, order=("hrrr", "rrfs")) -> dict | None:
    """One site file: the first model (HRRR) for its whole range, later models only
    after the previous one ends. Each value records its model."""
    docs = []
    for m in order:
        p = Path(models_dir) / m / "ridge.json"
        if p.exists():
            try:
                docs.append(json.loads(p.read_text(encoding="utf-8")))
            except ValueError:
                log.warning("ridge: bad %s", p)
    if not docs:
        return None
    times, src = [], []
    picks = []                           # (doc index, position)
    last = ""
    for n, d in enumerate(docs):
        for k, t in enumerate(d["valid"]):
            if t > last:
                picks.append((n, k)); times.append(t); src.append(n)
        last = max(last, d["valid"][-1] if d["valid"] else last)
    ids = sorted({a for d in docs for a in d["areas"]})
    areas = {}
    for a in ids:
        mph = [docs[n]["areas"].get(a, {}).get("mph", [None] * len(docs[n]["valid"]))[k] for n, k in picks]
        dd = [docs[n]["areas"].get(a, {}).get("dir", [None] * len(docs[n]["valid"]))[k] for n, k in picks]
        areas[a] = {"mph": mph, "dir": dd}
    doc = {"generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
           "models": [{"model": d["model"], "label": d["label"], "cycle": d["cycle"], "init": d["init"]} for d in docs],
           "valid": times, "src": src, "areas": areas}
    write_json(Path(out_path), doc)
    log.info("ridge wind: %s -> %d times, %d areas", "+".join(d["label"] for d in docs), len(times), len(areas))
    return doc
