"""Data ingest (python -m ingest): stores, publish planning, partial runs, SNOTEL seeding. Offline: FakeSession + fake S3."""

import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ingester import publish as P
from ingester import runner as R
from ingester.sources import registry, resolve
from ingester.store import LocalStore, R2Store, r2_credentials, secret
from ingester.fetch.common import load_config
from fakes import FakeResponse, FakeSession


@pytest.fixture
def cfg():
    c = load_config()
    c["region"]["states"] = ["CO", "UT"]
    return c


def write(p, text):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class FakeS3:
    """The few boto3 S3 client calls R2Store uses."""

    class NotFound(Exception):
        response = {"Error": {"Code": "NoSuchKey"}}

    def __init__(self):
        self.objects, self.calls = {}, []

    def put_object(self, **kw):
        self.calls.append(("put", kw["Key"]))
        self.objects[kw["Key"]] = kw

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise FakeS3.NotFound()
        return {"Body": io.BytesIO(self.objects[Key]["Body"])}

    def delete_object(self, Bucket, Key):
        self.calls.append(("delete", Key))
        self.objects.pop(Key, None)


# ---------- stores ----------

def test_local_store_round_trip_and_rejects_bad_keys(tmp_path):
    s = LocalStore(tmp_path)
    s.put("v1/data/a.json", b"{}", "application/json")
    assert s.get("v1/data/a.json") == b"{}" and s.get("v1/data/missing.json") is None
    s.delete("v1/data/a.json")
    s.delete("v1/data/a.json")                       # deleting twice is fine
    assert s.get("v1/data/a.json") is None
    for bad in ("/abs", "v1/../x", "v1//x", "a\\b", ""):
        with pytest.raises(ValueError):
            s.put(bad, b"", "text/plain")


def test_r2_store_headers_and_missing_key():
    c = FakeS3()
    s = R2Store(c, "bucket")
    s.put("v1/data/a.json", b"{}", "application/json", "public, max-age=60", "abc")
    kw = c.objects["v1/data/a.json"]
    assert kw["ContentType"] == "application/json" and kw["CacheControl"] == "public, max-age=60" and kw["Metadata"] == {"sha256": "abc"}
    assert s.get("v1/data/a.json") == b"{}" and s.get("nope") is None


def test_credentials_from_files_and_env(monkeypatch, tmp_path):
    for n in ("R2_ACCOUNT_ID", "R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(n, raising=False)
        monkeypatch.delenv(n + "_FILE", raising=False)
    f = tmp_path / "bucket.txt"
    f.write_text("snow-test\n", encoding="utf-8")
    monkeypatch.setenv("R2_BUCKET_FILE", str(f))
    assert secret("R2_BUCKET") == "snow-test"
    with pytest.raises(RuntimeError, match="R2_ACCESS_KEY_ID"):
        r2_credentials()
    monkeypatch.setenv("R2_ACCOUNT_ID", "acct")
    monkeypatch.setenv("R2_ACCESS_KEY_ID", "k")
    monkeypatch.setenv("R2_SECRET_ACCESS_KEY", "s")
    assert r2_credentials()["endpoint"] == "https://acct.r2.cloudflarestorage.com"


# ---------- publish ----------

def make_stage(root):
    write(root / "data" / "meta.json", '{"m":1}')
    write(root / "data" / "points" / "alta.json", '{"a":1}')
    write(root / "data" / "points" / "summary.json", '{"s":1}')
    write(root / "data" / "snotel.geojson", '{"type":"FeatureCollection","features":[]}')
    write(root / "models" / "hrrr" / "2026112400" / "snow" / "west" / "f001.png", "png")
    write(root / "models" / "hrrr" / "frame.npz", "working file")     # never published
    write(root / "web.html", "not data")                               # outside data/ + models/
    return root


def test_publish_keys_types_order_and_hash_skip(tmp_path):
    stage, store = make_stage(tmp_path / "stage"), LocalStore(tmp_path / "store")
    c = FakeS3()
    r2 = R2Store(c, "b")
    res = P.publish(r2, stage)
    assert res["put"] == 5 and res["skip"] == 0
    keys = [k for op, k in c.calls if op == "put"]
    data_keys = [k for k in keys if not k.startswith("v1/_")]
    assert set(data_keys) == {"v1/data/meta.json", "v1/data/points/alta.json", "v1/data/points/summary.json",
                              "v1/data/snotel.geojson", "v1/models/hrrr/2026112400/snow/west/f001.png"}
    # payload, then the index/summary that points at it, then meta.json, then the logs, and the manifest last
    assert data_keys.index("v1/data/points/alta.json") < data_keys.index("v1/data/points/summary.json") < data_keys.index("v1/data/meta.json")
    assert keys[-1] == "v1/_manifest.json" and any(k.startswith("v1/_runs/") for k in keys[:-1])   # logs before the manifest
    assert c.objects["v1/data/snotel.geojson"]["ContentType"] == "application/geo+json"
    assert c.objects["v1/models/hrrr/2026112400/snow/west/f001.png"]["ContentType"] == "image/png"
    assert c.objects["v1/_manifest.json"]["CacheControl"] == "no-store"
    # second publish: nothing changed -> only the manifest is rewritten
    c.calls.clear()
    res = P.publish(r2, stage)
    written = [k for _, k in c.calls]
    assert (res["put"], res["skip"]) == (0, 5) and [k for k in written if not k.startswith("v1/_")] == [] and written[-1] == "v1/_manifest.json"
    # local store: same keys, same bytes
    P.publish(store, stage)
    assert (tmp_path / "store" / "v1" / "data" / "points" / "alta.json").read_bytes() == (stage / "data" / "points" / "alta.json").read_bytes()
    man = json.loads((tmp_path / "store" / "v1" / "_manifest.json").read_text())
    assert man["layout"] == "v1" and "v1/data/points/alta.json" in man["objects"]


def test_prune_only_inside_scope_and_dry_run_writes_nothing(tmp_path):
    stage, store = make_stage(tmp_path / "stage"), LocalStore(tmp_path / "store")
    P.publish(store, stage)
    (stage / "data" / "points" / "alta.json").unlink()
    (stage / "data" / "snotel.geojson").unlink()
    dry = P.publish(store, stage, scope=["data/points"], prune=True, dry_run=True)
    assert dry["delete"] == 1 and dry["sample_delete"] == ["v1/data/points/alta.json"]
    assert store.get("v1/data/points/alta.json") is not None             # dry run: untouched
    P.publish(store, stage, scope=["data/points"], prune=True)
    assert store.get("v1/data/points/alta.json") is None                 # inside scope: pruned
    assert store.get("v1/data/snotel.geojson") is not None               # outside scope: kept
    man = P.load_manifest(store)
    assert "v1/data/points/alta.json" not in man["objects"] and "v1/data/snotel.geojson" in man["objects"]
    # without --prune nothing is ever deleted
    P.publish(store, stage)
    assert store.get("v1/data/snotel.geojson") is not None


def test_archive_copies_only_changed_objects(tmp_path):
    stage, store = make_stage(tmp_path / "stage"), LocalStore(tmp_path / "store")
    t1, t2 = datetime(2026, 11, 24, 1, tzinfo=timezone.utc), datetime(2026, 11, 24, 2, tzinfo=timezone.utc)
    P.publish(store, stage, archive=True, now=t1)
    write(stage / "data" / "points" / "alta.json", '{"a":2}')
    res = P.publish(store, stage, archive=True, now=t2)
    assert res["put"] == 1 and res["archive"] == "archive/runs/20261124T020000Z/"
    arch = sorted(p.relative_to(tmp_path / "store" / "archive" / "runs" / "20261124T020000Z").as_posix()
                  for p in (tmp_path / "store" / "archive" / "runs" / "20261124T020000Z").rglob("*") if p.is_file())
    assert arch == ["data/points/alta.json"]


def test_manifest_accepts_older_draft_format(tmp_path):
    store = LocalStore(tmp_path)
    store.put("v1/_manifest.json", json.dumps({"objects": {"v1/data/a.json": "abc"}}).encode(), "application/json")
    assert P.load_manifest(store)["objects"] == {"v1/data/a.json": {"sha256": "abc"}}


# ---------- sources ----------

def test_resolve_groups_defaults_and_unknown():
    reg = registry()
    names = [s.name for s in resolve([], True, reg)]
    assert {"snotel", "asos", "alerts", "points", "nohrsc", "ecmwf", "gefs"} <= set(names)
    assert "ndfd" not in names and not any(n.startswith("maps:") for n in names)      # opt-in only
    assert [s.name for s in resolve(["obs"], False, reg)] == ["alerts", "afd", "avalanche", "hazards", "snotel", "asos"]
    assert [s.name for s in resolve(["ndfd"], False, reg)] == ["ndfd"]
    with pytest.raises(ValueError):
        resolve(["nope"], False, reg)


# ---------- runs ----------

def run(cfg, names, stage, store, session=None, **kw):
    return R.run(cfg, resolve(names, False, registry()), stage, store, session=session or FakeSession(), **kw)


def test_obs_run_stores_the_stage_byte_for_byte(cfg, tmp_path):
    """Every file the sources wrote is stored under v1/ with the same bytes; the manifest lists them with their hashes."""
    store = LocalStore(tmp_path / "store")
    res = run(cfg, ["snotel", "asos", "avalanche"], tmp_path / "stage", store)
    assert res["ok"] and all(res["sources"][n]["ok"] for n in ("snotel", "asos", "avalanche"))
    files = {p.relative_to(tmp_path / "stage").as_posix() for p in (tmp_path / "stage").rglob("*") if p.is_file()}
    assert "data/snotel.geojson" in files and "data/asos.geojson" in files
    for rel in files:
        assert store.get("v1/" + rel) == (tmp_path / "stage" / rel).read_bytes(), rel
    man = P.load_manifest(store)
    assert man["sources"]["snotel"]["ok"] is True
    assert {"v1/" + r for r in files} <= set(man["objects"])
    assert "v1/data/meta.json" not in man["objects"]               # the ingester writes no website files


def test_partial_run_keeps_other_sources_status_and_objects(cfg, tmp_path):
    store = LocalStore(tmp_path / "store")
    # another job already published NBM points (its own stage) and recorded its status
    other = tmp_path / "points_job"
    write(other / "data" / "points" / "summary.json", json.dumps(
        {"cycle": "2026112413", "generated_at": "2026-11-24T15:00:00Z", "areas": [{}, {}]}))
    write(other / "data" / "points" / "alta.json", '{"a":1}')
    P.publish(store, other, scope=["data/points"], sources={"points": {"ok": True, "at": "2026-11-24T15:00:00Z"}})
    # a persistent local stage with an OLD points file must not overwrite the newer stored one
    stage = tmp_path / "stage"
    write(stage / "data" / "points" / "alta.json", '{"a":"old"}')
    res = run(cfg, ["asos"], stage, store, prune=True)
    assert res["ok"] and set(res["sources"]) == {"asos"}
    assert store.get("v1/data/points/alta.json") == b'{"a":1}'
    sources = P.load_manifest(store)["sources"]
    assert sources["points"]["ok"] is True                         # the other job's status is kept
    assert sources["asos"]["ok"] is True


def test_history_survives_a_fresh_stage(cfg, tmp_path):
    store = LocalStore(tmp_path / "store")
    run(cfg, ["avalanche"], tmp_path / "s1", store, session=FakeSession(fail=["avalanche.org"]))
    res = run(cfg, ["avalanche"], tmp_path / "s2", store, session=FakeSession(fail=["avalanche.org"]))
    assert res["ok"] is False                                      # the only source failed
    assert P.load_manifest(store)["sources"]["avalanche"]["consecutive_failures"] == 2


class AwdbDown(FakeSession):
    def get(self, url, params=None, timeout=None):
        if "avalanche.org" in url:
            return super().get(url, params, timeout)
        self.calls.append((url, params))
        return FakeResponse({}, 502)


def test_snotel_outage_keeps_the_stored_copy_on_a_fresh_stage(cfg, tmp_path):
    store = LocalStore(tmp_path / "store")
    run(cfg, ["snotel"], tmp_path / "s1", store)
    res = run(cfg, ["snotel"], tmp_path / "s2", store, session=AwdbDown())
    assert res["sources"]["snotel"]["ok"] is False
    gj = json.loads(store.get("v1/data/snotel.geojson"))
    assert gj["stale"] is True and gj["features"]                  # previous good copy, flagged stale (not "unavailable")
    assert (tmp_path / "s2" / "data" / "snotel" / "663_CO_SNTL.json").exists()


def test_store_none_fetches_into_the_stage_only(cfg, tmp_path):
    res = run(cfg, ["asos"], tmp_path / "stage", None)
    assert res["publish"] is None and (tmp_path / "stage" / "data" / "asos.geojson").exists()


def test_cli_list_and_missing_r2_credentials(monkeypatch, capsys):
    from ingester.__main__ import main
    assert main(["list"]) == 0
    assert "snotel" in capsys.readouterr().out
    for n in ("R2_ACCOUNT_ID", "R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET"):
        monkeypatch.delenv(n, raising=False)
        monkeypatch.delenv(n + "_FILE", raising=False)
    assert main(["publish", "--store", "r2", "--dry-run"]) == 2      # no credentials: a clear error, nothing touched


def test_output_paths_resolve_from_the_launch_folder(monkeypatch, tmp_path):
    from ingester.__main__ import _resolve, _settings
    monkeypatch.setenv("INGEST_LAUNCH_DIR", str(tmp_path / "launch"))
    assert _resolve("output") == tmp_path / "launch" / "output"          # relative: from the launch folder
    assert _resolve("/abs/dir") == Path("/abs/dir")                    # absolute: used as given
    monkeypatch.delenv("INGEST_LAUNCH_DIR")
    monkeypatch.chdir(tmp_path)
    assert _resolve("mine") == tmp_path / "mine"                       # no container: the current folder
    assert _settings({"ingest": {"output_dir": "output"}})["output"] == "output"
    assert _settings({})["output"] == "output"                          # default when the config has no ingest section


def test_vendored_config_is_found_and_complete():
    """The copied fetch code reads its rules and thresholds from the ingester's own config/ (regression: a wrong path
    made every point's daily summary fail, and a trimmed settings file would silently change the powder thresholds)."""
    from ingester.fetch import points, summary
    from ingester.fetch.common import REPO_ROOT
    assert summary.RULES_PATH == REPO_ROOT / "config" / "summary_rules.yml" and summary.RULES_PATH.exists()
    rules = summary.load_rules()
    assert rules["powder_quality"] == {"dense_below": 10, "blower_at": 15, "wind_gust_mph": 30, "min_snow_in": 0.5}
    points.configure_powder_quality({"powder_quality": rules["powder_quality"]})
    assert points.POWDER_Q["blower_at"] == 15


# ---------- step 1 of the history plan: content hashes, run log, change log ----------

def _doc(path, body):
    write(path, json.dumps(body))


def test_time_only_change_is_not_uploaded_and_the_stored_hash_is_kept(tmp_path):
    stage, store = tmp_path / "stage", LocalStore(tmp_path / "store")
    _doc(stage / "data" / "points" / "alta.json", {"id": "alta", "generated_at": "2026-11-27T01:00:00Z", "series": [1, 2]})
    P.publish(store, stage, scope=["data/points"], now=datetime(2026, 11, 27, 1, tzinfo=timezone.utc))
    stored_before = store.get("v1/data/points/alta.json")
    _doc(stage / "data" / "points" / "alta.json", {"id": "alta", "generated_at": "2026-11-27T07:00:00Z", "series": [1, 2]})
    res = P.publish(store, stage, scope=["data/points"], now=datetime(2026, 11, 27, 7, tzinfo=timezone.utc))
    assert (res["put"], res["skip"], res["changes"]) == (0, 1, 0)
    assert store.get("v1/data/points/alta.json") == stored_before            # nothing was uploaded
    man = P.load_manifest(store)["objects"]["v1/data/points/alta.json"]
    assert man["sha256"] == hashlib.sha256(stored_before).hexdigest()       # the manifest describes what is stored
    assert store.get("v1/_runs/20261127T070000Z.json") is not None          # the run is still logged
    assert store.get("v1/_changes/20261127T070000Z.json") is None           # but no content changed


def test_content_change_is_uploaded_and_logged(tmp_path):
    stage, store = tmp_path / "stage", LocalStore(tmp_path / "store")
    _doc(stage / "data" / "points" / "alta.json", {"id": "alta", "series": [1, 2]})
    P.publish(store, stage, scope=["data/points"], now=datetime(2026, 11, 27, 1, tzinfo=timezone.utc))
    _doc(stage / "data" / "points" / "alta.json", {"id": "alta", "series": [1, 3]})
    res = P.publish(store, stage, scope=["data/points"], now=datetime(2026, 11, 27, 7, tzinfo=timezone.utc))
    assert (res["put"], res["changes"]) == (1, 1)
    change = json.loads(store.get("v1/_changes/20261127T070000Z.json"))["changes"][0]
    assert change["key"] == "v1/data/points/alta.json" and change["change"] == "changed"
    assert change["old_content_sha256"] != change["new_content_sha256"]
    run = json.loads(store.get("v1/_runs/20261127T070000Z.json"))
    assert run["counts"] == {"files": 1, "baseline": 0, "new": 0, "changed": 1, "unchanged": 0, "deleted": 0}


def test_new_and_deleted_objects_are_logged(tmp_path):
    stage, store = tmp_path / "stage", LocalStore(tmp_path / "store")
    _doc(stage / "data" / "points" / "alta.json", {"id": "alta"})
    _doc(stage / "data" / "points" / "vail.json", {"id": "vail"})
    P.publish(store, stage, scope=["data/points"], now=datetime(2026, 11, 27, 1, tzinfo=timezone.utc))
    (stage / "data" / "points" / "vail.json").unlink()
    _doc(stage / "data" / "points" / "bear.json", {"id": "bear"})
    res = P.publish(store, stage, scope=["data/points"], prune=True, now=datetime(2026, 11, 27, 7, tzinfo=timezone.utc))
    changes = {c["key"]: c["change"] for c in json.loads(store.get("v1/_changes/20261127T070000Z.json"))["changes"]}
    assert changes == {"v1/data/points/bear.json": "new", "v1/data/points/vail.json": "deleted"}
    assert res["changes"] == 2


def test_older_manifest_without_content_hashes_is_uploaded_once(tmp_path):
    stage, store = tmp_path / "stage", LocalStore(tmp_path / "store")
    _doc(stage / "data" / "points" / "alta.json", {"id": "alta", "generated_at": "x"})
    P.publish(store, stage, scope=["data/points"])
    man = json.loads(store.get("v1/_manifest.json"))
    for v in man["objects"].values():
        v.pop("content_sha256", None)                                       # what a manifest written before this step looks like
    store.put("v1/_manifest.json", json.dumps(man).encode(), "application/json")
    res = P.publish(store, stage, scope=["data/points"])
    assert res["put"] == 1


def test_dry_run_writes_no_logs(tmp_path):
    stage, store = tmp_path / "stage", LocalStore(tmp_path / "store")
    _doc(stage / "data" / "points" / "alta.json", {"id": "alta"})
    P.publish(store, stage, scope=["data/points"], dry_run=True)
    assert not (tmp_path / "store" / "v1" / "_runs").exists()
    assert not (tmp_path / "store" / "v1" / "_manifest.json").exists()


def test_first_publish_into_an_empty_store_is_baseline(tmp_path):
    stage, store = tmp_path / "stage", LocalStore(tmp_path / "store")
    _doc(stage / "data" / "points" / "alta.json", {"id": "alta"})
    res = P.publish(store, stage, scope=["data/points"], now=datetime(2026, 11, 27, 1, tzinfo=timezone.utc))
    kinds = [c["change"] for c in json.loads(store.get("v1/_changes/20261127T010000Z.json"))["changes"]]
    assert kinds == ["baseline"]
    assert json.loads(store.get("v1/_runs/20261127T010000Z.json"))["counts"]["baseline"] == 1


def test_older_manifest_objects_are_baseline_not_changed(tmp_path):
    stage, store = tmp_path / "stage", LocalStore(tmp_path / "store")
    _doc(stage / "data" / "points" / "alta.json", {"id": "alta", "series": [1]})
    P.publish(store, stage, scope=["data/points"])
    man = json.loads(store.get("v1/_manifest.json"))
    man["objects"]["v1/data/points/alta.json"].pop("content_sha256")
    store.put("v1/_manifest.json", json.dumps(man).encode(), "application/json")
    _doc(stage / "data" / "points" / "alta.json", {"id": "alta", "series": [2]})
    P.publish(store, stage, scope=["data/points"], now=datetime(2026, 11, 27, 7, tzinfo=timezone.utc))
    kinds = [c["change"] for c in json.loads(store.get("v1/_changes/20261127T070000Z.json"))["changes"]]
    assert kinds == ["baseline"]


# ---------- step 2: forecast issue history, retention, field summaries ----------

from ingester import history as H


def _issue(cycle, snow24=0.0, tag="Dry", content="a" * 64):
    return {"id": "alta", "cycle": cycle, "liquid_cycle": cycle, "issued": cycle, "generated_at": "x",
            "summary": {"tag": tag, "confidence": "high"},
            "points": {"summit": {"totals": {"24h": {"snow_in": snow24}, "48h": {"snow_in": 1}, "72h": {"snow_in": 2}}},
                       "base": {"totals": {"24h": {"snow_in": 0}, "48h": {"snow_in": 0}, "72h": {"snow_in": 0}}}}}


def test_watched_changes_lists_only_changed_fields():
    fields = H.watched_changes(_issue("2026112712", snow24=0.0), _issue("2026112719", snow24=3.5, tag="Heavy snow"))
    assert fields == {"summary.tag": ["Dry", "Heavy snow"], "points.summit.totals.24h.snow_in": [0.0, 3.5]}


def test_retention_keeps_30_days_then_one_issue_per_day():
    now = datetime(2026, 12, 31, tzinfo=timezone.utc)
    recent = [{"cycle": f"202612{d:02d}{h:02d}"} for d in range(20, 32) for h in (1, 7, 13, 19)]
    old = [{"cycle": f"202611{d:02d}{h:02d}"} for d in range(1, 10) for h in (1, 7, 13, 19)]   # more than 30 days old
    kept, expired = H.retention(old + recent, now)
    assert all(e in kept for e in recent)
    kept_old = [e["cycle"] for e in kept if e in old]
    assert kept_old == [f"202611{d:02d}19" for d in range(1, 10)]          # the newest issue of each old day
    assert len(expired) == 9 * 3


def test_area_history_is_stored_once_per_content_and_indexed(tmp_path):
    store = LocalStore(tmp_path / "store")
    now = datetime(2026, 11, 28, 1, tzinfo=timezone.utc)
    d1 = _issue("2026112712")
    assert H.update_area_history(store, "v1", "alta", d1, "c1" * 32, now) == {"written": 1, "expired": 0}
    assert H.update_area_history(store, "v1", "alta", d1, "c1" * 32, now) == {"written": 0, "expired": 0}   # same content: no-op
    d2 = _issue("2026112719", snow24=3.5)
    H.update_area_history(store, "v1", "alta", d2, "c2" * 32, now)
    index = json.loads(store.get("v1/history/points/alta/index.json"))
    assert [e["cycle"] for e in index["issues"]] == ["2026112712", "2026112719"]
    assert store.get(index["issues"][1]["key"]) is not None


def test_publish_records_history_and_field_changes(tmp_path):
    stage, store = tmp_path / "stage", LocalStore(tmp_path / "store")
    _doc(stage / "data" / "points" / "alta.json", _issue("2026112712"))
    P.publish(store, stage, scope=["data/points"], now=datetime(2026, 11, 28, 1, tzinfo=timezone.utc))
    run1 = json.loads(store.get("v1/_runs/20261128T010000Z.json"))
    assert run1["history"] == {"written": 1, "expired": 0}
    assert not json.loads(store.get("v1/_changes/20261128T010000Z.json"))["changes"][0].get("fields")   # baseline: no field summary
    _doc(stage / "data" / "points" / "alta.json", _issue("2026112719", snow24=3.5, tag="Heavy snow"))
    P.publish(store, stage, scope=["data/points"], now=datetime(2026, 11, 28, 7, tzinfo=timezone.utc))
    change = json.loads(store.get("v1/_changes/20261128T070000Z.json"))["changes"][0]
    assert change["fields"]["summary.tag"] == ["Dry", "Heavy snow"]
    assert change["fields"]["points.summit.totals.24h.snow_in"] == [0.0, 3.5]
    index = json.loads(store.get("v1/history/points/alta/index.json"))
    assert len(index["issues"]) == 2
    assert store.get("v1/_manifest.json") and "v1/history/points/alta/index.json" not in P.load_manifest(store)["objects"]


def test_history_ignores_folder_summaries_and_non_forecast_files(tmp_path):
    stage, store = tmp_path / "stage", LocalStore(tmp_path / "store")
    _doc(stage / "data" / "points" / "summary.json", {"cycle": "2026112712", "points": {}})
    _doc(stage / "data" / "points" / "alta.json", {"id": "alta"})                 # an area file without a forecast
    res = P.publish(store, stage, scope=["data/points"])
    assert res["history"] == {"written": 0, "expired": 0}


# ---------- step 3: observation history (SNOTEL and ASOS) ----------

from ingester import obs_history as OH


def _station(times, wteq, triplet="1000:OR:SNTL", offset=-8.0):
    return {"triplet": triplet, "name": "Annie Springs", "utc_offset_h": offset, "times": times,
            "WTEQ": wteq, "SNWD": [10.0] * len(times), "PREC": [3.9] * len(times), "TOBS": [31.6] * len(times),
            "SNWD_med3": [9.5] * len(times)}


def test_snotel_local_standard_times_become_utc_rows():
    rows = OH.snotel_rows(_station(["2026-11-27 22:00"], [2.2]))
    assert rows == {"2026-11-28T06:00Z": {"WTEQ": 2.2, "SNWD": 10.0, "PREC": 3.9, "TOBS": 31.6}}


def test_overlapping_windows_add_each_reading_once(tmp_path):
    store = LocalStore(tmp_path / "store")
    now = datetime(2026, 11, 28, 1, tzinfo=timezone.utc)
    w1 = OH.snotel_rows(_station(["2026-11-27 20:00", "2026-11-27 21:00", "2026-11-27 22:00"], [2.0, 2.1, 2.2]))
    w2 = OH.snotel_rows(_station(["2026-11-27 21:00", "2026-11-27 22:00", "2026-11-27 23:00"], [2.1, 2.2, 2.3]))
    r1 = OH.update_station(store, "v1", "snotel", "1000:OR:SNTL", "Annie Springs", w1, now)
    r2 = OH.update_station(store, "v1", "snotel", "1000:OR:SNTL", "Annie Springs", w2, now)
    assert r1["added"] == 3 and r2["added"] == 1 and r2["revised"] == 0
    month = json.loads(store.get("v1/history/obs/snotel/1000_OR_SNTL/2026-11.json"))
    assert len(month["rows"]) == 4 and month["revisions"] == []


def test_a_revised_reading_is_updated_and_kept_in_revisions(tmp_path):
    store = LocalStore(tmp_path / "store")
    now = datetime(2026, 11, 28, 1, tzinfo=timezone.utc)
    OH.update_station(store, "v1", "snotel", "1000:OR:SNTL", "Annie", OH.snotel_rows(_station(["2026-11-27 22:00"], [2.2])), now)
    res = OH.update_station(store, "v1", "snotel", "1000:OR:SNTL", "Annie", OH.snotel_rows(_station(["2026-11-27 22:00"], [2.5])), now)
    assert res["revised"] == 1 and res["revisions"][0]["old"] == 2.2 and res["revisions"][0]["new"] == 2.5
    month = json.loads(store.get("v1/history/obs/snotel/1000_OR_SNTL/2026-11.json"))
    assert month["rows"]["2026-11-28T06:00Z"]["WTEQ"] == 2.5 and month["revisions"][0]["old"] == 2.2


def test_months_are_split_and_indexed(tmp_path):
    store = LocalStore(tmp_path / "store")
    now = datetime(2026, 12, 1, 1, tzinfo=timezone.utc)
    rows = OH.snotel_rows(_station(["2026-11-30 22:00", "2026-12-01 01:00"], [1.0, 1.5], offset=0.0))
    res = OH.update_station(store, "v1", "snotel", "1000:OR:SNTL", "Annie", rows, now)
    assert res["months_written"] == 2
    index = json.loads(store.get("v1/history/obs/snotel/1000_OR_SNTL/index.json"))
    assert index["months"]["2026-11"]["rows"] == 1 and index["months"]["2026-12"]["last"] == "2026-12-01T01:00Z"


def test_asos_latest_reports_accumulate_into_history(tmp_path):
    stage, store = tmp_path / "stage", LocalStore(tmp_path / "store")
    def asos(valid, temp):
        return {"features": [{"properties": {"id": "CLM", "name": "Port Angeles", "valid_utc": valid, "temp_f": temp,
                                              "wind_kt": 5, "precip_today_in": 0.03, "metar": "x"}}]}
    _doc(stage / "data" / "asos.geojson", asos("2026-11-28T06:53Z", 45.0))
    P.publish(store, stage, scope=["data/asos.geojson"], now=datetime(2026, 11, 28, 7, tzinfo=timezone.utc))
    _doc(stage / "data" / "asos.geojson", asos("2026-11-28T07:53Z", 46.0))
    res = P.publish(store, stage, scope=["data/asos.geojson"], now=datetime(2026, 11, 28, 8, tzinfo=timezone.utc))
    assert res["obs_history"] == {"added": 1, "revised": 0, "stations": 1}
    month = json.loads(store.get("v1/history/obs/asos/CLM/2026-11.json"))
    assert set(month["rows"]) == {"2026-11-28T06:53Z", "2026-11-28T07:53Z"} and "metar" not in month["rows"]["2026-11-28T07:53Z"]


def test_publish_logs_observation_revisions_in_the_change_record(tmp_path):
    stage, store = tmp_path / "stage", LocalStore(tmp_path / "store")
    _doc(stage / "data" / "snotel" / "1000_OR_SNTL.json", _station(["2026-11-27 22:00"], [2.2]))
    P.publish(store, stage, scope=["data/snotel"], now=datetime(2026, 11, 28, 1, tzinfo=timezone.utc))
    _doc(stage / "data" / "snotel" / "1000_OR_SNTL.json", _station(["2026-11-27 22:00"], [2.6]))
    P.publish(store, stage, scope=["data/snotel"], now=datetime(2026, 11, 28, 2, tzinfo=timezone.utc))
    change = json.loads(store.get("v1/_changes/20261128T020000Z.json"))["changes"][0]
    assert change["revisions"][0]["old"] == 2.2 and change["revisions"][0]["new"] == 2.6


def test_unchanged_station_without_history_is_recorded_on_the_next_publish(tmp_path):
    stage, store = tmp_path / "stage", LocalStore(tmp_path / "store")
    _doc(stage / "data" / "snotel" / "1000_OR_SNTL.json", _station(["2026-11-27 22:00"], [2.2]))
    P.publish(store, stage, scope=["data/snotel"], history=False, now=datetime(2026, 11, 28, 1, tzinfo=timezone.utc))
    assert store.get("v1/history/obs/snotel/1000_OR_SNTL/index.json") is None
    res = P.publish(store, stage, scope=["data/snotel"], now=datetime(2026, 11, 28, 2, tzinfo=timezone.utc))
    assert res["put"] == 0                                                   # the file did not change...
    assert res["obs_history"]["added"] == 1                                  # ...but its readings are now recorded
    assert store.get("v1/history/obs/snotel/1000_OR_SNTL/index.json") is not None


# ---------- step 3b: alert history and ECMWF / GEFS plume history ----------

from ingester import alert_history as AH


def _alerts(*ids, expires="2026-11-28T17:15:00-07:00"):
    return {"alerts": {i: {"event": "Winter Storm Warning", "severity": "Severe", "expires": expires} for i in ids}}


def test_alert_lifecycle_open_update_close_reopen(tmp_path):
    store = LocalStore(tmp_path / "store")
    t1, t2, t3, t4 = (datetime(2026, 11, 28, h, tzinfo=timezone.utc) for h in (1, 2, 3, 4))
    r = AH.update_alerts(store, "v1", _alerts("a1", "a2"), {"a1": {"description": "heavy"}}, t1)
    assert r == {"opened": ["a1", "a2"], "closed": [], "updated": []}
    r = AH.update_alerts(store, "v1", _alerts("a1", expires="2026-11-28T21:00:00-07:00"), {"a1": {"description": "heavy"}}, t2)
    assert r == {"opened": [], "closed": ["a2"], "updated": ["a1"]}
    r = AH.update_alerts(store, "v1", _alerts("a1", "a2"), {"a1": {"description": "heavy"}}, t3)
    assert r["opened"] == ["a2"]                                              # back after being closed
    index = json.loads(store.get("v1/history/alerts/index.json"))["alerts"]
    assert index["a2"]["closed_at"] is None and index["a1"]["versions"] == 3     # expiry 17:15, then 21:00, then 17:15 again
    versions = json.loads(store.get("v1/history/alerts/a1.json"))["versions"]
    assert [v["fields"]["expires"][11:16] for v in versions] == ["17:15", "21:00", "17:15"]


def test_publish_records_alert_changes_and_plume_history(tmp_path):
    stage, store = tmp_path / "stage", LocalStore(tmp_path / "store")
    now = datetime(2026, 11, 28, 1, tzinfo=timezone.utc)
    _doc(stage / "data" / "alerts" / "index.json", _alerts("a1"))
    _doc(stage / "data" / "alerts" / "details.json", {"a1": {"description": "heavy"}})
    _doc(stage / "models" / "ecmwf" / "plume" / "alta.json", {"id": "alta", "cycle": "2026112712", "tp": [0.1, 0.2]})
    res = P.publish(store, stage, scope=["data/alerts", "models/ecmwf"], now=now)
    assert res["alert_history"] == {"opened": 1, "closed": 0, "updated": 0}
    assert res["model_history"] == {"written": 1, "expired": 0}
    assert store.get("v1/history/ecmwf/alta/index.json") is not None
    change = {c["key"]: c for c in json.loads(store.get("v1/_changes/20261128T010000Z.json"))["changes"]}
    assert change["v1/data/alerts/index.json"]["alerts"] == {"opened": ["a1"], "closed": [], "updated": []}


def test_plume_history_is_stored_per_cycle_and_indexed(tmp_path):
    store = LocalStore(tmp_path / "store")
    now = datetime(2026, 11, 28, 1, tzinfo=timezone.utc)
    H.update_area_history(store, "v1", "alta", {"id": "alta", "cycle": "2026112712", "tp": [0.1]}, "e1" * 32, now, family="ecmwf")
    H.update_area_history(store, "v1", "alta", {"id": "alta", "cycle": "2026112800", "tp": [0.2]}, "e2" * 32, now, family="ecmwf")
    index = json.loads(store.get("v1/history/ecmwf/alta/index.json"))
    assert [e["cycle"] for e in index["issues"]] == ["2026112712", "2026112800"]
    assert store.get("v1/history/points/alta/index.json") is None            # families stay separate
