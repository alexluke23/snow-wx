"""dev23 Part 5: the external scheduler (infra/scheduler, a Cloudflare Worker; built, NOT deployed).

* every workflow it dispatches accepts workflow_dispatch (YAML check, no Node);
* its schedule table equals the real `schedule:` crons of the five workflows (drift guard; needs Node to read the JS table);
* the Node tests (`node --test`) pass (skipped when Node is missing);
* the Worker config stays within the free plan and carries no secret or account id."""
import json
import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SCHED = ROOT / "infra" / "scheduler"
WF = ROOT / ".github" / "workflows"
FILES = ["update-site.yml", "models.yml", "ecmwf.yml", "gefs.yml", "verify.yml"]


def node():
    for p in (shutil.which("node"), r"C:\miniforge3\envs\tools\node.exe"):
        if p and os.path.exists(p):
            return p
    return None


def on_of(path):
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    return d.get(True) or d.get("on")          # YAML 1.1 reads the key `on` as True


@pytest.mark.parametrize("file", FILES)
def test_every_dispatched_workflow_accepts_workflow_dispatch(file):
    assert "workflow_dispatch" in on_of(WF / file), f"{file} cannot be dispatched"


def test_wrangler_config_is_free_plan_and_secret_free():
    cfg = tomllib.loads((SCHED / "wrangler.toml").read_text(encoding="utf-8"))
    assert cfg["triggers"]["crons"] == ["*/10 * * * *"]                      # ONE cron trigger (free plan: 5 per account)
    assert cfg.get("workers_dev") is False and "routes" not in cfg           # no public URL
    assert "account_id" not in cfg
    raw = (SCHED / "wrangler.toml").read_text(encoding="utf-8")
    assert not re.search(r"ghp_|github_pat_|api[_-]?key|secret\s*=", raw, re.I)
    assert cfg["vars"]["GH_REF"] == "main" and cfg["vars"]["GH_REPOSITORY"] == "alexluke23/snow-wx"
    src = "".join(p.read_text(encoding="utf-8") for p in (SCHED / "src").glob("*.js"))
    assert "console.log(env" not in src and "GH_DISPATCH_TOKEN}" not in src.replace("env.GH_DISPATCH_TOKEN}", "")     # the token is only ever used as the bearer header
    assert "fetch(" not in (SCHED / "src" / "index.js").read_text(encoding="utf-8") and "async fetch" not in src      # no HTTP handler


def test_readme_has_at_most_six_owner_steps():
    text = (SCHED / "README.md").read_text(encoding="utf-8")
    steps = re.findall(r"^(\d+)\. \*\*", text, re.M)
    assert steps == [str(i) for i in range(1, len(steps) + 1)] and 1 <= len(steps) <= 6
    for needle in ("Actions: Read and write", "wrangler@4 secret put GH_DISPATCH_TOKEN", "wrangler@4 deploy", "Only select repositories"):
        assert needle in text


needs_node = pytest.mark.skipif(node() is None, reason="node not installed")


@needs_node
def test_node_decision_tests_pass():
    r = subprocess.run([node(), "--test"], cwd=SCHED, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1000:]
    assert re.search(r"# fail 0", r.stdout) and not re.search(r"# pass 0\b", r.stdout)


@needs_node
def test_schedule_table_equals_the_workflows_own_crons():
    out = subprocess.run([node(), "--input-type=module", "-e", f"import {{SCHEDULES}} from {json.dumps((SCHED / 'src' / 'due.js').as_uri())}; console.log(JSON.stringify(SCHEDULES))"],
                         capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    table = {w["file"]: sorted(w["crons"]) for w in json.loads(out.stdout)}
    real = {f: sorted(s["cron"] for s in (on_of(WF / f).get("schedule") or [])) for f in FILES}
    assert table == real, "src/due.js SCHEDULES and the workflows' schedule: crons differ"
