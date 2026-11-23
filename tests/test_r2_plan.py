"""dev23 Part 6 (W1 staging prep): the R2 sync PLAN printer and the config-driven redirect-stub target. Nothing uploads, nothing is enabled, no domain is named."""
import json
import re
import subprocess
import sys
from pathlib import Path

from pipeline import r2_plan as R
from pipeline import stub
from pipeline.common import load_config

REPO = Path(__file__).resolve().parents[1]


def make_data(tmp_path):
    d = tmp_path / "data"
    (d / "points" / "layers").mkdir(parents=True)
    (d / "points" / "alta-ski-area.json").write_text('{"id":"alta"}', encoding="utf-8")
    (d / "points" / "summary.json").write_text('{"areas":[]}', encoding="utf-8")
    (d / "points" / "layers" / "index.json").write_text("{}", encoding="utf-8")
    (d / "snotel").mkdir()
    (d / "snotel" / "x.json").write_text("{}", encoding="utf-8")                       # not a configured prefix: never part of the plan
    return d


def test_the_flags_are_off_and_nothing_names_a_bucket_or_domain():
    cfg = load_config()
    assert cfg["r2"] == {"enabled": False, "bucket": "", "prefixes": ["points"], "key_prefix": "data/"}
    assert cfg["site"]["stub_target_origin"] == "" and cfg["site"]["stub_target_base_path"] == ""


def test_scan_lists_only_the_configured_folders_with_posix_keys_and_hashes(tmp_path):
    local = R.scan(make_data(tmp_path), ["points"], "data/")
    assert [f["key"] for f in local] == ["data/points/alta-ski-area.json", "data/points/layers/index.json", "data/points/summary.json"]
    assert all(len(f["sha1"]) == 40 and f["content_type"] == "application/json" for f in local)


def test_plan_first_sync_then_only_changes(tmp_path):
    d = make_data(tmp_path)
    local = R.scan(d, ["points"])
    first = R.make_plan(local, None)
    assert first["first_sync"] and len(first["put"]) == 3 and first["skip"] == [] and first["delete"] == []
    prev = {f["key"]: f["sha1"] for f in local} | {"data/points/old-area.json": "0" * 40}
    (d / "points" / "summary.json").write_text('{"areas":[1]}', encoding="utf-8")        # one changed file
    (d / "points" / "new-area.json").write_text("{}", encoding="utf-8")                  # one new file
    plan = R.make_plan(R.scan(d, ["points"]), prev)
    assert sorted(f["key"] for f in plan["put"]) == ["data/points/new-area.json", "data/points/summary.json"]
    assert len(plan["skip"]) == 2 and plan["delete"] == ["data/points/old-area.json"] and not plan["first_sync"]


def test_render_says_it_only_prints_and_warns_about_big_files():
    cfg = {"enabled": False, "bucket": "", "prefixes": ["points"], "key_prefix": "data/"}
    local = [{"key": "data/points/a.json", "path": "x", "size": 120_000, "sha1": "a" * 40, "content_type": "application/json"},
             {"key": "data/points/big.json", "path": "y", "size": 30 * 1024 * 1024, "sha1": "b" * 40, "content_type": "application/json"}]
    text = R.render(R.make_plan(local, None), cfg, local)
    assert "r2.enabled=false" in text and "nothing is uploaded" in text and "<set by owner at W1>" in text
    assert "PUT 2" in text and "Cache-Control: public, max-age=60" in text and "WARNING: 1 file(s) over 25 MiB" in text and "Class A" in text
    on = R.render(R.make_plan(local, None), {**cfg, "enabled": True}, local)
    assert "r2.enabled=true in config, but this command only prints" in on


def test_the_command_prints_writes_only_a_local_manifest_and_has_no_network_code(tmp_path):
    d = make_data(tmp_path)
    man = tmp_path / "m.json"
    r = subprocess.run([sys.executable, "-m", "pipeline", "r2-plan", "--data", str(d), "--write-manifest", str(man)], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert "PUT 3" in r.stdout and "r2.enabled=false" in r.stdout
    assert set(json.loads(man.read_text(encoding="utf-8"))["objects"]) == {"data/points/alta-ski-area.json", "data/points/layers/index.json", "data/points/summary.json"}
    again = subprocess.run([sys.executable, "-m", "pipeline", "r2-plan", "--data", str(d), "--prev", str(man)], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    assert "PUT 0" in again.stdout and "skip 3" in again.stdout
    src = (REPO / "pipeline" / "r2_plan.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+(boto3?|botocore|requests|urllib|socket|http|subprocess|aiohttp)\b", src, re.M)


def test_stub_without_a_configured_target_writes_nothing(tmp_path):
    r = subprocess.run([sys.executable, "-m", "pipeline", "stub", "--out", str(tmp_path / "stub")], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert "nothing written" in r.stdout and "set by owner at W1" in r.stdout and not (tmp_path / "stub").exists()


def test_stub_target_comes_from_config_when_no_flag_is_given(tmp_path, monkeypatch):
    cfg = tmp_path / "s.yml"
    cfg.write_text((REPO / "config" / "settings.yml").read_text(encoding="utf-8").replace('stub_target_origin: ""', 'stub_target_origin: "https://staging.example.test"'), encoding="utf-8")
    r = subprocess.run([sys.executable, "-m", "pipeline", "stub", "--out", str(tmp_path / "stub"), "--config", str(cfg)], cwd=REPO, capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert 'href="https://staging.example.test/"' in (tmp_path / "stub" / "index.html").read_text(encoding="utf-8")
    assert stub.new_url("https://staging.example.test", "", "x") == "https://staging.example.test/x"
