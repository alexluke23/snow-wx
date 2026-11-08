"""Are NBM's snowfall exceedance probabilities consistent with its percentiles?

C:/miniforge3/envs/snow-wx/python.exe tools/nbm_prob_consistency.py 2026110801 24:29 24:125 72:077 72:173

For each window (length:end hour) decodes all 15 ASNOW percentile levels and every
probability threshold over the western US grid, derives P(>x) from the percentile
curve (piecewise linear between levels, 0 below the 1st / 100 above the 99th) and
compares it with NBM's probability field, over cells where the window can snow
(99th percentile >= the threshold / 2).
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pipeline  # noqa: E402,F401
from pipeline.catalog import lcc_ij  # noqa: E402
from pipeline.nbm.inventory import parse_idx  # noqa: E402
from pipeline.nbm.run import decode_at, url  # noqa: E402

LEVELS = (1, 5, 10, 20, 25, 30, 40, 50, 60, 70, 75, 80, 90, 95, 99)


def main():
    cyc = datetime.strptime(sys.argv[1], "%Y%m%d%H").replace(tzinfo=timezone.utc)
    grid = json.loads(Path("data/ski_areas.json").read_text(encoding="utf-8"))["nbm_grid"]
    # western US cells: bounding box in grid space, every 2nd cell (~1/4 million points)
    i0, j0 = lcc_ij(31.0, -124.5, grid)
    i1, j1 = lcc_ij(49.0, -102.5, grid)
    ii, jj = np.meshgrid(np.arange(min(i0, i1) - 60, max(i0, i1) + 60, 2), np.arange(min(j0, j1), max(j0, j1), 2))
    ij = (ii.ravel(), jj.ravel())
    s = requests.Session()
    rows = []
    for spec in sys.argv[2:]:
        win, h = map(int, spec.split(":"))
        inv = parse_idx(s.get(url(cyc, "core", h) + ".idx", timeout=60).text)
        mine = [m for m in inv if m.var == "ASNOW" and m.start is not None and m.end == h and m.end - m.start == win]
        if not any(m.kind == "pct" for m in mine):
            print(f"skip {win} h f{h:03d}: no such window", file=sys.stderr)
            continue
        get = lambda m: decode_at(s.get(url(cyc, "core", h), headers={"Range": f"bytes={m.offset}-{m.offset + m.length - 1}"},  # noqa: E731
                                        timeout=120).content, ij, grid)
        q = np.vstack([get(next(m for m in mine if m.kind == "pct" and m.value == p)) for p in LEVELS])   # (15, n), metres
        for m in [m for m in mine if m.kind == "prob"]:
            thr = float(re.search(r">([0-9.]+)", m.value).group(1))
            prob = get(m)
            mask = q[-1] >= thr / 2
            if mask.sum() < 50:
                continue
            qq, pp = q[:, mask], prob[mask]
            implied = np.array([100 - np.interp(thr, qq[:, k], LEVELS, left=0, right=100) for k in range(qq.shape[1])])
            d = pp - implied
            rows.append((win, h, thr * 39.3701, int(mask.sum()), float(np.mean(np.abs(d))), float(np.median(d)),
                         float(np.mean(np.abs(d) <= 10)), float(np.corrcoef(pp, implied)[0, 1]) if pp.std() > 0 else float("nan")))
    print(f"NBM {sys.argv[1]}: probability fields vs percentile-implied P(>x), western US cells (every 2nd)\n")
    print("| Window | End | Threshold | Cells | mean abs diff (pts) | median diff (prob - implied) | within 10 pts | corr |")
    print("|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r[0]} h | f{r[1]:03d} | >{r[2]:.1f} in | {r[3]:,} | {r[4]:.1f} | {r[5]:+.1f} | {100 * r[6]:.0f} % | {r[7]:.2f} |")


if __name__ == "__main__":
    main()
