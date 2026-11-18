"""Data-health monitor (W5a slice): one GitHub issue per unhealthy source, closed automatically on recovery.

Runs in its own job after every hourly deploy (update-site.yml `monitor`): reads the LIVE meta.json (so it reports
what visitors get), compares each source with its own limits from config `monitoring.sources` (set from the source's
real cadence: hourly obs sources by consecutive failures + age, 3-6 hourly products by the age of the product), and
opens / updates / closes issues labelled `data-health`, assigned to `monitoring.assignee` so GitHub e-mails them.

Safety: nothing here can fail the deploy. The job is `continue-on-error`, runs after (never before) the deploy, and
this module catches everything: `main()` always returns 0. Stdlib + PyYAML only (no pandas/herbie import).

Known gap (docs/specs/data-pipeline.md 5.2c): a check inside the hourly workflow cannot notice that the workflow
did not run at all.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

TITLE = "Data health: {name}"


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def age_hours(iso: str | None, now: datetime) -> float | None:
    t = _parse(iso)
    return None if t is None else round((now - t).total_seconds() / 3600, 1)


def _failing(e: dict) -> bool:
    """A source counts as failing when its run failed OR it is serving stale/unavailable data (SNOTEL fallbacks)."""
    return e.get("ok") is False or bool(e.get("unavailable")) or bool(e.get("stale"))


def evaluate(meta: dict, now: datetime, mcfg: dict) -> dict[str, dict]:
    """{source: {"problem": str | None, "detail": {...}, "log": str}} for every source listed in config monitoring.sources.

    Bootstrap rules (dev15, after the real SNOTEL outage opened no issue): history may be missing (the outage predates the
    monitor, or a fresh runner restarted the counters), so a failing source is judged by every clock we have, not only by
    `consecutive_failures`: the data's own age (`last_observed` / `observed_through` for stale and unavailable copies), the time
    since the last success, and `outage_since` (first-seen-failing). A failing source whose age cannot be known at all is a breach once
    the failure-count limit is reached."""
    sources = (meta or {}).get("sources") or {}
    out = {}
    for name, lim in (mcfg.get("sources") or {}).items():
        e = sources.get(name)
        reasons = []
        if not isinstance(e, dict):
            # absent from meta.json: a new source, or the Pages deploy has not propagated yet: not an alarm
            out[name] = {"problem": None, "detail": {"note": "no status in meta.json", "limits": lim},
                         "log": f"{name}: no status in meta.json -> no alarm"}
            continue
        failing = _failing(e)
        fails = int(e.get("consecutive_failures") or 0)
        if failing:
            fails = max(fails, 1)                                   # stale/unavailable/ok:false is at least one failed run
        max_f, max_a = lim.get("max_failures"), lim.get("max_age_hours")
        if max_f and fails >= int(max_f):
            reasons.append(f"failed {fails} runs in a row (limit {max_f})")
        # age of the source: last success if known, else the data's own time (stale/unavailable copies), else (failing) first-seen failing
        ref, ref_kind = e.get("last_success_at") or (e.get("at") if e.get("ok") and not e.get("stale") else None), "last success"
        if not ref and failing:
            for key, kind in (("observed_through", "data time"), ("last_observed", "data time"), ("outage_since", "first seen failing")):
                if e.get(key):
                    ref, ref_kind = e[key], kind
                    break
        age = age_hours(ref, now)
        if failing and e.get("last_success_at") and (e.get("observed_through") or e.get("last_observed")):
            # prefer the OLDER clock: a stale copy can be older than the last (re)stamped run
            alt = age_hours(e.get("observed_through") or e.get("last_observed"), now)
            if alt is not None and (age is None or alt > age):
                age, ref_kind = alt, "data time"
        if age is not None and max_a and age > float(max_a) and (failing or ref_kind == "last success"):
            reasons.append(f"{ref_kind} {age:.0f} h ago (limit {max_a} h)")
        if e.get("ok") is False and "consecutive_failures" not in e and not reasons:
            reasons.append(f"missing: {e.get('error') or 'no data'}")       # a product that never arrived
        state = "unavailable" if e.get("unavailable") else "stale" if e.get("stale") else "failed" if e.get("ok") is False else "ok"
        problem = "; ".join(reasons) or None
        out[name] = {"problem": problem,
                     "detail": {"ok": e.get("ok"), "error": e.get("error"), "last_success_at": e.get("last_success_at"),
                                "consecutive_failures": e.get("consecutive_failures"), "at": e.get("at"),
                                "stale": e.get("stale"), "age_h": e.get("age_h"), "unavailable": e.get("unavailable"),
                                "outage_since": e.get("outage_since"), "limits": lim},
                     "log": f"{name}: state={state} failures={fails}/{max_f or '-'} age={'?' if age is None else f'{age:.1f}h'}"
                            f"({ref_kind if age is not None else 'unknown'})/{max_a or '-'}h -> {'BREACH: ' + problem if problem else 'ok'}"}
    return out


def issue_body(name: str, res: dict, run_url: str | None) -> str:
    d = res["detail"]
    lines = [f"**{name}** is unhealthy: {res['problem']}.", ""]
    for k in ("ok", "error", "last_success_at", "consecutive_failures", "at", "stale", "age_h", "unavailable", "outage_since", "limits"):
        if d.get(k) not in (None, "", False) or k in ("ok",):
            lines.append(f"- {k}: `{d.get(k)}`")
    lines += ["", "Limits come from `config/settings.yml` `monitoring.sources` (set per source from its real cadence).",
              "This issue is updated while the problem lasts and closed automatically when the source recovers."]
    if run_url:
        lines.append(f"Latest check: {run_url}")
    return "\n".join(lines)


def plan(results: dict[str, dict], open_issues: list[dict], run_url: str | None = None) -> list[tuple]:
    """Actions: ("create", name, title, body) / ("update", number, body) / ("close", number, comment)."""
    by_title = {i["title"]: i for i in open_issues}
    actions = []
    for name, res in results.items():
        title = TITLE.format(name=name)
        issue = by_title.get(title)
        if res["problem"]:
            body = issue_body(name, res, run_url)
            stable = lambda b: "\n".join(x for x in (b or "").splitlines() if not x.startswith("Latest check"))  # noqa: E731
            if issue is None:
                actions.append(("create", name, title, body))
            elif stable(issue.get("body")) != stable(body):
                actions.append(("update", issue["number"], body))
        elif issue is not None:
            actions.append(("close", issue["number"], f"{name} has recovered: closing automatically."))
    return actions


def run_gh(args: list[str], input_text: str | None = None) -> str:
    r = subprocess.run(["gh", *args], input=input_text, capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(f"gh {' '.join(args[:2])} failed: {r.stderr.strip()[:200]}")
    return r.stdout


def apply(actions: list[tuple], mcfg: dict, gh=run_gh) -> list[str]:
    label, assignee = mcfg.get("issue_label", "data-health"), mcfg.get("assignee")
    done = []
    for a in actions:
        try:
            if a[0] == "create":
                try:
                    gh(["label", "create", label, "--color", "d93f0b", "--description", "Automatic data-health alerts"])
                except Exception:
                    pass                                              # already exists
                args = ["issue", "create", "--title", a[2], "--body-file", "-", "--label", label]
                if assignee:
                    args += ["--assignee", assignee]
                gh(args, a[3])
                done.append(f"created {a[2]}")
            elif a[0] == "update":
                gh(["issue", "edit", str(a[1]), "--body-file", "-"], a[2])
                done.append(f"updated #{a[1]}")
            elif a[0] == "close":
                gh(["issue", "close", str(a[1]), "--comment", a[2]])
                done.append(f"closed #{a[1]}")
        except Exception as exc:                                      # one failed gh call must not stop the rest
            done.append(f"FAILED {a[0]}: {exc}")
    return done


def fetch_meta(origin: str, tries: int = 3, wait: float = 20.0, opener=urllib.request.urlopen) -> dict | None:
    """The live meta.json (a just-finished Pages deploy can take a moment to appear)."""
    for i in range(tries):
        try:
            req = urllib.request.Request(f"{origin.rstrip('/')}/data/meta.json?t={int(time.time())}",
                                         headers={"User-Agent": "snow-wx-monitor"})
            with opener(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception:
            if i < tries - 1:
                time.sleep(wait)
    return None


def check(mcfg: dict, meta: dict | None, now: datetime, open_issues: list[dict], gh=run_gh,
          run_url: str | None = None) -> list[str]:
    if meta is None:
        return ["live meta.json unreachable: nothing to evaluate"]
    results = evaluate(meta, now, mcfg)
    actions = plan(results, open_issues, run_url)
    acting = {a[1] if a[0] == "create" else None: a[0] for a in actions}
    open_titles = {i["title"] for i in open_issues}
    lines = []
    for name, res in results.items():          # one line per source with its decision, so the Actions log explains it
        act = ("open issue" if acting.get(name) == "create" else "issue already open" if TITLE.format(name=name) in open_titles and res["problem"]
               else "close issue" if TITLE.format(name=name) in open_titles else "none")
        lines.append(f"{res['log']} | action: {act}")
    return lines + apply(actions, mcfg, gh)


def main(argv: list[str] | None = None) -> int:
    """Always returns 0: monitoring must never fail a deploy."""
    try:
        import argparse
        import yaml
        ap = argparse.ArgumentParser()
        ap.add_argument("--config", default=str(Path(__file__).resolve().parent.parent / "config" / "settings.yml"))
        ap.add_argument("--origin", default=os.environ.get("SITE_ORIGIN"))
        ap.add_argument("--dry-run", action="store_true", help="print the actions only")
        args = ap.parse_args(argv)
        cfg = yaml.safe_load(open(args.config, encoding="utf-8"))
        mcfg = cfg.get("monitoring") or {}
        origin = (args.origin or (cfg.get("site") or {}).get("origin") or "").rstrip("/")
        meta = fetch_meta(origin) if origin else None
        run_url = None
        if os.environ.get("GITHUB_RUN_ID"):
            run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
        gh = run_gh
        if args.dry_run:
            gh = lambda a, i=None: print("DRY gh", " ".join(a)) or ""  # noqa: E731
        try:
            open_issues = json.loads(gh(["issue", "list", "--label", mcfg.get("issue_label", "data-health"), "--state", "open",
                                         "--json", "number,title,body", "--limit", "100"]) or "[]") if not args.dry_run else []
        except Exception as exc:
            print(f"monitor: could not list issues: {exc}")
            return 0
        for line in check(mcfg, meta, datetime.now(timezone.utc), open_issues, gh, run_url):
            print("monitor:", line)
    except Exception as exc:                                          # never fail the job
        print(f"monitor: skipped ({type(exc).__name__}: {str(exc)[:200]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
