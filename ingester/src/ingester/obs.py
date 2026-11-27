"""Observation and NWS-product sources (alerts, afd, avalanche, hazards, snotel, asos): one call per source, failing independently."""

from __future__ import annotations

import logging
import time

from .fetch import afd, alerts, asos, avalanche, hazards, snotel
from .fetch.common import utcnow

log = logging.getLogger("snow-wx.ingest")

OBS = {
    "alerts": alerts.run,
    "afd": afd.run,
    "avalanche": avalanche.run,
    "hazards": hazards.run,
    "snotel": snotel.run,
    "asos": asos.run,
}


def run_obs(cfg: dict, session, outdir, names: list[str] | None = None) -> dict:
    """Run the chosen observation sources into outdir (the stage's data/ folder). Returns {name: status}."""
    status = {}
    for name, func in OBS.items():
        if names and name not in names:
            continue
        if not cfg.get(name, {}).get("enabled", True):
            continue
        t0 = time.time()
        try:
            info = func(cfg, session, outdir)
            status[name] = {"ok": True, **(info or {})}
        except Exception as exc:  # noqa: BLE001 - one source failing does not stop the others
            log.exception("%s failed", name)
            # a source may attach details (SNOTEL: stale / unavailable, ages) to its exception
            status[name] = {"ok": False, "error": str(exc)[:300], **(getattr(exc, "status", None) or {})}
        status[name]["seconds"] = round(time.time() - t0, 1)
        status[name]["at"] = utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    return status
