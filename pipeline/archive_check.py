"""Forecast-archive integrity guard (dev21 stretch 2; docs/verification.md "Integrity check").

    python -m pipeline archive-check --dir <folder with nbm-/ndfd-/snotel-YYYYMM.csv.gz> [--state check_state.json]
    python -m pipeline archive-check --release verification --state check_state.json        (downloads into a temp folder; needs gh)

Checks, per monthly file:
  * the header is exactly the archive format (pipeline/archive.py FORECAST_COLS / OBS_COLS): archive.read_csv_gz silently drops unknown columns,
    so a format change in the middle of a month would quietly lose data;
  * every row has as many fields as the header, its key is unique, and it belongs to the file's month (archive.month_of);
  * against the previous check (--state): the header did not change and the row count did not shrink (rows are only ever added or replaced);
and across files: no month is missing between the first and the last month of each kind, and the current month exists once it is a day old.
Exit 1 when a problem is found (the problems are printed), 0 otherwise. Pure functions are tested in tests/test_archive_check.py.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .archive import FORECAST_COLS, FORECAST_KEY, OBS_COLS, OBS_KEY, month_of

NAME = re.compile(r"^(nbm|ndfd|snotel)-(\d{6})\.csv\.gz$")
FORMAT = {"nbm": (FORECAST_COLS, FORECAST_KEY), "ndfd": (FORECAST_COLS, FORECAST_KEY), "snotel": (OBS_COLS, OBS_KEY)}


def check_file(path: Path) -> dict:
    """one file -> {kind, month, header, rows, bad_rows, dup_keys, wrong_month, sha1, problems}"""
    m = NAME.match(path.name)
    kind, month = m.group(1), m.group(2)
    cols, key = FORMAT[kind]
    out = {"kind": kind, "month": month, "rows": 0, "bad_rows": 0, "dup_keys": 0, "wrong_month": 0, "problems": []}
    raw = path.read_bytes()
    out["sha1"] = hashlib.sha1(raw).hexdigest()[:12]
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        r = csv.reader(f)
        header = next(r, [])
        out["header"] = header
        idx = {c: i for i, c in enumerate(header)}
        seen = set()
        for row in r:
            out["rows"] += 1
            if len(row) != len(header):
                out["bad_rows"] += 1
                continue
            d = dict(zip(header, row))
            if all(c in idx for c in key):
                k = tuple(d[c] for c in key)
                if k in seen:
                    out["dup_keys"] += 1
                seen.add(k)
                try:
                    if month_of(kind, d) != month:
                        out["wrong_month"] += 1
                except (KeyError, IndexError):
                    out["wrong_month"] += 1
    if tuple(header) != tuple(cols):
        extra, missing = [c for c in header if c not in cols], [c for c in cols if c not in header]
        out["problems"].append(f"{path.name}: columns differ from the archive format (extra {extra or '-'}, missing {missing or '-'}"
                               + (", order differs" if not extra and not missing else "") + ")")
    for k, what in (("bad_rows", "rows with a wrong number of fields"), ("dup_keys", "duplicate keys"), ("wrong_month", "rows from another month")):
        if out[k]:
            out["problems"].append(f"{path.name}: {out[k]} {what}")
    return out


def _months_between(a: str, b: str) -> list[str]:
    y, m = int(a[:4]), int(a[4:])
    out = []
    while f"{y:04d}{m:02d}" <= b:
        out.append(f"{y:04d}{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def check(folder: Path, previous: dict | None = None, now: datetime | None = None) -> dict:
    """all files in `folder` -> {"files": {name: info}, "problems": [...], "months": {kind: [months]}}; `previous` = the "files" of an earlier check"""
    now = now or datetime.now(timezone.utc)
    files = {p.name: check_file(p) for p in sorted(Path(folder).iterdir()) if NAME.match(p.name)}
    problems = [x for f in files.values() for x in f["problems"]]
    for name, f in files.items():
        old = (previous or {}).get(name)
        if not old:
            continue
        if old.get("header") and old["header"] != f["header"]:
            problems.append(f"{name}: columns changed since the last check ({len(old['header'])} -> {len(f['header'])} columns)")
        if f["rows"] < int(old.get("rows") or 0):
            problems.append(f"{name}: row count shrank since the last check ({old['rows']} -> {f['rows']})")
    for name in sorted(set(previous or {}) - set(files)):
        problems.append(f"{name}: present at the last check, missing now")
    months: dict[str, list[str]] = {}
    for f in files.values():
        months.setdefault(f["kind"], []).append(f["month"])
    cur = now.strftime("%Y%m")
    for kind in ("nbm", "ndfd", "snotel"):
        ms = sorted(months.get(kind, []))
        if not ms:
            problems.append(f"{kind}: no monthly file at all")
            continue
        gaps = [m for m in _months_between(ms[0], ms[-1]) if m not in ms]
        if gaps:
            problems.append(f"{kind}: missing months {', '.join(gaps)}")
        if ms[-1] < cur and now.day > 1:
            problems.append(f"{kind}: no file for the current month {cur} (newest {ms[-1]})")
        months[kind] = ms
    return {"checked_at": now.strftime("%Y-%m-%dT%H:%MZ"), "files": files, "months": months, "problems": problems}


def run(folder: Path | None, state: Path | None, release: str | None = None, now: datetime | None = None) -> int:
    import tempfile
    previous = None
    if state and Path(state).exists():
        previous = (json.loads(Path(state).read_text(encoding="utf-8")) or {}).get("files")
    with tempfile.TemporaryDirectory() as tmp:
        if release:
            from .archive import ReleaseStore
            store = ReleaseStore(release)
            folder = Path(tmp)
            for name in sorted(n for n in store.list() if NAME.match(n)):
                store.download(name, folder)
        res = check(Path(folder), previous, now)
    if state:
        Path(state).write_text(json.dumps({"checked_at": res["checked_at"], "files": {k: {x: v[x] for x in ("header", "rows", "sha1")} for k, v in res["files"].items()}}, indent=1),
                               encoding="utf-8")
    for name, f in res["files"].items():
        print(f"{name}: {f['rows']:,} rows, {len(f['header'])} columns" + (f" PROBLEMS: {len(f['problems'])}" if f["problems"] else ""))
    for p in res["problems"]:
        print(f"PROBLEM: {p}")
    print("archive check:", "OK" if not res["problems"] else f"{len(res['problems'])} problem(s)")
    return 1 if res["problems"] else 0
