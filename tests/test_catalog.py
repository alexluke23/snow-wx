"""Ski-area catalog: pure selection, terminal, join and grid helpers (offline)."""

import pytest

from pipeline import catalog as c

CCFG = {
    "states": ["UT", "CA"],
    "min_vertical_ft": 300,
    "exclude": ["Private Club"],
    "include": ["Nordic Tagged Hill"],
    "regions": [{"name": "Wasatch", "box": [-112.0, -111.3, 40.3, 41.45]}],
    "state_names": {"UT": "Utah", "CA": "California"},
}


def area(name, state="UT", status="operating", acts=("downhill",), lo=2500, hi=3000, aid=None):
    return {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-111.6, 40.6]},
            "properties": {"id": aid or name, "name": name, "status": status, "activities": list(acts),
                           "places": [{"iso3166_2": f"US-{state}"}],
                           "statistics": {"lifts": {"minElevation": lo, "maxElevation": hi},
                                          "runs": {"minElevation": lo, "byActivity": {"downhill": {
                                              "byDifficulty": {"easy": {"lengthInKm": 3.0},
                                                               "advanced": {"lengthInKm": 2.5}}}}}}}}


def test_select_areas_filters_and_dedupes():
    feats = [area("Big Hill"), area("Big Hill", aid="dup", lo=2900, hi=3000),   # duplicate, smaller
             area("Tiny Bump", lo=2500, hi=2550),                                # < 300 ft vertical
             area("Ghost Town", status="abandoned"),
             area("Private Club"),
             area("Nordic Tagged Hill", acts=("nordic",), lo=2500, hi=2600),     # forced include
             area("Elsewhere", state="MT")]
    got = {a["props"]["name"]: a for a in c.select_areas(feats, CCFG)}
    assert set(got) == {"Big Hill", "Nordic Tagged Hill"}
    assert got["Big Hill"]["props"]["id"] == "Big Hill"                          # kept the bigger one
    assert c.run_length_km(feats[0]["properties"]) == pytest.approx(5.5)


def lift(area_id, a, b, status="operating", kind="chair_lift"):
    return {"geometry": {"type": "LineString", "coordinates": [a, b]},
            "properties": {"status": status, "liftType": kind, "name": "L",
                           "skiAreas": [{"properties": {"id": area_id}}]}}


def test_terminals_and_base_summit_skip_transport_lifts():
    lifts = [
        lift("A", [-111.0, 40.0, 2600], [-111.01, 40.01, 3000]),
        lift("A", [-111.02, 40.02, 3300], [-111.03, 40.0, 2700]),     # drawn top->bottom
        lift("A", [-111.1, 40.1, 1600], [-111.05, 40.05, 2650], kind="gondola"),  # from the valley town
        lift("A", [-111.0, 40.0, 2000], [-111.0, 40.0, 2100], status="abandoned"),
        lift("B", [-111.0, 40.0, 2000], [-111.0, 40.0, 2100]),
    ]
    terms = c.lift_terminals(lifts, {"A"})
    assert set(terms) == {"A"} and len(terms["A"]) == 3
    assert terms["A"][1]["bottom"][2] == 2700 and terms["A"][1]["top"][2] == 3300
    base, summit, n = c.base_summit(terms["A"], runs_min_m=2580, drop_m=60)
    assert base == (-111.0, 40.0, 2600) and summit[2] == 3300 and n == 3
    # Without run statistics the town gondola would be the base.
    base, _, _ = c.base_summit(terms["A"], runs_min_m=None, drop_m=60)
    assert base[2] == 1600
    assert c.base_summit([], 0, 60) == (None, None, 0)


def test_slug_region_nearest_verify():
    taken = set()
    assert c.slugify("Ski Santa Fé", "NM", taken) == "ski-santa-fe"
    assert c.slugify("Ski Santa Fe", "NM", taken) == "ski-santa-fe-nm"
    assert c.slugify("Ski Santa Fe", "NM", taken) == "ski-santa-fe-nm-2"
    assert c.region_for(-111.64, 40.58, "UT", CCFG) == "Wasatch"
    assert c.region_for(-112.85, 37.69, "UT", CCFG) == "Utah"
    st = [{"id": "a", "name": "A", "lat": 40.60, "lon": -111.60, "elev_ft": 8000},
          {"id": "b", "name": "B", "lat": 40.70, "lon": -111.60, "elev_ft": 7000},
          {"id": "far", "name": "F", "lat": 42.0, "lon": -111.60, "elev_ft": 5000}]
    near = c.nearest(st, 40.58, -111.60, count=3, max_km=50)
    assert [s["id"] for s in near] == ["a", "b"] and near[0]["dist_km"] == pytest.approx(2.2, abs=0.1)
    assert c.verify(8000.0, 8050.0, 150)[0] == "ok"
    assert c.verify(8000.0, 8400.0, 150)[0] == "mismatch"
    assert c.verify(8000.0, None, 150)[0] == "dem-only"
    assert c.verify(None, 8000.0, 150)[0] == "no-dem"


def test_zone_for_point_in_polygon():
    from shapely.geometry import box
    zones = [(box(-112, 40, -111, 41), {"zone_id": 1, "zone": "Salt Lake"})]
    assert c.zone_for(-111.6, 40.6, zones)["zone_id"] == 1
    assert c.zone_for(-110.0, 40.6, zones) is None


# NDFD/NBM 2.5-km CONUS grid as decoded from an NBM message (see nbm_grid()).
NBM = {"nx": 2345, "ny": 1597, "lad": 25.0, "lov": -95.0, "latin1": 25.0, "latin2": 25.0,
       "lat1": 19.229, "lon1": -126.2766, "dx": 2539.703, "dy": 2539.703, "radius": 6371200.0}


def test_lcc_ij_round_trip_and_bounds():
    p = c.nbm_proj(NBM)
    x0, y0 = p(NBM["lon1"], NBM["lat1"])
    assert c.lcc_ij(NBM["lat1"], NBM["lon1"], NBM) == (0, 0)
    lon, lat = p(x0 + 1000 * NBM["dx"], y0 + 700 * NBM["dy"], inverse=True)
    assert c.lcc_ij(lat, lon, NBM) == (1000, 700)
    xmin, ymin, xmax, ymax = c.cell_envelope(1000, 700, NBM)
    assert xmin < lon < xmax and ymin < lat < ymax and (ymax - ymin) == pytest.approx(0.023, abs=0.003)
    with pytest.raises(ValueError):
        c.lcc_ij(10.0, -160.0, NBM)


def test_apply_merges_pools_members():
    feats = [area("Three Summits", lo=800, hi=1180), area("Summit West", lo=900, hi=1130),
             area("Summit East", lo=850, hi=880), area("Alpental", lo=950, hi=1650)]   # East: < 300 ft
    cfg = {**CCFG, "states": ["UT"], "merge": {"The Summit": ["Three Summits", "Summit West", "Summit East"]}}
    got = {a["props"]["name"]: a for a in c.apply_merges(c.select_areas(feats, cfg), feats, cfg)}
    assert set(got) == {"The Summit", "Alpental"}
    m = got["The Summit"]
    assert set(m["ids"]) == {"Three Summits", "Summit West", "Summit East"}        # filtered member pooled too
    assert m["runs_min_m"] == 800 and m["runs_km"] == pytest.approx(16.5)
    assert got["Alpental"]["ids"] == ["Alpental"]
