"""Sno-Park / winter recreation catalog helpers (pipeline/rec.py)."""

import json
from pathlib import Path

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


def test_activities_and_permit_only_as_stated():
    assert R.activities({"name": "Mount Spokane Nordic", "subtype": "nordic", "source_activities": []}) == []   # no inference
    s2 = {"name": "X", "subtype": "snopark", "source_activities": ["snowshoeing", "ice & snowcraft travel"]}
    assert R.activities(s2) == ["snowmobiling", "snowshoeing"]
    assert R.permit_for({"passes": None}) is None
    assert R.permit_for({"passes": "Sno-Park permit required"}) == "Sno-Park permit required"
    assert R.permit_check("OR", {})["url"].startswith("https://www.oregon.gov/odot/")
    assert R.permit_check("UT", {"link": "https://www.fs.usda.gov/r04/x"}) == {"name": "the managing agency", "url": "https://www.fs.usda.gov/r04/x"}
    assert R.permit_check("CO", {})["url"] == "https://www.fs.usda.gov/"


def test_high_point_within_radius():
    a = np.full((81, 81), 1000.0)
    a[40, 70] = 3000.0          # ~3.4 km east of the centre -> inside 5 km
    a[0, 0] = 5000.0            # corner, ~7 km away -> outside the circle
    bbox = (-121.064, 43.955, -120.936, 44.045)      # ~10 x 10 km around (44.0, -121.0)
    lat, lon, ft = R.high_point(a, (44.0, -121.0), bbox)
    assert round(ft) == round(3000 * 3.28084) and lon > -121.0 and abs(lat - 44.0) < 0.001


def _rec(i, name, lat, lon, source="usfs-edw", elev=6000, cell=6200, wfo="SLC"):
    return {"id": i, "name": name, "state": "UT", "source": source, "subtype": "snopark", "base": {"lat": lat, "lon": lon, "elev_ft": elev},
            "nbm_grid": {"base": {"elev_ft": cell}}, "nws": {"base": {"wfo": wfo} if wfo else {}}}


SKI = [{"name": "Alta Ski Area", "base": {"lat": 40.58, "lon": -111.64}, "summit": {"lat": 40.59, "lon": -111.63}}]


def test_review_flags_each_reason_from_fixtures():
    from pipeline.rec import review_flags
    ok = _rec("a", "Quiet Meadow Sno-Park", 41.5, -112.5)
    assert review_flags(ok, SKI, [ok])["reasons"] == []
    near = review_flags(_rec("b", "Cottonwood Nordic", 40.585, -111.64), SKI)
    assert "near_ski_area" in near["reasons"] and near["near_ski_area"] == "Alta Ski Area" and near["near_ski_km"] < 1
    assert "osm_only" in review_flags(_rec("c", "Gap Fill Sno-Park", 41.5, -112.5, source="osm"), SKI)["reasons"]
    assert "generic_name" in review_flags(_rec("d", "Trailhead 12", 41.5, -112.5), SKI)["reasons"]
    assert "elevation_mismatch" in review_flags(_rec("e", "Deep Valley", 41.5, -112.5, elev=5000, cell=8000), SKI)["reasons"]
    assert "no_nws_grid" in review_flags(_rec("f", "Offgrid", 41.5, -112.5, wfo=None), SKI)["reasons"]
    a, b = _rec("g", "Twin Sno-Park", 41.5, -112.5), _rec("h", "Twin Sno-Park Lot", 41.5, -112.503)
    assert "duplicate_nearby" in review_flags(a, SKI, [a, b])["reasons"]


def test_review_rows_lists_only_flagged_points_and_keeps_the_source():
    from pipeline.rec import review_rows
    rows = review_rows({"areas": [_rec("a", "Quiet", 41.5, -112.5), _rec("c", "Gap", 41.6, -112.6, source="osm")]}, {"areas": SKI})
    assert [r["id"] for r in rows] == ["c"] and rows[0]["source"] == "osm" and rows[0]["reasons"] == "osm_only"


def test_review_flags_tolerates_a_record_without_a_base():
    from pipeline.rec import review_flags
    odd = {"id": "x", "name": "No Base", "source": "osm", "nws": {}}
    assert "osm_only" in review_flags(odd, SKI, [odd, _rec("a", "Other", 41.5, -112.5)])["reasons"]


# ---- dev17 Part 0d: owner decisions (keep / drop / merge) in data/rec_points_review.csv
def _csv(tmp_path, rows, header="id,name,decision,merge_into,note"):
    p = tmp_path / "review.csv"
    p.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return p


def test_no_decisions_changes_nothing(tmp_path):
    from pipeline.rec import apply_decisions, read_decisions
    recs = [_rec("a", "A", 41.5, -112.5), _rec("b", "B", 41.6, -112.6)]
    assert read_decisions(tmp_path / "missing.csv") == {}
    p = _csv(tmp_path, ["a,A,,,", "b,B,  ,,just a note"])          # empty / blank decision cells
    assert read_decisions(p) == {}
    out, rep = apply_decisions(recs, read_decisions(p))
    assert out == recs and rep["drop"] == [] and rep["warnings"] == []
    assert out is recs or out == recs


def test_drop_keep_and_merge_are_applied_case_insensitively(tmp_path):
    from pipeline.rec import apply_decisions, read_decisions
    recs = [_rec(i, i.upper(), 41.5, -112.5) for i in "abcdef"]
    p = _csv(tmp_path, ["a,A,DROP,,duplicate of a resort", "b,B, Keep ,,fine", "c,C,merge,d,same lot", "e,E,maybe,,unknown value is ignored"])
    d = read_decisions(p)
    assert sorted(d) == ["a", "b", "c"] and d["c"]["merge_into"] == "d"
    out, rep = apply_decisions(recs, d)
    assert [r["id"] for r in out] == ["b", "d", "e", "f"] and rep["drop"] == ["a"] and rep["keep"] == ["b"] and rep["merge"] == [("c", "d")]
    assert next(r for r in out if r["id"] == "d")["merged_ids"] == ["c"] and "merged_ids" not in out[0]
    assert recs[0]["id"] == "a"                                       # input list untouched


def test_bad_merges_are_kept_with_a_warning():
    from pipeline.rec import apply_decisions
    recs = [_rec(i, i.upper(), 41.5, -112.5) for i in "abc"]
    dec = {"a": {"decision": "merge", "merge_into": "", "note": ""}, "b": {"decision": "merge", "merge_into": "c", "note": ""},
           "c": {"decision": "drop", "merge_into": "", "note": ""}, "zzz": {"decision": "drop", "merge_into": "", "note": ""}}
    out, rep = apply_decisions(recs, dec)
    assert [r["id"] for r in out] == ["a", "b"]                       # a (no target) and b (target dropped) stay; c dropped
    assert len(rep["warnings"]) == 3 and any("unknown id zzz" in w for w in rep["warnings"])


def test_regenerating_the_review_csv_keeps_decisions_and_dropped_rows(tmp_path):
    import csv
    from pipeline import rec as R
    ski = tmp_path / "ski.json"
    ski.write_text(json.dumps({"areas": SKI}), encoding="utf-8")
    recp = tmp_path / "rec_points.json"
    recp.write_text(json.dumps({"areas": [_rec("c", "Gap", 41.6, -112.6, source="osm")]}), encoding="utf-8")      # 'x' was dropped earlier
    out = tmp_path / "rec_points_review.csv"
    out.write_text("id,name,state,source,subtype,reasons,near_ski_area,near_ski_km,elev_ft,cell_elev_ft,lat,lon,decision,merge_into,note\n"
                   "c,Gap,UT,osm,snopark,osm_only,,,6000,6200,41.6,-112.6,keep,,ok by owner\n"
                   "x,Old,UT,osm,snopark,osm_only,,,6000,6200,41.5,-112.5,drop,,not a Sno-Park\n", encoding="utf-8")
    rows = R.write_review(recp, ski, out)
    got = {r["id"]: r for r in csv.DictReader(open(out, encoding="utf-8", newline=""))}
    assert got["c"]["decision"] == "keep" and got["c"]["note"] == "ok by owner" and got["x"]["decision"] == "drop"
    assert [r["id"] for r in rows] == ["c", "x"] or [r["id"] for r in rows] == ["c"]


def test_review_csv_is_never_published():
    """the owner CSV lives in data/ and must not reach the site: build_site copies only the two JSON catalogs, web/ holds no csv"""
    root = Path(__file__).resolve().parents[1]
    src = (root / "pipeline" / "__main__.py").read_text(encoding="utf-8")
    assert 'for name in ("ski_areas.json", "rec_points.json"):' in src
    assert not list((root / "web").rglob("*review*.csv")) and not list((root / "web").rglob("rec_points*"))
    for wf in (root / ".github" / "workflows").glob("*.yml"):
        assert "rec_points_review" not in wf.read_text(encoding="utf-8")
