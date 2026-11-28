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
