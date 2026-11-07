"""Model GRIB2 access: cycle discovery, Herbie byte-range downloads from NOAA
Open Data Dissemination (AWS), and decoding selected messages with ecCodes.

Only this module touches the network. Everything here returns plain numpy
arrays (float32, cropped to the model's map area) for derive.py / plot.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Iterable

import numpy as np

log = logging.getLogger("snow-wx.models")

# ---------------------------------------------------------------- variables


@dataclass(frozen=True)
class Var:
    name: str      # canonical name used in this package, e.g. "t700"
    where: str     # "sfc" or "upper": key into the model's `products`
    idx: str       # regex fragment matched against Herbie's .idx lines
    keys: tuple    # ecCodes (key, value) pairs identifying the decoded message


def var_catalog(levels: Iterable[int]) -> dict[str, Var]:
    """Canonical variables. NCEP models (HRRR, RRFS, GFS) share these names."""
    v: dict[str, Var] = {}

    def iso(short, p):
        return (("shortName", short), ("typeOfLevel", "isobaricInhPa"), ("level", int(p)))

    for p in levels:
        v[f"t{p}"] = Var(f"t{p}", "upper", rf":TMP:{p} mb:", iso("t", p))
        v[f"dpt{p}"] = Var(f"dpt{p}", "upper", rf":DPT:{p} mb:", iso("dpt", p))
        v[f"rh{p}"] = Var(f"rh{p}", "upper", rf":RH:{p} mb:", iso("r", p))
        v[f"gh{p}"] = Var(f"gh{p}", "upper", rf":HGT:{p} mb:", iso("gh", p))
    for p in (500, 700):
        v[f"u{p}"] = Var(f"u{p}", "upper", rf":UGRD:{p} mb:", iso("u", p))
        v[f"v{p}"] = Var(f"v{p}", "upper", rf":VGRD:{p} mb:", iso("v", p))
    v["absv500"] = Var("absv500", "upper", r":ABSV:500 mb:", iso("absv", 500))

    def sfc(name, idx, short, tol="surface", level=None, **extra):
        keys = [("shortName", short), ("typeOfLevel", tol)]
        if level is not None:
            keys.append(("level", level))
        keys.extend(extra.items())
        v[name] = Var(name, "sfc", idx, tuple(keys))

    sfc("t2m", r":TMP:2 m above ground:", "2t", "heightAboveGround", 2)
    sfc("d2m", r":DPT:2 m above ground:", "2d", "heightAboveGround", 2)
    sfc("gust", r":GUST:surface:", "gust")
    sfc("sp", r":PRES:surface:", "sp")
    sfc("orog", r":HGT:surface:", "orog")
    sfc("cpofp", r":CPOFP:surface:", "cpofp")
    sfc("csnow", r":CSNOW:surface:(?:anl|\d+ hour fcst)", "csnow")
    sfc("apcp", r":APCP:surface:0-\d+ (?:hour|day) acc", "tp", startStep=0)
    sfc("hgt0c", r":HGT:0C isotherm:", "gh", "isothermZero")
    # Free-atmosphere freezing level (not dragged to the ground by valley cold pools).
    sfc("fzl_top", r":HGT:highest tropospheric freezing level:", "gh", "highestTroposphericFreezing")
    return v


def needed_vars(mcfg: dict, fields: Iterable[str]) -> list[str]:
    """Canonical variables required to draw `fields` for one model."""
    levels = mcfg["levels"]
    moist = "rh" if mcfg.get("moisture") == "rh" else "dpt"
    need = {"orog"}
    for f in fields:
        if f == "h500":
            need |= {"gh500"} | ({"absv500"} if mcfg.get("vorticity") == "native" else {"u500", "v500"})
        elif f == "t700":
            need |= {"t700", "gh700", "u700", "v700"}
        elif f.startswith("qpf"):
            need.add("apcp")
        elif f == "snow":
            need |= {"apcp", "cpofp", "csnow", "t2m", "sp"} | {f"t{p}" for p in levels} \
                | {f"gh{p}" for p in levels}
        elif f == "snowlevel":
            need |= {"t2m", "d2m", "sp", "fzl_top", "hgt0c", "apcp"} | {f"t{p}" for p in levels} \
                | {f"{moist}{p}" for p in levels} | {f"gh{p}" for p in levels}
        elif f == "t2m":
            need.add("t2m")
        elif f == "gust":
            need.add("gust")
        else:
            raise ValueError(f"unknown field {f!r}")
    return sorted(need)


def search_regex(catalog: dict[str, Var], names: Iterable[str], where: set[str]) -> str:
    return "|".join(catalog[n].idx for n in names if catalog[n].where in where)


# ---------------------------------------------------------------- cycles

def candidate_cycles(now: datetime, cycles: Iterable[int], lookback_hours: int = 36) -> list[datetime]:
    """Allowed init times in the last `lookback_hours`, newest first (naive UTC)."""
    t = now.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    allowed = {int(c) for c in cycles}
    out = []
    for h in range(lookback_hours + 1):
        c = t - timedelta(hours=h)
        if c.hour in allowed:
            out.append(c)
    return out


def latest_cycle(candidates: list[datetime], exists: Callable[[datetime], bool]) -> datetime | None:
    """First (newest) candidate whose last needed forecast hour is published."""
    for c in candidates:
        if exists(c):
            return c
    return None


def make_herbie(mcfg: dict, cycle: datetime, fxx: int, product: str, save_dir: Path):
    from herbie import Herbie  # imported lazily: heavy, and needs the DLL bootstrap
    return Herbie(cycle, fxx=fxx, product=product, priority=["aws"], save_dir=str(save_dir),
                  verbose=False, **mcfg["herbie"])


def cycle_complete(mcfg: dict, cycle: datetime, fxx: int, save_dir: Path) -> bool:
    """True if every product's GRIB index for `fxx` exists on AWS."""
    for product in sorted(set(mcfg["products"].values())):
        try:
            H = make_herbie(mcfg, cycle, fxx, product, save_dir)
        except Exception as exc:
            log.debug("%s %s f%03d %s: %s", mcfg["label"], cycle, fxx, product, exc)
            return False
        if H.grib is None or H.idx is None:
            return False
    return True


def download_frame(mcfg: dict, catalog: dict[str, Var], names: list[str], cycle: datetime,
                   fxx: int, save_dir: Path) -> list[Path]:
    """Byte-range download the needed messages for one forecast hour.

    Returns one local GRIB2 subset file per distinct Herbie product.
    """
    by_product: dict[str, set[str]] = {}
    for where, product in mcfg["products"].items():
        by_product.setdefault(product, set()).add(where)
    paths = []
    for product, wheres in by_product.items():
        wanted = [n for n in names if not (n == "apcp" and fxx == 0)]  # no accumulation at f000
        regex = search_regex(catalog, wanted, wheres)
        if not regex:
            continue
        H = make_herbie(mcfg, cycle, fxx, product, save_dir)
        if H.grib is None:
            raise FileNotFoundError(f"{mcfg['label']} {cycle:%Y%m%d%H} f{fxx:03d} {product} not on AWS")
        paths.append(Path(H.download(regex, verbose=False)))
    return paths


# ---------------------------------------------------------------- decoding

@dataclass
class Grid:
    """Model grid cropped to the map area, plus what plotting needs to sample it."""
    lat: np.ndarray
    lon: np.ndarray
    crs: dict                  # {"kind": "lcc"|"latlon", ...} -> plot.crs_from_params
    uv_grid_relative: bool
    dx_m: float                # nominal spacing (vorticity, smoothing)
    dy_m: float
    rows: slice
    cols: slice


def crop_slices(lat: np.ndarray, lon: np.ndarray, extent, margin: float = 1.5) -> tuple[slice, slice]:
    w, e, s, n = extent
    m = (lat >= s - margin) & (lat <= n + margin) & (lon >= w - margin) & (lon <= e + margin)
    if not m.any():
        raise ValueError("map extent does not overlap the model grid")
    r = np.where(m.any(axis=1))[0]
    c = np.where(m.any(axis=0))[0]
    return slice(r[0], r[-1] + 1), slice(c[0], c[-1] + 1)


def _get(gid, key, default=None):
    import eccodes
    try:
        return eccodes.codes_get(gid, key)
    except Exception:
        return default


def _grid_from_message(gid, extent) -> Grid:
    import eccodes
    ny = int(_get(gid, "Nj") or _get(gid, "Ny"))
    nx = int(_get(gid, "Ni") or _get(gid, "Nx"))
    lat = eccodes.codes_get_array(gid, "latitudes").reshape(ny, nx)
    lon = eccodes.codes_get_array(gid, "longitudes").reshape(ny, nx)
    lon = ((lon + 180.0) % 360.0) - 180.0
    rows, cols = crop_slices(lat, lon, extent)
    grid_type = _get(gid, "gridType")
    radius = float(_get(gid, "radius", 6371229) or 6371229)
    if grid_type == "lambert":
        lov = float(_get(gid, "LoVInDegrees"))
        crs = {"kind": "lcc", "lon0": lov - 360.0 if lov > 180 else lov,
               "lat0": float(_get(gid, "LaDInDegrees")),
               "lat1": float(_get(gid, "Latin1InDegrees")), "lat2": float(_get(gid, "Latin2InDegrees")),
               "radius": radius}
        dx = float(_get(gid, "DxInMetres")); dy = float(_get(gid, "DyInMetres"))
    elif grid_type == "regular_ll":
        crs = {"kind": "latlon"}
        dlon = abs(float(_get(gid, "iDirectionIncrementInDegrees")))
        dlat = abs(float(_get(gid, "jDirectionIncrementInDegrees")))
        mid = np.deg2rad(float(np.mean(lat[rows, cols])))
        dx = dlon * 111_195.0 * np.cos(mid); dy = dlat * 111_195.0
    else:
        raise ValueError(f"unsupported gridType {grid_type!r}")
    return Grid(lat=lat[rows, cols].astype(np.float64), lon=lon[rows, cols].astype(np.float64),
                crs=crs, uv_grid_relative=bool(_get(gid, "uvRelativeToGrid", 0)),
                dx_m=dx, dy_m=dy, rows=rows, cols=cols)


def _match(gid, catalog_keys: dict[tuple, str]) -> str | None:
    for keys, name in catalog_keys.items():
        if all(_get(gid, k) == val for k, val in keys):
            return name
    return None


def decode(paths: Iterable[Path], catalog: dict[str, Var], names: Iterable[str],
           extent, grid: Grid | None = None) -> tuple[dict[str, np.ndarray], Grid]:
    """Read wanted messages from GRIB2 files -> ({name: float32 2-D cropped}, grid)."""
    import eccodes
    wanted = set(names)
    lookup = {catalog[n].keys: n for n in wanted}
    out: dict[str, np.ndarray] = {}
    for path in paths:
        with open(path, "rb") as f:
            while True:
                gid = eccodes.codes_grib_new_from_file(f)
                if gid is None:
                    break
                try:
                    name = _match(gid, lookup)
                    if name is None or name in out:
                        continue
                    if grid is None:
                        grid = _grid_from_message(gid, extent)
                    ny = int(_get(gid, "Nj") or _get(gid, "Ny"))
                    nx = int(_get(gid, "Ni") or _get(gid, "Nx"))
                    vals = eccodes.codes_get_values(gid).reshape(ny, nx)[grid.rows, grid.cols]
                    vals = vals.astype(np.float32)
                    if _get(gid, "bitmapPresent"):
                        vals[vals == np.float32(_get(gid, "missingValue", 9999))] = np.nan
                    out[name] = vals
                finally:
                    eccodes.codes_release(gid)
    if grid is None:
        raise ValueError("no wanted GRIB messages decoded")
    missing = wanted - set(out)
    if missing:
        log.debug("not in files: %s", ", ".join(sorted(missing)))
    return out, grid
