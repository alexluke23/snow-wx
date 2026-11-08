"""Compare our NBM decode with the GSL NBM 1-D viewer's station CSVs.

C:/miniforge3/envs/snow-wx/python.exe tools/nbm_validate_gsl.py 2026110801 KMLP=47.45,-115.67 KSMP=47.28,-121.34 ...
  (CSV files from apps.gsl.noaa.gov/nbmviewer/data/archive/YYYY/MM/DD/NBM5.0/HH/<ID>.csv in --csv-dir)

For 24/48/72-h ASNOW windows: percentiles 10/50/90 and exceedance probabilities
(>1, >4, >8 in) at ~6 valid times per window, decoded at the nearest 2.5-km cell.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pipeline  # noqa: E402,F401  (ecCodes DLL path on Windows)
from pipeline.catalog import lcc_ij  # noqa: E402
from pipeline.nbm.inventory import parse_idx  # noqa: E402
from pipeline.nbm.run import decode_at, url  # noqa: E402

M_TO_IN = 39.3701
PCTS = (10, 50, 90)
THR_IN = {1: "0.0254", 4: "0.1016", 8: "0.2032"}     # GSL / NBM thresholds in metres


def gsl_rows(path):
    return {r["ValidTime"]: r for r in csv.DictReader(open(path, encoding="utf-8"))}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cycle")
    ap.add_argument("stations", nargs="+")
    ap.add_argument("--csv-dir", default=".")
    ap.add_argument("--per-window", type=int, default=6)
    a = ap.parse_args()
    cyc = datetime.strptime(a.cycle, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    grid = json.loads(Path("data/ski_areas.json").read_text(encoding="utf-8"))["nbm_grid"]
    st = {}
    for s in a.stations:
        sid, ll = s.split("=")
        la, lo = map(float, ll.split(","))
        st[sid] = (lcc_ij(la, lo, grid), gsl_rows(Path(a.csv_dir) / f"{sid}.csv"))
    ii = np.array([v[0][0] for v in st.values()]); jj = np.array([v[0][1] for v in st.values()])
    sess = requests.Session()
    out = []
    for win in (24, 48, 72):
        col = f"ASNOW{win}hr_surface"
        times = sorted({t for _, rows in st.values() for t, r in rows.items() if r.get(f"{col}_50% level") not in (None, "")})
        # prefer times where some station has snow, then spread over the run
        wet = [t for t in times if any(float(rows.get(t, {}).get(f"{col}_90% level") or 0) > 0 for _, rows in st.values())]
        pick = (wet + [t for t in times if t not in wet])[: a.per_window]
        for t in sorted(pick):
            h = int((datetime.strptime(t, "%Y%m%d%H").replace(tzinfo=timezone.utc) - cyc).total_seconds() // 3600)
            inv = parse_idx(sess.get(url(cyc, "core", h) + ".idx", timeout=60).text)
            want = {}
            for m in inv:
                if m.var != "ASNOW" or m.start is None or m.end - m.start != win or m.end != h:
                    continue
                if m.kind == "pct" and m.value in PCTS:
                    want[m] = f"p{m.value}"
                elif m.kind == "prob":
                    for k, v in THR_IN.items():
                        if m.value.startswith(f">{v}"):
                            want[m] = f">{k}in"
            for m, key in want.items():
                blob = sess.get(url(cyc, "core", h), headers={"Range": f"bytes={m.offset}-{m.offset + m.length - 1}"}, timeout=120).content
                vals = decode_at(blob, (ii, jj), grid)
                for n, (sid, (_, rows)) in enumerate(st.items()):
                    r = rows.get(t, {})
                    if key.startswith("p"):
                        g = r.get(f"{col}_{key[1:]}% level")
                        ours, theirs = vals[n] * M_TO_IN, (float(g) * M_TO_IN if g not in (None, "") else None)
                    else:
                        thr = THR_IN[int(key[1:-2])]
                        g = next((r[c] for c in r if c.startswith(f"{col}_prob >{thr}")), None)
                        ours, theirs = vals[n], (float(g) if g not in (None, "") else None)
                    out.append((win, t, sid, key, ours, theirs))
    # report
    print(f"| Window | Valid | Station | Field | ours | GSL | diff |\n|---|---|---|---|---|---|---|")
    diffs = {}
    for win, t, sid, key, ours, theirs in out:
        d = None if theirs is None or ours is None or np.isnan(ours) else ours - theirs
        diffs.setdefault((win, key[0]), []).append(abs(d) if d is not None else None)
        unit = "in" if key.startswith("p") else "%"
        print(f"| {win} h | {t} | {sid} | {key} | {ours:.2f} {unit} | {'—' if theirs is None else f'{theirs:.2f}'} | {'—' if d is None else f'{d:+.2f}'} |")
    print("\nSummary (max |diff|; n compared):")
    for (win, kind), ds in sorted(diffs.items()):
        dd = [x for x in ds if x is not None]
        print(f"  {win} h {'percentiles (in)' if kind == 'p' else 'exceedance (%)'}: n={len(dd)}, "
              f"max |diff| {max(dd):.3f}, exact (<0.01) {sum(x < 0.01 for x in dd)}/{len(dd)}" if dd else f"  {win} h {kind}: n=0")


if __name__ == "__main__":
    main()
