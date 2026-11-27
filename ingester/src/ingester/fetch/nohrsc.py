"""NOHRSC snow analyses as interactive map layers (PLAN.md M3.5 / §5.4).

Sources (NOAA/NWS NOHRSC; public domain, credit "NOAA/NWS NOHRSC"):
- National Snowfall Analysis v2.1, 24/48/72-h windows ending 00Z and 12Z:
  https://www.nohrsc.noaa.gov/snowfall_v2/data/YYYYMM/sfav2_CONUS_{24,48,72}h_YYYYMMDDHH.nc
  (0.04° lat/lon grid, metres; issued ~12 h after the window ends).
- SNODAS daily (06Z) via NSIDC (NOAA data, cite NSIDC G02158):
  https://noaadata.apps.nsidc.org/NOAA/G02158/masked/YYYY/MM_Mon/SNODAS_YYYYMMDD.tar
  (30 arc-second grid; products 1034 = SWE, 1036 = snow depth, both mm, int16 BE).

Output (`<out>/`): value-encoded EPSG:3857 PNGs + index.json for the obs-map overlay,
and ski.json with the analyses sampled at every ski-area base and summit.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import re
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from . import layers as L
from .common import REPO_ROOT, utcnow, write_json

log = logging.getLogger("snow-wx.nohrsc")

SNOWFALL_URL = "https://www.nohrsc.noaa.gov/snowfall_v2/data/{t:%Y%m}/sfav2_CONUS_{win}h_{t:%Y%m%d%H}.nc"
SNODAS_URL = "https://noaadata.apps.nsidc.org/NOAA/G02158/masked/{d:%Y}/{d:%m}_{d:%b}/SNODAS_{d:%Y%m%d}.tar"
ATTRIBUTION = "NOAA/NWS NOHRSC (National Snowfall Analysis; SNODAS via NSIDC)"
M_TO_IN, MM_TO_IN = 39.3701, 1 / 25.4

# id -> label, palette key (web/js/colors.js), encoding, what draws transparent
LAYERS = {
    "sf24": {"label": "Snowfall, past 24 h (NOHRSC analysis)", "group": "Snowfall", "palette": "SNOWFALL",
             "scale": 0.1, "offset": 0.0, "units": "in", "clear_below": 0.1},
    "sf48": {"label": "Snowfall, past 48 h (NOHRSC analysis)", "group": "Snowfall", "palette": "SNOWFALL",
             "scale": 0.1, "offset": 0.0, "units": "in", "clear_below": 0.1},
    "sf72": {"label": "Snowfall, past 72 h (NOHRSC analysis)", "group": "Snowfall", "palette": "SNOWFALL",
             "scale": 0.1, "offset": 0.0, "units": "in", "clear_below": 0.1},
    "swe": {"label": "Snow water equivalent (SNODAS)", "group": "Snowpack", "palette": "swe_in",
            "scale": 0.05, "offset": 0.0, "units": "in", "clear_below": 0.05},
    "depth": {"label": "Snow depth (SNODAS)", "group": "Snowpack", "palette": "depth_in",
              "scale": 0.5, "offset": 0.0, "units": "in", "clear_below": 0.5},
    "swe24": {"label": "24-h SWE change (SNODAS)", "group": "Snowpack", "palette": "swe_24h",
              "scale": 0.02, "offset": -100.0, "units": "in", "clear_between": [-0.05, 0.05]},
}


# ---------------------------------------------------------------- pure helpers

def snowfall_candidates(now: datetime, days: int = 3) -> list[datetime]:
    """00Z/12Z window ends, newest first, starting with the last one not in the future."""
    t = now.replace(minute=0, second=0, microsecond=0)
    t -= timedelta(hours=t.hour % 12)
    return [t - timedelta(hours=12 * k) for k in range(days * 2 + 1)]


def run_key(snowfall_end: datetime | None, snodas_day: datetime | None) -> str:
    """Newest input time as YYYYMMDDHH (SNODAS is valid at 06Z of its day)."""
    times = [t for t in (snowfall_end, snodas_day + timedelta(hours=6) if snodas_day else None) if t]
    return max(times).strftime("%Y%m%d%H") if times else ""


def parse_snodas_header(text: str) -> dict:
    kv = {}
    for line in text.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            kv[k.strip().lower()] = v.strip()
    num = lambda k: float(kv[k])  # noqa: E731
    return {"ncols": int(num("number of columns")), "nrows": int(num("number of rows")),
            "x0": num("benchmark x-axis coordinate"), "y0": num("benchmark y-axis coordinate"),
            "dx": num("x-axis resolution"), "dy": num("y-axis resolution"),
            "nodata": num("no data value"), "units": kv.get("data units", ""),
            "slope": float(kv.get("data slope", 1)), "intercept": float(kv.get("data intercept", 0))}


def snodas_grid(raw: bytes, hdr: dict):
    """(values, lat centres north->south, lon centres) from a SNODAS .dat payload."""
    a = np.frombuffer(raw, dtype=">i2").reshape(hdr["nrows"], hdr["ncols"]).astype("float32")
    a[a == hdr["nodata"]] = np.nan
    a = a * hdr["slope"] + hdr["intercept"]
    lats = hdr["y0"] - np.arange(hdr["nrows"]) * hdr["dy"]
    lons = hdr["x0"] + np.arange(hdr["ncols"]) * hdr["dx"]
    return a, lats, lons


def crop(values, lats, lons, bbox, pad=0.2):
    """Cut a regular grid to bbox [w, s, e, n] (+pad degrees) before regridding."""
    w, s, e, n = bbox
    iy = np.where((lats >= s - pad) & (lats <= n + pad))[0]
    ix = np.where((lons >= w - pad) & (lons <= e + pad))[0]
    return values[iy[0]:iy[-1] + 1, ix[0]:ix[-1] + 1], lats[iy[0]:iy[-1] + 1], lons[ix[0]:ix[-1] + 1]


# ---------------------------------------------------------------- fetch

def _get(session, url, **kw):
    r = session.get(url, timeout=120, **kw)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r


def fetch_snowfall(session, now) -> tuple[datetime | None, dict]:
    """Newest 00/12Z end with all three windows -> {win: (inches, lats, lons)}."""
    import netCDF4
    for t in snowfall_candidates(now):
        got = {}
        for win in (24, 48, 72):
            r = _get(session, SNOWFALL_URL.format(t=t, win=win))
            if r is None:
                break
            ds = netCDF4.Dataset("sf.nc", mode="r", memory=r.content)
            try:
                data = np.ma.filled(ds.variables["Data"][:].astype("float32"), np.nan)
                lats, lons = np.array(ds.variables["lat"][:]), np.array(ds.variables["lon"][:])
            finally:
                ds.close()
            got[win] = (data * M_TO_IN, lats, lons)
        if len(got) == 3:
            return t, got
        log.debug("snowfall %s incomplete (%s)", t, list(got))
    return None, {}


def fetch_snodas_day(session, day: datetime) -> dict | None:
    """{1034: grid, 1036: grid} in inches for one SNODAS day, or None if not out yet."""
    r = _get(session, SNODAS_URL.format(d=day))
    if r is None:
        return None
    out = {}
    with tarfile.open(fileobj=io.BytesIO(r.content)) as tf:
        names = tf.getnames()
        for code in (1034, 1036):
            dat = next(n for n in names if re.search(rf"ssmv1{code}tS__T0001TTNATS.*\.dat\.gz$", n))
            hdr = parse_snodas_header(gzip.decompress(tf.extractfile(dat.replace(".dat.gz", ".txt.gz")).read()).decode("latin-1"))
            vals, lats, lons = snodas_grid(gzip.decompress(tf.extractfile(dat).read()), hdr)
            out[code] = (vals * MM_TO_IN, lats, lons)
    return out


def fetch_snodas(session, now, lookback_days: int = 5):
    """(day, grids) for the newest available day and (day-1, grids) before it."""
    d = now.replace(hour=0, minute=0, second=0, microsecond=0)
    for k in range(lookback_days):
        day = d - timedelta(days=k)
        cur = fetch_snodas_day(session, day)
        if cur is not None:
            prev = fetch_snodas_day(session, day - timedelta(days=1))
            return day, cur, prev
    return None, None, None


# ---------------------------------------------------------------- run

def build_layer(lid: str, values, lats, lons, grid: L.TargetGrid, out: Path, valid: str, source: str) -> dict:
    spec = LAYERS[lid]
    rg = L.regrid_regular(values, lats, lons, grid)
    png = L.png_bytes(L.encode(rg, spec["scale"], spec["offset"]))
    (out / f"{lid}.png").write_bytes(png)
    finite = rg[np.isfinite(rg)]
    return {"id": lid, **spec, "valid": valid, "source": source, "file": f"{lid}.png",
            "bytes": len(png), "max": round(float(finite.max()), 2) if finite.size else None, **grid.meta()}


def run(cfg: dict, session, out: Path, *, published: str | None = None, github_output: str | None = None,
        catalog: Path | None = None, now: datetime | None = None) -> int:
    def emit(**kv):
        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                for k, v in kv.items():
                    f.write(f"{k}={v}\n")

    now = now or utcnow()
    bbox = cfg["region"]["bbox"]                       # [w, s, e, n]
    sf_end, sf = fetch_snowfall(session, now)
    sd_day, sd, sd_prev = fetch_snodas(session, now)
    key = run_key(sf_end, sd_day)
    if not key:
        log.warning("no NOHRSC snowfall or SNODAS data found")
        emit(new="false")
        return 0
    from .version import stamp
    tag = stamp(key, "nohrsc")
    if published == tag:
        log.info("NOHRSC %s already published; nothing new", tag)
        emit(new="false", cycle=tag)
        return 0

    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    fine = L.TargetGrid.from_bbox(*bbox, res=1500.0)    # SNODAS ~1 km
    coarse = L.TargetGrid.from_bbox(*bbox, res=3000.0)  # NOHRSC snowfall 0.04°
    layers, samples = [], {}
    if sf:
        valid = sf_end.strftime("%Y-%m-%dT%H:%MZ")
        for win, (vals, lats, lons) in sf.items():
            v, la, lo = crop(vals, lats, lons, bbox)
            layers.append(build_layer(f"sf{win}", v, la, lo, coarse, out, valid, "NOHRSC National Snowfall Analysis v2.1"))
            samples[f"sf{win}"] = (v, la, lo)
    if sd:
        valid = (sd_day + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%MZ")
        for lid, code in (("swe", 1034), ("depth", 1036)):
            v, la, lo = crop(*sd[code], bbox)
            layers.append(build_layer(lid, v, la, lo, fine, out, valid, "NOHRSC SNODAS (via NSIDC)"))
            samples[lid] = (v, la, lo)
        if sd_prev:
            v1, la, lo = crop(*sd[1034], bbox)
            v0, _, _ = crop(*sd_prev[1034], bbox)
            layers.append(build_layer("swe24", v1 - v0, la, lo, fine, out, valid, "NOHRSC SNODAS (via NSIDC)"))
    write_json(out / "index.json", {
        "key": key, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "attribution": ATTRIBUTION,
        "snowfall_end": sf_end.strftime("%Y-%m-%dT%H:%MZ") if sf_end else None,
        "snodas_valid": (sd_day + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%MZ") if sd_day else None,
        "layers": layers}, ndigits=6)

    # bonus: analyses at every ski-area base and summit
    cat_path = catalog or REPO_ROOT / "data" / "ski_areas.json"
    if cat_path.exists():
        cat = json.loads(cat_path.read_text(encoding="utf-8"))
        rp = cat_path.with_name("rec_points.json")           # Sno-Park trailheads too (M4.5)
        if rp.exists():
            cat["areas"] = cat["areas"] + json.loads(rp.read_text(encoding="utf-8"))["areas"]
        areas = {}
        for a in cat["areas"]:
            rec = {}
            for k in ("summit", "base"):
                rec[k] = {lid: (None if (x := L.sample(*samples[lid], a[k]["lat"], a[k]["lon"])) is None else round(x, 1))
                          for lid in samples}
            areas[a["id"]] = rec
        write_json(out / "ski.json", {"key": key, "snowfall_end": sf_end.strftime("%Y-%m-%dT%H:%MZ") if sf_end else None,
                                      "snodas_valid": (sd_day + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%MZ") if sd_day else None,
                                      "attribution": ATTRIBUTION, "areas": areas})
    total = sum(l["bytes"] for l in layers)
    log.info("NOHRSC %s: %d layers (%s), %.1f MB", key, len(layers),
             ", ".join(f"{l['id']} {l['bytes'] / 1024:.0f} KB" for l in layers), total / 1e6)
    emit(new="true", cycle=tag)
    return 0
