"""Registry of ingest sources: what each one runs and which stage paths it owns.

Every source runs the vendored fetch code in `ingester/fetch/` (one module per source). Fetching is kept separate from
the pure processing functions there; ingest only decides WHERE the output goes. `writes` = stage-relative paths the
source rewrites on each run: publish uploads (and, with --prune, cleans) only these.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

# observation sources (run together by ingester/obs.py); stage paths each one writes
OBS_WRITES = {
    "alerts": ["data/alerts"],
    "afd": ["data/afd"],
    "avalanche": ["data/avalanche.geojson", "data/avalanche_ratings.json"],
    "hazards": ["data/hazards.json"],
    "snotel": ["data/snotel.geojson", "data/snotel"],
    "asos": ["data/asos.geojson"],
}


@dataclass
class Context:
    cfg: dict
    session: object
    stage: Path
    cycle: datetime | None = None
    force: bool = False
    workers: int | None = None


@dataclass
class Source:
    name: str
    group: str                       # obs | product | maps
    writes: list[str]
    run: Callable[[Context], dict] | None = None     # None for obs (run as a batch)
    default: bool = True             # part of `--all`
    help: str = ""
    extra: dict = field(default_factory=dict)


def _code_status(code: int) -> dict:
    return {"ok": code == 0, **({} if code == 0 else {"error": f"exit code {code}"})}


def _ndfd(ctx: Context) -> dict:
    from .fetch import ndfd
    return _code_status(ndfd.run(ctx.cfg, ctx.session, ctx.stage / "data" / "ndfd"))


def _nohrsc(ctx: Context) -> dict:
    from .fetch import nohrsc
    return _code_status(nohrsc.run(ctx.cfg, ctx.session, ctx.stage / "data" / "nohrsc"))


def _points(ctx: Context) -> dict:
    from .fetch.nbm.run import run_points
    cyc = ctx.cycle.replace(tzinfo=None) if ctx.cycle else None
    return _code_status(run_points(ctx.cfg, ctx.session, ctx.stage / "data" / "points", cycle=cyc,
                                   workers=ctx.workers or 6))


def _res_status(res: dict) -> dict:
    ok = bool(res.get("ok") or res.get("skipped"))
    out = {"ok": ok}
    for k in ("cycle", "skipped", "reason", "new"):
        if res.get(k) is not None:
            out[k] = res[k]
    if not ok:
        out["error"] = str(res.get("error") or res.get("reason") or "failed")[:300]
    return out


def _ecmwf(ctx: Context) -> dict:
    from .ecmwf_run import run_ecmwf
    cyc = ctx.cycle.replace(tzinfo=timezone.utc) if ctx.cycle else None
    return _res_status(run_ecmwf(ctx.cfg, ctx.session, ctx.stage / "models", cycle=cyc, force=ctx.force))


def _gefs(ctx: Context) -> dict:
    from .fetch import gefs
    cyc = ctx.cycle.replace(tzinfo=timezone.utc) if ctx.cycle else None
    return _res_status(gefs.run(ctx.cfg, ctx.session, ctx.stage / "models", cycle=cyc, force=ctx.force))


def _map_runner(model: str) -> Callable[[Context], dict]:
    def run(ctx: Context) -> dict:
        from .fetch.models.config import load_models_config
        from .fetch.models.run import run_model
        cyc = ctx.cycle.replace(tzinfo=None) if ctx.cycle else None
        return _code_status(run_model(load_models_config(), model, ctx.stage / "models", cycle=cyc, workers=ctx.workers))
    return run


def map_models() -> list[str]:
    try:
        from .fetch.models.config import load_models_config
        return list(load_models_config()["models"])
    except Exception:  # noqa: BLE001 - models.yml unreadable: no map sources, the rest still works
        return []


def registry() -> dict[str, Source]:
    reg = {n: Source(n, "obs", w, help="observations / NWS products (hourly)") for n, w in OBS_WRITES.items()}
    reg["points"] = Source("points", "product", ["data/points"], _points, help="NBM point forecasts (ski areas, Sno-Parks, SNOTEL)")
    reg["nohrsc"] = Source("nohrsc", "product", ["data/nohrsc"], _nohrsc, help="NOHRSC snowfall + SNODAS overlay layers")
    reg["ndfd"] = Source("ndfd", "product", ["data/ndfd"], _ndfd, default=False,
                         help="NWS NDFD point forecasts (archive/verification only; not shown on the site)")
    reg["ecmwf"] = Source("ecmwf", "product", ["models/ecmwf"], _ecmwf, help="ECMWF HRES + ENS (+AIFS) at summits (needs ecmwf.enabled)")
    reg["gefs"] = Source("gefs", "product", ["models/gefs"], _gefs, help="NOAA GEFS plume at summits (needs gefs.enabled)")
    for m in map_models():
        reg[f"maps:{m}"] = Source(f"maps:{m}", "maps", [f"models/{m}"], _map_runner(m), default=False,
                                  help=f"{m.upper()} model-map PNG frames (slow; needs ecCodes/cartopy)")
    return reg


def resolve(names: list[str], all_: bool, reg: dict[str, Source]) -> list[Source]:
    """Source names (or groups: obs, products, maps) -> Sources in registry order. Unknown names raise ValueError."""
    want: set[str] = set()
    if all_:
        want |= {n for n, s in reg.items() if s.default}
    for n in names:
        if n in reg:
            want.add(n)
        elif n in ("obs", "product", "products", "maps"):
            g = "product" if n == "products" else n
            want |= {k for k, s in reg.items() if s.group == g}
        else:
            raise ValueError(f"unknown source {n!r}; choose from {', '.join(reg)} (or obs, products, maps)")
    return [s for n, s in reg.items() if n in want]
