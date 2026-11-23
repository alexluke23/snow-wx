"""Snow-to-liquid-ratio ground truth from the forecast archive's SNOTEL rows, and a baseline score (dev22 Part 5c; docs/specs/snow-ratio-ml.md). READ-ONLY, offline, never published.

    C:/miniforge3/envs/snow-wx/python.exe tools/slr_baseline.py --dir <folder with snotel-YYYYMM.csv.gz> [--nbm-slr slr.csv] [--fixed 10 12 15]

Observed ratio per SNOTEL site and day = 24 h snow-depth change / 24 h SWE change (the archive's 12Z rows: `d_depth_med3_24h` / `d_swe_24h`). Filters follow Veals et al. 2025
(new snow > 2 in, SWE > 0.11 in; ratios <= 2, >= 50 and exactly 10.0 dropped: pillow/board artefacts), plus >= 20 hourly reports in the window. CAVEATS (printed with every run):
  * a 24 h depth change includes COMPACTION and settling, so it is a LOWER bound of new snow: observed ratios here are biased LOW against interval-board measurements;
  * the archive has NO temperature or precipitation-type columns, so warm / rain-affected days cannot be skipped (the >= 2 in depth gain and the ratio <= 2 rule are the only guards);
  * archive files written before dev23 have NO forecast snow ratio. From dev23 the nbm files carry NBM's native SLR percentiles (slr_p25/p50/p75, valid at the window end hour 12Z,
    docs/verification.md): the day-1 value of the newest cycle is scored as "NBM SLR p50" automatically when the folder has them (blank in older rows: skipped). `--nbm-slr` (a CSV with
    columns end,triplet,slr_p50) still overrides. Run it after >= 4 weeks of those columns. One hour is a coarse stand-in for the 24-h mean ratio: say so when quoting it.
The pure functions are tested offline (tests/test_slr_baseline.py).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

MIN_DEPTH_IN, MIN_SWE_IN, MIN_HOURS = 2.0, 0.11, 20
CAVEATS = ("Depth change includes compaction: observed ratios are a LOWER bound; the archive has no temperature, so warm/rain days are not skipped; "
           "the archive has no forecast snow ratio (NBM SLR p50 needs a new additive archive file).")


def derive_events(obs: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """SNOTEL archive rows -> qualifying events (one per site and 12Z day) with their observed ratio, and a count of what each filter removed"""
    d = obs.copy()
    n0 = len(d)
    for c in ("d_depth_med3_24h", "d_swe_24h", "hours_present"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.dropna(subset=["d_depth_med3_24h", "d_swe_24h"])
    stats = {"rows": n0, "with_both_changes": len(d)}
    d = d[d["hours_present"].fillna(0) >= MIN_HOURS]
    stats["enough_reports"] = len(d)
    d = d[(d["d_depth_med3_24h"] > MIN_DEPTH_IN) & (d["d_swe_24h"] > MIN_SWE_IN)]
    stats["new_snow_and_swe"] = len(d)
    d = d.assign(ratio=d["d_depth_med3_24h"] / d["d_swe_24h"])
    d = d[(d["ratio"] > 2) & (d["ratio"] < 50) & (d["ratio"].round(6) != 10.0)]
    stats["qualifying"] = len(d)
    d["end"] = pd.to_datetime(d["end"], utc=True, errors="coerce")
    d["state"] = d["triplet"].astype(str).str.split(":").str[1]
    d["week"] = d["end"].dt.strftime("%G-W%V")
    return d.reset_index(drop=True), stats


def counts(events: pd.DataFrame) -> dict:
    return {"by_site": events.groupby("triplet").size().sort_values(ascending=False), "by_week": events.groupby("week").size(), "by_state": events.groupby("state").size()}


def metrics(pred: pd.Series, obs: pd.Series) -> dict:
    e = (pred - obs).astype(float)
    ss = float(((obs - obs.mean()) ** 2).sum())
    return {"n": int(len(obs)), "mae": float(e.abs().mean()), "bias": float(e.mean()), "r2": (float(1 - (e ** 2).sum() / ss) if ss > 0 and len(obs) > 1 else float("nan"))}


def nbm_slr_from_archive(nbm: pd.DataFrame) -> pd.DataFrame | None:
    """(end, triplet, slr_p50) from the archive's nbm rows (dev23 columns): 24-h rows at SNOTEL sites, the newest cycle per (end, triplet) = the smallest lead"""
    if nbm is None or nbm.empty or "slr_p50" not in nbm.columns:
        return None
    f = nbm[(nbm["hours"] == 24) & nbm["point"].astype(str).str.startswith("snotel-") & pd.to_numeric(nbm["slr_p50"], errors="coerce").notna()].copy()
    if f.empty:
        return None
    f["triplet"] = f["point"].str.removeprefix("snotel-").str.replace("-", ":", regex=False)
    f["lead_h"] = pd.to_numeric(f["lead_h"], errors="coerce")
    f = f.sort_values("lead_h").drop_duplicates(["end", "triplet"], keep="first")
    return f[["end", "triplet", "slr_p50"]].reset_index(drop=True)


def score(events: pd.DataFrame, fixed=(10, 12, 15), nbm: pd.DataFrame | None = None) -> pd.DataFrame:
    """MAE, bias, R2 of each predictor against the observed ratio, overall and by state (the region proxy); NBM SLR p50 only when a file with it is given"""
    rows = []
    preds = {f"fixed {r}:1": pd.Series(float(r), index=events.index) for r in fixed}
    if nbm is not None and len(nbm):
        n = nbm.copy()
        n["end"] = pd.to_datetime(n["end"], utc=True, errors="coerce")
        m = events.merge(n[["end", "triplet", "slr_p50"]], on=["end", "triplet"], how="left")
        preds["NBM SLR p50"] = pd.Series(pd.to_numeric(m["slr_p50"], errors="coerce").values, index=events.index)
    for name, p in preds.items():
        ok = p.notna()
        rows.append({"predictor": name, "region": "all", **metrics(p[ok], events.loc[ok, "ratio"])})
        for st, g in events.loc[ok].groupby("state"):
            if len(g) >= 5:
                rows.append({"predictor": name, "region": st, **metrics(p[g.index], g["ratio"])})
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="folder with snotel-YYYYMM.csv.gz (the forecast archive; download into the scratchpad, never keep it)")
    ap.add_argument("--nbm-slr", help="optional CSV with columns end,triplet,slr_p50")
    ap.add_argument("--fixed", nargs="*", type=float, default=[10, 12, 15])
    a = ap.parse_args(argv)
    from pipeline import verify as V
    nbm_arc, _, obs = V.load_archive(Path(a.dir))
    ev, st = derive_events(obs)
    print("filters:", st)
    c = counts(ev)
    print("events by state:", dict(c["by_state"]))
    print("events by week:", dict(c["by_week"]))
    print("top sites:", dict(c["by_site"].head(8)))
    if len(ev):
        print("observed ratio: median %.1f, p25 %.1f, p75 %.1f" % (ev["ratio"].median(), ev["ratio"].quantile(.25), ev["ratio"].quantile(.75)))
        nbm = pd.read_csv(a.nbm_slr) if a.nbm_slr else nbm_slr_from_archive(nbm_arc)
        print(score(ev, a.fixed, nbm).round(2).to_string(index=False))
    print("CAVEATS:", CAVEATS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
