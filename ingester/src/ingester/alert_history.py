"""Step 3b of the history plan: alert history (first seen, last seen, closed, and every change to an alert).

Layout (under the store's layout prefix, e.g. v1):
    history/alerts/index.json    every alert ever seen: event, first_seen, last_seen, closed_at, number of versions
    history/alerts/<id>.json     one alert: its versions, each with the time it was seen and its fields and description

An alert is closed when it leaves the published alert list (it expired, was cancelled, or was replaced). If it returns, it is
reopened. A version is added only when the alert's fields or description differ from the last version.
"""

from __future__ import annotations

import json
from datetime import datetime

from .store import Store

ISO = "%Y-%m-%dT%H:%MZ"


def _base(layout: str) -> str:
    return f"{layout}/history/alerts"


def update_alerts(store: Store, layout: str, alerts_doc: dict, details: dict, now: datetime) -> dict:
    """Reconcile the store's alert history with the published alerts. Returns {"opened", "closed", "updated"} alert ids."""
    base = _base(layout)
    now_s = now.strftime(ISO)
    raw = store.get(f"{base}/index.json")
    master = json.loads(raw) if raw else {"alerts": {}}
    current = alerts_doc.get("alerts") or {}
    opened, closed, updated = [], [], []

    for aid, rec in current.items():
        fields = {**rec, "description": (details.get(aid) or {}).get("description")}
        m = master["alerts"].get(aid)
        if m is None or m.get("closed_at"):
            opened.append(aid)                                   # new, or back after being closed
        if m is None:
            per = {"id": aid, "versions": []}
            m = {"id": aid, "event": rec.get("event"), "first_seen": now_s, "last_seen": now_s, "closed_at": None,
                 "versions": 0, "key": f"{base}/{aid}.json"}
        else:
            per_raw = store.get(m["key"])
            per = json.loads(per_raw) if per_raw else {"id": aid, "versions": []}
        if not per["versions"] or per["versions"][-1]["fields"] != fields:
            if per["versions"] and aid not in opened:
                updated.append(aid)
            per["versions"].append({"seen_at": now_s, "fields": fields})
            store.put(m["key"], json.dumps(per, indent=1).encode("utf-8"), "application/json", "no-store")
        m.update(event=rec.get("event"), last_seen=now_s, closed_at=None, versions=len(per["versions"]))
        master["alerts"][aid] = m

    for aid, m in master["alerts"].items():
        if aid not in current and not m.get("closed_at"):
            m["closed_at"] = now_s
            closed.append(aid)

    master["updated_at"] = now_s
    store.put(f"{base}/index.json", json.dumps(master, indent=1).encode("utf-8"), "application/json", "no-store")
    return {"opened": opened, "closed": closed, "updated": updated}
