"""A fake HTTP session that returns canned responses shaped like the real
APIs, so tests (and offline previews) run without network access."""

from __future__ import annotations

import math
from datetime import timedelta
from urllib.parse import urlparse

from pipeline.common import utcnow


class FakeResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


STATIONS = {
    "CO": [("663:CO:SNTL", "Niwot", 40.03581, -105.5452, 9940),
           ("335:CO:SNTL", "Berthoud Summit", 39.80, -105.78, 11300)],
    "UT": [("766:UT:SNTL", "Snowbird", 40.57, -111.66, 9177)],
}


def hourly_values(code: str, hours: int = 170):
    """Synthetic storm: depth rises 12 in over the last day."""
    now = utcnow() - timedelta(hours=8)
    vals = []
    for i in range(hours, -1, -1):
        t = (now - timedelta(hours=i)).strftime("%Y-%m-%d %H:00")
        x = hours - i
        if code == "SNWD":
            v = 30 + (12 * max(0, x - (hours - 24)) / 24)
            if x == hours - 5:
                v = 999  # sensor spike -> QC removes
        elif code == "WTEQ":
            v = 8 + (1.2 * max(0, x - (hours - 24)) / 24)
        elif code == "PREC":
            v = 10 + (1.3 * max(0, x - (hours - 24)) / 24)
        else:  # TOBS
            v = 20 + 8 * math.sin(x / 24 * 2 * math.pi)
        vals.append({"date": t, "value": round(v, 1)})
    return vals


class FakeSession:
    request_timeout = 5

    def __init__(self, fail=()):
        self.fail = set(fail)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, params))
        path = urlparse(url).path
        host = urlparse(url).netloc
        if any(f in url for f in self.fail):
            return FakeResponse({}, 503)

        if path.endswith("/stations"):
            st = params["stationTriplets"].split(":")[1]
            return FakeResponse([
                {"stationTriplet": t, "name": n, "latitude": la, "longitude": lo,
                 "elevation": el, "stateCode": st, "networkCode": "SNTL"}
                for t, n, la, lo, el in STATIONS.get(st, [])
            ])

        if path.endswith("/data"):
            out = []
            for trip in params["stationTriplets"].split(","):
                blocks = []
                for code in params["elements"].split(","):
                    if params["duration"] == "DAILY":
                        values = [{"date": "2026-11-05", "value": 8.0, "median": 6.4}]
                    else:
                        values = hourly_values(code)
                    blocks.append({"stationElement": {"elementCode": code, "ordinal": 1},
                                   "values": values})
                out.append({"stationTriplet": trip, "data": blocks})
            return FakeResponse(out)

        if "currents" in path:
            net = params["network"]
            if net != "CO_ASOS":
                return FakeResponse({"data": []})
            valid = utcnow().strftime("%Y-%m-%dT%H:%M:00Z")
            return FakeResponse({"data": [
                {"station": "DEN", "name": "Denver Intl", "network": net,
                 "utc_valid": valid, "tmpf": 28, "dwpf": 20, "sknt": 17,
                 "drct": 340, "gust": 28, "vsby": 3, "raw": "KDEN 070253Z 34017G28KT"},
                {"station": "EGE", "name": "Eagle County", "network": net,
                 "utc_valid": "2026-01-01T00:00:00Z", "tmpf": 15, "sknt": 0, "drct": 0},
            ]})

        if "geojson/network" in path:
            return FakeResponse({"features": [
                {"id": "DEN", "properties": {"sid": "DEN", "elevation": 1640},
                 "geometry": {"type": "Point", "coordinates": [-104.66, 39.85]}},
                {"id": "EGE", "properties": {"sid": "EGE", "elevation": 1993},
                 "geometry": {"type": "Point", "coordinates": [-106.92, 39.64]}},
            ]})

        if "avalanche.org" in host:
            soon = (utcnow() + timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%S")
            past = (utcnow() - timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%S")
            square = [[[-106.0, 39.5], [-105.5, 39.5], [-105.5, 40.0],
                       [-106.0, 40.0], [-106.0, 39.5]]]
            zones = [
                ("Front Range", "CAIC", "CO", 3, soon),
                ("Salt Lake", "UAC", "UT", 2, past),
                ("Galena Summit", "SNFAC", "ID", -1, None),
                ("Turnagain Pass", "CNFAIC", "AK", 4, soon),
            ]
            return FakeResponse({"type": "FeatureCollection", "features": [
                {"type": "Feature", "id": i,
                 "properties": {"name": n, "center_id": c, "center": c, "state": s,
                                "danger_level": lvl, "end_date": end, "start_date": past,
                                "link": "https://example.org", "warning": {"product": None}},
                 "geometry": {"type": "Polygon", "coordinates": square}}
                for i, (n, c, s, lvl, end) in enumerate(zones)
            ]})

        return FakeResponse({}, 404)
