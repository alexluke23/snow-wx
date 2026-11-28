"""Step 3 of the history plan: observation history for SNOTEL stations and ASOS stations (JSON, kept indefinitely).

Layout (under the store's layout prefix, e.g. v1):
    history/obs/<network>/<station>/<YYYY-MM>.json   one station's readings for one UTC month
    history/obs/<network>/<station>/index.json       the station's months: row counts and first and last times

A month file holds:
    rows       {"2026-11-27T06:00Z": {"WTEQ": 2.2, ...}}   one entry per reading time (UTC), the latest value seen
    revisions  [{"time", "element", "old", "new"}, ...]    every change to a value already stored (e.g. after QC)

SNOTEL station files overlap (each holds a rolling 7-day window), so a reading is added once, when first seen. A reading
that is later revised is updated and its old value is kept in `revisions`. ASOS publishes only the latest report per station,
so ASOS history starts with the first run that includes this step.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from .store import Store

SNOTEL_ELEMENTS = ("WTEQ", "SNWD", "PREC", "TOBS")
ASOS_ELEMENTS = ("temp_f", "dewp_f", "rh", "wind_kt", "wind_dir", "vis_mi", "precip_today_in")
ISO = "%Y-%m-%dT%H:%MZ"


def safe(station: str) -> str:
    return station.replace(":", "_").replace("/", "_")


def month_key(layout: str, network: str, station: str, month: str) -> str:
    return f"{layout}/history/obs/{network}/{safe(station)}/{month}.json"


def index_key(layout: str, network: str, station: str) -> str:
    return f"{layout}/history/obs/{network}/{safe(station)}/index.json"


def snotel_rows(doc: dict) -> dict[str, dict]:
    """A SNOTEL station file -> {UTC time: {element: value}}. The file's times are local standard time (utc_offset_h)."""
    offset = float(doc.get("utc_offset_h") or 0)
    rows = {}
    for i, t in enumerate(doc.get("times") or []):
        try:
            local = datetime.strptime(t, "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        utc = local - timedelta(hours=offset)
        row = {el: doc[el][i] for el in SNOTEL_ELEMENTS if isinstance(doc.get(el), list) and i < len(doc[el]) and doc[el][i] is not None}
        if row:
            rows[utc.strftime(ISO)] = row
    return rows


def asos_rows(doc: dict) -> dict[str, dict[str, dict]]:
    """asos.geojson -> {station id: {UTC time: {element: value}}} (one reading per station: its latest report)."""
    out: dict[str, dict[str, dict]] = {}
    for f in doc.get("features") or []:
        p = f.get("properties") or {}
        if not p.get("id") or not p.get("valid_utc"):
            continue
        row = {el: p[el] for el in ASOS_ELEMENTS if p.get(el) is not None}
        if row:
            out.setdefault(p["id"], {})[p["valid_utc"]] = row
    return out


def merge_rows(rows: dict, incoming: dict, month: str) -> tuple[int, list[dict]]:
    """Add the incoming readings to `rows` in place. Returns (added readings, revisions)."""
    added, revisions = 0, []
    for t, row in incoming.items():
        if not t.startswith(month):
            continue
        old = rows.get(t)
        if old is None:
            rows[t] = dict(row)
            added += 1
            continue
        for el, v in row.items():
            if el not in old:
                old[el] = v
            elif old[el] != v:
                revisions.append({"time": t, "element": el, "old": old[el], "new": v})
                old[el] = v
    return added, revisions


def update_station(store: Store, layout: str, network: str, station: str, name: str, incoming: dict, now: datetime) -> dict:
    """Merge one station's readings into its month files and index. Writes only months that gained readings or revisions."""
    counts = {"added": 0, "revised": 0, "months_written": 0, "revisions": []}
    by_month = sorted({t[:7] for t in incoming})
    index_raw = store.get(index_key(layout, network, station))
    index = json.loads(index_raw) if index_raw else {"station": station, "network": network, "name": name, "months": {}}
    for month in by_month:
        raw = store.get(month_key(layout, network, station, month))
        doc = json.loads(raw) if raw else {"station": station, "network": network, "month": month, "rows": {}, "revisions": []}
        added, revisions = merge_rows(doc["rows"], incoming, month)
        if not added and not revisions:
            continue
        doc["revisions"].extend(revisions)
        doc["updated_at"] = now.strftime(ISO)
        store.put(month_key(layout, network, station, month), json.dumps(doc, separators=(",", ":")).encode("utf-8"), "application/json", "no-store")
        times = sorted(doc["rows"])
        index["months"][month] = {"rows": len(times), "first": times[0], "last": times[-1]}
        counts["added"] += added
        counts["revised"] += len(revisions)
        counts["months_written"] += 1
        counts["revisions"].extend(revisions)
    if counts["months_written"]:
        index["name"] = name
        index["updated_at"] = now.strftime(ISO)
        store.put(index_key(layout, network, station), json.dumps(index, indent=1).encode("utf-8"), "application/json", "no-store")
    return counts
