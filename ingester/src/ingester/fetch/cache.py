"""Local disk hygiene: prune data_cache at the start of every run (PLAN.md, Nov 8).

Per-cycle downloads (Herbie GRIB subsets, NBM samples, NDFD files, NOHRSC/SNODAS)
are only useful for a day or two. Files older than `prune_days` are deleted and
empty folders removed. Slow, deliberate lookup caches are kept (config `keep`:
data_cache/catalog = 3DEP + api.weather.gov lookups, data_cache/openskimap = seeds).
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

log = logging.getLogger("snow-wx.cache")

DEFAULT_KEEP = ("catalog", "openskimap")


def folder_bytes(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def prune(root: Path, days: float = 2.0, keep=DEFAULT_KEEP, now: float | None = None) -> dict:
    """Delete files under root older than `days` (by mtime), except under the top-level
    folders named in `keep`; then remove empty folders. -> {files, bytes}."""
    root = Path(root)
    if not root.is_dir():
        return {"files": 0, "bytes": 0}
    cutoff = (now or time.time()) - days * 86400
    keep = set(keep or ())
    n = freed = 0
    for top in root.iterdir():
        if top.name in keep:
            continue
        paths = [top] if top.is_file() else [Path(r) / f for r, _, fs in os.walk(top) for f in fs]
        for p in paths:
            try:
                st = p.stat()
                if st.st_mtime < cutoff:
                    p.unlink()
                    n += 1
                    freed += st.st_size
            except OSError as exc:            # in use / permissions: leave it
                log.debug("prune %s: %s", p, exc)
        if top.is_dir():
            for r, dirs, files in sorted(os.walk(top, topdown=False), key=lambda x: -len(x[0])):
                if not dirs and not files and Path(r) != root:
                    try:
                        Path(r).rmdir()
                    except OSError:
                        pass
            if top.exists() and not any(top.iterdir()):
                try:
                    top.rmdir()
                except OSError:
                    pass
    return {"files": n, "bytes": freed}


def housekeeping(repo: Path, cfg: dict | None = None) -> None:
    """Prune data_cache and log the project's disk use (called at the start of each run)."""
    c = (cfg or {}).get("cache") or {}
    if c.get("prune", True) is False:
        return
    root = repo / "data_cache"
    try:
        res = prune(root, float(c.get("prune_days", 2)), c.get("keep", DEFAULT_KEEP))
    except Exception as exc:  # noqa: BLE001 - housekeeping must never stop a run
        log.warning("cache prune failed: %s", exc)
        return
    sizes = {name: folder_bytes(repo / name) for name in ("data_cache", "build")}
    log.info("disk: data_cache %.0f MB%s, build %.0f MB", sizes["data_cache"] / 1e6,
             f" (pruned {res['files']} files, {res['bytes'] / 1e6:.0f} MB older than {c.get('prune_days', 2)} days)"
             if res["files"] else "", sizes["build"] / 1e6)
