"""Per-cycle attempt log of the ECMWF job (dev22 Part 4): when each cycle was expected, when we last tried, what came of it and why.

Every run of `python -m pipeline ecmwf` (published, nothing new, not released yet, incomplete, unreachable, error ...) appends ONE entry to data_cache/ecmwf/attempts.json
(the file travels with the resume cache across runs) and writes a copy to <out>/ecmwf/attempts.json, which the existing ecmwf tar carries to the site whenever a run publishes
(update-site.yml unpacks it to build/models/ecmwf/attempts.json). Attempts that publish nothing upload no tar, so the status page shows the attempts up to the last published run.
A dedicated small asset published after EVERY attempt would need one more workflow step (proposed in the dev22 report, not applied).
The status page reads the per-cycle view (`cycles_view`). Pure functions, tested offline (tests/test_ecmwf_attempts.py).

Times: LAG_H is the MEASURED release lag of the ECMWF cycle on the AWS mirror (S3 Last-Modified of the last file of 17 cycles, Nov 12-20 2026: HRES +7.57 h, ENS +7.75 h).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

LAG_H = 7.75
KEEP = 48                                       # entries kept (a few days of attempts)
RESULTS = {"published": "published", "published-partial": "published with gaps", "published-already": "already published", "not-released": "not on the mirror yet",
           "incomplete": "too incomplete to publish", "unreachable": "mirror unreachable", "disabled": "switched off", "error": "failed"}


def parse_cycle(tag: str | None) -> datetime | None:
    """'2026112012' or '2026112012-ab12cd34' -> aware UTC datetime"""
    if not tag:
        return None
    try:
        return datetime.strptime(str(tag)[:10], "%Y%m%d%H").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def expected_ready(cycle: datetime, lag_h: float = LAG_H) -> datetime:
    return cycle + timedelta(hours=lag_h)


def classify(res: dict | None, *, error: str | None = None) -> tuple[str, str]:
    """(result key, reason) from the dict ecmwf.run() returns (or an exception text)"""
    if error:
        return "error", error[:200]
    res = res or {}
    sk = res.get("skipped")
    if sk == "published":
        return "published-already", "the newest complete cycle was already published; nothing newer on the mirror"
    if sk == "not-released":
        return "not-released", "no cycle with its last file (240 h) on the mirror yet; the next one is not released"
    if sk == "incomplete":
        miss = (res.get("fetch") or {}).get("steps_missing") or []
        return "incomplete", f"fewer than 90% of the steps, or a hole in the first 120 h ({len(miss)} steps missing); the finished steps stay cached for the next attempt"
    if sk == "unreachable":
        return "unreachable", "no ensemble index could be read from any mirror (throttled or down)"
    if sk == "disabled":
        return "disabled", "config ecmwf.enabled is false"
    if res.get("ok"):
        miss = res.get("steps_missing") or []
        return ("published-partial" if miss else "published"), (f"{len(miss)} steps missing, drawn as gaps" if miss else "complete")
    return "error", "the run did not finish"


def entry(now: datetime, cycle_tag: str | None, result: str, reason: str) -> dict:
    return {"at": now.strftime("%Y-%m-%dT%H:%MZ"), "cycle": (cycle_tag or "")[:10] or None, "result": result, "reason": reason}


def load(path: Path | None) -> list[dict]:
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        return [e for e in doc.get("attempts", []) if isinstance(e, dict) and e.get("at")]
    except (OSError, ValueError, TypeError, AttributeError):
        return []


def append(prev: list[dict], e: dict, keep: int = KEEP) -> list[dict]:
    return (list(prev) + [e])[-keep:]


def cycles_view(attempts: list[dict], now: datetime, *, newest_published: str | None = None, lag_h: float = LAG_H, n: int = 4) -> list[dict]:
    """per cycle (newest first): expected time, attempts, last attempt, result and reason. A cycle is every nominal 00Z/12Z cycle from the oldest one that matters up to the newest
    one that should be complete by `now`; the attempts that named it (or, for 'not on the mirror yet', the attempts made while it was due) are matched by cycle tag/time."""
    pub = parse_cycle(newest_published)
    cur = now.replace(minute=0, second=0, microsecond=0)
    cur = cur.replace(hour=0 if cur.hour < 12 else 12)
    while expected_ready(cur, lag_h) > now:                    # the newest cycle that should exist by now
        cur -= timedelta(hours=12)
    cycles = [cur - timedelta(hours=12 * k) for k in range(n)]
    out = []
    for c in cycles:
        due = expected_ready(c, lag_h)
        # attempts that explicitly named the cycle, plus attempts made after it was due and before the next cycle was due (they were looking for it)
        nxt = expected_ready(c + timedelta(hours=12), lag_h)
        mine = []
        for e in attempts:
            t = datetime.strptime(e["at"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
            tag = parse_cycle(e.get("cycle"))
            if (tag == c) or (tag is None and due <= t < nxt):
                mine.append((t, e))
        last = max(mine, key=lambda x: x[0])[1] if mine else None
        if pub is not None and pub >= c:
            state, why = "published", "we hold this cycle or a newer one"
        elif last is None:
            state, why = ("no attempt", "no run has looked for this cycle yet" if now >= due else "not due yet")
        else:
            state, why = last["result"], last["reason"]
        out.append({"cycle": c.strftime("%Y%m%d%H"), "expected": due.strftime("%Y-%m-%dT%H:%MZ"), "due": now >= due, "attempts": len(mine),
                    "last_attempt": last["at"] if last else None, "result": state, "result_text": RESULTS.get(state, state), "reason": why})
    return out


def write(path: Path | None, out_dir: Path | None, attempts: list[dict]) -> None:
    doc = json.dumps({"attempts": attempts, "lag_h": LAG_H}, indent=1)
    for p in (path, None if out_dir is None else Path(out_dir) / "ecmwf" / "attempts.json"):
        if p is None:
            continue
        Path(p).parent.mkdir(parents=True, exist_ok=True)
        Path(p).write_text(doc, encoding="utf-8")


def record(cache_root: Path | None, out_dir: Path | None, now: datetime, res: dict | None = None, error: str | None = None, keep: int = KEEP) -> dict:
    """classify one finished (or crashed) run, append it to the log next to the resume cache and write the copy under <out_dir>/ecmwf/"""
    result, reason = classify(res, error=error)
    e = entry(now, (res or {}).get("cycle"), result, reason)
    path = None if cache_root is None else Path(cache_root) / "attempts.json"
    write(path, out_dir, append(load(path), e, keep))
    return e
