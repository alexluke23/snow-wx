"""dev18 Part 3: the public verification documents (pipeline/verify.py `public_docs` / `publish`) behind config verification_ui. Fixture archives only.
Results stay hidden until a SNOTEL site has >= min_days observation days AND >= min_pairs pairs; the flag is OFF; metrics are bias / MAE / hit rate for >= 1 in, NBM only (dev23: NDFD stays in the archive, never in the panel's files)."""
import csv
import gzip
import json
from datetime import date, timedelta


from pipeline import verify
from pipeline.__main__ import write_meta
from pipeline.common import load_config

FC = ("cycle", "point", "elev", "elev_ft", "cell_elev_ft", "hours", "end", "lead_h", "det", "det_cell", "p10", "p50", "p90", "p_ge4", "p_ge8", "p_ge12")
OB = ("end", "triplet", "depth_in", "depth_med3_in", "swe_in", "d_depth_24h", "d_depth_med3_24h", "d_swe_24h", "hours_present")


def write_gz(path, cols, rows):
    with gzip.open(path, "wt", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def make_archive(tmp_path, days: int, cycles_per_day: int = 1, station="1000-OR-SNTL", start=date(2026, 12, 1)):
    """observed snow alternates 0 / 2 / 0 / 3 in; NBM expected = obs + 0.5 (runs high); NDFD = obs - 0.5 (clipped at 0); `cycles_per_day` forecasts per window with leads 40, 32, 24..."""
    nbm, ndfd, ob = [], [], []
    trip = station.replace("-", ":")
    for k in range(days):
        end = f"{(start + timedelta(days=k)).isoformat()}T12:00Z"
        o = [0.0, 2.0, 0.0, 3.0][k % 4]
        ob.append({"end": end, "triplet": trip, "d_depth_med3_24h": o, "hours_present": 24})
        for c in range(cycles_per_day):
            lead = 40 - 8 * c
            row = {"cycle": f"c{c}", "point": f"snotel-{station}", "elev_ft": 7500, "hours": 24, "end": end, "lead_h": lead}
            nbm.append({**row, "det": o + 0.5, "p50": o})
            ndfd.append({**row, "det": max(0.0, o - 0.5)})
        nbm.append({"cycle": "old", "point": f"snotel-{station}", "elev_ft": 7500, "hours": 24, "end": end, "lead_h": 100, "det": 9.0})    # beyond 48 h: not used
    write_gz(tmp_path / "nbm-202612.csv.gz", FC, nbm)
    write_gz(tmp_path / "ndfd-202612.csv.gz", FC, ndfd)
    write_gz(tmp_path / "snotel-202612.csv.gz", OB, ob)
    return tmp_path


def run(tmp_path, days, cycles=1, **kw):
    (tmp_path / "arch").mkdir(exist_ok=True)
    arch = make_archive(tmp_path / "arch", days, cycles)
    cfg = {"verification": {}, "verification_ui": {"min_days": kw.get("min_days", 14), "min_pairs": kw.get("min_pairs", 30)}}
    data = tmp_path / "data"
    summary = verify.run(arch, tmp_path / "out", cfg, publish_dir=data)
    return summary, data


def test_the_flag_is_off_and_meta_says_so():
    cfg = load_config()
    assert cfg["verification_ui"] == {"enabled": False, "min_days": 14, "min_pairs": 30}


def test_meta_json_carries_the_flag_and_minima(tmp_path):
    write_meta(load_config(), tmp_path, {})
    assert json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["verification_ui"] == {"enabled": False, "min_days": 14, "min_pairs": 30}


def test_not_enough_days_shows_counts_only_and_no_results(tmp_path):
    summary, data = run(tmp_path, days=10, cycles=4)                                  # 40 pairs but only 10 days
    idx = json.loads((data / "verification.json").read_text(encoding="utf-8"))
    assert idx["stations"]["1000:OR:SNTL"] == {"d": 10, "n": 40} and idx["scorecard"] == {"ready": False, "days": 10, "pairs": 40, "rows": []}
    assert list((data / "verification").glob("*.json")) == []                          # nothing per-station is published below the minimum
    assert summary["published"] == {"stations": 1, "ready_stations": 0, "scorecard_ready": False}


def test_not_enough_pairs_also_hides_results(tmp_path):
    _, data = run(tmp_path, days=20, cycles=1)                                        # 20 days but only 20 pairs (< 30)
    idx = json.loads((data / "verification.json").read_text(encoding="utf-8"))
    assert idx["stations"]["1000:OR:SNTL"] == {"d": 20, "n": 20} and idx["scorecard"]["ready"] is False and not (data / "verification" / "1000_OR_SNTL.json").exists()


def test_enough_data_publishes_metrics_daily_series_and_the_scorecard(tmp_path):
    _, data = run(tmp_path, days=16, cycles=2)                                        # 16 days, 32 pairs
    idx = json.loads((data / "verification.json").read_text(encoding="utf-8"))
    st = idx["stations"]["1000:OR:SNTL"]
    assert st == {"d": 16, "n": 32, "ready": True} and idx["scorecard"]["ready"] is True and idx["lead_max_h"] == 48
    doc = json.loads((data / "verification" / "1000_OR_SNTL.json").read_text(encoding="utf-8"))
    assert set(doc["metrics"]) == {"NBM expected"}                                                   # the archive has NDFD rows too: they are never published
    nbm = doc["metrics"]["NBM expected"]
    assert nbm["bias_in"] == 0.5 and nbm["mae_in"] == 0.5 and nbm["n"] == 16                         # one forecast per day: the latest issued (lead 32 h), not the 100-h one
    assert nbm["events_1"] == 8 and nbm["hit_1"] == 1.0                                              # obs >= 1 in on 8 of 16 days; NBM (obs + 0.5) caught all of them
    d = doc["daily"]
    assert len(d["dates"]) == len(d["obs"]) == len(d["nbm"]) == 16 and "ndfd" not in d and d["obs"][:4] == [0.0, 2.0, 0.0, 3.0] and d["nbm"][:4] == [0.5, 2.5, 0.5, 3.5]
    sc = {r["source"]: r for r in idx["scorecard"]["rows"]}
    assert set(sc) == {"NBM expected"} and sc["NBM expected"]["n"] == 16


def test_stale_station_files_are_removed_on_republish(tmp_path):
    _, data = run(tmp_path, days=16, cycles=2)
    assert (data / "verification" / "1000_OR_SNTL.json").exists()
    run(tmp_path, days=5, cycles=2)                                                  # archive shrinks (e.g. a new season): the old site file must not linger
    assert not (data / "verification" / "1000_OR_SNTL.json").exists()


def test_minima_are_configurable(tmp_path):
    _, data = run(tmp_path, days=6, cycles=1, min_days=5, min_pairs=6)
    assert json.loads((data / "verification.json").read_text(encoding="utf-8"))["stations"]["1000:OR:SNTL"].get("ready") is True


def test_outage_window_is_excluded_from_the_public_numbers_too(tmp_path):
    (tmp_path / "arch").mkdir()
    arch = make_archive(tmp_path / "arch", 20, 2)
    cfg = {"verification": {"snotel_outage": {"start": "2026-12-05T12:00Z", "end": "2026-12-12T00:00Z"}}, "verification_ui": {"min_days": 5, "min_pairs": 5}}
    verify.run(arch, tmp_path / "out", cfg, publish_dir=tmp_path / "data")
    doc = json.loads((tmp_path / "data" / "verification" / "1000_OR_SNTL.json").read_text(encoding="utf-8"))
    assert "2026-12-06" not in doc["daily"]["dates"] and "2026-12-10" not in doc["daily"]["dates"] and doc["d"] < 20


def test_empty_archive_publishes_an_empty_index(tmp_path):
    (tmp_path / "arch").mkdir()
    summary = verify.run(tmp_path / "arch", tmp_path / "out", {}, publish_dir=tmp_path / "data")
    idx = json.loads((tmp_path / "data" / "verification.json").read_text(encoding="utf-8"))
    assert idx["stations"] == {} and idx["scorecard"]["ready"] is False and summary["published"]["ready_stations"] == 0
