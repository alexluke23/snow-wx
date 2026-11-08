"""Site-wide search index (header search on every page): data/search.json.

One small list of every place with a forecast page: ski areas (data/ski_areas.json) and
SNOTEL sites (data/snotel_points.json); Sno-Parks will join here. The browser ranks it
with web/js/search.js (the same ranking as the obs-map panel search).

Record: {"k": kind, "id": page id, "n": name, "s": subtitle, "x": extra ids to match}
"""

from __future__ import annotations

import json
from pathlib import Path

from .common import REPO_ROOT, write_json


def build_index(repo: Path = REPO_ROOT) -> dict:
    items = []
    cat = repo / "data" / "ski_areas.json"
    if cat.exists():
        for a in json.loads(cat.read_text(encoding="utf-8"))["areas"]:
            items.append({"k": "area", "id": a["id"], "n": a["name"], "s": f"Ski area · {a.get('region', '')}, {a.get('state', '')}"})
    sp = repo / "data" / "snotel_points.json"
    if sp.exists():
        for p in json.loads(sp.read_text(encoding="utf-8"))["points"]:
            num = p["triplet"].split(":")[0]
            elev = f" · {round(p['elev_ft']):,} ft" if p.get("elev_ft") else ""
            items.append({"k": "snotel", "id": p["id"], "n": p["name"], "s": f"SNOTEL {num} · {p.get('state', '')}{elev}",
                          "x": [num, p["triplet"]]})
    return {"items": items}


def write_index(outdir: Path, repo: Path = REPO_ROOT) -> int:
    idx = build_index(repo)
    write_json(Path(outdir) / "search.json", idx)
    return len(idx["items"])
