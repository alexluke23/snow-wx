"""NDFD sampling helpers (offline)."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np

from pipeline import ndfd as N


def test_steps_and_windows():
    assert N.parse_step("330m") == 330 and N.parse_step("6") == 360
    assert N.window_minutes("330m-690m") == 360 and N.window_minutes("0-6") == 360
    assert N.window_minutes("30m") == 0


def test_convert_units():
    assert N.convert("temp", np.array([273.15]))[0] == 32.0
    assert round(float(N.convert("wspd", np.array([10.0]))[0]), 2) == 22.37
    assert round(float(N.convert("snow", np.array([0.0254]))[0]), 3) == 1.0
    assert round(float(N.convert("qpf", np.array([25.4]))[0]), 3) == 1.0


def _msgs(t0, hours, value, minutes=0):
    return [{"end": t0 + timedelta(hours=h), "minutes": minutes, "ref": t0, "values": np.array([value])} for h in hours]


def test_point_doc_periods_totals_and_rain_flag():
    t0 = datetime(2026, 11, 8, 0, tzinfo=timezone.utc)
    data = {"temp": _msgs(t0, range(1, 73), 30.0), "wspd": _msgs(t0, range(1, 73), 10.0),
            "wgust": _msgs(t0, range(1, 73), 20.0), "sky": _msgs(t0, range(1, 73), 90.0),
            "snowlevel": _msgs(t0, range(1, 73), 4000.0),
            "qpf": _msgs(t0, range(6, 73, 6), 0.2, 360), "snow": _msgs(t0, range(6, 73, 6), 2.0, 360),
            "pop12": _msgs(t0, range(12, 73, 12), 80.0, 720)}
    times, fc = N.point_doc(data, 0, elev_ft=9000, tz=ZoneInfo("America/Denver"))
    assert len(times) == 72 and fc["series"]["t_f"][0] == 30.0 and fc["series"]["pop"][0] == 0.8
    p0 = fc["periods"][0]
    # raw NDFD: snow exactly as forecast, no scaling by snow level vs elevation
    assert p0["snow_in"] == 4.0 and p0["qpf_in"] == 0.4 and p0["type"] == "snow" and p0["snow_hi"] is None
    assert p0["p_snow"] is None
    assert fc["totals"]["24h"]["snow_in"] == 8.0 and fc["totals"]["72h"]["snow_in"] == 24.0
    _, low = N.point_doc(data, 0, elev_ft=2000, tz=ZoneInfo("America/Denver"))
    assert low["periods"][0]["snow_in"] == 4.0                     # same cell, same NWS numbers
    assert N.ndfd_type(0.4, 0.0) == "mostly rain" and N.ndfd_type(0.4, 1.0) == "mixed"
    assert N.ndfd_type(0.005, 0.0) is None
