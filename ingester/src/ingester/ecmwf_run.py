"""ECMWF run with its attempt log: every attempt is logged in data_cache/ecmwf/attempts.json (the copy for the store is
written only when a run publishes). A failure is logged, then raised."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .fetch import ecmwf
from .fetch import ecmwf_attempts as EA
from .fetch.common import REPO_ROOT


def run_ecmwf(cfg: dict, session, out: Path, *, cycle: datetime | None = None, force: bool = False,
              published: str | None = None, github_output: str | None = None) -> dict:
    croot, started = REPO_ROOT / "data_cache" / "ecmwf", datetime.now(timezone.utc)
    try:
        res = ecmwf.run(cfg, session, out, cycle=cycle, force=force, published=published, github_output=github_output)
    except Exception as exc:  # noqa: BLE001 - the attempt is logged, then the failure goes on
        EA.record(croot, None, started, error=f"{type(exc).__name__}: {exc}")
        raise
    EA.record(croot, out if res.get("ok") and not res.get("skipped") else None, started, res)
    return res
