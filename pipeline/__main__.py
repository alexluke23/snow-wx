"""Command-line entry point.

    python -m pipeline build            # website + fresh data -> build/
    python -m pipeline obs --out DIR    # data only

Each data source runs independently; one failing source does not stop the
others. The command exits non-zero only if every enabled source fails.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
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
    """Copy the static website into outdir, then fetch data into outdir/data."""
    web = REPO_ROOT / "web"
    shutil.copytree(web, outdir, dirs_exist_ok=True)
    return run_obs(cfg, outdir / "data", only)


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
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    if args.cmd == "obs":
        return run_obs(cfg, Path(args.out), args.only)
    if args.cmd == "build":
        return build_site(cfg, Path(args.out), args.only)
    return 2


if __name__ == "__main__":
    sys.exit(main())
