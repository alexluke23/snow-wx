"""One ingest run: fetch the chosen sources into the stage folder, then publish to a store.

    stage (working folder: data/ and models/, as the sources write them)  ->  publish (local folder or R2)

Sources fail independently: the run exits non-zero only when every source failed, or the publish failed.
Ingest builds no website files (no meta.json, search index or catalogs). Per-source status and history are kept in
the store's manifest (`sources`).
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from . import publish as P
from .fetch.common import make_session, utcnow
from .obs import run_obs
from .sources import Context, Source
from .store import Store

log = logging.getLogger("snow-wx.ingest")


def with_history(entry: dict, prev: dict | None) -> dict:
    """Per-source history in the manifest: last_success_at, consecutive_failures, outage_since."""
    prev = prev or {}
    at = entry.get("at")
    if entry.get("ok"):
        return {**entry, "last_success_at": at, "consecutive_failures": 0}
    return {**entry, "last_success_at": prev.get("last_success_at"),
            "consecutive_failures": int(prev.get("consecutive_failures") or 0) + 1,
            "outage_since": prev.get("outage_since") or at}


def pull_files(store: Store, stage: Path, rels: list[str], *, layout: str = P.LAYOUT) -> list[str]:
    got = []
    for rel in rels:
        dest = Path(stage) / rel
        if dest.exists():
            continue
        body = store.get(f"{layout}/{rel}")
        if body is None:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        got.append(rel)
    return got


def seed_snotel(cfg: dict, store: Store, stage: Path, layout: str = P.LAYOUT) -> int:
    """The store is the 'previous good copy' of SNOTEL: if the stage has no snotel.geojson, copy the stored one plus the
    station files still younger than snotel.max_age_hours, so an AWDB outage keeps recent stations (flagged stale)."""
    import json

    from .fetch.snotel import split_by_age

    data = Path(stage) / "data"
    if (data / "snotel.geojson").exists():
        return 0
    raw = store.get(f"{layout}/data/snotel.geojson")
    if not raw:
        return 0
    try:
        feats = [f for f in json.loads(raw).get("features", []) if (f.get("properties") or {}).get("triplet")]
    except ValueError:
        return 0
    usable, _ = split_by_age(feats, utcnow(), float((cfg.get("snotel") or {}).get("max_age_hours", 48)))
    if not usable:
        return 0
    rels = ["data/" + (f["properties"].get("file") or f"snotel/{f['properties']['triplet'].replace(':', '_')}.json") for f in usable]
    n = len(pull_files(store, stage, rels, layout=layout))
    data.mkdir(parents=True, exist_ok=True)
    (data / "snotel.geojson").write_bytes(raw)
    log.info("seeded %d SNOTEL station files from %s (previous good copy)", n, store.describe())
    return n


def run(cfg: dict, sources: list[Source], stage: Path, store: Store | None, *, session=None, cycle=None, force: bool = False,
        workers: int | None = None, prune: bool = False, archive: bool = False,
        dry_run: bool = False, layout: str = P.LAYOUT) -> dict:
    """Returns {"ok": bool, "sources": {name: status}, "publish": {...} | None}."""
    stage = Path(stage)
    (stage / "data").mkdir(parents=True, exist_ok=True)
    (stage / "models").mkdir(parents=True, exist_ok=True)
    if session is None:
        session = make_session(cfg)
    owned = [p for s in sources for p in s.writes]

    prev_sources: dict = {}
    if store is not None:
        prev_sources = P.load_manifest(store, layout).get("sources") or {}
        if any(s.name == "snotel" for s in sources):
            seed_snotel(cfg, store, stage, layout)

    status: dict[str, dict] = {}
    obs = [s.name for s in sources if s.group == "obs"]
    if obs:
        status.update(run_obs(cfg, session, stage / "data", obs))
        for n in obs:
            status.setdefault(n, {"ok": None, "skipped": "disabled in config"})

    ctx = Context(cfg, session, stage, cycle=cycle, force=force, workers=workers)
    for s in sources:
        if s.group == "obs":
            continue
        t0 = time.time()
        try:
            st = s.run(ctx)
        except Exception as exc:  # noqa: BLE001 - sources fail independently
            log.exception("%s failed", s.name)
            st = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
        st["seconds"] = round(time.time() - t0, 1)
        st["at"] = utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        status[s.name] = st

    for n, st in status.items():
        if st.get("ok") is not None:
            status[n] = with_history(st, prev_sources.get(n))

    pub = None
    if store is not None:
        pub = P.publish(store, stage, scope=owned, prune=prune, archive=archive, dry_run=dry_run, sources=status, layout=layout)
    ran = [st for st in status.values() if st.get("ok") is not None]
    ok = (not ran) or any(st["ok"] for st in ran)
    return {"ok": ok, "sources": status, "publish": pub}
