"""One ingest run: fetch the chosen sources into the stage folder, derive the cross-source files, publish to a store.

    stage (local working folder, the pipeline's usual data/ + models/ layout)
      -> derive (meta.json, search index, catalogs, merges; no network)
      -> publish (local folder or R2; hash skip; only the paths this run owns)

Sources fail independently (as in `pipeline obs`): the run exits non-zero only when every source failed or the
publish itself failed.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from . import publish as P
from .sources import DERIVE_INPUT_PATTERNS, DERIVED_WRITES, Context, Source
from .store import Store

log = logging.getLogger("snow-wx.ingest")


def _under(rel: str, prefixes: list[str]) -> bool:
    return any(rel == p or rel.startswith(p.rstrip("/") + "/") for p in prefixes)


def pull_files(store: Store, stage: Path, rels: list[str], *, overwrite: bool, layout: str = P.LAYOUT) -> list[str]:
    got = []
    for rel in rels:
        dest = Path(stage) / rel
        if dest.exists() and not overwrite:
            continue
        body = store.get(f"{layout}/{rel}")
        if body is None:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        got.append(rel)
    return got


def seed_snotel(cfg: dict, store: Store, stage: Path, layout: str = P.LAYOUT) -> int:
    """The store replaces the live site as the 'previous good copy' (pipeline/restore.py): if the stage has no
    snotel.geojson, copy the store's one plus the station files still younger than snotel.max_age_hours, so an AWDB
    outage keeps showing recent stations (flagged stale) instead of 'unavailable'. Returns stations copied."""
    from pipeline.common import utcnow
    from pipeline.snotel import split_by_age
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
    n = len(pull_files(store, stage, rels, overwrite=False, layout=layout))
    data.mkdir(parents=True, exist_ok=True)
    (data / "snotel.geojson").write_bytes(raw)
    log.info("seeded %d SNOTEL station files from %s (previous good copy)", n, store.describe())
    return n


def derive_inputs(store: Store, layout: str = P.LAYOUT) -> list[str]:
    """Stage-relative paths of the derive step's inputs that exist in the store's manifest."""
    rx = [re.compile(p + r"\Z") for p in DERIVE_INPUT_PATTERNS]
    keys = P.load_manifest(store, layout)["objects"]
    rels = [k[len(layout) + 1:] for k in keys if k.startswith(layout + "/")]
    return sorted(r for r in rels if any(x.match(r) for x in rx))


def run(cfg: dict, sources: list[Source], stage: Path, store: Store | None, *, session=None, cycle=None, force: bool = False,
        workers: int | None = None, derive: bool = True, prune: bool = False, archive: bool = False,
        dry_run: bool = False, layout: str = P.LAYOUT) -> dict:
    """Returns {"sources": {name: status}, "derived": bool, "publish": {...} | None, "ok": bool}."""
    from pipeline.__main__ import derive_outputs, read_meta, run_obs
    from pipeline.common import make_session
    stage = Path(stage)
    (stage / "data").mkdir(parents=True, exist_ok=True)
    (stage / "models").mkdir(parents=True, exist_ok=True)
    session = session or make_session(cfg)
    owned = [p for s in sources for p in s.writes]

    # previous state from the store: per-source history in meta.json, the last good SNOTEL copy
    if store is not None:
        pull_files(store, stage, ["data/meta.json"], overwrite=True, layout=layout)
        if any(s.name == "snotel" for s in sources):
            seed_snotel(cfg, store, stage, layout)

    status: dict[str, dict] = {}
    obs = [s.name for s in sources if s.group == "obs"]
    if obs:
        run_obs(cfg, stage / "data", obs, session=session)
        meta = read_meta(stage / "data").get("sources") or {}
        for n in obs:
            m = meta.get(n)
            status[n] = ({"ok": bool(m.get("ok")), "at": m.get("at"), **({"error": m["error"]} if m.get("error") else {})}
                         if m else {"ok": None, "skipped": "disabled in config"})
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
        status[s.name] = st

    if derive:
        if store is not None:          # the other sources' current index/status files (never over this run's own output)
            others = [r for r in derive_inputs(store, layout) if not _under(r, owned) and r != "data/meta.json"]
            pull_files(store, stage, others, overwrite=True, layout=layout)
        derive_outputs(cfg, stage)

    pub = None
    if store is not None:
        scope = owned + (DERIVED_WRITES if derive else [])
        pub = P.publish(store, stage, scope=scope, prune=prune, archive=archive, dry_run=dry_run,
                        sources={n: st for n, st in status.items()}, layout=layout)
    ran = [st for st in status.values() if st.get("ok") is not None]
    ok = (not ran) or any(st["ok"] for st in ran)
    return {"ok": ok, "sources": status, "derived": derive, "publish": pub}
