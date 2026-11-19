"""ECMWF open data at every ski area's summit: IFS HRES (operational) and the IFS ENS ensemble plume (M8-lite, docs/specs/multi-model.md; dev17).

Source: ECMWF Open Data (CC BY 4.0), AWS mirror `ecmwf-forecasts` (no portal, no key). One byte-range request per GRIB message using the
`.index` files (JSON lines: param, type, number, step, _offset, _length): only `tp` (total precipitation, m, accumulated since the run start)
and `sf` (snowfall water equivalent, m of water) are fetched; HRES also supplies `z` (surface geopotential, the model terrain).
Measured Nov 18 2026 (00Z run): 0.25 degree ENS = 16.2 MB (tp) + 7.1 MB (sf) per step for the 50 perturbed members, about 5 s per step
(41 steps 0-240 h by 6 h: ~0.95 GB). The 0.1 degree ENS is ~72 MB per step for tp alone (~2.9 GB per cycle) and is not used.
FOUND, not assumed: the mirror carries 50 perturbed members (type pf, numbers 1-50) and NO control member (type cf) in any enfo file, so the
plume has 50 members, not 51; the control is not drawn.

Statistics (NOT summing percentiles): every member is one complete scenario. The values are accumulated PER MEMBER (the GRIB fields already are
cumulative from the start), then quantiles are taken ACROSS members at each step (`quantiles`: numpy "linear" = Hyndman-Fan type 7 on the
valid members, plus the mean). Nothing in NBM's percentile products is read or combined here.

Outputs under <out> (the models folder, like every other product: `--out out/models`; update-site unpacks `ecmwf-<cycle>.tar` into build/models/):
  ecmwf/precip.json          HRES in the M7 sampler format -> merged into data/multimodel.json as a fifth source (multimodel.merge)
  ecmwf/index.json           cycle, steps, member count, sizes, attribution
  ecmwf/plume/<area>.json    LAZY plume file (fetched only when the Ensemble view is selected): members x steps in 0.1 mm integers
Everything is gated by config `ecmwf.enabled` (false until the owner wires the workflow, docs/workflow_snippets/ecmwf.yml).
"""

from __future__ import annotations

import json
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from .common import REPO_ROOT, utcnow, write_json

log = logging.getLogger("snow-wx.ecmwf")
MIRROR = "https://ecmwf-forecasts.s3.amazonaws.com"
DEFAULTS = {
    "enabled": False,
    "mirror": MIRROR,
    "cycles": [0, 12],                      # ENS 00Z and 12Z (06/18Z carry only 0-144 h)
    "step_h": 6,
    "max_step_h": 240,
    "members": 50,                          # perturbed members on the mirror (no control)
    "max_missing_frac": 0.2,                # more than 20 % of a step's member messages missing = the run fails (like the NBM rule)
    "workers": 6,
    "stale_hours": 24,
    "release_lag_h": 8,                     # ENS lands ~7-9 h after the nominal time
}
MM_PER_M = 1000.0
Q_STEP_MM = 0.1                              # quantization of the plume files (0.1 mm)
ATTRIBUTION = ("Adapted from 'ECMWF IFS 15-day Forecast Data' by ECMWF, licensed under CC BY 4.0, available at https://data.ecmwf.int/forecasts/. "
               "Values were sampled at ski-area summit points, accumulated per ensemble member and summarised by Snow-Wx (adapted).")
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
TERMS_URL = "https://apps.ecmwf.int/datasets/licences/general/"
QS = (10, 25, 50, 75, 90)


def configure(cfg: dict | None) -> dict:
    out = dict(DEFAULTS)
    out.update({k: v for k, v in ((cfg or {}).get("ecmwf") or {}).items() if k in DEFAULTS})
    return out


# ---------------------------------------------------------------- pure helpers
def steps_for(c: dict) -> list[int]:
    return list(range(0, int(c["max_step_h"]) + 1, int(c["step_h"])))


def grid_index(lat: float, lon: float) -> tuple[int, int]:
    """Nearest cell of ECMWF's 0.25 degree global grid (721 x 1440): rows run from 90 N south, columns from 180 E eastward (so longitude -180 is column 0
    after the shift): j = ((lon - 180) mod 360) / 0.25. Pure, no wrap bugs at the date line."""
    i = int(round((90.0 - lat) / 0.25))
    j = int(round(((lon - 180.0) % 360.0) / 0.25)) % 1440
    return min(max(i, 0), 720), j


def grid_latlon(i: int, j: int) -> tuple[float, float]:
    lon = 180.0 + 0.25 * j
    return 90.0 - 0.25 * i, lon - 360.0 if lon > 180.0 else lon


def parse_index(text: str) -> list[dict]:
    """JSON-lines .index -> rows (bad lines skipped)."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def select(rows: list[dict], param: str, typ: str | None = None, step: int | None = None) -> dict[int, dict]:
    """{member number: row} for surface `param` (ENS: type pf; HRES: number 0)."""
    out = {}
    for r in rows:
        if r.get("param") != param or r.get("levtype") != "sfc":
            continue
        if typ and r.get("type") != typ:
            continue
        if step is not None and int(r.get("step", -1)) != step:
            continue
        out[int(r.get("number", 0))] = r
    return out


def url(c: dict, cycle: datetime, stream: str, step: int, ext: str) -> str:
    """e.g. .../20261118/00z/ifs/0p25/enfo/20261118000000-24h-enfo-ef.grib2 (HRES: oper/...-oper-fc.grib2)"""
    kind = "enfo-ef" if stream == "enfo" else "oper-fc"
    return f"{c['mirror']}/{cycle:%Y%m%d}/{cycle:%H}z/ifs/0p25/{stream}/{cycle:%Y%m%d%H}0000-{step}h-{kind}.{ext}"


def quantiles(members: np.ndarray) -> dict:
    """Across-member statistics at each step. `members`: (steps, n) cumulative amounts, NaN = missing member. Returns {p10,p25,p50,p75,p90,mean,n}
    per step; method documented above (linear / type 7 on the valid members). A step with no valid member gives NaN."""
    a = np.asarray(members, dtype="float64")
    out = {"n": np.sum(np.isfinite(a), axis=1)}
    import warnings
    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)       # an all-NaN step is NaN, not an error
        for q in QS:
            out[f"p{q}"] = np.nanpercentile(a, q, axis=1, method="linear") if a.shape[1] else np.full(a.shape[0], np.nan)
        out["mean"] = np.nanmean(a, axis=1)
    return out


def monotone(members: np.ndarray) -> np.ndarray:
    """Cumulative handling: each member's running total never decreases (GRIB packing of different steps can differ in the last bit). NaN stays NaN
    and does not reset the running maximum."""
    a = np.array(members, dtype="float64", copy=True)
    for k in range(a.shape[1]):
        run = 0.0
        for s in range(a.shape[0]):
            if np.isfinite(a[s, k]):
                run = max(run, a[s, k])
                a[s, k] = run
    return a


def to_tenths_mm(m: np.ndarray) -> list:
    """metres -> integer 0.1 mm (None for missing): small files, no float noise."""
    flat = np.asarray(m, dtype="float64") * MM_PER_M / Q_STEP_MM
    return [[None if not math.isfinite(v) else int(round(v)) for v in row] for row in flat]


def member_shares(totals_mm: np.ndarray, thresholds_in: list[float]) -> dict:
    """{threshold in: (members at or above it, valid members)} for one array of member totals (mm of water)."""
    v = np.asarray(totals_mm, dtype="float64")
    ok = v[np.isfinite(v)]
    return {t: (int(np.sum(ok >= t * 25.4)), int(ok.size)) for t in thresholds_in}


class Sampler:
    """Collects values at the area cells, step by step: ens[param] -> {step: (n_members, n_areas)}, hres[param] -> {step: (n_areas,)}."""

    def __init__(self, points: list[dict], members: int):
        self.points, self.n = points, members
        self.idx = [grid_index(p["lat"], p["lon"]) for p in points]
        self.flat = np.array([i * 1440 + j for i, j in self.idx])
        self.ens: dict[str, dict[int, np.ndarray]] = {"tp": {}, "sf": {}}
        self.hres: dict[str, dict[int, np.ndarray]] = {"tp": {}, "sf": {}}
        self.z = None
        self.missing: dict[int, int] = {}

    def sample(self, field: np.ndarray) -> np.ndarray:
        return np.asarray(field, dtype="float64").ravel()[self.flat]

    def add_ens(self, param: str, step: int, fields: dict[int, np.ndarray]) -> None:
        """fields: {member number 1..n: 2-D array}; absent members stay NaN (counted in self.missing)"""
        arr = np.full((self.n, len(self.points)), np.nan)
        for k, f in fields.items():
            if 1 <= k <= self.n:
                arr[k - 1] = self.sample(f)
        self.ens[param][step] = arr
        if param == "tp":
            self.missing[step] = int(self.n - len(fields))

    def add_hres(self, param: str, step: int, field: np.ndarray | None) -> None:
        self.hres[param][step] = np.full(len(self.points), np.nan) if field is None else self.sample(field)

    def ens_matrix(self, param: str, area: int, steps: list[int]) -> np.ndarray:
        """(steps, members) cumulative metres at one area; step 0 is zero by definition; per-member monotone."""
        rows = [np.zeros(self.n) if s == 0 else self.ens[param].get(s, np.full((self.n, len(self.points)), np.nan))[:, area] for s in steps]
        return monotone(np.vstack(rows))

    def hres_series(self, param: str, area: int, steps: list[int]) -> np.ndarray:
        v = np.array([0.0 if s == 0 else self.hres[param].get(s, np.full(len(self.points), np.nan))[area] for s in steps])
        return monotone(v[:, None])[:, 0]


def area_docs(sampler: Sampler, cycle: datetime, steps: list[int]) -> tuple[dict, dict]:
    """(per-area plume documents, HRES precip.json in the M7 format). Pure given the sampler."""
    init = cycle.strftime("%Y-%m-%dT%H:00Z")
    plume, hres_areas = {}, {}
    for a, p in enumerate(sampler.points):
        tp = sampler.ens_matrix("tp", a, steps)
        sf = sampler.ens_matrix("sf", a, steps)
        h_tp = sampler.hres_series("tp", a, steps)
        h_sf = sampler.hres_series("sf", a, steps)
        z_ft = None if sampler.z is None or not np.isfinite(sampler.z[a]) else int(round(float(sampler.z[a]) * 3.28084))
        if not np.isfinite(tp[-1]).any() and not np.isfinite(h_tp).any():
            continue
        plume[p["id"]] = {"id": p["id"], "model": "ECMWF IFS ENS", "init": init, "cycle": cycle.strftime("%Y%m%d%H"), "generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "hours": steps,
                          "n_members": sampler.n, "unit": f"{Q_STEP_MM} mm", "z_ft": z_ft,
                          "tp": to_tenths_mm(tp), "sf": to_tenths_mm(sf), "hres_tp": [r[0] for r in to_tenths_mm(h_tp[:, None])],
                          "hres_sf": [r[0] for r in to_tenths_mm(h_sf[:, None])]}
        hres_areas[p["id"]] = {"q": [None if not math.isfinite(v) else round(v * 39.3701, 2) for v in h_tp], "z": z_ft}
    hres_doc = {"model": "ecmwf", "label": "ECMWF", "plume": True, "cycle": cycle.strftime("%Y%m%d%H"), "init": init, "hours": steps, "areas": hres_areas}
    return plume, hres_doc


# ---------------------------------------------------------------- network (thin)
def _get(session, u: str, headers=None, tries: int = 6):
    """GET with backoff: the S3 mirror answers 503 SlowDown under bursts."""
    last = None
    for i in range(tries):
        r = session.get(u, headers=headers or {}, timeout=90)
        if r.status_code in (200, 206):
            return r
        last = r.status_code
        if r.status_code == 404:
            return None
        time.sleep(min(30, 2 * (i + 1)))
    raise RuntimeError(f"{u}: HTTP {last}")


def newest_cycle(session, c: dict, now: datetime) -> datetime | None:
    """Newest 00/12Z cycle whose LAST step (HRES and ENS index files) is already published (HEAD, no body)."""
    t = now.replace(minute=0, second=0, microsecond=0)
    for back in range(0, 72):
        cyc = t - timedelta(hours=back)
        if cyc.hour not in c["cycles"] or (now - cyc) < timedelta(hours=c["release_lag_h"] - 1):
            continue
        ok = True
        for stream in ("oper", "enfo"):
            r = session.head(url(c, cyc, stream, c["max_step_h"], "index"), timeout=30)
            ok = ok and r.status_code == 200
        if ok:
            return cyc
    return None


def decode(blob: bytes) -> np.ndarray:
    """One GRIB2 message -> (721, 1440) float32 in the file's units (m)."""
    import eccodes
    h = eccodes.codes_new_from_message(blob)
    try:
        ni, nj = eccodes.codes_get(h, "Ni"), eccodes.codes_get(h, "Nj")
        if (ni, nj) != (1440, 721) or eccodes.codes_get(h, "scanningMode") != 0:
            raise ValueError(f"unexpected ECMWF grid {ni}x{nj}")
        return eccodes.codes_get_values(h).reshape(nj, ni).astype("float32")
    finally:
        eccodes.codes_release(h)


def run(cfg: dict, session, out: Path, *, cycle: datetime | None = None, force: bool = False, points: list[dict] | None = None, now: datetime | None = None,
        published: str | None = None, github_output: str | None = None) -> dict:
    """Fetch, sample, write. `out` is the MODELS folder (writes <out>/ecmwf/...). Needs `force=True` while config ecmwf.enabled is false (a manual test run).
    `published` (the newest ecmwf asset tag on the release) and `github_output` follow the other products: new=false when nothing newer is complete."""
    def emit(**kv):
        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                for k2, v in kv.items():
                    f.write(f"{k2}={v}" + chr(10))

    c = configure(cfg)
    if not c["enabled"] and not force:
        log.info("ecmwf: disabled (config ecmwf.enabled)")
        emit(new="false")
        return {"ok": False, "skipped": "disabled"}
    from .models.multimodel import load_points
    pts = points or load_points()
    now = now or utcnow()
    cyc = cycle or newest_cycle(session, c, now)
    if cyc is None:
        raise RuntimeError("no complete ECMWF cycle on the mirror yet")
    from .version import stamp
    tag = stamp(cyc.strftime("%Y%m%d%H"), "ecmwf")
    if published == tag:
        log.info("ecmwf %s already published; nothing new", tag)
        emit(new="false", cycle=tag)
        return {"ok": True, "skipped": "published", "cycle": tag}
    steps = steps_for(c)
    t0 = time.time()
    nbytes = {"n": 0}
    sam = Sampler(pts, c["members"])
    session.headers["User-Agent"] = session.headers.get("User-Agent", "snow-wx")

    def fetch(u, row):
        r = _get(session, u, {"Range": f"bytes={row['_offset']}-{row['_offset'] + row['_length'] - 1}"})
        if r is None:
            raise RuntimeError(f"{u}: not found")
        nbytes["n"] += len(r.content)
        return decode(r.content)

    def maybe(u, row):
        """one message, or None when it cannot be fetched/decoded: a failed member is a MISSING member (counted against max_missing_frac), not a dead run"""
        try:
            return fetch(u, row)
        except Exception as exc:  # noqa: BLE001
            log.warning("ecmwf: %s: %s", u.rsplit("/", 1)[-1], exc)
            return None

    def index(stream, step, required):
        r = _get(session, url(c, cyc, stream, step, "index"))
        if r is None:
            if required:
                raise RuntimeError(f"ECMWF {stream} index for step {step} not on the mirror")
            return []
        return parse_index(r.text)

    # HRES: terrain once, then tp / sf per step (HRES is optional per step: a gap in the line, the ensemble still publishes)
    z = select(index("oper", 0, False), "z").get(0)
    if z:
        zf = maybe(url(c, cyc, "oper", 0, "grib2"), z)
        if zf is not None:
            sam.z = sam.sample(zf) / 9.80665               # geopotential (m2/s2) -> metres
    with ThreadPoolExecutor(c["workers"]) as ex:
        for s in steps[1:]:
            hrows = index("oper", s, False)
            for param in ("tp", "sf"):
                row = select(hrows, param).get(0)
                sam.add_hres(param, s, maybe(url(c, cyc, "oper", s, "grib2"), row) if row else None)
            erows = index("enfo", s, True)
            for param in ("tp", "sf"):
                sel = select(erows, param, "pf")
                fetched = dict(zip(sel, ex.map(lambda k: maybe(url(c, cyc, "enfo", s, "grib2"), sel[k]), sel)))
                sam.add_ens(param, s, {k: v for k, v in fetched.items() if v is not None})
            if sam.missing.get(s, 0) > c["max_missing_frac"] * c["members"]:
                raise RuntimeError(f"ECMWF ENS step {s}: {sam.missing[s]} of {c['members']} member messages missing")
    plume, hres_doc = area_docs(sam, cyc, steps)
    if not plume:                                      # nothing usable: fail BEFORE touching the last good files
        raise RuntimeError("ECMWF: no area has data")
    out = Path(out)
    (out / "ecmwf" / "plume").mkdir(parents=True, exist_ok=True)
    for old in (out / "ecmwf" / "plume").glob("*.json"):
        old.unlink()
    sizes = []
    for aid, d in plume.items():
        write_json(out / "ecmwf" / "plume" / f"{aid}.json", d)
        sizes.append((out / "ecmwf" / "plume" / f"{aid}.json").stat().st_size)
    write_json(out / "ecmwf" / "precip.json", hres_doc)
    secs = round(time.time() - t0, 1)
    index = {"generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "cycle": cyc.strftime("%Y%m%d%H"), "init": cyc.strftime("%Y-%m-%dT%H:00Z"),
             "hours": steps, "n_members": c["members"], "areas": len(plume), "resolution": "0.25 degree", "control_member": False,
             "stale_hours": c["stale_hours"], "missing_member_messages": sum(sam.missing.values()), "bytes_downloaded": nbytes["n"], "seconds": secs,
             "source": "ECMWF Open Data (IFS HRES and ENS), AWS mirror", "attribution": ATTRIBUTION, "license": LICENSE_URL, "terms": TERMS_URL}
    write_json(out / "ecmwf" / "index.json", index)
    emit(new="true", cycle=tag)
    log.info("ecmwf %s: %d areas, %d steps, %.0f MB downloaded in %.0f s; per-area file avg %.1f KB",
             index["cycle"], len(plume), len(steps), nbytes["n"] / 1e6, secs, (sum(sizes) / max(1, len(sizes))) / 1024)
    return {"ok": True, **index, "avg_area_bytes": int(sum(sizes) / max(1, len(sizes))), "max_area_bytes": max(sizes) if sizes else 0}
