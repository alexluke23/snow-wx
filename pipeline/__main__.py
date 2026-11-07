"""Command-line entry point.

    python -m pipeline build            # website + fresh obs data -> build/ (+ model catalog)
    python -m pipeline obs --out DIR    # obs data only
    python -m pipeline models --model hrrr [--fhours 0 6 12] [--domains west wasatch]

Each obs source runs independently; one failing source does not stop the
others. The obs command exits non-zero only if every enabled source fails.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from . import asos, avalanche, snotel
from .common import REPO_ROOT, load_config, make_session, utcnow, write_json

SOURCES = {
    "avalanche": avalanche.run,
    "snotel": snotel.run,
    "asos": asos.run,
}


def run_obs(cfg: dict, outdir: Path, only: list[str] | None = None) -> int:
    session = make_session(cfg)
    status = {}
    for name, func in SOURCES.items():
        if only and name not in only:
            continue
        if not cfg.get(name, {}).get("enabled", True):
            continue
        t0 = time.time()
        try:
            info = func(cfg, session, outdir)
            status[name] = {"ok": True, **info}
        except Exception as exc:
            logging.getLogger("snow-wx").exception("%s failed", name)
            status[name] = {"ok": False, "error": str(exc)[:300]}
        status[name]["seconds"] = round(time.time() - t0, 1)

    write_json(outdir / "meta.json", {
        "generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "region": cfg["region"],
        "sources": status,
    })
    ok = [n for n, s in status.items() if s["ok"]]
    print(f"Done. OK: {ok or 'none'}; failed: {[n for n in status if n not in ok] or 'none'}")
    return 0 if ok else 1


def build_site(cfg: dict, outdir: Path, only: list[str] | None = None) -> int:
    """Copy the static website into outdir, fetch obs into outdir/data, and
    merge any model runs already present in outdir/models into one catalog."""
    web = REPO_ROOT / "web"
    shutil.copytree(web, outdir, dirs_exist_ok=True)
    code = run_obs(cfg, outdir / "data", only)
    try:
        from .models.catalog import write_catalog
        from .models.config import load_models_config
        write_catalog(outdir / "models", list(load_models_config()["models"]))
    except Exception:
        logging.getLogger("snow-wx").exception("model catalog failed")
    return code


def _models_args(sub) -> None:
    p = sub.add_parser("models", help="render model maps for one model into OUT/<model>/")
    p.add_argument("--model", required=True, help="model key in config/models.yml (hrrr, rrfs, gfs)")
    p.add_argument("--out", default="build/models", help="output folder (default build/models)")
    p.add_argument("--models-config", default=None, help="path to models.yml")
    p.add_argument("--fhours", nargs="*", type=int, help="forecast hours (default: from config)")
    p.add_argument("--domains", nargs="*", help="limit to these domains")
    p.add_argument("--fields", nargs="*", help="limit to these fields")
    p.add_argument("--cycle", help="init time YYYYMMDDHH (default: newest complete cycle)")
    p.add_argument("--published", default=None,
                   help="cycle already on the site (YYYYMMDDHH); exit 0 without output if unchanged")
    p.add_argument("--workers", type=int, default=None, help="plotting processes")
    p.add_argument("--keep-grib", action="store_true", help="keep GRIB subsets in the cache")
    p.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"),
                   help="append new=/cycle= lines here (set automatically in Actions)")
    p.add_argument("-v", "--verbose", action="store_true")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m pipeline")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, help_text, default_out in (
        ("obs", "fetch observations and avalanche danger into a data folder", "build/data"),
        ("build", "copy the website and fetch fresh data (what GitHub Actions runs)", "build"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--out", default=default_out, help=f"output folder (default {default_out})")
        p.add_argument("--config", default=None, help="path to settings.yml")
        p.add_argument("--only", nargs="*", choices=list(SOURCES), help="run only these sources")
        p.add_argument("-v", "--verbose", action="store_true")
    _models_args(sub)
    args = ap.parse_args(argv)

    # Windows consoles/pipes default to cp1252; Herbie prints emoji. Never crash on that.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("matplotlib", "PIL", "urllib3", "fiona", "herbie"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if args.cmd == "models":
        from .models.config import load_models_config
        from .models.run import run_model
        mcfg = load_models_config(args.models_config)
        if args.model not in mcfg["models"]:
            ap.error(f"unknown model {args.model!r}; choose from {', '.join(mcfg['models'])}")
        cycle = datetime.strptime(args.cycle, "%Y%m%d%H") if args.cycle else None
        return run_model(mcfg, args.model, Path(args.out), fhours=args.fhours, domains=args.domains,
                         fields=args.fields, cycle=cycle, published=args.published,
                         workers=args.workers, keep_grib=args.keep_grib,
                         github_output=args.github_output)

    cfg = load_config(args.config)
    if args.cmd == "obs":
        return run_obs(cfg, Path(args.out), args.only)
    if args.cmd == "build":
        return build_site(cfg, Path(args.out), args.only)
    return 2


if __name__ == "__main__":
    sys.exit(main())
