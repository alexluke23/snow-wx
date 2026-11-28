"""Publish a stage folder (data/ + models/, the layout the pipeline writes) to a Store.

- Keys: <layout>/data/... and <layout>/models/... (layout "v1"); the bytes are the pipeline's files, unchanged.
- Hash skip: objects whose sha256 matches the manifest are not uploaded (R2 Class A operations are budgeted).
- Order: payload files first, then index/summary files that point at them, then meta.json, then the manifest, so a
  reader never sees a freshness stamp or index that runs ahead of the data.
- Archive (optional): every CHANGED object is also written once to archive/runs/<stamp>/<data|models>/...
- Prune (opt-in): objects in the manifest, inside this publish's scope, that are no longer in the stage are deleted.
  Scope = the stage subfolders this publish covers (all of data/ and models/ unless narrowed), so a partial run
  (e.g. only SNOTEL) never deletes another source's objects.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
from datetime import datetime, timezone
from pathlib import Path

from .history import is_area_doc, parse_doc, parse_plume, update_area_history, watched_changes
from .alert_history import update_alerts
from . import obs_history as OH
from .store import Store

log = logging.getLogger("snow-wx.ingest")

LAYOUT = "v1"
MANIFEST = "_manifest.json"
RUNS_DIR = "_runs"        # one immutable record per publish: per-source status and counts
CHANGES_DIR = "_changes"  # one immutable record per publish that changed content: which objects changed
TOP_DIRS = ("data", "models")
# working files some jobs leave in their output folders; never published
EXCLUDE_SUFFIXES = (".tmp", ".npz", ".grib2", ".grib", ".idx", ".tar", ".part", ".lock")
TYPES = {".json": "application/json", ".geojson": "application/geo+json", ".png": "image/png", ".csv": "text/csv",
         ".txt": "text/plain; charset=utf-8", ".svg": "image/svg+xml", ".webp": "image/webp", ".gz": "application/gzip"}


# Fields that change on every run without the forecast or observation changing. They are left out of the content hash, so a
# document whose only change is one of these is not uploaded again (its stored copy keeps the older timestamp; the run log
# records when each run happened).
TIME_KEYS = frozenset({"generated_at", "checked_at", "fetched_at", "age_h"})


def strip_time(obj):
    if isinstance(obj, dict):
        return {k: strip_time(v) for k, v in obj.items() if k not in TIME_KEYS}
    if isinstance(obj, list):
        return [strip_time(v) for v in obj]
    return obj


def content_sha256(raw: bytes, name: str) -> str:
    """Hash of what the document says: canonical JSON without the time-only fields; other files are hashed as bytes."""
    if name.lower().endswith((".json", ".geojson")):
        try:
            doc = json.loads(raw)
        except ValueError:
            return hashlib.sha256(raw).hexdigest()
        canon = json.dumps(strip_time(doc), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canon.encode("utf-8")).hexdigest()
    return hashlib.sha256(raw).hexdigest()


def manifest_key(layout: str = LAYOUT) -> str:
    return f"{layout}/{MANIFEST}"


def content_type(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return TYPES.get(suffix) or mimetypes.guess_type(name)[0] or "application/octet-stream"


def cache_control(ctype: str) -> str:
    """JSON changes every run (short cache); images are written under cycle-specific paths (longer cache)."""
    if ctype.startswith("application/json") or ctype == "application/geo+json":
        return "public, max-age=60"
    return "public, max-age=3600"


def scan_stage(stage: Path, scope: list[str] | None = None, layout: str = LAYOUT) -> list[dict]:
    """Files under stage/data and stage/models (or only under the `scope` subfolders, e.g. ["data/points"]) as
    {key, path, sha256, size, content_type}, sorted by key."""
    stage = Path(stage)
    roots = [stage / s for s in (scope or TOP_DIRS)]
    out = []
    for root in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")) if root.is_dir() else [root]:
            if not path.is_file() or path.name.startswith(".") or path.name.lower().endswith(EXCLUDE_SUFFIXES):
                continue
            rel = path.relative_to(stage).as_posix()
            if rel.split("/", 1)[0] not in TOP_DIRS:
                continue
            raw = path.read_bytes()
            out.append({"key": f"{layout}/{rel}", "path": path, "sha256": hashlib.sha256(raw).hexdigest(),
                        "content_sha256": content_sha256(raw, path.name), "size": len(raw),
                        "content_type": content_type(path.name)})
    out.sort(key=lambda f: f["key"])
    return out


def _upload_rank(key: str) -> tuple:
    name = key.rsplit("/", 1)[-1]
    return (name == "meta.json", name in ("index.json", "summary.json", "exceed_summary.json"), key)


def plan(files: list[dict], previous: dict, scope_keys: list[str], prune: bool) -> tuple[list[dict], list[dict], list[str]]:
    """(put, skip, delete). `previous` = manifest objects {key: {sha256, content_sha256, ...}}; `scope_keys` = key prefixes this
    publish covers. A file is skipped when its CONTENT hash matches what is stored (time-only changes are not uploads)."""
    put, skip = [], []
    for f in files:
        old = previous.get(f["key"]) or {}
        same = bool(old.get("content_sha256")) and old["content_sha256"] == f["content_sha256"]
        (skip if same else put).append(f)
    put.sort(key=lambda f: _upload_rank(f["key"]))
    delete = []
    if prune:
        current = {f["key"] for f in files}
        delete = sorted(k for k in previous if k not in current
                        and any(k == p or k.startswith(p.rstrip("/") + "/") for p in scope_keys))
    return put, skip, delete


def load_manifest(store: Store, layout: str = LAYOUT) -> dict:
    raw = store.get(manifest_key(layout))
    if not raw:
        return {"layout": layout, "objects": {}, "sources": {}}
    doc = json.loads(raw.decode("utf-8"))
    objs = doc.get("objects") or {}
    # accept the older draft format {key: sha256}
    doc["objects"] = {k: (v if isinstance(v, dict) else {"sha256": v}) for k, v in objs.items()}
    doc.setdefault("sources", {})
    return doc


def publish(store: Store, stage: Path, *, scope: list[str] | None = None, prune: bool = False, archive: bool = False,
            dry_run: bool = False, sources: dict | None = None, layout: str = LAYOUT, now: datetime | None = None,
            history: bool = True) -> dict:
    """Upload the stage to `store`. `sources` = per-source run status merged into the manifest ("sources")."""
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    scope = [s.strip("/") for s in (scope or TOP_DIRS)]
    files = scan_stage(stage, scope, layout)
    manifest = load_manifest(store, layout)
    previous = manifest["objects"]
    scope_keys = [f"{layout}/{s}" for s in scope]
    put, skip, delete = plan(files, previous, scope_keys, prune)
    result = {"store": store.describe(), "layout": layout, "scope": scope, "files": len(files), "put": len(put),
              "skip": len(skip), "delete": len(delete), "bytes_put": sum(f["size"] for f in put),
              "archive": f"archive/runs/{stamp}/" if archive and put else None, "dry_run": dry_run, "published_at": stamp}
    if dry_run:
        result["sample_put"] = [f["key"] for f in put[:15]]
        result["sample_delete"] = delete[:15]
        return result

    # forecast history (history.py): the previous copy of each changed area forecast, read before it is overwritten
    area_new, area_old = {}, {}
    if history:
        for f in put:
            if is_area_doc(f["key"], layout):
                new_doc = parse_doc(f["path"].read_bytes())
                if new_doc is not None:
                    area_new[f["key"]] = new_doc
                    area_old[f["key"]] = parse_doc(store.get(f["key"]))

    # ECMWF and GEFS summit plumes (history/ecmwf|gefs), and the alert list (history/alerts): only files that changed
    plume_items, alert_trigger = [], False
    if history:
        for f in put:
            parts = f["key"].split("/")
            if len(parts) == 5 and parts[:2] == [layout, "models"] and parts[2] in ("ecmwf", "gefs") and parts[3] == "plume" and parts[4].endswith(".json"):
                doc = parse_plume(f["path"].read_bytes())
                if doc is not None:
                    plume_items.append((parts[2], parts[4][:-5], doc, f["content_sha256"]))
            if f["key"] in (f"{layout}/data/alerts/index.json", f"{layout}/data/alerts/details.json"):
                alert_trigger = True

    # observation history (obs_history.py): SNOTEL station windows and the ASOS file, only for files that changed
    obs_items = []                       # (network, station id, name, {time: row}, file key)
    if history:
        put_keys = {f["key"] for f in put}
        for f in put:
            if f["key"] == f"{layout}/data/asos.geojson":
                for sid, rows in OH.asos_rows(json.loads(f["path"].read_bytes())).items():
                    obs_items.append(("asos", sid, sid, rows, f["key"]))
        for f in files:
            parts = f["key"].split("/")
            if len(parts) == 4 and parts[:3] == [layout, "data", "snotel"] and parts[3].endswith(".json"):
                doc = json.loads(f["path"].read_bytes())
                if not doc.get("triplet"):
                    continue
                # a station file whose content is unchanged adds nothing, except to a station that has no history yet
                # (its window was published before this step, so it must still be recorded once)
                if f["key"] in put_keys or store.get(OH.index_key(layout, "snotel", doc["triplet"])) is None:
                    obs_items.append(("snotel", doc["triplet"], doc.get("name") or doc["triplet"], OH.snotel_rows(doc), f["key"]))

    if archive:
        for f in put:
            store.put(f"archive/runs/{stamp}/{f['key'][len(layout) + 1:]}", f["path"].read_bytes(), f["content_type"],
                      "public, max-age=31536000, immutable", f["sha256"])
    for f in put:
        store.put(f["key"], f["path"].read_bytes(), f["content_type"], cache_control(f["content_type"]), f["sha256"])
    for key in delete:
        store.delete(key)

    obs_counts = {"added": 0, "revised": 0, "stations": 0}
    obs_revisions = {}
    for network, sid, name, rows, key in obs_items:
        if not rows:
            continue
        res = OH.update_station(store, layout, network, sid, name, rows, now)
        if res["months_written"]:
            obs_counts["stations"] += 1
        obs_counts["added"] += res["added"]
        obs_counts["revised"] += res["revised"]
        if res["revisions"]:
            obs_revisions.setdefault(key, []).extend(res["revisions"])

    model_counts = {"written": 0, "expired": 0}
    for model, area, doc, sha in plume_items:
        res = update_area_history(store, layout, area, doc, sha, now, family=model)
        model_counts["written"] += res["written"]
        model_counts["expired"] += res["expired"]

    alert_summary = None
    if alert_trigger:
        ap, dp = stage / "data" / "alerts" / "index.json", stage / "data" / "alerts" / "details.json"
        alerts_doc = json.loads(ap.read_text(encoding="utf-8")) if ap.exists() else {}
        details = json.loads(dp.read_text(encoding="utf-8")) if dp.exists() else {}
        alert_summary = update_alerts(store, layout, alerts_doc, details, now)

    history_counts = {"written": 0, "expired": 0}
    for key, new_doc in area_new.items():
        f = next(x for x in put if x["key"] == key)
        area = key.rsplit("/", 1)[-1][:-5]
        res = update_area_history(store, layout, area, new_doc, f["content_sha256"], now)
        history_counts["written"] += res["written"]
        history_counts["expired"] += res["expired"]

    # the manifest records what is STORED: uploaded files get their new hashes; skipped files keep their stored entry
    objects = {k: v for k, v in previous.items() if k not in set(delete)}
    objects.update({f["key"]: {"sha256": f["sha256"], "content_sha256": f["content_sha256"], "size": f["size"]} for f in put})
    doc = {"layout": layout, "published_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "sources": {**(manifest.get("sources") or {}), **(sources or {})},
           "objects": dict(sorted(objects.items()))}
    # change log (only when content changed) and run log (every run), both immutable, under the layout
    def kind(key: str, new_hash: str) -> str:
        # baseline: no content hash was stored before (a first publish into an empty store, or a manifest written before
        # content hashes); new: the key did not exist; changed: its content hash differs from the stored one
        old = (previous.get(key) or {}).get("content_sha256")
        if old is None:
            return "baseline" if key in previous or not previous else "new"
        return "changed"

    changes = [{"key": f["key"], "change": kind(f["key"], f["content_sha256"]),
                "old_content_sha256": (previous.get(f["key"]) or {}).get("content_sha256"),
                "new_content_sha256": f["content_sha256"]} for f in put]
    for c in changes:
        if alert_summary is not None and c["key"] == f"{layout}/data/alerts/index.json":
            c["alerts"] = alert_summary
        if c["key"] in obs_revisions:
            c["revisions"] = obs_revisions[c["key"]]
        if c["key"] in area_new and area_old.get(c["key"]) is not None:
            fields = watched_changes(area_old[c["key"]], area_new[c["key"]])
            if fields:
                c["fields"] = fields
    changes += [{"key": k, "change": "deleted", "old_content_sha256": (previous.get(k) or {}).get("content_sha256"),
                 "new_content_sha256": None} for k in delete]
    run_doc = {"run": stamp, "published_at": doc["published_at"], "store": store.describe(), "scope": scope,
               "sources": sources or {},
               "counts": {"files": len(files), "baseline": sum(c["change"] == "baseline" for c in changes),
                          "new": sum(c["change"] == "new" for c in changes),
                          "changed": sum(c["change"] == "changed" for c in changes), "unchanged": len(skip), "deleted": len(delete)},
               "archive": result["archive"], "history": history_counts, "obs_history": obs_counts,
               "model_history": model_counts, "alert_history": {k: len(v) for k, v in alert_summary.items()} if alert_summary else None}
    store.put(f"{layout}/{RUNS_DIR}/{stamp}.json", json.dumps(run_doc, indent=1).encode("utf-8"), "application/json", "no-store")
    if changes:
        store.put(f"{layout}/{CHANGES_DIR}/{stamp}.json",
                  json.dumps({"run": stamp, "changes": changes}, indent=1).encode("utf-8"), "application/json", "no-store")
    result["changes"] = len(changes)
    result["history"] = history_counts
    result["obs_history"] = obs_counts
    result["model_history"] = model_counts
    result["alert_history"] = {k: len(v) for k, v in alert_summary.items()} if alert_summary else None
    result["run_log"] = f"{layout}/{RUNS_DIR}/{stamp}.json"
    # the manifest is written last: it is the pointer readers use, so it never runs ahead of the data or the logs
    store.put(manifest_key(layout), json.dumps(doc, indent=1).encode("utf-8"), "application/json", "no-store")

    log.info("published to %s: %d uploaded, %d unchanged, %d deleted", store.describe(), len(put), len(skip), len(delete))
    return result
