"""SNOTEL observations from the NRCS Air and Water Database (AWDB) REST API.

Docs: https://wcc.sc.egov.usda.gov/awdbRestApi/swagger-ui/index.html
Data are public domain (USDA NRCS). No API key required.

Outputs
  snotel.geojson                 one point per station with latest values and
                                 24/72-hr changes
  snotel/<triplet>.json          hourly time series for the station chart
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
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

class SnotelUnavailable(RuntimeError):
    """The AWDB service is down or returned nothing usable. `status` is merged into the source's
    meta.json entry (stale / unavailable, ages, dates) by run_obs."""

    def __init__(self, message: str, status: dict | None = None):
        super().__init__(message)
        self.status = status or {}


_clock = time.monotonic          # tests replace this to simulate a slow service


class Deadline:
    """Hard overall time budget for one source run (a down AWDB used to cost ~5 min per hourly run)."""

    def __init__(self, seconds: float):
        self.end = _clock() + seconds

    def left(self) -> float:
        return self.end - _clock()

    def check(self) -> None:
        if self.left() <= 0:
            raise SnotelUnavailable("SNOTEL fetch hit its time limit")


def _get(session, url: str, params: dict, deadline: Deadline | None = None, timeout: float | None = None):
    """One request through the session's fast (low-retry) variant, never longer than the deadline."""
    s = getattr(session, "fast", session)
    t = timeout or session.request_timeout
    if deadline is not None:
        deadline.check()
        t = max(1.0, min(t, deadline.left()))
    r = s.get(url, params=params, timeout=t)
    r.raise_for_status()
    return r


def probe(session, timeout: float = 10.0) -> None:
    """Cheap health check (one station, short timeout): raises SnotelUnavailable when AWDB is down, so a
    dead service costs seconds, not minutes. The next hourly run simply tries again."""
    try:
        r = _get(session, f"{AWDB}/stations", {"stationTriplets": "1308:UT:SNTL", "returnStationElements": "false"},
                 timeout=timeout)
        rows = r.json()
    except SnotelUnavailable:
        raise
    except Exception as exc:
        raise SnotelUnavailable(f"AWDB health probe failed: {str(exc)[:160]}") from exc
    if not isinstance(rows, list):
        raise SnotelUnavailable("AWDB health probe returned an unexpected payload")


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
        "utc_offset_h": utc_offset(row.get("dataTimeZone"), row.get("stateCode") or (parts[1] if len(parts) > 1 else None),
                                   float(lon)),
    }


PACIFIC_STATES = {"WA", "OR", "CA", "NV"}


def utc_offset(data_tz, state: str | None, lon: float) -> float:
    """Hours from UTC of the station's (standard-time) data clock: AWDB's dataTimeZone,
    else by state (Pacific for WA/OR/CA/NV and northern Idaho west of 115.5 W)."""
    try:
        if data_tz is not None and -12 <= float(data_tz) <= 0:
            return float(data_tz)
    except (TypeError, ValueError):
        pass
    if state in PACIFIC_STATES or (state == "ID" and lon < -115.5):
        return -8.0
    return -7.0


def fetch_stations(session, states: Iterable[str], deadline: Deadline | None = None) -> list[dict]:
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
            rows = _get(session, f"{AWDB}/stations", params, deadline).json()
        except SnotelUnavailable:
            raise
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


def _awdb_data(session, triplets, elements, duration, begin, end, tendency="NONE", deadline=None):
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
    return parse_data(_get(session, f"{AWDB}/data", params, deadline).json())


# --------------------------------------------------------------------------
# Processing (pure functions -> easy to unit test)
# --------------------------------------------------------------------------

def to_series(pairs: list[tuple], element: str) -> pd.Series:
    if not pairs:
        # Keep a DatetimeIndex so frames built from several elements stay time-indexed.
        return pd.Series(dtype="float64", index=pd.DatetimeIndex([]))
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


def rolling_median(s: pd.Series, hours: int = 3) -> pd.Series:
    """Centered time-based rolling median (tames ultrasonic depth-sensor noise).

    Missing hours stay missing, so gaps are not bridged on the chart.
    """
    if s.empty or not isinstance(s.index, pd.DatetimeIndex):
        return s
    med = s.rolling(f"{hours}h", center=True, min_periods=1).median()
    return med.where(s.notna())


def timeseries(series: dict[str, list[tuple]], elements: Iterable[str],
               smooth_hours: int = 3) -> dict:
    """Aligned hourly arrays for charting, plus a smoothed snow depth (SNWD_med3)."""
    frame = pd.DataFrame({el: to_series(series.get(el, []), el) for el in elements})
    frame = frame.sort_index()
    if "SNWD" in frame:
        frame[f"SNWD_med{smooth_hours}"] = rolling_median(frame["SNWD"], smooth_hours)
    out = {"times": [t.strftime("%Y-%m-%d %H:%M") for t in frame.index]}
    for col in frame.columns:
        out[col] = [None if pd.isna(v) else round(float(v), 1) for v in frame[col]]
    return out


def median_swe(daily: dict[str, list[tuple]]) -> tuple[float | None, float | None]:
    """(latest SWE, its median) from the most recent daily value with a median."""
    for date, value, median in reversed(daily.get("WTEQ", [])):
        if value is not None and median is not None:
            return float(value), float(median)
    return None, None


def pct_of_median(daily: dict[str, list[tuple]], min_median: float = 0.0) -> float | None:
    """Percent of median SWE, or None when the median is below `min_median`.

    Early in the season a tiny median makes the ratio meaningless (0.7" vs a
    0.175" median reads as 400%), so it is suppressed below the threshold.
    """
    value, median = median_swe(daily)
    if value is None or not median or median < min_median:
        return None
    return 100.0 * value / median


# --------------------------------------------------------------------------
# Main entry
# --------------------------------------------------------------------------

def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i : i + n]


# --------------------------------------------------------------------------
# Last good copy (stale handling)
# --------------------------------------------------------------------------

def feature_obs_utc(f: dict) -> datetime | None:
    """UTC time of a station feature's latest observation (obs_time is station-local standard time)."""
    props = f.get("properties") or {}
    ot = props.get("obs_time")
    if not ot:
        return None
    try:
        local = datetime.strptime(ot, "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    lon = (f.get("geometry") or {}).get("coordinates", [-111.0])[0]
    off = utc_offset(None, props.get("state"), float(lon))
    return (local - timedelta(hours=off)).replace(tzinfo=timezone.utc)


def load_previous(outdir: Path) -> list[dict]:
    """Station features of the last snotel.geojson in outdir (the previous good copy), or []."""
    try:
        gj = json.loads((outdir / "snotel.geojson").read_text(encoding="utf-8"))
        return [f for f in gj.get("features", []) if f.get("properties", {}).get("triplet")]
    except (OSError, ValueError):
        return []


def split_by_age(features: list[dict], now: datetime, max_age_h: float) -> tuple[list[dict], list[dict]]:
    """(usable, too old) previous features. A feature without a parsable observation time is too old."""
    ok, old = [], []
    for f in features:
        t = feature_obs_utc(f)
        (ok if t is not None and (now - t).total_seconds() / 3600 <= max_age_h else old).append(f)
    return ok, old


def _station_file(outdir: Path, props: dict) -> Path:
    return outdir / (props.get("file") or f"snotel/{props['triplet'].replace(':', '_')}.json")


def _iso(t: datetime | None) -> str | None:
    return t.strftime("%Y-%m-%dT%H:%MZ") if t else None


def _stale(f: dict, now: datetime) -> dict:
    """A previous feature kept as is (ORIGINAL timestamps), flagged stale with its age in hours."""
    age = round((now - feature_obs_utc(f)).total_seconds() / 3600, 1)
    props = {**f["properties"], "stale": True, "age_h": age}
    # a change over the last 24 h / 72 h says nothing once the data are older than that window: hide it
    # (owner Nov 17); the obs_time and every other timestamp stay exactly as originally observed
    for window, keys in ((24, ("depth_24h", "swe_24h", "precip_24h", "tmax_24h", "tmin_24h")), (72, ("depth_72h", "swe_72h"))):
        if age > window:
            for k in keys:
                if k in props:
                    props[k] = None
    return {**f, "properties": props}


def run(cfg: dict, session, outdir: Path) -> dict:
    """Fetch SNOTEL, or fail fast and fall back to the last good copy (never older than max_age_hours).

    Fresh data replaces everything, so recovery needs no manual step. When AWDB is down, stations whose
    latest observation is younger than max_age_hours stay as they were, with their ORIGINAL timestamps and
    `stale`/`age_h` flags, and the status says stale; older ones are removed, and when nothing is left the
    source reports "unavailable" with the last observation date, so an old value is never shown as current.
    """
    scfg = cfg["snotel"]
    max_age = float(scfg.get("max_age_hours", 48))
    now = utcnow()
    previous = load_previous(outdir)
    usable_prev, _ = split_by_age(previous, now, max_age)
    try:
        return _fetch_all(cfg, session, outdir, scfg, Deadline(float(scfg.get("max_seconds", 600))), usable_prev, now)
    except SnotelUnavailable as exc:
        raise _fall_back(exc, outdir, previous, usable_prev, now, max_age) from exc
    except Exception as exc:                      # any other failure of the fetch is treated the same way
        raise _fall_back(SnotelUnavailable(str(exc)[:300]), outdir, previous, usable_prev, now, max_age) from exc


def _fall_back(exc: SnotelUnavailable, outdir: Path, previous: list[dict], usable: list[dict], now: datetime,
               max_age: float) -> SnotelUnavailable:
    """Keep the usable previous copy (flagged stale), drop the rest; fill exc.status for meta.json."""
    newest = max((t for t in (feature_obs_utc(f) for f in previous) if t), default=None)
    keep = {f["properties"]["triplet"] for f in usable}
    dropped = 0
    for f in previous:
        if f["properties"]["triplet"] not in keep:
            try:
                _station_file(outdir, f["properties"]).unlink()
            except OSError:
                pass
            dropped += 1
    if usable:
        feats = [_stale(f, now) for f in usable]
        through = max(feature_obs_utc(f) for f in usable)
        age_h = round((now - through).total_seconds() / 3600, 1)
        write_json(outdir / "snotel.geojson", feature_collection(feats, stale=True, observed_through=_iso(through),
                                                                 checked_at=_iso(now)))
        log.warning("SNOTEL down (%s): keeping %d stations from the last good copy (%.1f h old, max %.0f h), "
                    "dropped %d older", exc, len(feats), age_h, max_age, dropped)
        exc.status = {"stale": True, "age_h": age_h, "observed_through": _iso(through), "count": len(feats),
                      "dropped_too_old": dropped}
    else:
        try:
            (outdir / "snotel.geojson").unlink()
        except OSError:
            pass
        log.warning("SNOTEL down (%s): no usable previous copy (max age %.0f h): unavailable", exc, max_age)
        exc.status = {"unavailable": True, "last_observed": _iso(newest), "dropped_too_old": dropped}
    return exc


def _fetch_all(cfg: dict, session, outdir: Path, scfg: dict, deadline: Deadline, usable_prev: list[dict],
               now: datetime) -> dict:
    elements = scfg["elements"]
    min_median = float(scfg.get("min_median_swe_in", 1.0))
    probe(session, float(scfg.get("probe_timeout_s", 10)))
    stations = fetch_stations(session, cfg["region"]["states"], deadline)
    if not stations:
        raise SnotelUnavailable("no SNOTEL stations returned")

    # AWDB dates are station-local standard time. Asking a little past "now"
    # in Pacific Standard Time (UTC-8) covers every western station.
    now_pst = utcnow() - timedelta(hours=8)
    end = (now_pst + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    begin = (now_pst - timedelta(hours=scfg["hours"] + 2)).strftime("%Y-%m-%d %H:%M")
    d_end = now_pst.strftime("%Y-%m-%d")
    d_begin = (now_pst - timedelta(days=3)).strftime("%Y-%m-%d")

    by_trip = {s["triplet"]: s for s in stations}
    features, failed_chunks, failed_stations, in_a_row = [], 0, 0, 0
    max_in_a_row = int(scfg.get("max_consecutive_chunk_failures", 3))
    for chunk in _chunks(list(by_trip), scfg["chunk_size"]):
        try:
            deadline.check()
            hourly = _awdb_data(session, chunk, elements, "HOURLY", begin, end, deadline=deadline)
            in_a_row = 0
        except SnotelUnavailable as exc:        # out of time: keep what we have, else give up
            log.warning("SNOTEL stopped early: %s", exc)
            break
        except Exception as exc:
            failed_chunks += 1
            in_a_row += 1
            log.warning("SNOTEL hourly chunk failed (%s...): %s", chunk[0], exc)
            if in_a_row >= max_in_a_row:        # the service died mid-run: stop wasting the run
                log.warning("SNOTEL: %d chunks in a row failed, stopping", in_a_row)
                break
            continue
        try:
            daily = _awdb_data(session, chunk, ["WTEQ"], "DAILY", d_begin, d_end, "MEDIAN", deadline=deadline)
        except Exception as exc:                # includes the time limit: medians are optional
            log.info("SNOTEL median lookup failed (%s...): %s", chunk[0], exc)
            daily = {}

        for trip in chunk:
            st = by_trip[trip]
            series = hourly.get(trip, {})
            try:
                summary = summarize(series)
                if summary["obs_time"] is None:
                    continue  # no usable data in the window
                st_daily = daily.get(trip, {})
                summary["median_swe_in"] = median_swe(st_daily)[1]
                summary["pct_median"] = pct_of_median(st_daily, min_median)
                ts = timeseries(series, elements)
            except Exception as exc:  # one odd station must not sink the source
                failed_stations += 1
                log.warning("SNOTEL %s skipped: %s", trip, exc)
                continue
            fname = trip.replace(":", "_")
            write_json(
                outdir / "snotel" / f"{fname}.json",
                {"triplet": trip, "name": st["name"], "elev_ft": st["elev_ft"],
                 "utc_offset_h": st.get("utc_offset_h"), **ts},   # times are local standard time
            )
            props = {k: st[k] for k in ("triplet", "id", "state", "name", "elev_ft")}
            props["file"] = f"snotel/{fname}.json"
            props.update(summary)
            features.append(feature(st["lon"], st["lat"], props))
    return _finish(outdir, features, usable_prev, now, failed_chunks, failed_stations)


def _finish(outdir: Path, features: list[dict], usable_prev: list[dict], now: datetime, failed_chunks: int,
            failed_stations: int) -> dict:
    if not features:
        raise SnotelUnavailable("SNOTEL returned no usable data")
    # stations this run did not refresh keep their previous copy (original timestamps, flagged stale)
    fresh = {f["properties"]["triplet"] for f in features}
    carried = [_stale(f, now) for f in usable_prev if f["properties"]["triplet"] not in fresh]
    write_json(outdir / "snotel.geojson", feature_collection(features + carried, stale=False, checked_at=_iso(now)))
    log.info("SNOTEL: wrote %d stations (%d carried from the last good copy, %d failed chunks, %d stations skipped)",
             len(features), len(carried), failed_chunks, failed_stations)
    out = {"count": len(features), "failed_chunks": failed_chunks, "skipped_stations": failed_stations}
    if carried:
        out["carried_stale"] = len(carried)
    return out
