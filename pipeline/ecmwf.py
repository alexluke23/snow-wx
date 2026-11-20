"""ECMWF open data at every ski area's summit: IFS HRES (operational) and the IFS ENS ensemble plume (M8-lite, docs/specs/multi-model.md; dev17).

Source: ECMWF Open Data (CC BY 4.0), no key. Mirrors (dev19, `mirrors_for`): AWS `ecmwf-forecasts` (regional eu-central-1 endpoint) -> Google Cloud -> ECMWF portal, with
per-run failover after repeated 503s; every request goes through the shared `fetch_resilient.Fetcher` (backoff + jitter, Retry-After, adaptive concurrency). A step that cannot be
fetched is dropped for ALL members and HRES (a gap, never interpolated; `steps_missing`); a run needs >= 90 % of the steps AND the first 120 h, else it exits 0 with new=false.
Sampled steps are cached per cycle (`data_cache/ecmwf/<cycle>/`, restored/saved by the workflow) so a retry resumes. One byte-range request per GRIB message using the
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
Everything is gated by config `ecmwf.enabled` (live since dev18 via .github/workflows/ecmwf.yml).
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
MIRROR = "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com"      # the documented REGIONAL AWS endpoint (ecmwf-opendata `URLS["aws"]`); the global s3.amazonaws.com host throttled the first live run
DEFAULTS = {
    "enabled": False,
    "mirror": MIRROR,
    "cycles": [0, 12],                      # ENS 00Z and 12Z (06/18Z carry only 0-144 h)
    "step_h": 6,
    "max_step_h": 240,
    "members": 50,                          # perturbed members on the mirror (no control)
    "max_missing_frac": 0.2,                # more than 20 % of a step's member messages missing = the run fails (like the NBM rule)
    "workers": 3,                           # modest on purpose: the mirrors answer HTTP 503 SlowDown to fast runners (dev19); the fetcher halves it further when throttled
    "attempts": 8,                          # per request, exponential backoff with jitter, Retry-After honoured (pipeline/fetch_resilient.py)
    "max_request_s": 300,                   # total time cap per request across its retries
    "trip_after": 6,                        # consecutive failures on a mirror before the run switches to the next one (aws -> google -> ecmwf portal)
    "backoff_s": 1.0,
    "min_interval_s": 0.05,                 # global pacing between request starts
    "required_hours": 120,                  # every step up to this hour must be present, else the attempt publishes nothing (exit 0, new=false)
    "min_steps_frac": 0.9,                  # and at least this share of the planned steps
    "mirrors": None,                        # override list of {name, base[, max_conc]} (tests)
    "probe_after_h": 24,                    # the other mirrors are re-probed at most this often (the preferred one is tried first on every other run)
    "keep_cycles": 2,                       # data_cache/ecmwf keeps the newest N cycles ...
    "cache_max_mb": 300,                    # ... and never more than this (oldest cycles go first; the newest one is always kept)
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

    def __init__(self, points: list[dict], members: int, index_fn=None):
        self.points, self.n = points, members
        self.idx = [(index_fn or grid_index)(p["lat"], p["lon"]) for p in points]      # index_fn: another 0.25 degree grid (GEFS starts at 0 E, not 180 E)
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


def area_docs(sampler: Sampler, cycle: datetime, steps: list[int], model: str = "ECMWF IFS ENS") -> tuple[dict, dict]:
    """(per-area plume documents, HRES precip.json in the M7 format). Pure given the sampler. `model` names the ensemble in each document (GEFS reuses this)."""
    init = cycle.strftime("%Y-%m-%dT%H:00Z")
    plume, hres_areas = {}, {}
    for a, p in enumerate(sampler.points):
        tp = sampler.ens_matrix("tp", a, steps)
        sf = sampler.ens_matrix("sf", a, steps)
        h_tp = sampler.hres_series("tp", a, steps)
        h_sf = sampler.hres_series("sf", a, steps)
        z_ft = None if sampler.z is None or not np.isfinite(sampler.z[a]) else int(round(float(sampler.z[a]) * 3.28084))
        if not np.isfinite(tp).any() and not np.isfinite(h_tp).any():
            continue
        plume[p["id"]] = {"id": p["id"], "model": model, "init": init, "cycle": cycle.strftime("%Y%m%d%H"), "generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "hours": steps,
                          "n_members": sampler.n, "control_member": bool(getattr(sampler, "control_member", False)), "unit": f"{Q_STEP_MM} mm", "z_ft": z_ft,
                          "tp": to_tenths_mm(tp), "sf": to_tenths_mm(sf), "hres_tp": [r[0] for r in to_tenths_mm(h_tp[:, None])],
                          "hres_sf": [r[0] for r in to_tenths_mm(h_sf[:, None])]}
        hres_areas[p["id"]] = {"q": [None if not math.isfinite(v) else round(v * 39.3701, 2) for v in h_tp], "z": z_ft}
    hres_doc = {"model": "ecmwf", "label": "ECMWF", "plume": True, "cycle": cycle.strftime("%Y%m%d%H"), "init": init, "hours": steps, "areas": hres_areas}
    return plume, hres_doc


# ---------------------------------------------------------------- mirrors, cache, network (dev19: resilient fetching, resume, graceful degradation)
GOOGLE_MIRROR = "https://storage.googleapis.com/ecmwf-open-data"          # same file layout as the AWS mirror (ecmwf-opendata `URLS`: aws / google / ecmwf)
PORTAL_MIRROR = "https://data.ecmwf.int/forecasts"                          # ECMWF's own portal: ~500 simultaneous connections for everybody, so only 2 of ours


def mirrors_for(c: dict) -> list:
    """AWS regional endpoint -> Google Cloud -> ECMWF portal (Azure needs a short-lived SAS token: skipped). `c["mirrors"]` (list of {name, base[, max_conc]}) overrides."""
    from .fetch_resilient import Mirror
    if c.get("mirrors"):
        return [Mirror(m["name"], m["base"], m.get("max_conc")) for m in c["mirrors"]]
    return [Mirror("aws", c["mirror"]), Mirror("google", GOOGLE_MIRROR), Mirror("ecmwf", PORTAL_MIRROR, max_conc=2)]


PREF_FILE = "mirror_pref.json"


def load_pref(root: Path | None) -> dict:
    """the remembered mirror: {"mirror": name, "at": ISO time it last served a run, "probed_at": ISO time the other mirrors were last tried}; {} when unknown"""
    if root is None:
        return {}
    try:
        d = json.loads((Path(root) / PREF_FILE).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def order_mirrors(mirrors: list, pref: dict, now: datetime, probe_after_h: float = 24) -> tuple[list, bool]:
    """(mirrors in the order this run tries them, is_probe). The preferred mirror (the one that worked last time) goes FIRST; the others are re-probed at most once per
    `probe_after_h`: on a probe run the highest-priority OTHER mirror goes first and the preferred one second (so a failing probe costs one breaker trip, not the run).
    The per-run circuit breaker still moves on when the first mirror fails, so a preferred mirror that broke is replaced within the same run."""
    names = [m.name for m in mirrors]
    pm = pref.get("mirror")
    if pm not in names:
        return list(mirrors), False
    first = next(m for m in mirrors if m.name == pm)
    others = [m for m in mirrors if m.name != pm]
    try:
        due = (now - datetime.fromisoformat(str(pref.get("probed_at")).replace("Z", "+00:00"))) >= timedelta(hours=float(probe_after_h))
    except (TypeError, ValueError):
        due = True
    if due and others:
        return [others[0], first, *others[1:]], True
    return [first, *others], False


def save_pref(root: Path | None, old: dict, health: dict, now: datetime, probe: bool, first_mirror: str) -> dict:
    """remember the mirror that served MOST of this run's successful requests (nothing served = keep the old note). `probed_at` moves only when this run probed (or there was no note)."""
    used = health.get("mirrors_used") or {}
    new = dict(old)
    if used:
        new["mirror"] = max(used, key=lambda k: used[k])
        new["at"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        if probe or not old.get("probed_at"):
            new["probed_at"] = new["at"]
        elif old.get("mirror") != new["mirror"] and first_mirror != old.get("mirror"):
            new["probed_at"] = new["at"]
        if root is not None:
            try:
                Path(root).mkdir(parents=True, exist_ok=True)
                (Path(root) / PREF_FILE).write_text(json.dumps(new), encoding="utf-8")
            except OSError as exc:
                log.warning("ecmwf: could not save the mirror preference: %s", exc)
    return new


def rel(cycle: datetime, stream: str, step: int, ext: str) -> str:
    kind = "enfo-ef" if stream == "enfo" else "oper-fc"
    return f"{cycle:%Y%m%d}/{cycle:%H}z/ifs/0p25/{stream}/{cycle:%Y%m%d%H}0000-{step}h-{kind}.{ext}"


def make_fetcher(c: dict, session, mirrors: list | None = None):
    from .fetch_resilient import Fetcher
    return Fetcher(mirrors or mirrors_for(c), session=session, workers=int(c["workers"]), attempts=int(c["attempts"]), max_total_s=float(c["max_request_s"]), trip_after=int(c["trip_after"]),
                   backoff=float(c["backoff_s"]), min_interval=float(c["min_interval_s"]))


def newest_cycle(session, c: dict, now: datetime) -> datetime | None:
    """Newest 00/12Z cycle whose LAST step (HRES and ENS index files) is already published (HEAD, no body). `session` may be a Fetcher (retries/failover) or a plain session.
    A mirror that stays throttled through every retry means "cannot tell": None (new=false, exit 0), never an error."""
    from .fetch_resilient import Fetcher, FetchError
    f = session if isinstance(session, Fetcher) else make_fetcher(c, session)
    t = now.replace(minute=0, second=0, microsecond=0)
    for back in range(0, 72):
        cyc = t - timedelta(hours=back)
        if cyc.hour not in c["cycles"] or (now - cyc) < timedelta(hours=c["release_lag_h"] - 1):
            continue
        ok = True
        try:
            for stream in ("oper", "enfo"):
                r = f.head(rel(cyc, stream, c["max_step_h"], "index"))
                ok = ok and r is not None and r.status_code == 200
        except FetchError as exc:
            log.warning("ecmwf: cannot tell whether %s is complete (%s)", cyc.strftime("%Y%m%d%H"), exc)
            return None
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


def partial_tag(tag: str) -> str:
    """the release tag of a PARTIAL run (steps missing): same cycle, a different 8-hex version, so a later attempt that completes the cycle is NOT skipped as "already published"
    and replaces it (the workflow keeps only the newest ecmwf asset)"""
    import hashlib
    cyc, _, ver = tag.partition("-")
    return f"{cyc}-{hashlib.sha1((ver + 'partial').encode()).hexdigest()[:8]}"


class StepCache:
    """Per-cycle resume store: data_cache/ecmwf/<cycle>/step_<hhh>.npz (the SAMPLED values of one step: members x areas for tp and sf, HRES per area), z.npy and meta.json.
    Valid only for the same cycle, area points and member count; anything else is discarded. Other cycles' folders are removed. The Actions cache restores this folder between the
    four daily attempts, so a retry continues where the last one stopped."""

    def __init__(self, root: Path | None, cycle: datetime, points: list[dict], keep: int = 2, max_mb: float = 300):
        import hashlib
        self.root = None if root is None else Path(root) / "ecmwf"
        self.dir = None if root is None else self.root / cycle.strftime("%Y%m%d%H")
        self.key = hashlib.sha1(json.dumps([(p["id"], round(p["lat"], 4), round(p["lon"], 4)) for p in points]).encode()).hexdigest()[:12]
        self.n_members: int | None = None
        if self.dir is None:
            return
        self.pruned = prune_cycles(self.root, self.dir.name, keep=keep, max_mb=max_mb)
        meta = self.dir / "meta.json"
        try:
            m = json.loads(meta.read_text(encoding="utf-8"))
            if m.get("key") == self.key:
                self.n_members = m.get("n_members")
            else:
                raise ValueError("points changed")
        except (OSError, ValueError):
            import shutil
            shutil.rmtree(self.dir, ignore_errors=True)

    def _meta(self, n_members: int) -> None:
        if self.dir is None:
            return
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "meta.json").write_text(json.dumps({"key": self.key, "n_members": n_members}), encoding="utf-8")
        self.n_members = n_members

    def load(self, step: int) -> dict | None:
        if self.dir is None:
            return None
        try:
            with np.load(self.dir / f"step_{step:03d}.npz") as z:
                return {k: z[k] for k in z.files}
        except (OSError, ValueError, KeyError):
            return None

    def save(self, step: int, data: dict, n_members: int) -> None:
        if self.dir is None:
            return
        self._meta(n_members)
        tmp = self.dir / f"step_{step:03d}.tmp.npz"
        np.savez_compressed(tmp, **data)
        tmp.replace(self.dir / f"step_{step:03d}.npz")

    def load_z(self):
        try:
            return np.load(self.dir / "z.npy") if self.dir else None
        except (OSError, ValueError):
            return None

    def save_z(self, z: np.ndarray, n_members: int) -> None:
        if self.dir is not None:
            self._meta(n_members)
            np.save(self.dir / "z.npy", z)


def _dir_mb(d: Path) -> float:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file()) / 1e6


def prune_cycles(root: Path | None, current: str, keep: int = 2, max_mb: float = 300) -> list[str]:
    """dev20 cache hygiene: keep only the newest `keep` cycle folders (the current one always counts as kept) and never more than `max_mb` in total (oldest first,
    the current cycle is never removed). Files at the top level (mirror_pref.json) stay. Returns the removed cycle names."""
    import shutil
    if root is None or not Path(root).exists():
        return []
    dirs = sorted((d for d in Path(root).iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)
    others = [d for d in dirs if d.name != current]
    keep_others = [d for d in others if d.name < current][: max(0, keep - 1)]      # only OLDER cycles may stay beside the current one
    removed = [d for d in others if d not in keep_others]
    for d in removed:
        shutil.rmtree(d, ignore_errors=True)
    kept = [d for d in keep_others]
    total = sum(_dir_mb(d) for d in kept) + (_dir_mb(Path(root) / current) if (Path(root) / current).exists() else 0)
    for d in sorted(kept, key=lambda d: d.name):                                        # oldest first
        if total <= max_mb:
            break
        total -= _dir_mb(d)
        shutil.rmtree(d, ignore_errors=True)
        removed.append(d)
    return [d.name for d in removed]


def cache_sizes(root: Path | None) -> dict:
    """{"cycles": {cycle: MB}, "total_mb": MB} of data_cache/ecmwf (what the Actions cache saves)"""
    if root is None or not Path(root).exists():
        return {"cycles": {}, "total_mb": 0.0}
    cyc = {d.name: round(_dir_mb(d), 2) for d in sorted(Path(root).iterdir()) if d.is_dir()}
    return {"cycles": cyc, "total_mb": round(_dir_mb(Path(root)), 2)}


# ---------------------------------------------------------------- ECMWF AIFS Single (dev20): one more line in "Precipitation by model", experimental, OFF by default
# FOUND on the real mirror (Google, 12Z Nov 19 2026): {date}/{HH}z/aifs-single/0p25/oper/{date}{HH}0000-{step}h-oper-fc.{index,grib2}; steps every 6 h from 0 to 360 h
# (no 3-hourly steps); `tp` exists at every step, stepType accum (0-<step> h, cumulative since the run start), grid 1440 x 721 scanning 0 like IFS, and UNITS kg m-2
# (= mm of water), NOT metres as in the IFS files. One tp message is ~0.28 MB, so 40 steps are ~11 MB.
AIFS_DEFAULTS = {"enabled": False, "in_badge": False, "step_h": 6, "max_step_h": 240, "max_seconds": 180, "attempts": 4, "max_request_s": 60}
AIFS_ATTRIBUTION = ("Adapted from ECMWF AIFS Single open data (Copyright ECMWF), licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/) and the ECMWF Terms of Use. "
                    "Total precipitation sampled at ski-area summit points and converted to inches by Snow-Wx (adapted). AIFS is ECMWF's machine-learning (AI) model: experimental here.")
AIFS_LABEL = "AIFS (AI, experimental)"


def aifs_config(cfg: dict | None) -> dict:
    out = dict(AIFS_DEFAULTS)
    out.update({k: v for k, v in ((cfg or {}).get("aifs") or {}).items() if k in AIFS_DEFAULTS})
    return out


def rel_aifs(cycle: datetime, step: int, ext: str) -> str:
    return f"{cycle:%Y%m%d}/{cycle:%H}z/aifs-single/0p25/oper/{cycle:%Y%m%d%H}0000-{step}h-oper-fc.{ext}"


def aifs_doc(points: list[dict], cycle: datetime, steps: list[int], fields_mm: dict[int, np.ndarray], steps_missing: list[int], in_badge: bool) -> dict:
    """the M7 precip document for AIFS (pure): cumulative liquid inches per area since the run start; a missing step is null (a gap, never interpolated);
    per-area running maximum against GRIB packing noise. fields_mm: {step: (n_areas,) mm}."""
    areas = {}
    for a, pt in enumerate(points):
        v = np.array([0.0 if s == 0 else (fields_mm[s][a] if s in fields_mm else np.nan) for s in steps], dtype="float64")
        v = monotone(v[:, None])[:, 0]
        if not np.isfinite(v[1:]).any():
            continue
        areas[pt["id"]] = {"q": [None if not math.isfinite(x) else round(x / 25.4, 2) for x in v], "z": None}
    return {"model": "aifs", "label": AIFS_LABEL, "experimental": True, "badge": bool(in_badge), "cycle": cycle.strftime("%Y%m%d%H"), "init": cycle.strftime("%Y-%m-%dT%H:00Z"),
            "hours": steps, "areas": areas, "steps_missing": steps_missing, "attribution": AIFS_ATTRIBUTION, "license": LICENSE_URL, "terms": TERMS_URL}


def run_aifs(cfg: dict, session, out: Path, cyc: datetime, pts: list[dict], mirrors: list, cache_dir: Path | None, required_hours: int, min_frac: float) -> dict:
    """ISOLATED: called after the HRES/ENS files are written; every failure is caught by the caller and only recorded (fetch health). Its own fetcher (its throttling
    never trips the main run's breaker), fewer retries and a hard time budget (`max_seconds`), so it cannot hold the ECMWF job for long. Writes <out>/ecmwf/aifs/precip.json."""
    from .fetch_resilient import Fetcher, FetchError
    a = aifs_config(cfg)
    t0 = time.time()
    deadline = t0 + float(a["max_seconds"])
    c = configure(cfg)
    f = Fetcher(mirrors, session=session, workers=2, attempts=int(a["attempts"]), max_total_s=float(a["max_request_s"]), trip_after=int(c["trip_after"]),
                backoff=float(c["backoff_s"]), min_interval=float(c["min_interval_s"]))
    steps = list(range(0, int(a["max_step_h"]) + 1, int(a["step_h"])))
    planned = steps[1:]
    sam = Sampler(pts, 1)
    cdir = None if cache_dir is None else Path(cache_dir)
    fields, missing, nbytes, cached = {}, [], 0, 0
    for s in planned:
        cf = None if cdir is None else cdir / f"aifs_tp_{s:03d}.npy"
        if cf is not None and cf.exists():
            try:
                v = np.load(cf)
                if v.shape == (len(pts),):
                    fields[s] = v
                    cached += 1
                    continue
            except (OSError, ValueError):
                pass
        if time.time() >= deadline:
            missing.append(s)
            continue
        try:
            r = f.get(rel_aifs(cyc, s, "index"))
            row = next((x for x in parse_index(r.text) if x.get("param") == "tp"), None) if r is not None else None
            if row is None:
                missing.append(s)
                continue
            g = f.get(rel_aifs(cyc, s, "grib2"), {"Range": f"bytes={row['_offset']}-{row['_offset'] + row['_length'] - 1}"})
            if g is None:
                missing.append(s)
                continue
            nbytes += len(g.content)
            v = sam.sample(decode(g.content))                    # kg m-2 = mm (NOT metres: see the note above)
        except (FetchError, ValueError, RuntimeError) as exc:
            log.warning("ecmwf aifs: step %d: %s", s, exc)
            missing.append(s)
            continue
        fields[s] = v
        if cf is not None:
            cf.parent.mkdir(parents=True, exist_ok=True)
            np.save(cf, v)
    health = {"enabled": True, "steps_planned": len(planned), "steps_missing": missing, "steps_cached": cached, "bytes_downloaded": nbytes,
              "seconds": round(time.time() - t0, 1), "fetch": f.stats()}
    need_early = [s for s in planned if s <= required_hours]
    if len(planned) - len(missing) < math.ceil(min_frac * len(planned)) or any(s in missing for s in need_early):
        health.update(ok=False, published=False, reason=f"only {len(planned) - len(missing)} of {len(planned)} steps (missing {missing[:8]})")
        log.warning("ecmwf aifs: %s: not published this attempt", health["reason"])
        return health
    doc = aifs_doc(pts, cyc, steps, fields, missing, a["in_badge"])
    (Path(out) / "ecmwf" / "aifs").mkdir(parents=True, exist_ok=True)
    write_json(Path(out) / "ecmwf" / "aifs" / "precip.json", doc)
    health.update(ok=True, published=True, areas=len(doc["areas"]), partial=bool(missing))
    log.info("ecmwf aifs %s: %d areas, %d steps (%d missing, %d cached), %.1f MB in %.0f s", doc["cycle"], len(doc["areas"]), len(steps), len(missing), cached, nbytes / 1e6, health["seconds"])
    return health


class StepMissing(RuntimeError):
    """a step that cannot be completed (index not obtainable, too many member messages lost): dropped for ALL members and HRES, never interpolated"""


def run(cfg: dict, session, out: Path, *, cycle: datetime | None = None, force: bool = False, points: list[dict] | None = None, now: datetime | None = None,
        published: str | None = None, github_output: str | None = None, cache_dir: Path | None = None) -> dict:
    """Fetch, sample, write. `out` is the MODELS folder (writes <out>/ecmwf/...). Needs `force=True` while config ecmwf.enabled is false (a manual test run).
    `published` (the newest ecmwf asset tag on the release) and `github_output` follow the other products: new=false when nothing newer is complete.
    dev19: every request goes through pipeline.fetch_resilient (backoff + jitter, Retry-After, mirror failover, adaptive concurrency); a step that still fails is DROPPED for
    all members and HRES (listed in `steps_missing`, drawn as a gap, never interpolated); fewer than 90 % of the steps or a hole in the first 120 h = exit 0 with new=false
    (a warning, not a failure); sampled steps are cached under data_cache/ecmwf/<cycle> and reused by the next attempt."""
    from .fetch_resilient import FetchError

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
    croot = None if cache_dir is False else (REPO_ROOT / "data_cache" if cache_dir is None else Path(cache_dir)) / "ecmwf"
    pref = load_pref(croot)
    order, probe = order_mirrors(mirrors_for(c), pref, now, c["probe_after_h"])
    if pref.get("mirror"):
        log.info("ecmwf: preferred mirror %s (worked %s); %s", pref["mirror"], pref.get("at"), f"probing {order[0].name} first today" if probe else "trying it first")
    fetcher = make_fetcher(c, session, order)

    def pref_health(h: dict) -> dict:
        p2 = save_pref(croot, pref, h, now, probe, order[0].name)
        return {**h, "first_mirror": order[0].name, "probe": probe, "preferred_before": pref.get("mirror"), "preferred_after": p2.get("mirror")}
    cyc = cycle or newest_cycle(fetcher, c, now)
    if cyc is None:
        # nothing complete on the mirror (a new cycle not released yet, and no older one within 72 h, or the mirrors stay throttled): not an error of ours. new=false, exit 0;
        # the monitor judges how old the last PUBLISHED run is (monitoring.sources.ecmwf.max_age_hours), so a long outage still alerts
        log.warning("ecmwf: no complete cycle on the mirror yet; nothing to publish")
        emit(new="false")
        return {"ok": True, "skipped": "not-released", "fetch": pref_health(fetcher.stats())}
    from .version import stamp
    tag_full = stamp(cyc.strftime("%Y%m%d%H"), "ecmwf")
    if published == tag_full:
        log.info("ecmwf %s already published; nothing new", tag_full)
        emit(new="false", cycle=tag_full)
        return {"ok": True, "skipped": "published", "cycle": tag_full}
    steps = steps_for(c)
    planned = steps[1:]
    t0 = time.time()
    nbytes = {"n": 0}
    cache = StepCache(None if croot is None else croot.parent, cyc, pts, keep=int(c["keep_cycles"]), max_mb=float(c["cache_max_mb"]))

    def get_rows(stream, step):
        """the .index rows of one file; None when it is not on any mirror or stays unreachable (FetchError): the caller decides what that costs"""
        try:
            r = fetcher.get(rel(cyc, stream, step, "index"))
        except FetchError as exc:
            log.warning("ecmwf: %s index f%03d: %s", stream, step, exc)
            return None
        return None if r is None else parse_index(r.text)

    def fetch_field(stream, step, row):
        try:
            r = fetcher.get(rel(cyc, stream, step, "grib2"), {"Range": f"bytes={row['_offset']}-{row['_offset'] + row['_length'] - 1}"})
            if r is None:
                return None
            nbytes["n"] += len(r.content)
            return decode(r.content)
        except Exception as exc:  # noqa: BLE001 - FetchError, a corrupt message ...: a MISSING message, counted
            log.warning("ecmwf: %s f%03d %s: %s", stream, step, row.get("param"), exc)
            return None

    # the member count comes from the DATA (the perturbed members listed in an ensemble index), never from a constant: config `members` is only the last-resort fallback.
    # A cache from an earlier attempt of this cycle knows it already; otherwise the first step whose ensemble index can be read tells.
    n_members = cache.n_members
    if not n_members:
        for s in planned:
            rows = get_rows("enfo", s)
            if rows is not None:
                n_members = len(select(rows, "tp", "pf")) or c["members"]
                break
    if not n_members:
        log.warning("ecmwf: no ensemble index could be read from any mirror; nothing to publish this attempt")
        emit(new="false")
        return {"ok": True, "skipped": "unreachable", "fetch": pref_health(fetcher.stats())}
    sam = Sampler(pts, n_members)
    log.info("ecmwf %s: %d perturbed members in the ensemble index", cyc.strftime("%Y%m%d%H"), n_members)
    # HRES terrain (optional: without it the page just omits the terrain note)
    zc = cache.load_z()
    if zc is not None and len(zc) == len(pts):
        sam.z = zc
    else:
        zrows = get_rows("oper", 0)
        z = select(zrows or [], "z").get(0)
        zf = fetch_field("oper", 0, z) if z else None
        if zf is not None:
            sam.z = sam.sample(zf) / 9.80665               # geopotential (m2/s2) -> metres
            cache.save_z(sam.z, n_members)

    def apply(s, d):
        for p in ("tp", "sf"):
            sam.ens[p][s] = d[f"ens_{p}"]
            sam.hres[p][s] = d[f"hres_{p}"]
        sam.missing[s] = int(d["missing"])

    def build_step(s, ex):
        erows = get_rows("enfo", s)
        if erows is None:
            raise StepMissing(f"step {s}: ensemble index unavailable")
        ens, miss = {}, 0
        for param in ("tp", "sf"):
            sel = select(erows, param, "pf")
            got = dict(zip(sel, ex.map(lambda k: fetch_field("enfo", s, sel[k]), sel)))
            ens[param] = {k: v for k, v in got.items() if v is not None}
            if param == "tp":
                miss = n_members - len(ens[param])
        if miss > c["max_missing_frac"] * n_members:
            raise StepMissing(f"step {s}: {miss} of {n_members} member messages missing")
        hrows = get_rows("oper", s) or []                   # HRES is optional per step: a gap in the line, the ensemble still publishes
        out_d = {"missing": np.array(miss)}
        for param in ("tp", "sf"):
            sam.add_ens(param, s, ens[param])
            row = select(hrows, param).get(0)
            sam.add_hres(param, s, fetch_field("oper", s, row) if row else None)
            out_d[f"ens_{param}"], out_d[f"hres_{param}"] = sam.ens[param][s], sam.hres[param][s]
        return out_d

    steps_missing, cached = [], 0
    with ThreadPoolExecutor(int(c["workers"])) as ex:
        for s in planned:
            d = cache.load(s)
            if d is not None and d["ens_tp"].shape == (n_members, len(pts)):
                apply(s, d)
                cached += 1
                continue
            try:
                d = build_step(s, ex)
            except StepMissing as exc:
                log.warning("ecmwf: %s: step dropped for all members and HRES", exc)
                sam.ens["tp"].pop(s, None), sam.ens["sf"].pop(s, None), sam.hres["tp"].pop(s, None), sam.hres["sf"].pop(s, None)
                steps_missing.append(s)
                continue
            cache.save(s, d, n_members)
    health = pref_health({**fetcher.stats(), "steps_planned": len(planned), "steps_missing": steps_missing, "steps_cached": cached})
    health["cache"] = {**cache_sizes(croot), "pruned": getattr(cache, "pruned", [])}
    need_early = [s for s in planned if s <= int(c["required_hours"])]
    if len(planned) - len(steps_missing) < math.ceil(float(c["min_steps_frac"]) * len(planned)) or any(s in steps_missing for s in need_early):
        # too incomplete to publish (< 90 % of the steps, or a hole in the first 120 h): NOT an error. The sampled steps stay cached for the next attempt.
        log.warning("ecmwf: only %d of %d steps usable (missing %s): not publishing this attempt (cache kept: %s)", len(planned) - len(steps_missing), len(planned), steps_missing, cache.dir)
        emit(new="false", cycle=tag_full)
        return {"ok": True, "skipped": "incomplete", "cycle": tag_full, "fetch": health}
    plume, hres_doc = area_docs(sam, cyc, steps)
    if not plume:                                      # nothing usable: fail BEFORE touching the last good files
        raise RuntimeError("ECMWF: no area has data")
    out = Path(out)
    (out / "ecmwf" / "plume").mkdir(parents=True, exist_ok=True)
    for old in (out / "ecmwf" / "plume").glob("*.json"):
        old.unlink()
    sizes = []
    for aid, d in plume.items():
        d["steps_missing"] = steps_missing
        write_json(out / "ecmwf" / "plume" / f"{aid}.json", d)
        sizes.append((out / "ecmwf" / "plume" / f"{aid}.json").stat().st_size)
    hres_doc["steps_missing"] = steps_missing
    write_json(out / "ecmwf" / "precip.json", hres_doc)
    secs = round(time.time() - t0, 1)
    # AIFS (dev20): AFTER the HRES/ENS files are on disk, isolated and time-boxed; a failure is recorded, never raised. An old AIFS file never outlives its cycle.
    import shutil
    shutil.rmtree(out / "ecmwf" / "aifs", ignore_errors=True)
    ac = aifs_config(cfg)
    if ac["enabled"]:
        try:
            aifs_health = run_aifs(cfg, session, out, cyc, pts, order, cache.dir, int(c["required_hours"]), float(c["min_steps_frac"]))
        except Exception as exc:  # noqa: BLE001 - AIFS must never break the HRES/ENS output
            log.warning("ecmwf aifs: failed (%s); HRES/ENS unaffected", exc)
            aifs_health = {"enabled": True, "ok": False, "published": False, "reason": f"{type(exc).__name__}: {str(exc)[:160]}"}
    else:
        aifs_health = {"enabled": False}
    index = {"generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "cycle": cyc.strftime("%Y%m%d%H"), "init": cyc.strftime("%Y-%m-%dT%H:00Z"),
             "hours": steps, "n_members": n_members, "areas": len(plume), "resolution": "0.25 degree", "control_member": False,
             "stale_hours": c["stale_hours"], "missing_member_messages": sum(sam.missing.values()), "bytes_downloaded": nbytes["n"], "seconds": secs,
             "steps_missing": steps_missing, "partial": bool(steps_missing), "fetch": health, "aifs": aifs_health,
             "source": "ECMWF Open Data (IFS HRES and ENS), mirror: " + health["mirror"], "attribution": ATTRIBUTION, "license": LICENSE_URL, "terms": TERMS_URL}
    write_json(out / "ecmwf" / "index.json", index)
    tag = partial_tag(tag_full) if steps_missing else tag_full
    emit(new="true", cycle=tag)
    log.info("ecmwf %s: %d areas, %d steps (%d missing, %d from cache), %.0f MB downloaded in %.0f s, mirror %s, %d retries; per-area file avg %.1f KB",
             index["cycle"], len(plume), len(steps), len(steps_missing), cached, nbytes["n"] / 1e6, secs, health["mirror"], health["retries"], (sum(sizes) / max(1, len(sizes))) / 1024)
    return {"ok": True, **index, "avg_area_bytes": int(sum(sizes) / max(1, len(sizes))), "max_area_bytes": max(sizes) if sizes else 0}
