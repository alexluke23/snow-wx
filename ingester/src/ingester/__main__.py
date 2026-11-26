"""Data ingest: fetch weather/snow data and store it as JSON (+ model PNGs) in a local folder or Cloudflare R2.
No website files are built here (the site build stays `python -m pipeline build`).

    python -m ingester list                                  # sources and what they write
    python -m ingester run snotel asos                       # fetch two sources -> data_out/stage -> data_out/store (local)
    python -m ingester run --all                             # every default source (obs + NBM points + NOHRSC + ECMWF + GEFS)
    python -m ingester run obs --store r2 --dry-run          # what an R2 push would upload (reads the R2 manifest, writes nothing)
    python -m ingester run obs --store r2                    # push to R2 (credentials from R2_* env vars or Docker secrets)
    python -m ingester publish --store r2                    # publish an existing stage without fetching

Store layout (identical locally and in R2): v1/data/..., v1/models/..., v1/_manifest.json, archive/runs/<stamp>/...
Defaults come from config/settings.yml `ingest:`; INGEST_STORE (local|r2) overrides the default store.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import pipeline  # noqa: F401 - Windows: puts ecCodes on PATH before any GRIB import (see pipeline/__init__.py)
from pipeline.common import REPO_ROOT, load_config

from . import publish as P
from .runner import run as run_ingest
from .sources import registry, resolve
from .store import LocalStore, open_r2


def _settings(cfg: dict) -> dict:
    s = cfg.get("ingest") or {}
    return {"stage": s.get("stage_dir", "data_out/stage"), "local": s.get("local_store_dir", "data_out/store"),
            "layout": s.get("layout", P.LAYOUT), "archive": bool(s.get("archive", False))}


def _path(p: str) -> Path:
    q = Path(p)
    return q if q.is_absolute() else REPO_ROOT / q


def _store(kind: str, local_root: str, bucket: str):
    if kind == "none":
        return None
    if kind == "local":
        return LocalStore(_path(local_root))
    if kind == "r2":
        return open_r2(bucket)
    raise SystemExit(f"unknown store {kind!r} (local, r2, none)")


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--stage", default=None, help="working folder with data/ and models/ (default: config ingest.stage_dir)")
    p.add_argument("--store", default=os.environ.get("INGEST_STORE", "local"), choices=["local", "r2", "none"],
                   help="where to publish (default: local, or INGEST_STORE). none = fetch into the stage only")
    p.add_argument("--local-root", default=None, help="local store folder (default: config ingest.local_store_dir)")
    p.add_argument("--bucket", default="", help="R2 bucket (default: R2_BUCKET)")
    p.add_argument("--prune", action="store_true", help="delete stored objects (inside this run's paths) that the stage no longer has")
    p.add_argument("--archive", action=argparse.BooleanOptionalAction, default=None,
                   help="also copy changed objects to archive/runs/<stamp>/ (default: config ingest.archive)")
    p.add_argument("--dry-run", action="store_true", help="plan the publish only: nothing is uploaded or deleted")
    p.add_argument("--config", default=None, help="path to settings.yml")
    p.add_argument("-v", "--verbose", action="store_true")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ingester", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list sources")
    p = sub.add_parser("run", help="fetch sources into the stage, derive, publish")
    p.add_argument("sources", nargs="*", help="source names or groups (obs, products, maps); see `list`")
    p.add_argument("--all", action="store_true", help="every default source")
    p.add_argument("--cycle", help="model cycle YYYYMMDDHH for points/ecmwf/gefs/maps (default: newest)")
    p.add_argument("--force", action="store_true", help="ecmwf/gefs: run even when disabled in config (local test)")
    p.add_argument("--workers", type=int, default=None, help="worker processes for points/maps")
    p.add_argument("--no-derive", action="store_true", help="skip meta.json / search / catalogs")
    _common(p)
    p = sub.add_parser("publish", help="publish the current stage without fetching")
    p.add_argument("--scope", nargs="*", default=None, help="stage paths to publish (default: all of data/ and models/)")
    _common(p)
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(level=logging.DEBUG if getattr(args, "verbose", False) else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("matplotlib", "PIL", "urllib3", "fiona", "herbie", "botocore", "boto3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    reg = registry()
    if args.cmd == "list":
        for name, s in reg.items():
            print(f"{name:14} {s.group:8} {'default' if s.default else 'opt-in ':8} {', '.join(s.writes)}  {s.help}")
        return 0

    cfg = load_config(args.config)
    st = _settings(cfg)
    stage = _path(args.stage or st["stage"])
    archive = st["archive"] if args.archive is None else args.archive
    try:
        store = _store(args.store, args.local_root or st["local"], args.bucket)
    except RuntimeError as exc:                 # missing R2 credentials
        logging.getLogger("snow-wx.ingest").error("%s", exc)
        return 2

    if args.cmd == "publish":
        if store is None:
            print("publish: --store none has nothing to do")
            return 2
        res = P.publish(store, stage, scope=args.scope, prune=args.prune, archive=archive, dry_run=args.dry_run, layout=st["layout"])
        print(json.dumps(res, indent=1, default=str))
        return 0

    try:
        chosen = resolve(args.sources, args.all, reg)
    except ValueError as exc:
        ap.error(str(exc))
    if not chosen:
        ap.error("name at least one source (see `python -m ingester list`) or use --all")
    from pipeline.cache import housekeeping
    housekeeping(REPO_ROOT, cfg)
    cycle = datetime.strptime(args.cycle, "%Y%m%d%H") if args.cycle else None
    try:
        res = run_ingest(cfg, chosen, stage, store, cycle=cycle, force=args.force, workers=args.workers,
                         derive=not args.no_derive, prune=args.prune, archive=archive, dry_run=args.dry_run, layout=st["layout"])
    except Exception:  # noqa: BLE001 - a publish failure (network, credentials) is reported, not a traceback dump
        logging.getLogger("snow-wx.ingest").exception("ingest failed")
        return 1
    print(json.dumps(res, indent=1, default=str))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
