"""SNOTEL observations from the NRCS Air and Water Database (AWDB) REST API.

Docs: https://wcc.sc.egov.usda.gov/awdbRestApi/swagger-ui/index.html
Data are public domain (USDA NRCS). No API key required.

Outputs
  snotel.geojson                 one point per station with latest values and
                                 24/72-hr changes
  snotel/<triplet>.json          hourly time series for the station chart
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Iterable

import pandas as pd

from .common import feature, feature_collection, utcnow, write_json

log = logging.getLogger("snow-wx.snotel")

AWDB = "https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1"

# Physically plausible ranges (US units: in, in, in, degF). Values outside are
# treated as missing. SNOTEL ultrasonic depth sensors in particular can spike.
QC_LIMITS = {
    "WTEQ": (0.0, 250.0),
    "SNWD": (0.0, 500.0),
    "PREC": (0.0, 400.0),
    "TOBS": (-60.0, 120.0),
}


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

def normalize_station(row: dict) -> dict | None:
    trip = row.get("stationTriplet")
    if not trip or not trip.upper().endswith(":SNTL"):
        return None
    lat, lon = row.get("latitude"), row.get("longitude")
    if lat is None or lon is None:
        return None
    parts = trip.split(":")
    return {
        "triplet": trip,
        "id": parts[0],
        "state": row.get("stateCode") or (parts[1] if len(parts) > 1 else None),
        "name": row.get("name") or trip,
        "lat": float(lat),
        "lon": float(lon),
        "elev_ft": row.get("elevation"),
    }


def fetch_stations(session, states: Iterable[str]) -> list[dict]:
    """Active SNOTEL stations for the given states (one request per state)."""
    stations: list[dict] = []
    for st in states:
        params = {
            "stationTriplets": f"*:{st}:SNTL",
            "activeOnly": "true",
            "returnStationElements": "false",
            "returnForecastPointMetadata": "false",
            "returnReservoirMetadata": "false",
        }
        try:
            r = session.get(f"{AWDB}/stations", params=params, timeout=session.request_timeout)
            r.raise_for_status()
            rows = r.json()
        except Exception as exc:  # keep going with other states
            log.warning("SNOTEL station list failed for %s: %s", st, exc)
            continue
        for row in rows:
            s = normalize_station(row)
            if s:
                stations.append(s)
    log.info("SNOTEL: %d active stations", len(stations))
    return stations


def parse_data(payload: list) -> dict[str, dict[str, list[tuple]]]:
    """AWDB /data response -> {triplet: {element: [(date_str, value), ...]}}.

    Response shape: [{"stationTriplet": ..., "data": [{"stationElement":
    {"elementCode": "WTEQ", "ordinal": 1, ...}, "values": [{"date": ...,
    "value": ..., "median": ...}]}]}]
    """
    out: dict[str, dict[str, list[tuple]]] = {}
    for station in payload or []:
        trip = station.get("stationTriplet")
        if not trip:
            continue
        elements = out.setdefault(trip, {})
        for block in station.get("data") or []:
            meta = block.get("stationElement") or {}
            code = meta.get("elementCode")
            if not code or code in elements:  # keep first (ordinal 1) sensor
                continue
            elements[code] = [
                (v.get("date"), v.get("value"), v.get("median"))
                for v in block.get("values") or []
            ]
    return out


def _awdb_data(session, triplets, elements, duration, begin, end, tendency="NONE"):
    params = {
        "stationTriplets": ",".join(triplets),
        "elements": ",".join(elements),
        "duration": duration,
        "beginDate": begin,
        "endDate": end,
        "periodRef": "END",
        "centralTendencyType": tendency,
        "returnFlags": "false",
        "returnOriginalValues": "false",
        "returnSuspectData": "false",
    }
    r = session.get(f"{AWDB}/data", params=params, timeout=session.request_timeout)
    r.raise_for_status()
    return parse_data(r.json())


# --------------------------------------------------------------------------
# Processing (pure functions -> easy to unit test)
# --------------------------------------------------------------------------

def to_series(pairs: list[tuple], element: str) -> pd.Series:
    if not pairs:
        return pd.Series(dtype="float64")
    idx = pd.to_datetime([p[0] for p in pairs], errors="coerce")
    s = pd.Series([p[1] for p in pairs], index=idx, dtype="float64")
    s = s[~s.index.isna()].sort_index()
    s = s[~s.index.duplicated(keep="last")]
    lo, hi = QC_LIMITS.get(element, (float("-inf"), float("inf")))
    return s.where((s >= lo) & (s <= hi))


def change_over(s: pd.Series, hours: int, smooth_hours: int = 1) -> float | None:
    """Latest value minus the value `hours` earlier (None if not enough data).

    smooth_hours > 1 applies a rolling median first, which tames the noise
    typical of ultrasonic snow-depth sensors.
    """
    s = s.dropna()
    if s.empty:
        return None
    if smooth_hours > 1:
        s = s.rolling(f"{smooth_hours}h", min_periods=1).median()
    t_end = s.index[-1]
    target = t_end - pd.Timedelta(hours=hours)
    earlier = s.index[s.index <= target]
    if len(earlier) == 0 or (target - earlier[-1]) > pd.Timedelta(hours=2):
        return None
    return float(s.iloc[-1] - s.loc[earlier[-1]])


def latest(s: pd.Series) -> float | None:
    s = s.dropna()
    return None if s.empty else float(s.iloc[-1])


def summarize(series: dict[str, list[tuple]]) -> dict:
    """Latest values and changes for one station's hourly data."""
    sw = to_series(series.get("WTEQ", []), "WTEQ")
    sd = to_series(series.get("SNWD", []), "SNWD")
    pr = to_series(series.get("PREC", []), "PREC")
    ta = to_series(series.get("TOBS", []), "TOBS")

    valid_times = [x.dropna().index.max() for x in (sw, sd, ta) if not x.dropna().empty]
    obs_time = max(valid_times) if valid_times else None

    precip_24 = change_over(pr, 24)
    if precip_24 is not None and precip_24 < 0:  # water-year reset on Oct 1
        precip_24 = None

    last24 = ta.dropna()
    if obs_time is not None and not last24.empty:
        last24 = last24[last24.index > obs_time - pd.Timedelta(hours=24)]

    return {
        "obs_time": obs_time.strftime("%Y-%m-%d %H:%M") if obs_time is not None else None,
        "swe_in": latest(sw),
        "swe_24h": change_over(sw, 24),
        "swe_72h": change_over(sw, 72),
        "depth_in": latest(sd),
        "depth_24h": change_over(sd, 24, smooth_hours=3),
        "depth_72h": change_over(sd, 72, smooth_hours=3),
        "temp_f": latest(ta),
        "tmax_24h": float(last24.max()) if not last24.empty else None,
        "tmin_24h": float(last24.min()) if not last24.empty else None,
        "precip_24h": precip_24,
    }


def timeseries(series: dict[str, list[tuple]], elements: Iterable[str]) -> dict:
    """Aligned hourly arrays for charting."""
    frame = pd.DataFrame({el: to_series(series.get(el, []), el) for el in elements})
    frame = frame.sort_index()
    out = {"times": [t.strftime("%Y-%m-%d %H:%M") for t in frame.index]}
    for el in elements:
        out[el] = [None if pd.isna(v) else round(float(v), 1) for v in frame[el]]
    return out


def pct_of_median(daily: dict[str, list[tuple]]) -> float | None:
    """Percent of median SWE from the most recent daily value with a median."""
    for date, value, median in reversed(daily.get("WTEQ", [])):
        if value is not None and median not in (None, 0):
            return 100.0 * float(value) / float(median)
    return None


# --------------------------------------------------------------------------
# Main entry
# --------------------------------------------------------------------------

def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


def run(cfg: dict, session, outdir: Path) -> dict:
    scfg = cfg["snotel"]
    elements = scfg["elements"]
    stations = fetch_stations(session, cfg["region"]["states"])
    if not stations:
        raise RuntimeError("no SNOTEL stations returned")

    # AWDB dates are station-local standard time. Asking a little past "now"
    # in Pacific Standard Time (UTC-8) covers every western station.
    now_pst = utcnow() - timedelta(hours=8)
    end = (now_pst + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    begin = (now_pst - timedelta(hours=scfg["hours"] + 2)).strftime("%Y-%m-%d %H:%M")
    d_end = now_pst.strftime("%Y-%m-%d")
    d_begin = (now_pst - timedelta(days=3)).strftime("%Y-%m-%d")

    by_trip = {s["triplet"]: s for s in stations}
    features, failed_chunks = [], 0
    for chunk in _chunks(list(by_trip), scfg["chunk_size"]):
        try:
            hourly = _awdb_data(session, chunk, elements, "HOURLY", begin, end)
        except Exception as exc:
            failed_chunks += 1
            log.warning("SNOTEL hourly chunk failed (%s...): %s", chunk[0], exc)
            continue
        try:
            daily = _awdb_data(session, chunk, ["WTEQ"], "DAILY", d_begin, d_end, "MEDIAN")
        except Exception as exc:
            log.info("SNOTEL median lookup failed (%s...): %s", chunk[0], exc)
            daily = {}

        for trip in chunk:
            st = by_trip[trip]
            series = hourly.get(trip, {})
            summary = summarize(series)
            if summary["obs_time"] is None:
                continue  # no usable data in the window
            summary["pct_median"] = pct_of_median(daily.get(trip, {}))
            fname = trip.replace(":", "_")
            write_json(
                outdir / "snotel" / f"{fname}.json",
                {"triplet": trip, "name": st["name"], "elev_ft": st["elev_ft"],
                 **timeseries(series, elements)},
            )
            props = {k: st[k] for k in ("triplet", "id", "state", "name", "elev_ft")}
            props["file"] = f"snotel/{fname}.json"
            props.update(summary)
            features.append(feature(st["lon"], st["lat"], props))

    write_json(outdir / "snotel.geojson", feature_collection(features))
    log.info("SNOTEL: wrote %d stations (%d failed chunks)", len(features), failed_chunks)
    if not features:
        raise RuntimeError("SNOTEL returned no usable data")
    return {"count": len(features), "failed_chunks": failed_chunks}
