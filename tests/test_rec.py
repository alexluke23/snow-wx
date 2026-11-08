"""Sno-Park / winter recreation catalog helpers (pipeline/rec.py)."""

import numpy as np

from pipeline import rec as R


def test_edw_site_filters_and_titles():
    a = {"site_type": "SNOWPARK", "site_name": "DUTCHMAN FLAT", "latitude": "44.0", "longitude": "-121.66",
         "fee_charged": "N", "passes": "Oregon State Sno-Park Permit required", "activity_type_list": "No Data", "site_cn": "1"}
    s = R.edw_site(a)
    assert s["name"] == "Dutchman Flat" and s["subtype"] == "snopark" and s["source"] == "usfs-edw"
    assert R.edw_site({**a, "site_type": "TRAILHEAD", "site_name": "LOST LAKE TRAILHEAD"}) is None      # summer trailhead
    assert R.edw_site({**a, "site_type": "TRAILHEAD", "site_name": "WOLF CREEK SNOWMOBILE TH"})["subtype"] == "trailhead"
    assert R.edw_site({**a, "site_type": "CAMPGROUND"}) is None


def test_osm_site_excludes_terrain_parks():
    e = {"type": "node", "id": 5, "lat": 47.4, "lon": -121.4, "tags": {"name": "Gold Creek Sno-Park", "amenity": "parking"}}
    assert R.osm_site(e)["subtype"] == "snopark"
    assert R.osm_site({**e, "tags": {"name": "Big Air Terrain Park"}}) is None
    assert R.osm_site({**e, "tags": {"name": "Lot 4", "amenity": "parking", "snowmobile": "designated"}})["activities" if False else "source_activities"] == ["snowmobiling"]


def test_dedupe_prefers_edw_and_merges_nearby_osm():
    edw = [{"name": "Gold Creek", "lat": 47.40, "lon": -121.40, "source": "usfs-edw", "link": None}]
    osm = [{"name": "Gold Creek Sno-Park", "lat": 47.402, "lon": -121.401, "source": "osm", "link": "https://x"},   # 0.2 km
           {"name": "Gold Creek Pond Sno-Park", "lat": 47.41, "lon": -121.40, "source": "osm", "link": None},         # 1.1 km, same name token
           {"name": "Hyak Sno-Park", "lat": 47.39, "lon": -121.39, "source": "osm", "link": None}]                   # 1.3 km, other name
    out = R.dedupe(edw, osm)
    assert [s["name"] for s in out] == ["Gold Creek", "Hyak Sno-Park"] and out[0]["link"] == "https://x"


def test_activities_and_permit():
    s = {"name": "Mount Spokane Nordic", "subtype": "nordic", "source_activities": []}
    assert R.activities(s) == (["cross-country skiing"], True)
    s2 = {"name": "X", "subtype": "snopark", "source_activities": ["snowshoeing", "ice & snowcraft travel"]}
    assert R.activities(s2) == (["snowmobiling", "snowshoeing"], False)
    assert R.permit_for("OR", {"subtype": "snopark", "passes": None}).startswith("Likely: Oregon Sno-Park permit")
    assert R.permit_for("UT", {"subtype": "snopark", "passes": None, "fee": False}) is None
    assert R.permit_for("WA", {"subtype": "snopark", "passes": "Sno-Park permit required"}) == "Sno-Park permit required"


def test_high_point_within_radius():
    a = np.full((81, 81), 1000.0)
    a[40, 70] = 3000.0          # ~3.4 km east of the centre -> inside 5 km
    a[0, 0] = 5000.0            # corner, ~7 km away -> outside the circle
    bbox = (-121.064, 43.955, -120.936, 44.045)      # ~10 x 10 km around (44.0, -121.0)
    lat, lon, ft = R.high_point(a, (44.0, -121.0), bbox)
    assert round(ft) == round(3000 * 3.28084) and lon > -121.0 and abs(lat - 44.0) < 0.001
