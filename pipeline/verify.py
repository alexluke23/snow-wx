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
import math
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


def run(archive_dir: Path, out_dir: Path, cfg: dict | None = None, min_hours: int = 20, publish_dir: Path | None = None) -> dict:
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
    by_src = {n: {"pairs": int(len(g)), "days": int(g["end_ts"].dt.normalize().nunique())} for n, g in pairs.groupby("_src")} if not pairs.empty else {}
    summary = {"generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "pairs": int(len(pairs)), "days": days, "span": span,
               "outage_excluded": outage, "min_hours": min_hours, "exclusions": exs, "by_source": by_src}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    (out_dir / "README.md").write_text(readme(summary, by_lead), encoding="utf-8")
    if publish_dir is not None:                                 # the public JSON for the (flag-gated) verification UI
        ui = (cfg or {}).get("verification_ui") or {}
        summary["published"] = publish(pairs, summary, Path(publish_dir), int(ui.get("min_days", 14)), int(ui.get("min_pairs", 30)))
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

# ---------------------------------------------------------------- public documents for the verification UI (dev18 Part 3; behind config verification_ui.enabled, never enabled by a dev session)
# dev23 (owner decision Nov 21): the public documents show NBM only. NDFD stays in the archive and in the local scorer CSVs / README above, never in the panel's JSON.
SRC_LABEL = {"nbm": "NBM expected"}
UI_LEAD_MAX_H = 48            # the panel scores forecasts issued at most 48 h before the window ends (days 1-2): one lead range per chart and table


def _lead_filtered(pairs: pd.DataFrame) -> pd.DataFrame:
    """every forecast/observation pair whose forecast was issued less than UI_LEAD_MAX_H before the window end (NBM `det` = expected amount, NDFD `det`)"""
    if pairs.empty:
        return pairs
    d = pairs[pd.to_numeric(pairs["lead_h"], errors="coerce") < UI_LEAD_MAX_H].copy()
    d["lead_h"] = pd.to_numeric(d["lead_h"], errors="coerce")
    d["fc"] = pd.to_numeric(d["det"], errors="coerce")
    return d[d["fc"].notna()]


def _select_leads(pairs: pd.DataFrame) -> pd.DataFrame:
    """one forecast per (source, SNOTEL site, window end): the shortest lead (the latest issued). The metrics and the daily chart use these, so a day counts once."""
    d = _lead_filtered(pairs)
    return d if d.empty else d.sort_values("lead_h").drop_duplicates(["_src", "triplet", "end_ts"], keep="first")


def _metrics(fc: pd.Series, ob: pd.Series) -> dict:
    hit = int(((fc >= 1.0) & (ob >= 1.0)).sum())
    miss = int(((fc < 1.0) & (ob >= 1.0)).sum())
    return {"n": int(len(fc)), "bias_in": round(float((fc - ob).mean()), 2), "mae_in": round(float((fc - ob).abs().mean()), 2),
            "events_1": hit + miss, "hit_1": round(hit / (hit + miss), 2) if hit + miss else None}


def _ready(days: int, n: int, min_days: int, min_pairs: int) -> bool:
    return days >= min_days and n >= min_pairs


def public_exclusions(ex: dict | None) -> dict | None:
    """the exclusion counts of the NBM scoring only (the summary also counts NDFD, which is not shown)"""
    return None if ex is None else {k: v for k, v in ex.items() if k == "nbm"}


def public_docs(pairs: pd.DataFrame, summary: dict, min_days: int = 14, min_pairs: int = 30, window_days: int = 30) -> tuple[dict, dict[str, dict]]:
    """(index document, {station file name: station document}). Results stay hidden (only counts) until a SNOTEL site has `min_days` observation days AND `min_pairs`
    forecast/observation pairs; the same minima gate the regional scorecard. Every metric compares forecasts with the observed 24-h snow-depth change, a LOWER BOUND of snowfall."""
    if "_src" in pairs.columns:
        pairs = pairs[pairs["_src"] == "nbm"]                                          # NBM only: no NDFD / "NWS" row, column or number reaches the public files
    allp = _lead_filtered(pairs)
    sel = _select_leads(pairs)
    index = {"generated_at": summary.get("generated_at"), "min_days": min_days, "min_pairs": min_pairs, "span": list(summary.get("span") or [None, None]),
             "outage_excluded": summary.get("outage_excluded"), "exclusions": public_exclusions(summary.get("exclusions")), "lead_max_h": UI_LEAD_MAX_H,
             "metric": "24-h snow-depth change at SNOTEL sites (lower bound of snowfall)", "stations": {}, "scorecard": {"ready": False, "days": 0, "pairs": 0, "rows": []}}
    files: dict[str, dict] = {}
    if sel.empty:
        return index, files
    both = sel.pivot_table(index=["triplet", "end_ts"], columns="_src", values="fc", aggfunc="first")
    obs = sel.drop_duplicates(["triplet", "end_ts"]).set_index(["triplet", "end_ts"])["obs"]
    all_days = int(sel["end_ts"].dt.normalize().nunique())
    for trip, g in sel.groupby("triplet"):
        days = int(g["end_ts"].dt.normalize().nunique())
        n = int(allp[allp["triplet"] == trip].groupby("_src").size().max())          # forecast/observation pairs (several cycles can cover one day)
        index["stations"][trip] = {"d": days, "n": n}
        if not _ready(days, n, min_days, min_pairs):
            continue
        keep = both.loc[trip]
        o = obs.loc[trip]
        metrics = {}
        if "nbm" in keep.columns:
            col = keep["nbm"].dropna()
            if len(col):
                metrics[SRC_LABEL["nbm"]] = _metrics(col.astype(float), o.reindex(col.index).astype(float))
        last = keep.sort_index().tail(window_days)
        span = sel[sel["triplet"] == trip]["end_ts"]

        def series(src):
            return [None if src not in last.columns or pd.isna(last.loc[i, src]) else round(float(last.loc[i, src]), 2) for i in last.index]
        files[trip.replace(":", "_") + ".json"] = {
            "triplet": trip, "d": days, "n": n, "span": [str(span.min().date()), str(span.max().date())], "metrics": metrics,
            "daily": {"dates": [str(i.date()) for i in last.index], "obs": [round(float(o.get(i)), 2) for i in last.index], "nbm": series("nbm")}}
        index["stations"][trip]["ready"] = True
    # regional scorecard over all sites (same minima on days and pairs)
    index["scorecard"].update(days=all_days, pairs=int(allp.groupby("_src").size().max()))
    if _ready(all_days, index["scorecard"]["pairs"], min_days, min_pairs):
        rows = []
        if "nbm" in both.columns:
            col = both["nbm"].dropna()
            if len(col):
                rows.append({"source": SRC_LABEL["nbm"], **_metrics(col.astype(float), obs.reindex(col.index).astype(float))})
        index["scorecard"].update(ready=True, rows=rows)
    return index, files


def publish(pairs: pd.DataFrame, summary: dict, data_dir: Path, min_days: int = 14, min_pairs: int = 30) -> dict:
    """write data/verification.json and data/verification/<station>.json under `data_dir` (stale station files are removed first)"""
    from .common import write_json
    data_dir = Path(data_dir)
    index, files = public_docs(pairs, summary, min_days, min_pairs)
    vdir = data_dir / "verification"
    vdir.mkdir(parents=True, exist_ok=True)
    for old in vdir.glob("*.json"):
        old.unlink()
    for name, doc in files.items():
        write_json(vdir / name, doc)
    write_json(data_dir / "verification.json", index)
    return {"stations": len(index["stations"]), "ready_stations": len(files), "scorecard_ready": index["scorecard"]["ready"]}


# ---------------------------------------------------------------- CI (dev21 Part 1: .github/workflows/verify.yml)
# The daily job downloads the archive CSVs from the "verification" release (written by update-site's archive step, SNOTEL obs included) and runs THE SAME
# scorer as above (run(): same outage window, same stale-observation rule). Its output is a product tar on the model-maps release, verify-<key>-<version>.tar,
# which update-site already extracts into build/models/: the panel reads models/verify/verification.json (flag verification_ui.enabled stays the only switch).
# key = the newest SNOTEL observation in the archive (YYYYMMDDHH, the daily 12Z): no new observation day = nothing new (exit 0, the last good result stays).
OUT_DIR = "verify"
STALE_OBS_H = 48


def newest_obs(archive_dir: Path) -> pd.Timestamp | None:
    obs = _read(archive_dir, "snotel")
    if obs.empty or "end" not in obs.columns:
        return None
    t = pd.to_datetime(obs["end"], utc=True, errors="coerce").dropna()
    return t.max() if len(t) else None


def ready_estimate(index: dict, newest: pd.Timestamp | None, min_days: int, min_pairs: int) -> dict:
    """When the minima will be met (a projection from the current pace, not a promise): the first SNOTEL site and the regional scorecard.
    Days grow by one per observation day; pairs grow at the site's current pairs-per-day rate (several cycles cover each day)."""
    def when(days: int, pairs: int) -> tuple[int, str | None]:
        if days >= min_days and pairs >= min_pairs:
            return 0, str(newest.date()) if newest is not None else None
        rate = pairs / days if days else 0
        need_d = max(0, min_days - days)
        need_p = math.ceil((min_pairs - pairs) / rate) if pairs < min_pairs and rate > 0 else (0 if pairs >= min_pairs else 10 ** 4)
        n = max(need_d, need_p)
        return n, (str((newest + pd.Timedelta(days=n)).date()) if newest is not None and n < 10 ** 4 else None)
    st = index.get("stations") or {}
    best = max(st.values(), key=lambda s: (min(s["d"] / min_days, s["n"] / min_pairs), s["d"], s["n"]), default=None)
    sc = index.get("scorecard") or {}
    first_n, first = when(best["d"], best["n"]) if best else (None, None)
    sc_n, sc_date = when(int(sc.get("days") or 0), int(sc.get("pairs") or 0))
    return {"stations_ready": sum(1 for s in st.values() if s.get("ready")), "stations": len(st), "best_station": best,
            "first_station_ready": first, "first_station_days_to_go": first_n, "scorecard_ready": sc_date, "scorecard_days_to_go": sc_n}


def ci_run(archive_dir: Path, out_models: Path, cfg: dict | None, published: str = "", github_output: str | None = None, now: datetime | None = None) -> dict:
    """Score the downloaded archive and write out_models/verify/{verification.json, verification/<site>.json, run.json}. Never raises for missing / stale input:
    returns {"new": False, "reason": ...} and the job exits 0, so the last good published result stays on the site."""
    from .common import write_json
    from .version import product_version
    now = now or datetime.now(timezone.utc)
    ui = (cfg or {}).get("verification_ui") or {}
    min_days, min_pairs = int(ui.get("min_days", 14)), int(ui.get("min_pairs", 30))

    def out(res: dict) -> dict:
        if github_output:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write(f"new={'true' if res.get('new') else 'false'}\n")
                if res.get("key"):
                    f.write(f"cycle={res['key']}\n")
                if res.get("warning"):
                    f.write(f"warning={res['warning']}\n")
        return res

    if not ((cfg or {}).get("verification") or {}).get("ci_enabled", True):
        return out({"new": False, "reason": "verification.ci_enabled is false"})
    newest = newest_obs(archive_dir)
    if newest is None:
        return out({"new": False, "reason": "no SNOTEL observations in the archive (download failed or empty)", "warning": "no archive observations: kept the last result"})
    age_h = (pd.Timestamp(now) - newest).total_seconds() / 3600
    warning = f"newest SNOTEL observation is {age_h:.0f} h old (archive step or SNOTEL fetch behind): kept the last result" if age_h > STALE_OBS_H else None
    key = f"{newest.strftime('%Y%m%d%H')}-{product_version('verify')}"
    if published and published == key:
        return out({"new": False, "key": key, "reason": "already published", "warning": warning})
    import tempfile
    vdir = Path(out_models) / OUT_DIR
    with tempfile.TemporaryDirectory() as tmp:
        summary = run(Path(archive_dir), Path(tmp), cfg, 20, vdir)
    index = json.loads((vdir / "verification.json").read_text(encoding="utf-8"))
    est = ready_estimate(index, newest, min_days, min_pairs)
    nbm_n = (summary.get("by_source") or {}).get("nbm") or {"pairs": 0, "days": 0}             # run.json is public: NBM counts only
    info = {"generated_at": now.strftime("%Y-%m-%dT%H:%MZ"), "key": key, "newest_obs": newest.strftime("%Y-%m-%dT%H:%MZ"), "obs_age_h": round(age_h, 1),
            "pairs": nbm_n["pairs"], "days": nbm_n["days"], "span": summary["span"], "exclusions": public_exclusions(summary["exclusions"]), "outage_excluded": summary["outage_excluded"],
            "min_days": min_days, "min_pairs": min_pairs, **est, **({"warning": warning} if warning else {})}
    write_json(vdir / "run.json", info)
    return out({"new": True, **info})
