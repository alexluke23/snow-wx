"""NOAA GEFS ensemble plume at ski-area summits (dev18 stretch 5; BUILT BEHIND config `gefs.enabled: false`, never wired into a workflow by a dev session).

The second plume view next to ECMWF's: 31 members (control gec00 + 30 perturbed gep01-gep30), 0.25 degree, 6-hourly to 240 h, liquid precipitation (APCP) and a snow-water-equivalent
estimate (APCP x CSNOW, the categorical-snow fraction of the same 6-h window: GEFS has no snowfall accumulation field). Public domain (NOAA); credit NOAA/NWS.

Method = the ECMWF pipeline's, unchanged (pipeline/ecmwf.py): every member is ONE scenario; its own running total is accumulated over time (sum of that member's 6-h buckets),
and quantiles are taken ACROSS members at each step in the browser (`web/js/ensemble.js`). Nothing in NBM's percentile products is read, and no percentile is ever summed over time.

Source: https://noaa-gefs-pds.s3.amazonaws.com (anonymous HTTPS), `gefs.YYYYMMDD/HH/atmos/pgrb2sp25/<member>.tHHz.pgrb2s.0p25.fFFF` with a wgrib2-style `.idx` beside every file
(`n:offset:d=YYYYMMDDHH:APCP:surface:6-12 hour acc fcst:ENS=...`); one byte-range GET per message. Probed Nov 18 2026: members geavg, gec00, gep01..gep30, gespr; steps 0..240 every 3 h (81);
APCP at f006 = "0-6 hour acc", at f012 = "6-12 hour acc" (6-h buckets), CSNOW the same windows ("ave"). ~0.28 MB per APCP message.
GEFS grid: 721 x 1440, rows from 90 N, columns from 0 E (ECMWF's start at 180 E): `grid_index` below.

Outputs: <out>/gefs/index.json and <out>/gefs/plume/<area>.json (same document format as the ECMWF plume: members x steps in 0.1 mm integers, `n_members` read from the data,
`control_member: true`). CLI: `python -m pipeline gefs --out build/models [--force] [--cycle YYYYMMDDHH] [--published TAG] [--github-output F]`.
"""

from __future__ import annotations

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from . import ecmwf as E
from .common import utcnow, write_json

log = logging.getLogger("snow-wx.gefs")
MIRROR = "https://noaa-gefs-pds.s3.amazonaws.com"
DEFAULTS = {"enabled": False, "mirror": MIRROR, "cycles": [0, 12], "step_h": 6, "max_step_h": 240, "max_missing_frac": 0.2, "workers": 6, "stale_hours": 24, "release_lag_h": 6}
ATTRIBUTION = "NOAA/NCEP Global Ensemble Forecast System (GEFS) via the NOAA Open Data Dissemination (AWS): public domain. Values sampled at ski-area summit points and accumulated per member by Snow-Wx."
MEMBERS = ["gec00"] + [f"gep{n:02d}" for n in range(1, 31)]          # control first (member 1), then the 30 perturbed members


def configure(cfg: dict | None) -> dict:
    out = dict(DEFAULTS)
    out.update({k: v for k, v in ((cfg or {}).get("gefs") or {}).items() if k in DEFAULTS})
    return out


def steps_for(c: dict) -> list[int]:
    return list(range(0, int(c["max_step_h"]) + 1, int(c["step_h"])))


def grid_index(lat: float, lon: float) -> tuple[int, int]:
    """Nearest cell of GEFS's 0.25 degree grid (721 x 1440): rows from 90 N southward, columns from 0 E eastward (longitude mod 360)."""
    i = int(round((90.0 - lat) / 0.25))
    j = int(round((lon % 360.0) / 0.25)) % 1440
    return min(max(i, 0), 720), j


def url(c: dict, cycle: datetime, member: str, step: int, ext: str = "") -> str:
    d = f"{cycle:%Y%m%d}/{cycle:%H}"
    return f"{c['mirror']}/gefs.{d}/atmos/pgrb2sp25/{member}.t{cycle:%H}z.pgrb2s.0p25.f{step:03d}{ext}"


IDX = re.compile(r"^(\d+):(\d+):d=\d+:([A-Z0-9]+):([^:]+):(\d+)-(\d+) hour (acc|ave) fcst")


def parse_idx(text: str) -> list[dict]:
    """wgrib2 inventory lines -> rows {n, offset, length (None for the last message), param, level, start, end, kind}; bad lines are skipped.
    Only windowed messages (acc / ave) are kept: that is all this module reads (APCP, CSNOW)."""
    raw = []
    for line in text.splitlines():
        parts = line.split(":")
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            raw.append((int(parts[0]), int(parts[1]), line))
    rows = []
    for k, (n, off, line) in enumerate(raw):
        m = IDX.match(line)
        if not m:
            continue
        nxt = raw[k + 1][1] if k + 1 < len(raw) else None
        rows.append({"n": n, "offset": off, "length": (nxt - off) if nxt is not None else None, "param": m.group(3), "level": m.group(4),
                     "start": int(m.group(5)), "end": int(m.group(6)), "kind": m.group(7)})
    return rows


def pick(rows: list[dict], param: str, step: int, width: int) -> dict | None:
    """the surface `param` message whose window is exactly the `width` hours ending at `step`"""
    for r in rows:
        if r["param"] == param and r["level"] == "surface" and r["end"] == step and r["end"] - r["start"] == width:
            return r
    return None


def byte_range(row: dict) -> str:
    return f"bytes={row['offset']}-{row['offset'] + row['length'] - 1}" if row["length"] else f"bytes={row['offset']}-"


def newest_cycle(session, c: dict, now: datetime) -> datetime | None:
    """newest configured cycle whose LAST step index exists for the control and the last perturbed member (HEAD only)"""
    t = now.replace(minute=0, second=0, microsecond=0)
    for back in range(0, 72):
        cyc = t - timedelta(hours=back)
        if cyc.hour not in c["cycles"] or (now - cyc) < timedelta(hours=c["release_lag_h"] - 1):
            continue
        if all(session.head(url(c, cyc, m, c["max_step_h"], ".idx"), timeout=30).status_code == 200 for m in (MEMBERS[0], MEMBERS[-1])):
            return cyc
    return None


def run(cfg: dict, session, out: Path, *, cycle: datetime | None = None, force: bool = False, points: list[dict] | None = None, now: datetime | None = None,
        published: str | None = None, github_output: str | None = None) -> dict:
    """fetch, sample, write. `out` is the MODELS folder (writes <out>/gefs/...). Needs force=True while config gefs.enabled is false (manual test run)."""
    def emit(**kv):
        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                for k2, v in kv.items():
                    f.write(f"{k2}={v}" + chr(10))

    c = configure(cfg)
    if not c["enabled"] and not force:
        log.info("gefs: disabled (config gefs.enabled)")
        emit(new="false")
        return {"ok": False, "skipped": "disabled"}
    from .models.multimodel import load_points
    from .version import stamp
    pts = points or load_points()
    now = now or utcnow()
    cyc = cycle or newest_cycle(session, c, now)
    if cyc is None:
        log.warning("gefs: no complete cycle on the mirror yet; nothing to publish")
        emit(new="false")
        return {"ok": True, "skipped": "not-released"}
    tag = stamp(cyc.strftime("%Y%m%d%H"), "gefs")
    if published == tag:
        log.info("gefs %s already published; nothing new", tag)
        emit(new="false", cycle=tag)
        return {"ok": True, "skipped": "published", "cycle": tag}
    steps = steps_for(c)
    width = int(c["step_h"])
    t0 = time.time()
    nbytes = {"n": 0}
    session.headers["User-Agent"] = session.headers.get("User-Agent", "snow-wx")
    sam = E.Sampler(pts, len(MEMBERS), index_fn=grid_index)
    sam.control_member = True
    cum = {p: np.zeros((len(MEMBERS), len(pts))) for p in ("tp", "sf")}            # running totals (m of water) per member and area: each member's OWN buckets are summed

    def member_buckets(member: str, step: int):
        """(apcp mm field | None, csnow fraction | None) for one member and 6-h window; None = missing (counted)"""
        try:
            r = E._get(session, url(c, cyc, member, step, ".idx"))
            if r is None:
                return None
            rows = parse_idx(r.text)
            ap, cs = pick(rows, "APCP", step, width), pick(rows, "CSNOW", step, width)
            if ap is None:
                return None
            got = []
            for row in (ap, cs):
                if row is None:
                    got.append(None)
                    continue
                g = E._get(session, url(c, cyc, member, step), {"Range": byte_range(row)})
                if g is None:
                    got.append(None)
                    continue
                nbytes["n"] += len(g.content)
                got.append(E.decode(g.content))
            return got[0], got[1]
        except Exception as exc:  # noqa: BLE001
            log.warning("gefs: %s f%03d: %s", member, step, exc)
            return None

    missing = {}
    with ThreadPoolExecutor(c["workers"]) as ex:
        for s in steps[1:]:
            res = list(ex.map(lambda m: member_buckets(m, s), MEMBERS))
            miss = sum(1 for r in res if r is None)
            missing[s] = miss
            if miss > c["max_missing_frac"] * len(MEMBERS):
                raise RuntimeError(f"GEFS step {s}: {miss} of {len(MEMBERS)} members missing")
            for k, r in enumerate(res):
                if r is None:
                    cum["tp"][k] = np.nan                                           # a member that skipped a bucket has no valid running total from here on
                    cum["sf"][k] = np.nan
                    continue
                ap, cs = r
                v = sam.sample(ap) / 1000.0                                         # kg m-2 == mm of water -> metres
                cum["tp"][k] += v
                frac = np.clip(sam.sample(cs), 0.0, 1.0) if cs is not None else np.zeros(len(pts))
                cum["sf"][k] += v * frac                                            # frozen share of this bucket's water
            for p in ("tp", "sf"):
                sam.ens[p][s] = cum[p].copy()
            sam.missing[s] = miss
    plume, _ = E.area_docs(sam, cyc, steps, model="NOAA GEFS")
    if not plume:
        raise RuntimeError("GEFS: no area has data")
    out = Path(out)
    (out / "gefs" / "plume").mkdir(parents=True, exist_ok=True)
    for old in (out / "gefs" / "plume").glob("*.json"):
        old.unlink()
    sizes = []
    for aid, d in plume.items():
        d.pop("hres_tp", None)
        d.pop("hres_sf", None)                                                       # no deterministic companion in GEFS
        write_json(out / "gefs" / "plume" / f"{aid}.json", d)
        sizes.append((out / "gefs" / "plume" / f"{aid}.json").stat().st_size)
    secs = round(time.time() - t0, 1)
    index = {"generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "cycle": cyc.strftime("%Y%m%d%H"), "init": cyc.strftime("%Y-%m-%dT%H:00Z"), "hours": steps,
             "n_members": len(MEMBERS), "control_member": True, "areas": len(plume), "resolution": "0.25 degree", "stale_hours": c["stale_hours"],
             "missing_member_messages": sum(missing.values()), "bytes_downloaded": nbytes["n"], "seconds": secs, "source": "NOAA GEFS (NODD on AWS)", "attribution": ATTRIBUTION,
             "snow": "estimate: APCP x CSNOW (categorical snow fraction) per 6-h bucket"}
    write_json(out / "gefs" / "index.json", index)
    emit(new="true", cycle=tag)
    log.info("gefs %s: %d areas, %d steps, %.0f MB downloaded in %.0f s; per-area file avg %.1f KB", index["cycle"], len(plume), len(steps), nbytes["n"] / 1e6, secs,
             (sum(sizes) / max(1, len(sizes))) / 1024)
    return {"ok": True, **index, "avg_area_bytes": int(sum(sizes) / max(1, len(sizes)))}
