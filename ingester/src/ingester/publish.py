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

from .store import Store

log = logging.getLogger("snow-wx.ingest")

LAYOUT = "v1"
MANIFEST = "_manifest.json"
TOP_DIRS = ("data", "models")
# working files some jobs leave in their output folders; never published
EXCLUDE_SUFFIXES = (".tmp", ".npz", ".grib2", ".grib", ".idx", ".tar", ".part", ".lock")
TYPES = {".json": "application/json", ".geojson": "application/geo+json", ".png": "image/png", ".csv": "text/csv",
         ".txt": "text/plain; charset=utf-8", ".svg": "image/svg+xml", ".webp": "image/webp", ".gz": "application/gzip"}


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
                        "size": len(raw), "content_type": content_type(path.name)})
    out.sort(key=lambda f: f["key"])
    return out


def _upload_rank(key: str) -> tuple:
    name = key.rsplit("/", 1)[-1]
    return (name == "meta.json", name in ("index.json", "summary.json", "exceed_summary.json"), key)


def plan(files: list[dict], previous: dict, scope_keys: list[str], prune: bool) -> tuple[list[dict], list[dict], list[str]]:
    """(put, skip, delete). `previous` = manifest objects {key: {sha256, ...}}; `scope_keys` = key prefixes this publish covers."""
    put, skip = [], []
    for f in files:
        old = previous.get(f["key"]) or {}
        (skip if old.get("sha256") == f["sha256"] else put).append(f)
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
            dry_run: bool = False, sources: dict | None = None, layout: str = LAYOUT, now: datetime | None = None) -> dict:
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

    if archive:
        for f in put:
            store.put(f"archive/runs/{stamp}/{f['key'][len(layout) + 1:]}", f["path"].read_bytes(), f["content_type"],
                      "public, max-age=31536000, immutable", f["sha256"])
    for f in put:
        store.put(f["key"], f["path"].read_bytes(), f["content_type"], cache_control(f["content_type"]), f["sha256"])
    for key in delete:
        store.delete(key)

    objects = {k: v for k, v in previous.items() if k not in set(delete)}
    objects.update({f["key"]: {"sha256": f["sha256"], "size": f["size"]} for f in files})
    doc = {"layout": layout, "published_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
           "sources": {**(manifest.get("sources") or {}), **(sources or {})},
           "objects": dict(sorted(objects.items()))}
    store.put(manifest_key(layout), json.dumps(doc, indent=1).encode("utf-8"), "application/json", "no-store")
    log.info("published to %s: %d uploaded, %d unchanged, %d deleted", store.describe(), len(put), len(skip), len(delete))
    return result
