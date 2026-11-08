"""Sanity report: NBM 24-h snow (median, 10-90 range) vs NWS official (NDFD via
api.weather.gov gridpoints) over the same 24 h, at the summit point of N areas.

    python -m pipeline.nbm.sanity [--points build/data/points] [-n 10]

NDFD snowfall comes in ISO-8601 intervals (mm); each interval is prorated by
its overlap with the NBM window [issued, issued + 24 h].
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from ..common import REPO_ROOT, load_config, make_session

GRIDPOINT = "https://api.weather.gov/gridpoints/{wfo}/{x},{y}"
_DUR = re.compile(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?")


def parse_interval(s: str) -> tuple[datetime, datetime]:
    start, dur = s.split("/")
    t0 = datetime.fromisoformat(start)
    d, h, m = (int(x or 0) for x in _DUR.fullmatch(dur).groups())
    return t0, t0 + timedelta(days=d, hours=h, minutes=m)


def overlap_sum(values: list[dict], t0: datetime, t1: datetime) -> float | None:
    """Sum of interval values (prorated by overlap) inside [t0, t1)."""
    total, covered = 0.0, timedelta(0)
    for v in values:
        a, b = parse_interval(v["validTime"])
        lo, hi = max(a, t0), min(b, t1)
        if hi <= lo or v.get("value") is None:
            continue
        total += v["value"] * ((hi - lo) / (b - a))
        covered += hi - lo
    return total if covered >= (t1 - t0) * 0.9 else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--points", default="build/data/points")
    ap.add_argument("-n", type=int, default=10)
    args = ap.parse_args(argv)
    cfg = load_config()
    session = make_session(cfg)
    cat = {a["id"]: a for a in json.loads((REPO_ROOT / "data" / "ski_areas.json").read_text(encoding="utf-8"))["areas"]}
    summ = json.loads((Path(args.points) / "summary.json").read_text(encoding="utf-8"))
    t0 = datetime.fromisoformat(summ["issued"].replace("Z", "+00:00"))
    t1 = t0 + timedelta(hours=24)
    # the major areas with the most NBM snow, one per region, so the check covers wet cases
    rows, seen = [], set()
    for r in sorted((r for r in summ["areas"] if r["major"]),
                    key=lambda r: -((r["summit"].get("24h") or {}).get("50") or 0)):
        if r["region"] in seen:
            continue
        seen.add(r["region"])
        rows.append(r)
        if len(rows) == args.n:
            break
    print(f"NBM cycle {summ['cycle']} vs NWS gridpoints, 24 h from {t0:%Y-%m-%d %HZ}, summit points (in)\n")
    print("| Area | Region | NBM p50 | NBM 10–90 | NWS (NDFD) | NWS issued |")
    print("|---|---|---:|---|---:|---|")
    for r in rows:
        nws = cat[r["id"]]["nws"]["summit"]
        js = session.get(GRIDPOINT.format(**nws), headers={"Accept": "application/geo+json"}, timeout=60).json()
        p = js.get("properties") or {}
        mm = overlap_sum((p.get("snowfallAmount") or {}).get("values") or [], t0, t1)
        s24 = r["summit"].get("24h") or {}
        ndfd = "n/a" if mm is None else f"{mm / 25.4:.1f}"
        print(f"| {r['name']} | {r['region']} | {s24.get('50')} | {s24.get('10')}–{s24.get('90')} | {ndfd} "
              f"| {(p.get('updateTime') or '')[:16]} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
