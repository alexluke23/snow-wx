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
    rp = repo / "data" / "rec_points.json"
    if rp.exists():
        for a in json.loads(rp.read_text(encoding="utf-8"))["areas"]:
            items.append({"k": "snopark", "id": a["id"], "n": a["name"],
                          "s": f"{a.get('type_label', 'Sno-Park')} · {a.get('region', '')}, {a.get('state', '')}"})
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


def map_points(repo: Path = REPO_ROOT) -> dict:
    """Compact ski-area + Sno-Park list for the obs map (symbols and popups only): the full
    catalogs are ~170 KB + more; the map needs a few fields per place."""
    pt = lambda p: {"lat": p["lat"], "lon": p["lon"], "elev_ft": p.get("elev_ft")}  # noqa: E731
    out = {"areas": [], "snoparks": []}
    cat = repo / "data" / "ski_areas.json"
    if cat.exists():
        js = json.loads(cat.read_text(encoding="utf-8"))
        out["attribution"] = js.get("attribution")
        for a in js["areas"]:
            out["areas"].append({"id": a["id"], "name": a["name"], "region": a.get("region"), "state": a.get("state"),
                                 "major": a.get("major", False), "base": pt(a["base"]), "summit": pt(a["summit"]),
                                 "vertical_ft": a.get("vertical_ft"), "lifts": a.get("lifts"), "url": a.get("url"),
                                 "avalanche": {"zone": a["avalanche"]["zone"]} if a.get("avalanche") else None})
    rp = repo / "data" / "rec_points.json"
    if rp.exists():
        for a in json.loads(rp.read_text(encoding="utf-8"))["areas"]:
            out["snoparks"].append({"id": a["id"], "name": a["name"], "region": a.get("region"), "state": a.get("state"),
                                    "type_label": a.get("type_label"), "permit": a.get("permit"),
                                    "base": pt(a["base"]), "summit": pt(a["summit"]),
                                    "avalanche": {"zone": a["avalanche"]["zone"]} if a.get("avalanche") else None})
    return out


def write_map_points(outdir: Path, repo: Path = REPO_ROOT) -> None:
    write_json(Path(outdir) / "map_points.json", map_points(repo))
