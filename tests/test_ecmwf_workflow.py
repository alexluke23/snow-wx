"""dev18 Part 0f: the standalone ECMWF workflow (.github/workflows/ecmwf.yml). Offline checks: the YAML has the required keys and copies models.yml's action
versions; environment.yml covers every package pipeline/ecmwf.py (and what it imports) needs; the CLI exits 0 with new=false when the newest cycle is already
published or not yet released; and the upload/cleanup shell step ends with status 0 and deletes only OLD ecmwf assets (run under `bash -e` with a fake `gh`)."""
import ast
import os
import re
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from pipeline import ecmwf as E

REPO = Path(__file__).resolve().parents[1]
WF = REPO / ".github" / "workflows" / "ecmwf.yml"


def load(p):
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def on_of(doc):
    return doc.get("on") or doc.get(True)             # YAML 1.1 reads the bare key `on` as the boolean True


# ---------------------------------------------------------------- the workflow file
def test_workflow_yaml_has_the_required_keys():
    d = load(WF)
    on = on_of(d)
    assert d["name"] and on["schedule"] == [{"cron": "40 9,11,21,23 * * *"}]                  # schedule ACTIVE
    inputs = on["workflow_dispatch"]["inputs"]["force"]
    assert inputs["type"] == "boolean" and inputs["default"] is False
    assert d["permissions"] == {"contents": "write", "actions": "write"}
    assert d["concurrency"] == {"group": "ecmwf", "cancel-in-progress": False}                # its own group, never model-maps
    assert d["env"]["RELEASE"] == "model-maps" and d["env"]["MODEL"] == "ecmwf"
    job = d["jobs"]["ecmwf"]
    assert job["runs-on"] == "ubuntu-24.04" and job["timeout-minutes"] == 30
    names = [s.get("name") or s.get("uses") for s in job["steps"]]
    assert names == ["actions/checkout@v7", "mamba-org/setup-micromamba@v3", "Find the published cycle", "Restore the resume cache",
                     "Fetch, sample, write", "Save the resume cache", "Upload to the model-maps release", "Redeploy the site"]
    by = {s.get("name"): s for s in job["steps"] if s.get("name")}
    assert by["Upload to the model-maps release"]["if"] == "steps.render.outputs.new == 'true'" == by["Redeploy the site"]["if"]
    assert "gh workflow run update-site.yml" in by["Redeploy the site"]["run"]


def test_resume_cache_steps_restore_before_and_save_always_after_the_python_step():
    steps = load(WF)["jobs"]["ecmwf"]["steps"]
    names = [s.get("name") for s in steps]
    assert names.index("Restore the resume cache") < names.index("Fetch, sample, write") < names.index("Save the resume cache")
    restore = steps[names.index("Restore the resume cache")]
    save = steps[names.index("Save the resume cache")]
    assert restore["uses"] == "actions/cache/restore@v6" and save["uses"] == "actions/cache/save@v6"                       # the same major as models.yml's actions/cache@v6
    assert restore["with"]["path"] == save["with"]["path"] == "data_cache/ecmwf" and restore["with"]["restore-keys"].strip() == "ecmwf-"
    assert save["if"] == "always()" and "run_id" in save["with"]["key"] and "run_attempt" in save["with"]["key"]            # always, and a fresh key per attempt (a cache key is immutable)
    models_cache = {s["uses"] for job in load(REPO / ".github" / "workflows" / "models.yml")["jobs"].values() for s in job["steps"] if s.get("uses", "").startswith("actions/cache")}
    assert "actions/cache@v6" in models_cache


def test_action_versions_are_copied_from_models_yml():
    def uses(p):
        out = {}
        for job in load(p)["jobs"].values():
            for s in job["steps"]:
                if "uses" in s:
                    out[s["uses"].split("@")[0]] = s["uses"]
        return out
    mine, models = uses(WF), uses(REPO / ".github" / "workflows" / "models.yml")
    for action in ("actions/checkout", "mamba-org/setup-micromamba"):
        assert mine[action] == models[action], f"{action}: use the version models.yml uses"


def test_the_old_cleanup_form_that_ends_with_status_1_is_gone():
    run = next(s for s in load(WF)["jobs"]["ecmwf"]["steps"] if s.get("name") == "Upload to the model-maps release")["run"]
    assert "&& gh release delete-asset" not in run and 'if [ "$old" != "$asset" ]; then' in run and run.rstrip().endswith("done")


# ---------------------------------------------------------------- environment.yml covers the imports
STDLIB = set(sys.stdlib_module_names)
CONDA = {"numpy": "numpy", "requests": "requests", "urllib3": "requests", "yaml": "pyyaml", "eccodes": "eccodes", "scipy": "scipy", "pandas": "pandas",
         "xarray": "xarray", "cfgrib": "cfgrib", "herbie": "herbie-data", "matplotlib": "matplotlib", "metpy": "metpy", "cartopy": "cartopy", "netCDF4": "netcdf4"}


def third_party_imports(path: Path, seen: set) -> set:
    """top-level third-party modules imported (at module level or inside functions) by `path` and the pipeline modules it pulls in"""
    if path in seen or not path.exists():
        return set()
    seen.add(path)
    found = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    pkg = path.parent
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                found.add(a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:                                                                  # relative: another pipeline module
                base = pkg
                for _ in range(node.level - 1):
                    base = base.parent
                parts = (node.module or "").split(".") if node.module else []
                cand = base.joinpath(*parts) if parts else base
                for target in ([cand.with_suffix(".py"), cand / "__init__.py"] + [cand / f"{n.name}.py" for n in node.names]):
                    found |= third_party_imports(target, seen)
            elif node.module:
                found.add(node.module.split(".")[0])
    return found


def test_environment_yml_has_every_package_the_ecmwf_job_imports():
    mods = {m for m in third_party_imports(REPO / "pipeline" / "ecmwf.py", set()) if m not in STDLIB and m not in ("pipeline", "__future__")}
    assert {"numpy", "eccodes", "requests", "yaml"} <= mods                                  # the walk really saw the lazy imports (decode, load_config)
    env = {re.split(r"[<>=\s]", d)[0] for d in load(REPO / "environment.yml")["dependencies"] if isinstance(d, str)}
    missing = sorted(m for m in mods if CONDA.get(m, m) not in env)
    assert not missing, f"environment.yml lacks packages for: {missing}"


# ---------------------------------------------------------------- the CLI: new=false exits 0
class Mirror:
    """HEAD answers 200 only for cycles in `released`; everything else 404 (an upstream cycle that is not out yet)"""
    def __init__(self, released):
        self.released, self.headers, self.gets = set(released), {}, []

    def head(self, u, **k):
        return type("R", (), {"status_code": 200 if any(f"/{c[:8]}/{c[8:]}z/" in u for c in self.released) else 404})()

    def get(self, u, **k):
        self.gets.append(u)
        raise AssertionError("nothing may be downloaded when there is nothing new")


def cli(tmp_path, monkeypatch, mirror, now, published=None, enabled=True):
    from pipeline import __main__ as M
    from pipeline.common import load_config
    cfg = load_config()
    cfg["ecmwf"]["enabled"] = enabled
    monkeypatch.setattr(M, "load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(M, "make_session", lambda c: mirror)
    monkeypatch.setattr(E, "utcnow", lambda: now)
    gh = tmp_path / "gh.txt"
    argv = ["ecmwf", "--out", str(tmp_path / "out"), "--github-output", str(gh)] + (["--published", published] if published else [])
    return M.main(argv), gh.read_text(encoding="utf-8") if gh.exists() else ""


def test_cli_exits_0_with_new_false_when_the_newest_cycle_is_already_published(tmp_path, monkeypatch):
    from pipeline.version import stamp
    now = datetime(2026, 11, 18, 11, 0, tzinfo=timezone.utc)                                 # 00Z is 11 h old: released
    code, out = cli(tmp_path, monkeypatch, Mirror(["2026111800", "2026111712"]), now, published=stamp("2026111800", "ecmwf"))
    assert code == 0 and "new=false" in out and "cycle=2026111800-" in out and not (tmp_path / "out").exists()


def test_cli_exits_0_with_new_false_when_the_next_cycle_is_not_released_upstream_yet(tmp_path, monkeypatch):
    from pipeline.version import stamp
    now = datetime(2026, 11, 18, 21, 0, tzinfo=timezone.utc)                                 # 12Z is 9 h old, but its files are not on the mirror yet
    code, out = cli(tmp_path, monkeypatch, Mirror(["2026111800", "2026111712"]), now, published=stamp("2026111800", "ecmwf"))
    assert code == 0 and "new=false" in out and "new=true" not in out and not (tmp_path / "out").exists()


def test_cli_exits_0_with_new_false_when_the_mirror_has_no_complete_cycle_at_all(tmp_path, monkeypatch):
    code, out = cli(tmp_path, monkeypatch, Mirror([]), datetime(2026, 11, 18, 21, 0, tzinfo=timezone.utc))
    assert code == 0 and "new=false" in out and not (tmp_path / "out").exists()


def test_cli_with_the_flag_off_does_nothing_and_says_so(tmp_path, monkeypatch):
    code, out = cli(tmp_path, monkeypatch, Mirror(["2026111800"]), datetime(2026, 11, 18, 21, 0, tzinfo=timezone.utc), enabled=False)
    assert code == 0 and "new=false" in out


# ---------------------------------------------------------------- the upload / cleanup step under `bash -e` with a fake gh
BASH = shutil.which("bash")
FAKE_GH = r"""#!/bin/bash
# fake gh: state in $FAKE_DIR (assets.txt = what the release lists, calls.txt = every call)
echo "gh $*" >> "$FAKE_DIR/calls.txt"
case "$1 $2" in
  "release view")
    if [[ "$*" == *"--json"* ]]; then cat "$FAKE_DIR/assets.txt"; fi
    exit 0 ;;
  "release upload") grep -qx "$4" "$FAKE_DIR/assets.txt" || echo "$4" >> "$FAKE_DIR/assets.txt"; exit 0 ;;
  "release delete-asset") grep -vx "$4" "$FAKE_DIR/assets.txt" > "$FAKE_DIR/a2.txt"; mv "$FAKE_DIR/a2.txt" "$FAKE_DIR/assets.txt"; exit 0 ;;
esac
exit 0
"""
NEW = "ecmwf-2026111812-abcd1234.tar"
OLD1, OLD2 = "ecmwf-2026111800-abcd1234.tar", "ecmwf-2026111712.tar"
OTHERS = ["hrrr-2026111812.tar", "points-2026111808-0123abcd.tar", "ecmwf-notes.txt", "gfs-2026111812-aaaaaaaa.tar"]


def run_upload(tmp_path, assets):
    step = next(s for s in load(WF)["jobs"]["ecmwf"]["steps"] if s.get("name") == "Upload to the model-maps release")["run"]
    script = step.replace("${{ steps.render.outputs.cycle }}", "2026111812-abcd1234")
    work = tmp_path / "work"
    (work / "out" / "models" / "ecmwf").mkdir(parents=True)
    (work / "out" / "models" / "ecmwf" / "index.json").write_text("{}", encoding="utf-8")
    fake = tmp_path / "bin"
    fake.mkdir()
    gh = fake / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8", newline="\n")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    st = tmp_path / "state"
    st.mkdir()
    (st / "assets.txt").write_text("\n".join(assets) + ("\n" if assets else ""), encoding="utf-8", newline="\n")
    (st / "calls.txt").write_text("", encoding="utf-8")
    env = {**os.environ, "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}", "FAKE_DIR": str(st).replace("\\", "/"), "RELEASE": "model-maps", "MODEL": "ecmwf"}
    r = subprocess.run([BASH, "-e", "-c", script], cwd=work, env=env, capture_output=True, text=True)
    calls = (st / "calls.txt").read_text(encoding="utf-8").splitlines()
    deleted = [c.split()[4] for c in calls if c.startswith("gh release delete-asset")]
    left = (st / "assets.txt").read_text(encoding="utf-8").split()
    return r, deleted, left, calls


@pytest.mark.skipif(not BASH, reason="bash not available")
@pytest.mark.parametrize("assets,deleted", [
    ([], []),                                               # no old assets
    ([NEW], []),                                            # only the new asset (a re-run of the same cycle)
    ([OLD1, NEW], [OLD1]),                                  # old plus new
    ([OLD1, OLD2], [OLD1, OLD2]),                           # only old ones
    ([OLD2, *OTHERS, NEW], [OLD2]),                         # other products and a non-tar ecmwf file are never touched
], ids=["none", "only-new", "old-and-new", "only-old", "bystanders"])
def test_upload_step_ends_with_status_0_and_deletes_only_old_ecmwf_assets(tmp_path, assets, deleted):
    r, dels, left, calls = run_upload(tmp_path, assets)
    assert r.returncode == 0, r.stderr
    assert sorted(dels) == sorted(deleted)
    assert NEW in left and not [a for a in left if a.startswith("ecmwf-") and a.endswith(".tar") and a != NEW]
    assert all(o in left for o in OTHERS if o in assets)                                   # bystanders survive
    assert any(c.startswith("gh release upload model-maps ecmwf-2026111812-abcd1234.tar --clobber") for c in calls)


@pytest.mark.skipif(not BASH, reason="bash not available")
def test_the_old_shell_form_really_did_end_with_status_1(tmp_path):
    """the bug the fix addresses: when the loop is the LAST statement of the step, `[ test ] && cmd` leaves the loop (and so the whole step script) at status 1
    as soon as the last item fails the test (set -e does not fire inside an && list, but the script's exit status is the loop's): the step goes red and the redeploy is skipped"""
    old = 'for old in a b; do [ "$old" != "b" ] && echo delete $old; done'
    new = 'for old in a b; do if [ "$old" != "b" ]; then echo delete $old; fi; done'
    assert subprocess.run([BASH, "-e", "-c", old], capture_output=True, text=True).returncode == 1
    assert subprocess.run([BASH, "-e", "-c", new], capture_output=True, text=True).returncode == 0
