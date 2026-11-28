"""Step 2 of the history plan: forecast issue history per area, retention, and field summaries for changed forecasts.

Layout (under the store's layout prefix, e.g. v1):
    history/points/<area>/<cycle>-<content prefix>.json   one NBM issue of an area (the document as published)
    history/points/<area>/index.json                       the area's issues, newest last, with their summaries

Retention: issues up to KEEP_DAYS old are kept in full. Older issues are kept only as the newest issue of each UTC
day. The index is the record: history objects are not listed in the manifest (that would grow with every issue).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .store import Store

KEEP_DAYS = 30

# the forecast fields the change log summarises (old and new values), as paths into the area document
WATCH = [
    ("summary", "tag"),
    ("summary", "confidence"),
    ("points", "summit", "totals", "24h", "snow_in"),
    ("points", "summit", "totals", "48h", "snow_in"),
    ("points", "summit", "totals", "72h", "snow_in"),
    ("points", "base", "totals", "24h", "snow_in"),
    ("points", "base", "totals", "48h", "snow_in"),
    ("points", "base", "totals", "72h", "snow_in"),
]

# documents in points/ that are not one area's forecast
NOT_AN_AREA = {"summary", "exceed_summary", "calibration"}


def is_area_doc(key: str, layout: str) -> bool:
    """v1/data/points/<area>.json, not the folder-level summary files and not the layers folder."""
    parts = key.split("/")
    return (len(parts) == 4 and parts[0] == layout and parts[1] == "data" and parts[2] == "points"
            and parts[3].endswith(".json") and parts[3][:-5] not in NOT_AN_AREA)


def parse_doc(raw: bytes | None) -> dict | None:
    """The area document, or None when it is missing, not JSON, or not a forecast (no cycle or points)."""
    if not raw:
        return None
    try:
        doc = json.loads(raw)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) and "cycle" in doc and "points" in doc else None


def _get(doc, path):
    for part in path:
        if not isinstance(doc, dict):
            return None
        doc = doc.get(part)
    return doc


def watched_changes(old: dict, new: dict) -> dict:
    """{field path: [old, new]} for the watched fields whose values differ."""
    out = {}
    for path in WATCH:
        a, b = _get(old, path), _get(new, path)
        if a != b:
            out[".".join(path)] = [a, b]
    return out


def parse_plume(raw: bytes | None) -> dict | None:
    """An ECMWF or GEFS summit plume (models/<model>/plume/<area>.json): a forecast with a cycle and precipitation."""
    if not raw:
        return None
    try:
        doc = json.loads(raw)
    except ValueError:
        return None
    return doc if isinstance(doc, dict) and "cycle" in doc and "tp" in doc else None


def issue_key(layout: str, area: str, cycle: str, content_sha256: str, family: str = "points") -> str:
    return f"{layout}/history/{family}/{area}/{cycle}-{content_sha256[:12]}.json"


def index_key(layout: str, area: str, family: str = "points") -> str:
    return f"{layout}/history/{family}/{area}/index.json"


def issue_entry(doc: dict, key: str, content_sha256: str) -> dict:
    summary = doc.get("summary") or {}
    return {"cycle": doc.get("cycle"), "liquid_cycle": doc.get("liquid_cycle"), "issued": doc.get("issued"),
            "generated_at": doc.get("generated_at"), "content_sha256": content_sha256, "key": key,
            "tag": summary.get("tag"), "confidence": summary.get("confidence")}


def _cycle_time(cycle: str) -> datetime:
    return datetime.strptime(cycle, "%Y%m%d%H").replace(tzinfo=timezone.utc)


def retention(entries: list[dict], now: datetime, keep_days: int = KEEP_DAYS) -> tuple[list[dict], list[dict]]:
    """(kept, expired). Issues newer than keep_days are kept; older ones only when they are the newest issue of their UTC day."""
    cutoff = now - timedelta(days=keep_days)
    newest_by_day = {}
    for e in entries:
        day = _cycle_time(e["cycle"]).date()
        if day not in newest_by_day or e["cycle"] > newest_by_day[day]["cycle"]:
            newest_by_day[day] = e
    kept, expired = [], []
    for e in entries:
        t = _cycle_time(e["cycle"])
        if t >= cutoff or newest_by_day[t.date()] is e:
            kept.append(e)
        else:
            expired.append(e)
    return kept, expired


def update_area_history(store: Store, layout: str, area: str, doc: dict, content_sha256: str, now: datetime,
                       family: str = "points") -> dict:
    """Record one issue for an area: store the document, add it to the index, apply retention. Idempotent per content.
    family: "points" (NBM area forecasts), "ecmwf" or "gefs" (summit plumes)."""
    raw_index = store.get(index_key(layout, area, family))
    index = json.loads(raw_index) if raw_index else {"area": area, "issues": []}
    if any(e["content_sha256"] == content_sha256 for e in index["issues"]):
        return {"written": 0, "expired": 0}
    key = issue_key(layout, area, doc["cycle"], content_sha256, family)
    store.put(key, json.dumps(doc, separators=(",", ":")).encode("utf-8"), "application/json", "public, max-age=31536000, immutable", content_sha256)
    entries = sorted(index["issues"] + [issue_entry(doc, key, content_sha256)], key=lambda e: (e["cycle"], e["content_sha256"]))
    kept, expired = retention(entries, now)
    for e in expired:
        store.delete(e["key"])
    index["issues"] = kept
    index["updated_at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    store.put(index_key(layout, area, family), json.dumps(index, indent=1).encode("utf-8"), "application/json", "no-store")
    return {"written": 1, "expired": len(expired)}
