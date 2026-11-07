"""Latest ASOS/AWOS observations from the Iowa Environmental Mesonet (IEM).

IEM services: https://mesonet.agron.iastate.edu/api/
IEM states its services may be used for any lawful purpose, including
commercial. Underlying ASOS data are public (NWS/FAA).

Output
  asos.geojson    one point per station with the latest observation
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .common import feature, feature_collection, utcnow, write_json

log = logging.getLogger("snow-wx.asos")

IEM = "https://mesonet.agron.iastate.edu"

# Fields copied from the IEM "currents" rows when present.
FIELDS = {
    "tmpf": "temp_f",
    "dwpf": "dewp_f",
    "relh": "rh",
    "sknt": "wind_kt",
    "drct": "wind_dir",
    "gust": "gust_kt",
    "vsby": "vis_mi",
    "max_tmpf": "tmax_f",
    "min_tmpf": "tmin_f",
    "pday": "precip_today_in",
    "snow": "snow_today_in",
    "snowd": "snow_depth_in",
    "raw": "metar",
}


def fetch_network_coords(session, network: str) -> dict[str, dict]:
    """Station id -> {lon, lat, elev_m} from the IEM network GeoJSON."""
    r = session.get(f"{IEM}/geojson/network/{network}.geojson", timeout=session.request_timeout)
    r.raise_for_status()
    out = {}
    for f in r.json().get("features", []):
        p = f.get("properties") or {}
        sid = p.get("sid") or f.get("id")
        coords = (f.get("geometry") or {}).get("coordinates")
        if sid and coords:
            out[str(sid)] = {"lon": coords[0], "lat": coords[1], "elev_m": p.get("elevation")}
    return out


def fetch_currents(session, network: str) -> list[dict]:
    r = session.get(f"{IEM}/api/1/currents.json", params={"network": network},
                    timeout=session.request_timeout)
    r.raise_for_status()
    return r.json().get("data", [])


def normalize_row(row: dict, coords: dict, now, stale_minutes: int) -> dict | None:
    sid = row.get("station")
    if not sid:
        return None
    c = coords.get(str(sid), {})
    lat = row.get("lat") if row.get("lat") is not None else c.get("lat")
    lon = row.get("lon") if row.get("lon") is not None else c.get("lon")
    if lat is None or lon is None:
        return None
    valid = pd.to_datetime(row.get("utc_valid"), utc=True, errors="coerce")
    if pd.isna(valid):
        return None
    age_min = (now - valid).total_seconds() / 60.0
    props = {
        "id": sid,
        "name": row.get("name") or sid,
        "network": row.get("network"),
        "elev_m": c.get("elev_m"),
        "valid_utc": valid.strftime("%Y-%m-%dT%H:%MZ"),
        "stale": age_min > stale_minutes,
    }
    for src, dst in FIELDS.items():
        if src in row and row[src] is not None:
            props[dst] = row[src]
    return feature(float(lon), float(lat), props)


def run(cfg: dict, session, outdir: Path) -> dict:
    stale = cfg["asos"].get("stale_minutes", 180)
    now = pd.Timestamp(utcnow())
    features, failed = [], []
    for st in cfg["region"]["states"]:
        network = f"{st}_ASOS"
        try:
            rows = fetch_currents(session, network)
        except Exception as exc:
            log.warning("ASOS currents failed for %s: %s", network, exc)
            failed.append(network)
            continue
        coords = {}
        if any(r.get("lat") is None for r in rows):
            try:
                coords = fetch_network_coords(session, network)
            except Exception as exc:
                log.warning("ASOS station coords failed for %s: %s", network, exc)
        for row in rows:
            f = normalize_row(row, coords, now, stale)
            if f:
                features.append(f)
    write_json(outdir / "asos.geojson", feature_collection(features))
    log.info("ASOS: wrote %d stations (%d networks failed)", len(features), len(failed))
    if not features:
        raise RuntimeError("ASOS returned no usable data")
    return {"count": len(features), "failed_networks": failed}
