---
name: snow-wx-backlog-fix
description: Work one Snow-Wx backlog item or code-review finding (IDs like C1, H3, M15, A-07) end to end - read the evidence, write the failing test, fix, verify, update docs and open a reviewable merge request. Use when asked to fix, implement or close a backlog or review item.
---

# Fix a backlog item end to end

## 1. Load the item

1. Find the ID in `docs/BACKLOG.md`. Record: severity, owner area, MR group, what it **blocks**, status.
   If status is not ○ (open), stop and tell the user.
2. If it is a review finding, read its row in `docs/reviews/2026-11-code-review.md` §3 (problem, evidence file:line,
   suggested fix, effort) and any related rows (§5 scope-trim, §6 GitHub coupling, §7 test gaps).
3. Check the MR group: if other items share the MR (e.g. MR 1 = C2 + H2 + M12 + N1), do them together on one branch.
4. Read the one relevant spec (`docs/PLAN.md` "Where things live"). For UI: `docs/DESIGN.md`. For NBM: also skill `snow-wx-nbm-change`.

## 2. Confirm the problem still exists

Line numbers in the review are from commit `bf8f8ac`. Open the cited file, find the code by content (not by line number),
and confirm the defect. If it's already fixed, update BACKLOG (✅ with the commit) and stop.

## 3. Branch and plan

- Branch `<area>/<id>-<topic>` from the latest `main`, e.g. `web/mr1-safety-display`, `pipeline/h1-window-fix`.
- Effort M or larger, or anything touching safety info: write a short plan (files, test, risk, rollout) and get it approved.

## 4. Test first

Write a test that fails on the current code and passes after the fix. Patterns in this repo:
- Pure Python: `tests/test_points.py`, `tests/test_summary.py`, `tests/test_verify.py` (fixtures built in the test, no network).
- Fetch paths: `tests/fakes.py` FakeSession with canned responses; never real HTTP; never the real `data_cache`
  (autouse fixtures patch `REPO_ROOT`).
- JS logic: node-driven tests like `tests/test_agreement_js.py`, `tests/test_freshness_js.py`, `tests/test_ensemble_js.py`.
- Browser behaviour: a check in `tools/browser_check.py` using frozen fixtures from `tools/browser_fixtures.py`
  (never live build data: M19).
- Workflows (until GitLab): YAML assertion tests like `tests/test_dev21_workflows.py`. Do not edit `.github/` without owner authorisation.

Examples of the test each finding needs (from review §7 "Gaps"): H1 → an 01Z/13Z fixture checking `slr`/`snow_type` past f036;
C1 → a release store that fails after the delete; H2 → frozen clock + expired `end_date`; H3 → alerts/avalanche fetch failure on
a fresh runner; H4 → empty release listing; M8 → truncated `.npz`; M6 → plume series with a null step; C2 → contrast on 5 levels.

## 5. Fix

Smallest change that satisfies the suggested fix and the spec. Keep fetch/pure separation; `common.write_json` for JSON;
config over code; no flag flips; no `.github/` edits.

## 6. Verify

- `python -m pytest -q` (all offline). Web: copy `web/*` → `build/`, `python tools/browser_check.py --quick`, then the full run.
- Safety or range-related → run skill `snow-wx-hard-rules` and paste its report.
- If the sandbox lacks `shapely`/`cartopy`/`pyproj`, run the same tests on an unmodified checkout and compare.

## 7. Docs (same MR)

Skill `snow-wx-docs-update`: set the BACKLOG row to "✅ <MR/branch> <date>", update STATUS if live behaviour changed, update the
spec / `web/about.html` if a method changed. If the fix unblocks something (e.g. M14 → scheduler deploy), say so in BACKLOG.

## 8. Merge request

Use the template in `AGENTS.md` §8. Title: `<ID(s)>: <imperative summary>`. Request review from the area owner
(`CONTRIBUTING.md`); safety-related → also run the `safety-reviewer` subagent and include its verdict.
