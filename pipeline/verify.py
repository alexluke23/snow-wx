"""M9-prep: score archived 24-h snowfall forecasts against SNOTEL (script, not UI). docs/verification.md.

    python -m pipeline verify --dir <folder with nbm-*.csv.gz ndfd-*.csv.gz snotel-*.csv.gz> --out <folder>

Pairs every archived 24-h forecast window at a SNOTEL site (`snotel-<triplet>` points: forecast and observation are co-located) with the
SNOTEL observation for the same window end (12Z): the 24-h change in the 3-h-median snow depth, clipped at 0. A depth change is a LOWER BOUND
of snowfall (settling, melt and wind take it away), so BIAS is expected to be positive (forecast > observed); read it with that in mind.

Excluded before scoring, and counted in the output:
  * observations whose 24-h window overlaps the NRCS SNOTEL outage window (config verification.snotel_outage: start .. first CONFIRMED live recovery, PLAN §2);
  * observations with fewer than `min_hours` hourly reports in the 24 h (stale / carried / patchy stations; `hours_present`);
  * pairs with a missing forecast or observation.
Scores are by lead bucket and by state / elevation band: n, bias, MAE, and the event skill (POD, FAR) for >= 1 in and >= 4 in; NBM also gets
a Brier score for its own P(>= 4 in). Sources scored: NBM deterministic (`det`), NBM median (`p50`), NWS NDFD (`det`, grid cell, raw).
Temperature is NOT scored: the archive carries snow only (see the README the script writes).
"""

from __future__ import annotations

import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

LEADS = [(0, 24, "day 1 (0-24 h)"), (24, 48, "day 2 (24-48 h)"), (48, 72, "day 3 (48-72 h)"), (72, 120, "days 4-5"), (120, 400, "days 6+")]
THRESHOLDS = (1.0, 4.0)
BANDS = [(0, 6000, "< 6,000 ft"), (6000, 8000, "6,000-8,000 ft"), (8000, 99999, ">= 8,000 ft")]
SOURCES = (("nbm", "det", "NBM expected"), ("nbm", "p50", "NBM median"), ("ndfd", "det", "NWS (NDFD)"))


def _read(dir_: Path, prefix: str) -> pd.DataFrame:
    frames = [pd.read_csv(p, dtype={"cycle": str}) for p in sorted(Path(dir_).glob(f"{prefix}-*.csv.gz"))]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_archive(dir_: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return _read(dir_, "nbm"), _read(dir_, "ndfd"), _read(dir_, "snotel")


def _ts(s: str) -> pd.Timestamp:
    return pd.Timestamp(s).tz_convert("UTC") if pd.Timestamp(s).tzinfo else pd.Timestamp(s, tz="UTC")


def pair(forecasts: pd.DataFrame, obs: pd.DataFrame, outage: tuple[str, str] | None, min_hours: int = 20) -> tuple[pd.DataFrame, dict]:
    """24-h SNOTEL-site forecasts joined to the observation at the same window end. Returns (pairs, exclusion counts)."""
    ex = {"forecast_rows": 0, "no_observation": 0, "outage_window": 0, "low_coverage": 0, "missing_value": 0}
    f = forecasts[(forecasts["hours"] == 24) & forecasts["point"].astype(str).str.startswith("snotel-")].copy()
    ex["forecast_rows"] = int(len(f))
    if f.empty or obs.empty:
        return pd.DataFrame(), ex
    f["triplet"] = f["point"].str.removeprefix("snotel-").str.replace("-", ":", regex=False)
    f["end_ts"] = pd.to_datetime(f["end"], utc=True)
    o = obs.copy()
    o["end_ts"] = pd.to_datetime(o["end"], utc=True)
    o = o.drop_duplicates(["triplet", "end_ts"], keep="last")                    # overlapping monthly files must not duplicate forecast rows
    both = f.merge(o[["triplet", "end_ts", "d_depth_med3_24h", "hours_present"]], on=["triplet", "end_ts"], how="left")
    ex["no_observation"] = int(both["d_depth_med3_24h"].isna().sum())
    keep = both
    if outage:
        a, b = _ts(outage[0]), _ts(outage[1])
        # OVERLAP test: a 24-h window that touches the outage at all is excluded (it would use stale / carried depths), including the
        # window ending at the outage start and the first windows ending after the recovery
        inside = (keep["end_ts"] >= a) & ((keep["end_ts"] - pd.Timedelta(hours=24)) < b)
        ex["outage_window"] = int(inside.sum())
        keep = keep[~inside]
    low = keep["hours_present"].fillna(0) < min_hours
    ex["low_coverage"] = int((low & keep["d_depth_med3_24h"].notna()).sum())
    keep = keep[~low]
    ex["missing_value"] = int(keep["d_depth_med3_24h"].isna().sum())
    keep = keep[keep["d_depth_med3_24h"].notna()].copy()
    keep["obs"] = keep["d_depth_med3_24h"].astype(float).clip(lower=0.0)
    keep["state"] = keep["triplet"].str.split(":").str[1]
    ef = pd.to_numeric(keep["elev_ft"], errors="coerce")
    keep["band"] = [next((lab for lo, hi, lab in BANDS if lo <= v < hi), "unknown") if pd.notna(v) else "unknown" for v in ef]
    keep["lead_bucket"] = [next((lab for lo, hi, lab in LEADS if lo <= v < hi), "other") for v in pd.to_numeric(keep["lead_h"], errors="coerce").fillna(-1)]
    return keep, ex


def _skill(fc: pd.Series, ob: pd.Series, thr: float) -> dict:
    hit = int(((fc >= thr) & (ob >= thr)).sum())
    miss = int(((fc < thr) & (ob >= thr)).sum())
    fa = int(((fc >= thr) & (ob < thr)).sum())
    return {f"pod_{thr:g}": round(hit / (hit + miss), 3) if hit + miss else None, f"far_{thr:g}": round(fa / (hit + fa), 3) if hit + fa else None,
            f"events_{thr:g}": hit + miss}


def score(pairs: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """One row per (source, group): n, bias, MAE, POD/FAR at 1 and 4 in, and NBM's Brier score for P(>= 4 in)."""
    rows = []
    if pairs.empty:
        return pd.DataFrame()
    for _, col, label in SOURCES:
        if col not in pairs.columns:
            continue
        src = "ndfd" if label.startswith("NWS") else "nbm"
        d = pairs[pairs["_src"] == src] if "_src" in pairs.columns else pairs
        d = d[pd.to_numeric(d[col], errors="coerce").notna()]
        for key, g in (d.groupby(by) if by else [("all", d)]):
            fc, ob = pd.to_numeric(g[col]).astype(float), g["obs"].astype(float)
            r = {"source": label, **({b: k for b, k in zip(by, key if isinstance(key, tuple) else (key,))} if by else {"group": "all"}),
                 "n": int(len(g)), "bias_in": round(float((fc - ob).mean()), 2), "mae_in": round(float((fc - ob).abs().mean()), 2),
                 "mean_obs_in": round(float(ob.mean()), 2)}
            for t in THRESHOLDS:
                r.update(_skill(fc, ob, t))
            if src == "nbm" and col == "det":
                pg = pd.to_numeric(g.get("p_ge4"), errors="coerce")
                m = pg.notna()
                if m.any():
                    r["brier_p_ge4"] = round(float((((pg[m] / 100.0) - (ob[m] >= 4).astype(float)) ** 2).mean()), 3)
            rows.append(r)
    return pd.DataFrame(rows)


def run(archive_dir: Path, out_dir: Path, cfg: dict | None = None, min_hours: int = 20) -> dict:
    nbm, ndfd, obs = load_archive(archive_dir)
    outage = None
    so = ((cfg or {}).get("verification") or {}).get("snotel_outage")
    if so:
        outage = (so["start"], so["end"])
    allp, exs = [], {}
    for name, fdf in (("nbm", nbm), ("ndfd", ndfd)):
        p, ex = pair(fdf, obs, outage, min_hours) if not fdf.empty else (pd.DataFrame(), {"forecast_rows": 0})
        if not p.empty:
            p["_src"] = name
            allp.append(p)
        exs[name] = ex
    pairs = pd.concat(allp, ignore_index=True) if allp else pd.DataFrame()
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    by_lead = score(pairs, ["lead_bucket"]) if not pairs.empty else pd.DataFrame()
    by_state = score(pairs[pairs["lead_bucket"].isin(["day 1 (0-24 h)", "day 2 (24-48 h)"])], ["state"]) if not pairs.empty else pd.DataFrame()
    by_band = score(pairs[pairs["lead_bucket"].isin(["day 1 (0-24 h)", "day 2 (24-48 h)"])], ["band"]) if not pairs.empty else pd.DataFrame()
    for name, df in (("scores_by_lead.csv", by_lead), ("scores_by_state_days12.csv", by_state), ("scores_by_elevation_days12.csv", by_band)):
        df.to_csv(out_dir / name, index=False)
    span = (pairs["end_ts"].min().strftime("%Y-%m-%d"), pairs["end_ts"].max().strftime("%Y-%m-%d")) if not pairs.empty else (None, None)
    days = int(pairs["end_ts"].dt.normalize().nunique()) if not pairs.empty else 0
    summary = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "pairs": int(len(pairs)), "days": days, "span": span,
               "outage_excluded": outage, "min_hours": min_hours, "exclusions": exs}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    (out_dir / "README.md").write_text(readme(summary, by_lead), encoding="utf-8")
    return summary


def md_table(df: pd.DataFrame) -> str:
    cell = lambda v: "–" if v is None or (isinstance(v, float) and v != v) else str(v)  # noqa: E731
    out = ["| " + " | ".join(df.columns) + " |", "|" + "|".join("---" for _ in df.columns) + "|"]
    out += ["| " + " | ".join(cell(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(out)


def readme(s: dict, by_lead: pd.DataFrame) -> str:
    lines = ["# Forecast verification (M9-prep)", "",
             f"Generated {s['generated_at']}. Pairs scored: **{s['pairs']}** (24-h windows ending 12Z, SNOTEL-site forecasts vs the observed depth change), "
             f"over **{s['days']} days** ({s['span'][0]} to {s['span'][1]}).", "",
             "Excluded: observations inside the SNOTEL outage window " + (f"({s['outage_excluded'][0]} to {s['outage_excluded'][1]})" if s["outage_excluded"] else "(none configured)")
             + f"; observations with fewer than {s['min_hours']} hourly reports in the 24 h (stale / carried / patchy); pairs missing either side. Counts: "
             + "; ".join(f"{k}: " + ", ".join(f"{a}={b}" for a, b in v.items()) for k, v in s["exclusions"].items()) + ".", ""]
    if not by_lead.empty:
        lines += ["## By lead time", "", md_table(by_lead[["source", "lead_bucket", "n", "bias_in", "mae_in", "pod_1", "far_1", "pod_4", "far_4"]]), ""]
    lines += ["## What about 10 days of archive can and cannot support", "",
              "- **Can:** a first look at bias and MAE for days 1-3, whether NBM's expected amount runs high against the observed depth change, and whether NBM beats NDFD on days 1-2.",
              "- **Cannot:** seasonal skill or regional rankings (a handful of storms, many dry days: scores are dominated by zeros), rare-event skill (>= 4 in events are few: PODs are noisy), "
              "calibration of probabilities (Brier needs hundreds of events), or elevation effects within a state.",
              "- **Observation limits:** depth change is a lower bound of snowfall (compaction), so positive forecast bias is expected; the SWE change is the better liquid check but the archive has no forecast liquid column.",
              "- **Temperature is not scored:** the archive holds snow forecasts only and no SNOTEL temperatures. To score temperature, add forecast tmax/tmin (24 h, 12Z-12Z) and the observed tmax/tmin from SNOTEL TOBS to the archive columns first.",
              "- **Ski-area points** are not scored here (no co-located observation); they would need the nearest-station proxy with its elevation difference.", ""]
    return "\n".join(lines)
