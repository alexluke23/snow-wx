"""Restore the previous good SNOTEL copy from the live site (CI, before every build).

A fresh CI runner has no previous output, so without this an AWDB outage would show "unavailable" immediately.
This downloads the live site's meta.json, snotel.geojson and the station files whose latest observation is still
younger than snotel.max_age_hours into the build folder; snotel.run then keeps them (flagged stale, ORIGINAL
timestamps) only if AWDB is down. When AWDB is up the next successful run replaces everything.

Origin = SITE_ORIGIN (env) or config site.origin: the live URL changes at the W1 domain cutover.
Never raises: a failed restore only means "no previous copy" (docs/specs/data-pipeline.md 5.2b).
"""

from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .common import utcnow
from .snotel import split_by_age

log = logging.getLogger("snow-wx.restore")


def site_origin(cfg: dict) -> str:
    """Live site origin without a trailing slash: SITE_ORIGIN env > config site.origin."""
    return (os.environ.get("SITE_ORIGIN") or (cfg.get("site") or {}).get("origin") or "").rstrip("/")


def _get_json(session, url: str, timeout: float = 30):
    r = session.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def restore_previous(cfg: dict, session, outdir: Path, origin: str | None = None, workers: int = 12) -> dict:
    """Download meta.json, snotel.geojson and the young station files from the live site into `outdir`.
    Existing local files are never overwritten (a developer's own previous copy wins)."""
    origin = (origin or site_origin(cfg)).rstrip("/")
    out = {"origin": origin, "meta": False, "stations": 0, "skipped": None}
    if not origin:
        out["skipped"] = "no site origin configured"
        return out
    base = f"{origin}/data"
    try:
        if (outdir / "snotel.geojson").exists():
            out["skipped"] = "a local copy exists"
            return out
        try:
            meta = _get_json(session, f"{base}/meta.json")
            if isinstance(meta, dict) and isinstance(meta.get("sources"), dict) and not (outdir / "meta.json").exists():
                (outdir).mkdir(parents=True, exist_ok=True)
                (outdir / "meta.json").write_text(json.dumps(meta, separators=(",", ":")), encoding="utf-8")
                out["meta"] = True
        except Exception as exc:                    # history is optional
            log.info("restore: previous meta.json not available: %s", exc)
        gj = _get_json(session, f"{base}/snotel.geojson", timeout=60)
        feats = [f for f in gj.get("features", []) if (f.get("properties") or {}).get("triplet")]
        usable, _ = split_by_age(feats, utcnow(), float((cfg.get("snotel") or {}).get("max_age_hours", 48)))
        if not usable:
            out["skipped"] = "live copy has no station younger than the max age"
            return out

        def fetch(f):
            rel = f["properties"].get("file") or f"snotel/{f['properties']['triplet'].replace(':', '_')}.json"
            try:
                doc = _get_json(session, f"{base}/{rel}")
                if not isinstance(doc, dict) or "times" not in doc:
                    return None
                dest = outdir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(json.dumps(doc, separators=(",", ":")), encoding="utf-8")
                return f
            except Exception:
                return None

        with ThreadPoolExecutor(max_workers=workers) as ex:
            got = [f for f in ex.map(fetch, usable) if f is not None]
        if got:                                        # only stations whose chart file arrived
            gj["features"] = got
            (outdir / "snotel.geojson").write_text(json.dumps(gj, separators=(",", ":")), encoding="utf-8")
        out["stations"] = len(got)
        log.info("restore: %d of %d young SNOTEL stations restored from %s", len(got), len(usable), origin)
    except Exception as exc:
        out["skipped"] = f"failed: {str(exc)[:160]}"
        log.warning("restore: no previous SNOTEL copy (%s)", exc)
    return out
