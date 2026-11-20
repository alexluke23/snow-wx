"""dev21: the two new owner-authorized workflows, .github/workflows/verify.yml and gefs.yml. Offline checks: modelled on ecmwf.yml (same action versions, minimal
permissions, own concurrency group, resume/archive cache restore + save(always)), their release asset names are extracted by update-site.yml's EXISTING unpack step
into build/models/<product>/ (no edit there), the upload step deletes only this product's old assets, and verify's archive download never fails the job."""
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.test_ecmwf_workflow import FAKE_GH, load, on_of

REPO = Path(__file__).resolve().parents[1]
WFD = REPO / ".github" / "workflows"
BASH = shutil.which("bash")
SPEC = {"verify": {"file": "verify.yml", "cron": "25 15 * * *", "cache": "verify_archive", "timeout": 20},
        "gefs": {"file": "gefs.yml", "cron": "10 6,8,18,20 * * *", "cache": "data_cache/gefs", "timeout": 40}}


def uses(p):
    return {s["uses"].split("@")[0]: s["uses"] for job in load(p)["jobs"].values() for s in job["steps"] if "uses" in s}


@pytest.mark.parametrize("product", SPEC)
def test_modelled_on_ecmwf_yml(product):
    sp = SPEC[product]
    d = load(WFD / sp["file"])
    on = on_of(d)
    assert on["schedule"] == [{"cron": sp["cron"]}] and on["workflow_dispatch"]["inputs"]["force"]["type"] == "boolean"
    assert d["permissions"] == {"contents": "write", "actions": "write"}
    assert d["concurrency"] == {"group": product, "cancel-in-progress": False}
    assert d["env"]["RELEASE"] == "model-maps" and d["env"]["MODEL"] == product
    job = d["jobs"][product]
    assert job["runs-on"] == "ubuntu-24.04" and job["timeout-minutes"] == sp["timeout"]
    eu = uses(WFD / "ecmwf.yml")
    for action, ref in uses(WFD / sp["file"]).items():
        assert eu.get(action) == ref, f"{product}: {ref} must match ecmwf.yml ({eu.get(action)})"
    steps = job["steps"]
    names = [s.get("name") for s in steps]
    restore = next(s for s in steps if s.get("uses", "").startswith("actions/cache/restore"))
    save = next(s for s in steps if s.get("uses", "").startswith("actions/cache/save"))
    assert restore["with"]["path"] == save["with"]["path"] == sp["cache"] and save["if"] == "always()" and "run_attempt" in save["with"]["key"]
    assert names.index(restore["name"]) < names.index(save["name"])
    by = {s.get("name"): s for s in steps if s.get("name")}
    assert by["Upload to the model-maps release"]["if"] == "steps.render.outputs.new == 'true'" == by["Redeploy the site"]["if"]
    assert "gh workflow run update-site.yml" in by["Redeploy the site"]["run"]


def test_only_the_authorized_workflow_files_exist():
    assert sorted(p.name for p in WFD.glob("*.yml")) == ["ecmwf.yml", "gefs.yml", "models.yml", "tests.yml", "update-site.yml", "verify.yml"]


@pytest.mark.parametrize("product", SPEC)
def test_update_site_already_unpacks_the_asset_into_build_models(product):
    """the unpack loop in update-site.yml: product regex and destination (models/ unless points|nohrsc|ndfd)"""
    run = next(s for s in load(WFD / "update-site.yml")["jobs"]["build"]["steps"] if s.get("name") == "Fetch model maps (newest run per model)")["run"]
    rx = re.search(r"sed -n -E 's/(\^\(\[a-z0-9\]\+\)-[^/]+)/\\1/p'", run).group(1)
    m = re.match(rx.replace("\\.", r"\."), f"{product}-2026112012-abcd1234.tar")
    assert m and m.group(1) == product
    case = re.search(r"case \"\$m\" in ([a-z|]+)\) dest=build/data", run).group(1).split("|")
    assert product not in case                                                    # -> dest=build/models: build/models/<product>/...


@pytest.mark.skipif(not BASH, reason="bash not available")
@pytest.mark.parametrize("product", SPEC)
def test_upload_deletes_only_this_products_old_assets(tmp_path, product):
    step = next(s for s in load(WFD / SPEC[product]["file"])["jobs"][product]["steps"] if s.get("name") == "Upload to the model-maps release")["run"]
    script = step.replace("${{ steps.render.outputs.cycle }}", "2026112012-abcd1234")
    work = tmp_path / "work"
    (work / "out" / "models" / product).mkdir(parents=True)
    (work / "out" / "models" / product / "x.json").write_text("{}", encoding="utf-8")
    st, fake = tmp_path / "state", tmp_path / "bin"
    st.mkdir()
    fake.mkdir()
    gh = fake / "gh"
    gh.write_text(FAKE_GH, encoding="utf-8", newline="\n")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    others = ["ecmwf-2026112000-aaaaaaaa.tar", "points-2026112008-0123abcd.tar", "hrrr-2026112012.tar"]
    old = f"{product}-2026111912-abcd1234.tar"
    (st / "assets.txt").write_text("\n".join([old, *others]) + "\n", encoding="utf-8", newline="\n")
    (st / "calls.txt").write_text("", encoding="utf-8")
    env = {**os.environ, "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}", "FAKE_DIR": str(st).replace("\\", "/"), "RELEASE": "model-maps", "MODEL": product}
    r = subprocess.run([BASH, "-e", "-c", script], cwd=work, env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    left = (st / "assets.txt").read_text(encoding="utf-8").split()
    assert f"{product}-2026112012-abcd1234.tar" in left and old not in left and all(o in left for o in others)


FAKE_ARCHIVE_GH = r"""#!/bin/bash
echo "gh $*" >> "$FAKE_DIR/calls.txt"
case "$1 $2" in
  "release view") [ -f "$FAKE_DIR/list_fails" ] && exit 1; cat "$FAKE_DIR/assets.txt"; exit 0 ;;
  "release download") [ -f "$FAKE_DIR/dl_fails" ] && exit 1; for a in "$@"; do last=$a; done; touch "verify_archive/$5"; exit 0 ;;
esac
exit 0
"""


def run_download(tmp_path, assets, list_fails=False, dl_fails=False, cached=()):
    step = next(s for s in load(WFD / "verify.yml")["jobs"]["verify"]["steps"] if s.get("name") == "Download the forecast archive")["run"]
    work, st, fake = tmp_path / "work", tmp_path / "state", tmp_path / "bin"
    for d in (work / "verify_archive", st, fake):
        d.mkdir(parents=True)
    for c in cached:
        (work / "verify_archive" / c).write_text("x", encoding="utf-8")
    gh = fake / "gh"
    gh.write_text(FAKE_ARCHIVE_GH, encoding="utf-8", newline="\n")
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    (st / "assets.txt").write_text("\n".join(assets) + "\n", encoding="utf-8", newline="\n")
    (st / "calls.txt").write_text("", encoding="utf-8")
    if list_fails:
        (st / "list_fails").write_text("1")
    if dl_fails:
        (st / "dl_fails").write_text("1")
    out = tmp_path / "gh_output.txt"
    env = {**os.environ, "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}", "FAKE_DIR": str(st).replace("\\", "/"), "ARCHIVE": "verification", "GITHUB_OUTPUT": str(out).replace("\\", "/")}
    r = subprocess.run([BASH, "-e", "-c", step], cwd=work, env=env, capture_output=True, text=True)
    calls = (st / "calls.txt").read_text(encoding="utf-8").splitlines()
    return r, (out.read_text(encoding="utf-8") if out.exists() else ""), [c for c in calls if c.startswith("gh release download")]


@pytest.mark.skipif(not BASH, reason="bash not available")
def test_verify_download_never_fails_the_job(tmp_path):
    r, out, _ = run_download(tmp_path / "a", [], list_fails=True)
    assert r.returncode == 0 and "ok=false" in out
    r, out, _ = run_download(tmp_path / "b", ["nbm-209901.csv.gz", "snotel-209901.csv.gz"], dl_fails=True)
    assert r.returncode == 0 and "ok=false" in out


@pytest.mark.skipif(not BASH, reason="bash not available")
def test_verify_download_reuses_cached_closed_months(tmp_path):
    r, out, dls = run_download(tmp_path, ["nbm-202001.csv.gz", "snotel-202001.csv.gz", "state.json", "nbm-209912.csv.gz"], cached=["nbm-202001.csv.gz"])
    assert r.returncode == 0 and "ok=true" in out, r.stderr
    got = " ".join(dls)
    assert "nbm-202001" not in got and "snotel-202001" in got and "nbm-209912" in got and "state.json" not in got


def test_environment_has_pandas_for_the_scorer():
    env = {re.split(r"[<>=\s]", d)[0] for d in yaml.safe_load((REPO / "environment.yml").read_text(encoding="utf-8"))["dependencies"] if isinstance(d, str)}
    assert "pandas" in env and "numpy" in env
