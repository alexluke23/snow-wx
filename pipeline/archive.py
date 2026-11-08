"""Forecast archive for verification (PLAN.md M9-prep; format in docs/verification.md).

Every site build appends what it has to monthly gzipped CSVs kept as assets of the
"verification" GitHub prerelease (never in git, never on the owner's PC):

  nbm-YYYYMM.csv.gz     NBM, every 24-h window ending 12Z (days 1-10) and every 72-h
                        window ending 12Z, per ski-area summit/base and SNOTEL site
  ndfd-YYYYMM.csv.gz    NWS official (NDFD), the same windows where NDFD covers them
  snotel-YYYYMM.csv.gz  observed SNOTEL depth/SWE at 12Z and their 24-h changes
  state.json            which NBM/NDFD cycles are already archived (so the big
                        monthly files are only downloaded when there is something new)

Rows are keyed (forecasts: cycle + point + elev + hours + end; obs: end + triplet), so
re-running is idempotent and later values (SNOTEL QC revisions) replace earlier ones.
Pure row builders and merging are tested offline; the stores are thin wrappers.
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import logging
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .common import utcnow

log = logging.getLogger("snow-wx.archive")

FORECAST_COLS = ("cycle", "point", "elev", "elev_ft", "cell_elev_ft", "hours", "end", "lead_h",
                 "det", "det_cell", "p10", "p50", "p90", "p_ge4", "p_ge8", "p_ge12")
FORECAST_KEY = ("cycle", "point", "elev", "hours", "end")
OBS_COLS = ("end", "triplet", "depth_in", "depth_med3_in", "swe_in",
            "d_depth_24h", "d_depth_med3_24h", "d_swe_24h", "hours_present")
OBS_KEY = ("end", "triplet")
WINDOWS = (24, 72)
THRESHOLDS = (4.0, 8.0, 12.0)
STATE_KEEP = 400                     # cycle ids remembered per source
ISO = "%Y-%m-%dT%H:%MZ"


def _dt(s: str) -> datetime:
    return datetime.strptime(s, ISO).replace(tzinfo=timezone.utc)


def _iso(t: datetime) -> str:
    return t.strftime(ISO)


def _s(v, nd: int = 1) -> str:
    """CSV cell: '' for missing, rounded numbers without trailing noise."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return str(int(v))
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v != v:                     # NaN
            return ""
        r = round(v, nd)
        return str(int(r)) if nd == 0 or r == int(r) else f"{r:.{nd}f}".rstrip("0").rstrip(".")
    return str(v)


# ---------------------------------------------------------------- forecast rows (pure)

def twelve_z_windows(periods: list[dict], hours: int) -> list[tuple[str, str, float | None]]:
    """(start, end, sum of snow_in) for every `hours` window ending at 12Z that is exactly
    covered by consecutive 12-h periods; the sum is None if any period lacks snow_in."""
    by_end = {p["end"]: p for p in periods if p.get("start") and p.get("end")}
    n = hours // 12
    out = []
    for p in periods:
        end = p.get("end")
        if not end or not end.endswith("T12:00Z"):
            continue
        chain, cur = [], end
        for _ in range(n):
            q = by_end.get(cur)
            if q is None or (_dt(q["end"]) - _dt(q["start"])) != timedelta(hours=12):
                chain = None
                break
            chain.append(q)
            cur = q["start"]
        if not chain:
            continue
        vals = [q.get("snow_in") for q in chain]
        out.append((cur, end, None if any(v is None for v in vals) else round(sum(vals), 1)))
    return out


def _forecast_row(cycle: str, point: str, elev: str, pt: dict, hours: int, end: str, **vals) -> dict:
    lead = int((_dt(end) - datetime.strptime(cycle, "%Y%m%d%H").replace(tzinfo=timezone.utc)).total_seconds() // 3600)
    row = {"cycle": cycle, "point": point, "elev": elev, "elev_ft": _s(pt.get("elev_ft"), 0),
           "cell_elev_ft": _s(pt.get("grid_elev_ft"), 0), "hours": str(hours), "end": end, "lead_h": str(lead)}
    for c in FORECAST_COLS[8:]:
        row[c] = _s(vals.get(c), 0 if c.startswith("p_ge") else 1)
    return row


def nbm_rows(doc: dict) -> list[dict]:
    """Rows for one NBM point file (ski area: summit + base; SNOTEL: point).

    det = NBM mean as shown on the site (12-h periods scaled by P(snow) at the point's
    elevation); det_cell, p10/p50/p90 and p_ge* = NBM's values for the 2.5 km cell
    (exceedance windows of the 01/07/13/19Z cycles)."""
    cycle, point = doc["cycle"], doc["id"]
    rows = []
    for elev, pt in doc.get("points", {}).items():
        for hours in WINDOWS:
            ex = (pt.get("exceed") or {}).get(f"{hours}h") or {}
            ex_at = {e: k for k, e in enumerate(ex.get("end") or [])}
            det = {end: v for _, end, v in twelve_z_windows(pt.get("periods") or [], hours)}
            for end in sorted(set(det) | set(ex_at)):
                vals = {"det": det.get(end)}
                k = ex_at.get(end)
                if k is not None:
                    if ex.get("mean") and ex["mean"][k] is not None and vals["det"] is None:
                        vals["det"] = ex["mean"][k]
                    vals["det_cell"] = (ex.get("cell_mean") or [None] * (k + 1))[k]
                    for q in ("10", "50", "90"):
                        vals[f"p{q}"] = ((ex.get("pct") or {}).get(q) or [None] * (k + 1))[k]
                    thr = [float(t) for t in ex.get("thr") or []]
                    for t in THRESHOLDS:
                        if t in thr and ex.get("p"):
                            vals[f"p_ge{int(t)}"] = ex["p"][k][thr.index(t)]
                rows.append(_forecast_row(cycle, point, elev, pt, hours, end, **vals))
    return rows


def ndfd_cycle(doc: dict) -> str | None:
    iss = doc.get("issued")
    return _dt(iss).strftime("%Y%m%d%H") if iss else None


def ndfd_rows(doc: dict) -> list[dict]:
    """NWS official (NDFD, raw for the grid cell): deterministic snow for the 12Z windows
    its 12-h periods cover (NDFD snowfall runs 72 h, so mostly days 1-2)."""
    cycle = ndfd_cycle(doc)
    if not cycle:
        return []
    rows = []
    for elev, pt in doc.get("points", {}).items():
        for hours in WINDOWS:
            for start, end, v in twelve_z_windows(pt.get("periods") or [], hours):
                if _dt(start) >= _dt(doc["issued"]):
                    rows.append(_forecast_row(cycle, doc["id"], elev, pt, hours, end, det=v))
    return rows


# ---------------------------------------------------------------- SNOTEL rows (pure)

def snotel_rows(ts: dict, offset_h: float) -> list[dict]:
    """Daily rows at the hour that is 12Z (the time NBM's daily windows end).
    ts times are the station's local standard time; offset_h = local - UTC (e.g. -8)."""
    times = ts.get("times") or []
    idx = {t: i for i, t in enumerate(times)}
    sd, med, swe = ts.get("SNWD") or [], ts.get("SNWD_med3") or [], ts.get("WTEQ") or []
    get = lambda a, i: a[i] if i is not None and i < len(a) else None  # noqa: E731
    rows = []
    for i, t in enumerate(times):
        local = datetime.strptime(t, "%Y-%m-%d %H:%M")
        utc = local - timedelta(hours=offset_h)
        if utc.hour != 12 or utc.minute != 0:
            continue
        j = idx.get((local - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M"))
        cur = (get(sd, i), get(med, i), get(swe, i))
        if all(v is None for v in cur):
            continue
        prev = (get(sd, j), get(med, j), get(swe, j))
        diff = [None if a is None or b is None else a - b for a, b in zip(cur, prev)]
        present = sum(1 for k in range(i - 23, i + 1) if 0 <= k < len(sd) and sd[k] is not None) if j is not None else 0
        rows.append({"end": utc.strftime(ISO), "triplet": ts["triplet"], "depth_in": _s(cur[0]),
                     "depth_med3_in": _s(cur[1]), "swe_in": _s(cur[2]), "d_depth_24h": _s(diff[0]),
                     "d_depth_med3_24h": _s(diff[1]), "d_swe_24h": _s(diff[2]), "hours_present": str(present)})
    return rows


# ---------------------------------------------------------------- CSV + merge (pure-ish)

def read_csv_gz(path: Path, cols: tuple, key: tuple) -> dict[tuple, dict]:
    out = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            row = {c: row.get(c, "") or "" for c in cols}
            out[tuple(row[k] for k in key)] = row
    return out


def write_csv_gz(path: Path, cols: tuple, rows: dict[tuple, dict]) -> None:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=list(cols), lineterminator="\n")
    w.writeheader()
    for k in sorted(rows):
        w.writerow(rows[k])
    raw = buf.getvalue().encode("utf-8")
    with open(path, "wb") as f, gzip.GzipFile(fileobj=f, mode="wb", mtime=0, compresslevel=9) as gz:
        gz.write(raw)                  # mtime=0: identical content -> identical bytes


def merge(existing: dict[tuple, dict], new: list[dict], key: tuple) -> tuple[dict, int, int]:
    """-> (merged, rows added, rows changed). New rows replace existing ones with the same key."""
    merged, added, changed = dict(existing), 0, 0
    for r in new:
        k = tuple(r[c] for c in key)
        old = merged.get(k)
        if old is None:
            added += 1
        elif old != r:
            changed += 1
        else:
            continue
        merged[k] = r
    return merged, added, changed


def month_of(kind: str, row: dict) -> str:
    return row["cycle"][:6] if kind in ("nbm", "ndfd") else row["end"][:7].replace("-", "")


def allowed_months(now: datetime) -> set[str]:
    first = now.replace(day=1)
    return {now.strftime("%Y%m"), (first - timedelta(days=1)).strftime("%Y%m")}


# ---------------------------------------------------------------- stores

class LocalStore:
    """A directory standing in for the release (tests and local dry runs)."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def ensure(self) -> None:
        pass

    def list(self) -> set[str]:
        return {p.name for p in self.root.iterdir() if p.is_file()}

    def download(self, name: str, dest: Path) -> Path:
        out = Path(dest) / name
        out.write_bytes((self.root / name).read_bytes())
        return out

    def upload(self, path: Path) -> None:
        (self.root / Path(path).name).write_bytes(Path(path).read_bytes())


class ReleaseStore:
    """Assets of one GitHub release via the gh CLI (CI only: needs GH_TOKEN with contents: write)."""

    def __init__(self, tag: str, run=subprocess.run):
        self.tag, self._run = tag, run

    def _gh(self, *args, check=True) -> str:
        r = self._run(["gh", *args], capture_output=True, text=True)
        if check and r.returncode != 0:
            raise RuntimeError(f"gh {' '.join(args[:3])}: {r.stderr.strip()[:300]}")
        return r.stdout if r.returncode == 0 else ""

    def ensure(self) -> None:
        if self._run(["gh", "release", "view", self.tag], capture_output=True, text=True).returncode == 0:
            return
        notes = ("Forecast archive for verification (NBM, NDFD, SNOTEL), appended automatically by the "
                 "Update site workflow. Format: docs/verification.md. Not a software release.")
        r = self._run(["gh", "release", "create", self.tag, "--prerelease", "--title", "Forecast archive (automated)",
                       "--notes", notes], capture_output=True, text=True)
        if r.returncode != 0:              # a parallel job may have created it
            self._gh("release", "view", self.tag)

    def list(self) -> set[str]:
        out = self._gh("release", "view", self.tag, "--json", "assets", "-q", ".assets[].name")
        return {x.strip() for x in out.splitlines() if x.strip()}

    def download(self, name: str, dest: Path) -> Path:
        self._gh("release", "download", self.tag, "-p", name, "-D", str(dest), "--clobber")
        return Path(dest) / name

    def upload(self, path: Path) -> None:
        self._gh("release", "upload", self.tag, str(path), "--clobber")


# ---------------------------------------------------------------- run

def _load_docs(folder: Path) -> list[dict]:
    docs = []
    for p in sorted(Path(folder).glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            log.warning("archive: unreadable %s", p)
            continue
        if isinstance(d, dict) and d.get("points") and d.get("id"):
            docs.append(d)
    return docs


def _snotel_offsets(data: Path) -> dict[str, tuple[str | None, float]]:
    """triplet -> (state, lon) from snotel.geojson, for files without utc_offset_h."""
    p = data / "snotel.geojson"
    if not p.exists():
        return {}
    out = {}
    for f in json.loads(p.read_text(encoding="utf-8")).get("features", []):
        pr = f.get("properties") or {}
        out[pr.get("triplet")] = (pr.get("state"), float(f["geometry"]["coordinates"][0]))
    return out


def collect(data: Path) -> tuple[dict[str, list[dict]], dict[str, set[str]]]:
    """All rows the current build can contribute -> ({kind: rows}, {kind: cycles})."""
    from .snotel import utc_offset
    data = Path(data)
    rows: dict[str, list[dict]] = {"nbm": [], "ndfd": [], "snotel": []}
    cycles: dict[str, set[str]] = {"nbm": set(), "ndfd": set()}
    for d in _load_docs(data / "points"):
        rows["nbm"].extend(nbm_rows(d))
        cycles["nbm"].add(d["cycle"])
    for d in _load_docs(data / "ndfd"):
        r = ndfd_rows(d)
        rows["ndfd"].extend(r)
        if r:
            cycles["ndfd"].add(r[0]["cycle"])
    where = _snotel_offsets(data)
    for p in sorted((data / "snotel").glob("*.json")):
        ts = json.loads(p.read_text(encoding="utf-8"))
        if "triplet" not in ts:
            continue
        off = ts.get("utc_offset_h")
        if off is None:
            st, lon = where.get(ts["triplet"], (ts["triplet"].split(":")[1] if ts["triplet"].count(":") == 2 else None, -120.0))
            off = utc_offset(None, st, lon)
        rows["snotel"].extend(snotel_rows(ts, float(off)))
    return rows, cycles


def archive(data: Path, store, work: Path, now: datetime | None = None) -> dict:
    """Merge this build's rows into the store's monthly files. Returns per-file stats.

    Safety: a monthly file that exists in the store is always downloaded and merged
    before it is replaced; a failed download raises (nothing is uploaded)."""
    now = now or utcnow()
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    store.ensure()
    names = store.list()
    state = {"nbm": [], "ndfd": []}
    if "state.json" in names:
        saved = json.loads(store.download("state.json", work).read_text(encoding="utf-8"))
        state = {k: list(saved.get(k, [])) for k in state}
    rows, cycles = collect(data)
    ok_months = allowed_months(now)
    stats, new_state = {}, {k: list(v) for k, v in state.items()}     # {"nbm": [...], "ndfd": [...]}
    for kind in ("nbm", "ndfd", "snotel"):
        cols, key = (OBS_COLS, OBS_KEY) if kind == "snotel" else (FORECAST_COLS, FORECAST_KEY)
        todo = rows[kind]
        if kind != "snotel":
            done = set(state.get(kind, []))
            todo = [r for r in todo if r["cycle"] not in done]
        by_month: dict[str, list[dict]] = {}
        for r in todo:
            m = month_of(kind, r)
            if m in ok_months:
                by_month.setdefault(m, []).append(r)
        for m, new in sorted(by_month.items()):
            name = f"{kind}-{m}.csv.gz"
            existing = read_csv_gz(store.download(name, work), cols, key) if name in names else {}
            merged, added, changed = merge(existing, new, key)
            if added or changed:
                path = work / name
                write_csv_gz(path, cols, merged)
                store.upload(path)
                stats[name] = {"rows": len(merged), "added": added, "changed": changed, "bytes": path.stat().st_size}
                log.info("archive %s: +%d rows, %d changed, %d total, %.1f MB", name, added, changed,
                         len(merged), path.stat().st_size / 1e6)
        if kind != "snotel":
            new_state[kind] = sorted(set(new_state.get(kind, [])) | {c for c in cycles[kind] if c[:6] in ok_months})[-STATE_KEEP:]
    if new_state != state:
        p = work / "state.json"
        p.write_text(json.dumps({**new_state, "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ")}, indent=1), encoding="utf-8")
        store.upload(p)
    if not stats:
        log.info("archive: nothing new (NBM %s, NDFD %s already archived)",
                 ",".join(sorted(cycles["nbm"])) or "-", ",".join(sorted(cycles["ndfd"])) or "-")
    return stats
