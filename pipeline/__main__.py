"""Command-line entry point.

    python -m pipeline build            # website + fresh obs data -> build/ (+ model catalog)
    python -m pipeline obs --out DIR    # obs data only
    python -m pipeline models --model hrrr [--fhours 0 6 12] [--domains west wasatch]

Each obs source runs independently; one failing source does not stop the
others. The obs command exits non-zero only if every enabled source fails.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from . import afd, alerts, asos, avalanche, snotel
from .common import REPO_ROOT, load_config, make_session, utcnow, write_json

SOURCES = {
    "alerts": alerts.run,
    "afd": afd.run,
    "avalanche": avalanche.run,
    "snotel": snotel.run,
    "asos": asos.run,
}


def read_meta(outdir: Path) -> dict:
    try:
        return json.loads((outdir / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_meta(cfg: dict, outdir: Path, updates: dict) -> None:
    """Merge source statuses into outdir/meta.json. A partial run (e.g. --only
    avalanche) updates its own entries and keeps the others."""
    meta = read_meta(outdir)
    sources = {**(meta.get("sources") or {}), **updates}
    write_json(outdir / "meta.json", {
        "generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "region": cfg["region"],
        "sources": sources,
    })


def product_status(outdir: Path) -> dict:
    """Status entries for products made by other jobs and merged at build time
    (NBM points, model maps): what is present in the site folder and how old it is."""
    out = {}
    pts = outdir / "data" / "points" / "summary.json"
    try:
        js = json.loads(pts.read_text(encoding="utf-8"))
        q = js.get("quality") or {}
        out["points"] = {"ok": True, "count": len(js.get("areas", [])), "unit": "ski areas",
                         "detail": f"NBM {js['cycle'][8:10]}Z run" + (f", {q['missing']} of {q['required']} required "
                                                                      f"messages missing" if q.get("missing") else ""),
                         "at": js.get("generated_at"), **({"quality": q} if q else {})}
    except (OSError, ValueError, KeyError):
        out["points"] = {"ok": False, "error": "no NBM point forecasts yet"}
    nh = outdir / "data" / "nohrsc" / "index.json"
    try:
        js = json.loads(nh.read_text(encoding="utf-8"))
        out["nohrsc"] = {"ok": bool(js.get("layers")), "count": len(js.get("layers", [])), "unit": "layers",
                         "detail": f"snowfall to {(js.get('snowfall_end') or '')[5:13].replace('T', ' ')}Z, "
                                   f"SNODAS {(js.get('snodas_valid') or '')[5:10]}",
                         "at": js.get("generated_at")}
    except (OSError, ValueError):
        out["nohrsc"] = {"ok": False, "error": "no NOHRSC layers yet"}
    idx = outdir / "models" / "index.json"
    try:
        js = json.loads(idx.read_text(encoding="utf-8"))
        models = js.get("models") or {}
        out["models"] = {"ok": bool(models), "count": len(models), "unit": "models",
                         "detail": ", ".join(f"{m.get('label', k)} {m.get('cycle', '')[8:10]}Z"
                                             for k, m in models.items()),
                         "at": max((m.get("generated_at") or "" for m in models.values()), default=None)}
        if not models:
            out["models"]["error"] = "no model runs yet"
    except (OSError, ValueError):
        out["models"] = {"ok": False, "error": "no model runs yet"}
    return out


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
        status[name]["at"] = utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    write_meta(cfg, outdir, status)
    ok = [n for n, s in status.items() if s["ok"]]
    print(f"Done. OK: {ok or 'none'}; failed: {[n for n in status if n not in ok] or 'none'}")
    return 0 if ok else 1


def build_site(cfg: dict, outdir: Path, only: list[str] | None = None) -> int:
    """Copy the static website into outdir, fetch obs into outdir/data, and
    merge any model runs already present in outdir/models into one catalog."""
    web = REPO_ROOT / "web"
    shutil.copytree(web, outdir, dirs_exist_ok=True)
    code = run_obs(cfg, outdir / "data", only)
    # Static catalogs that live in the repo (built on demand, e.g. `pipeline catalog`).
    for name in ("ski_areas.json",):
        src = REPO_ROOT / "data" / name
        if src.exists():
            shutil.copy2(src, outdir / "data" / name)
    try:
        from .models.catalog import write_catalog
        from .models.config import load_models_config
        write_catalog(outdir / "models", list(load_models_config()["models"]))
        from .models.ridge import merge as merge_ridge
        merge_ridge(outdir / "models", outdir / "data" / "ridge.json")
    except Exception:
        logging.getLogger("snow-wx").exception("model catalog failed")
    write_meta(cfg, outdir / "data", product_status(outdir))
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
    p = sub.add_parser("catalog", help="rebuild data/ski_areas.json (on demand; slow external lookups are cached)")
    p.add_argument("--out", default=str(REPO_ROOT / "data" / "ski_areas.json"))
    p.add_argument("--obs-dir", default="build/data", help="folder with snotel/asos.geojson for nearest-station joins")
    p.add_argument("--refresh", action="store_true", help="re-download OpenSkiMap")
    p.add_argument("--snotel", action="store_true", help="build data/snotel_points.json (SNOTEL forecast points) instead")
    p.add_argument("--config", default=None, help="path to settings.yml")
    p.add_argument("-v", "--verbose", action="store_true")
    p = sub.add_parser("ndfd", help="NWS official forecast (NDFD) at every ski area and SNOTEL site into OUT/")
    p.add_argument("--out", default="build/data/ndfd")
    p.add_argument("--published", default=None, help="key already on the site; exit 0 if unchanged")
    p.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    p.add_argument("--config", default=None, help="path to settings.yml")
    p.add_argument("-v", "--verbose", action="store_true")
    p = sub.add_parser("nohrsc", help="NOHRSC snowfall analysis + SNODAS overlay layers into OUT/")
    p.add_argument("--out", default="build/data/nohrsc")
    p.add_argument("--published", default=None, help="key already on the site; exit 0 if unchanged")
    p.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    p.add_argument("--config", default=None, help="path to settings.yml")
    p.add_argument("-v", "--verbose", action="store_true")
    p = sub.add_parser("points", help="NBM point forecasts for every ski area into OUT/<id>.json")
    p.add_argument("--out", default="build/data/points")
    p.add_argument("--cycle", help="NBM cycle YYYYMMDDHH (default: newest complete 00/06/12/18Z)")
    p.add_argument("--published", default=None, help="cycle already on the site; exit 0 if unchanged")
    p.add_argument("--max-hour", type=int, default=264)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--github-output", default=os.environ.get("GITHUB_OUTPUT"))
    p.add_argument("--config", default=None, help="path to settings.yml")
    p.add_argument("-v", "--verbose", action="store_true")
    p = sub.add_parser("archive", help="append forecasts + SNOTEL obs to the verification archive (CI)")
    p.add_argument("--data", default="build/data", help="site data folder (points/, ndfd/, snotel/)")
    p.add_argument("--release", default=None, help="GitHub release tag (default: config archive.release)")
    p.add_argument("--local", default=None, help="use this folder instead of the release (dry runs, tests)")
    p.add_argument("--work", default=None, help="scratch folder for downloads (default: a temp dir)")
    p.add_argument("--config", default=None, help="path to settings.yml")
    p.add_argument("-v", "--verbose", action="store_true")
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
        from .cache import housekeeping
        housekeeping(REPO_ROOT, load_config(None))
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
    from .cache import housekeeping
    housekeeping(REPO_ROOT, cfg)                 # prune data_cache (> 2 days), log disk use
    if args.cmd == "archive":
        import tempfile
        from . import archive
        store = (archive.LocalStore(Path(args.local)) if args.local
                 else archive.ReleaseStore(args.release or (cfg.get("archive") or {}).get("release", "verification")))
        with tempfile.TemporaryDirectory() as tmp:
            stats = archive.archive(Path(args.data), store, Path(args.work or tmp))
        print(json.dumps(stats, indent=1))
        return 0
    if args.cmd == "ndfd":
        from . import ndfd
        return ndfd.run(cfg, make_session(cfg), Path(args.out), published=args.published,
                        github_output=args.github_output)
    if args.cmd == "nohrsc":
        from . import nohrsc
        return nohrsc.run(cfg, make_session(cfg), Path(args.out), published=args.published,
                          github_output=args.github_output)
    if args.cmd == "points":
        from .nbm.run import run_points
        cycle = datetime.strptime(args.cycle, "%Y%m%d%H") if args.cycle else None
        return run_points(cfg, make_session(cfg), Path(args.out), cycle=cycle, published=args.published,
                          max_hour=args.max_hour, workers=args.workers, github_output=args.github_output)
    if args.cmd == "catalog":
        from . import catalog
        if args.snotel:
            return catalog.build_snotel_points(make_session(cfg), catalog.load_catalog_config(), Path(args.obs_dir))
        return catalog.run(cfg, make_session(cfg), Path(args.out), Path(args.obs_dir), args.refresh)
    if args.cmd == "obs":
        return run_obs(cfg, Path(args.out), args.only)
    if args.cmd == "build":
        return build_site(cfg, Path(args.out), args.only)
    return 2


if __name__ == "__main__":
    sys.exit(main())
