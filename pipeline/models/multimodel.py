"""Precipitation by model at every ski area's summit (M7, docs/specs/multi-model.md; PLAN §8.3).

Per model run the loop in run.py hands each derived frame to `PrecipSampler`, which keeps the RUN-TOTAL liquid precipitation (APCP since
init, inches; the same array the QPF maps difference) at the nearest grid cell of every area's summit coordinates, plus the model's own
terrain height there. The sampler writes <models>/<model>/precip.json; `merge` combines the models into ONE site file
data/multimodel.json (like ridge.json). No new source: these are the HRRR / RRFS / GFS fields the model maps already download.

Nothing is summed across models and no percentiles are involved. Series are cumulative from each model's OWN init; the page aligns them to a
common start (js/multimodel.js `rebase`, linear interpolation of a cumulative series) and adds the NBM line from the points file.
Config: models.yml `multi_model: {enabled: true}` (false = no sampling, no file; the page then says the comparison is unavailable).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from ..common import REPO_ROOT, utcnow, write_json
from .ridge import nearest_index

log = logging.getLogger("snow-wx.models")
ORDER = ("hrrr", "rrfs", "gfs")


def load_points(repo: Path = REPO_ROOT) -> list[dict]:
    """One sample point per ski area: the summit (the page's headline point)."""
    cat = json.loads((repo / "data" / "ski_areas.json").read_text(encoding="utf-8"))
    return [{"id": a["id"], "lat": a["summit"]["lat"], "lon": a["summit"]["lon"], "elev_ft": a["summit"]["elev_ft"]}
            for a in cat["areas"] if a.get("summit")]


class PrecipSampler:
    """Collects run-total precipitation at each point, frame by frame, for one model run."""

    def __init__(self, points: list[dict]):
        self.points = points
        self.idx = None
        self.hours: list[int] = []
        self.rows: list[list] = []
        self.terrain: list[int | None] = [None] * len(points)

    def add(self, f: int, arrays: dict, grid) -> None:
        """`arrays` = derive_frame output (needs qpf_total for f > 0; orog_ft once)."""
        if self.idx is None:
            # 0.3 deg: a 0.25-degree GFS grid center can be ~0.18 deg from a point; the model terrain at the cell is reported with the series
            self.idx = nearest_index(grid.lat, grid.lon, [(p["lat"], p["lon"]) for p in self.points], max_deg=0.3)
        total = arrays.get("qpf_total")
        if f > 0 and total is None:
            return                                                      # this frame has no run total: skip it, the series just has a gap
        orog = arrays.get("orog_ft")
        row = []
        for j, ij in enumerate(self.idx):
            if ij is None:
                row.append(None)
                continue
            r, c = ij
            v = 0.0 if f == 0 else float(total[r, c])
            row.append(None if not np.isfinite(v) else round(max(v, 0.0), 2))
            if orog is not None and self.terrain[j] is None and np.isfinite(orog[r, c]):
                self.terrain[j] = int(round(float(orog[r, c])))
        self.hours.append(f)
        self.rows.append(row)

    def document(self, model: str, label: str, cycle: datetime) -> dict:
        order = sorted(range(len(self.hours)), key=lambda k: self.hours[k])
        hours = [self.hours[k] for k in order]
        areas = {}
        for j, p in enumerate(self.points):
            q = [self.rows[k][j] for k in order]
            if any(v is not None for v in q):
                areas[p["id"]] = {"q": q, "z": self.terrain[j]}
        return {"model": model, "label": label, "cycle": cycle.strftime("%Y%m%d%H"), "init": cycle.strftime("%Y-%m-%dT%H:00Z"),
                "hours": hours, "areas": areas}


def merge(models_dir: Path, out_path: Path, order=ORDER) -> dict | None:
    """data/multimodel.json: {generated_at, models: [{model, label, cycle, init, hours}], areas: {id: {model: {q, z}}}}.
    Each model keeps its own hours and init; q is cumulative liquid precipitation (in) since that init."""
    docs = []
    for m in order:
        p = Path(models_dir) / m / "precip.json"
        if p.exists():
            try:
                docs.append(json.loads(p.read_text(encoding="utf-8")))
            except ValueError:
                log.warning("multimodel: bad %s", p)
    if not docs:
        return None
    areas: dict[str, dict] = {}
    for d in docs:
        for aid, a in d["areas"].items():
            areas.setdefault(aid, {})[d["model"]] = {"q": a["q"], "z": a.get("z")}
    doc = {"generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
           "units": "inches of liquid precipitation, cumulative since each model's own init",
           "models": [{"model": d["model"], "label": d["label"], "cycle": d["cycle"], "init": d["init"], "hours": d["hours"]} for d in docs],
           "areas": areas}
    write_json(Path(out_path), doc)
    log.info("multimodel: %s -> %d areas", "+".join(d["label"] for d in docs), len(areas))
    return doc


def rebase(init: datetime, hours: list[int], q: list, t0: datetime) -> list | None:
    """Reference implementation of the page's alignment (js/multimodel.js `rebase`): cumulative q (None = gap) since `init`, re-expressed as
    liquid since t0 by linear interpolation of the cumulative series; None where t0 is outside the series or a bracketing value is missing."""
    xs = [(init + timedelta(hours=h) - t0).total_seconds() / 3600 for h in hours]
    pts = [(x, v) for x, v in zip(xs, q) if v is not None]
    if not pts or not (pts[0][0] <= 0 <= pts[-1][0]):
        return None
    base = None
    for (x0, v0), (x1, v1) in zip(pts, pts[1:] + [pts[-1]]):
        if x0 <= 0 <= x1:
            base = v0 if x1 == x0 else v0 + (v1 - v0) * (0 - x0) / (x1 - x0)
            break
    return [None if v is None else round(v - base, 3) for v in q]
