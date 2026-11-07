"""Site-wide model catalog: merges <models>/<model>/index.json files.

Each model is rendered by its own job/schedule, so the site build combines
whatever per-model indexes are present into models/index.json for the viewer.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..common import utcnow, write_json

log = logging.getLogger("snow-wx.models")


def collect(models_dir: Path, order: list[str] | None = None) -> dict:
    found = {}
    for p in sorted(Path(models_dir).glob("*/index.json")):
        try:
            idx = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("skipping %s: %s", p, exc)
            continue
        idx["base"] = f"{p.parent.name}/"
        found[idx.get("model", p.parent.name)] = idx
    names = [m for m in (order or []) if m in found] + sorted(m for m in found if m not in (order or []))
    return {"generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "models": {m: found[m] for m in names}}


def write_catalog(models_dir: Path, order: list[str] | None = None) -> dict:
    cat = collect(models_dir, order)
    write_json(Path(models_dir) / "index.json", cat)
    log.info("model catalog: %s", ", ".join(f"{m} {i['cycle']}" for m, i in cat["models"].items())
             or "no model runs yet")
    return cat
