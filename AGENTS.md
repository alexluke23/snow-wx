# AGENTS.md — operating protocol for AI coding agents

Applies to every AI agent working in this repository (Claude Code, other coding assistants, CI bots, subagents).
`CLAUDE.md` imports this file; other tools should read it first. Human developers: the same rules apply to you, and
`CONTRIBUTING.md` covers the team workflow.

Snow-Wx is a public safety-adjacent product: people decide where to ski and travel in avalanche terrain partly from
what this site shows. **A wrong number shown confidently is worse than a missing number shown honestly.** When unsure,
stop and ask.

---

## 1. Orientation (read in this order, and no more than the task needs)

1. `docs/PLAN.md` — hard rules (§0), current decisions (§3), roadmap (§8). Always.
2. `docs/BACKLOG.md` — find the item you are working on (ID like `H1`, `M15`, `A-07`). Note its owner area, merge-request
   group and what it blocks.
3. The **one** spec for the task (`docs/specs/…`, table "Where things live" in PLAN.md). For review findings, also the
   finding's row in `docs/reviews/2026-11-code-review.md` (it has file:line evidence and a suggested fix).
4. `docs/ARCHITECTURE.md` when you need to know where data comes from or goes; `docs/GLOSSARY.md` for unfamiliar terms.
5. `docs/DESIGN.md` only for UI work; `docs/verification.md` only for archive/verification work; `docs/nbm_inventory.md`
   before touching NBM fetch/decode.

Do **not** read `docs/archive/`, `docs/specs/retired/` or `docs/reference/` unless the task is about history or that
reference topic. Do not read large generated files (`build/`, `data_cache/`, GRIB) into context; inspect them with scripts.

## 2. Task intake

Before writing code, write down (in your plan or the MR description):

- **What** — one sentence, plus the backlog ID or spec section.
- **Owner area** — pipeline / api-infra / web-mobile (`CONTRIBUTING.md`). Stay inside it; if you must touch another
  area, say so and keep that part minimal.
- **Scope-trim check** — is any file you will touch slated for removal (model maps, Sno-Parks, SNOTEL-site pages;
  `docs/BACKLOG.md` §3)? Don't polish code that is about to be deleted; don't delete it outside the trim MR.
- **Safety check** — does the change touch avalanche danger, NWS alerts/hazards, snow level/rain-at-base, freshness,
  or any percentile/range? If yes, run the `snow-wx-hard-rules` skill (or follow §6) and ask for a safety review.
- **Plan size** — anything bigger than "S" (½ day) gets a written plan first (plan mode in Claude Code), reviewed by the
  human who assigned it.

## 3. Never do (hard stops)

| Never | Why / instead |
|---|---|
| Enable a feature flag in `config/settings.yml` (`pages`, `pwa`, `analytics`, `verification_ui`, `alerts_backend`, `wind_exposure`, `r2`, `og_images`, `ml_adjusted`, …) | The owner flips flags. Build behind the flag, default off, and say how to enable it. |
| Edit `.github/` workflows | Only with explicit owner authorisation for that exact change. Put proposed workflow text in `docs/workflow_snippets/`. (GitLab CI / Cloudflare Workflows after the platform move: same rule.) |
| Add business content (pricing, entity, positioning, brand/domain choices, partner strategy) to any tracked file | Private by owner decision; `tests/test_no_business_content.py`. Write "set by owner". |
| Sum, scale, interpolate or average percentiles across windows; show a range that isn't from one native NBM window | Hard rule 4. Show the expected amount without a range instead (`native: false`). |
| Hide, delay, restyle into illegibility, or gate safety info; show expired alerts/ratings as current | Hard rule 1 (review C2, H2, H3, M12 were exactly this). |
| Present a heuristic as accuracy or an avalanche rating; claim "more accurate" without published verification | Hard rule 2. |
| Add a data source without checking its licence | Hard rule 3. Ask first when terms are unclear. No scraping. |
| Write tests that touch the network or the real `data_cache` | Hard rule 5; use `tests/fakes.py` and the autouse `REPO_ROOT` patches. |
| Rename/drop/reorder forecast-archive columns, or delete/overwrite archive months | The archive is additive and its only copy is remote (review C1). |
| Commit secrets, tokens, personal addresses, `.env` files | Secrets live in the CI/Cloudflare secret stores. |
| Push to `main`, force-push shared branches, rewrite history | Branch + merge request; one human review minimum. |
| Hard-code ensemble member counts (e.g. "51 members") | Read them from the data; `tests/test_ecmwf_wording.py`. |
| Leave `print`-debugging, commented-out code or TODOs without a backlog ID | Keep diffs reviewable in < 30 minutes. |

## 4. Stop and ask a human when

- The task conflicts with a hard rule, a decision in `docs/DECISIONS.md`, or a spec — even if the request seems to want it.
- You would need to change a public data contract (points JSON fields, archive columns, URL scheme, `meta.json` keys).
- A test fails for a reason you don't understand, or you'd need to loosen/skip a test to proceed.
- Live data looks wrong (e.g. a decode disagrees with the NBS text bulletin, a source returns nonsense). Report evidence; don't "fix" by clamping.
- The change needs credentials, a paid service, a new external host in the browser, or an account the team doesn't have.
- You are about to delete more than ~50 lines outside the scope-trim MR.

## 5. Work loop

1. **Branch:** `<area>/<backlog-id>-<topic>` (e.g. `pipeline/h1-window-fix`). One backlog item (or one MR group) per branch.
2. **Reproduce first:** for a bug, write the failing test before the fix (fixture-based, offline). The review lists the
   missing test for most findings (§7 "Gaps").
3. **Implement** the smallest change that satisfies the spec. Keep fetch code separate from pure functions; write JSON with
   `common.write_json`; config over code.
4. **Run checks** (§7). For web changes copy `web/*` over `build/` and run the browser checks on frozen fixtures.
5. **Update docs in the same MR** (skill `snow-wx-docs-update`): BACKLOG status, STATUS if what's live changed, the spec if
   behaviour changed, `web/about.html` if a method changed, DECISIONS if a decision was made.
6. **Write the MR description** (template in §8). Request review from the area owner; safety-related → also the safety reviewer.

Commits: imperative subject ≤ 72 chars, body says why, references the backlog ID. Small, logical commits.

## 6. Safety and correctness checklist (UI, summaries, alerts, anything users read)

- [ ] Avalanche danger shows for every zone with a rating; expired ratings are greyed **at view time** (compare `end_date`
      with the browser clock), never coloured as current; text contrast ≥ 4.5:1 on all five danger colours; the center
      link is always present, even when the rating fetch failed.
- [ ] NWS alerts: expired alerts (`ends` in the past) are not shown as active; the page says when alerts were last checked;
      a failed fetch shows "could not be loaded" + a weather.gov link, never an empty "no alerts" state.
- [ ] Snow level / rain-at-base is visible wherever snowfall is shown.
- [ ] Every module shows its source and issue time; every model line shows its own run time; stale data is greyed and labelled.
- [ ] Ranges: "likely" = p25–p75 from **one** native window; 10–90 only where DESIGN §6 says; no cross-hour envelopes called "likely".
- [ ] Gaps stay gaps (no interpolation across missing steps, `connectgaps: false`).
- [ ] Heuristics (powder quality, agreement badge, daily summary, wind flag) carry their label.
- [ ] Attribution present: NOAA/NWS, USDA NRCS (SNOTEL), avalanche.org, ECMWF CC BY 4.0, ODbL/OpenSkiMap, OpenFreeMap.
- [ ] Works offline in tests; no new third-party host in the browser (the `privacy` browser check).

## 7. Checks to run

| Change touches | Run |
|---|---|
| Anything | `python -m pytest -q` (offline; ~2.5 min; expect ~606 pass, 9 browser tests skipped) |
| `web/` | copy `web/*` → `build/`, then `python tools/browser_check.py --quick` (full run before merge: no `--quick`) |
| NBM decode/selection | compare a sample against the NBS text bulletin (`blend_nbstx`), `python -m pipeline.nbm.sanity` |
| Archive / verify | `python -m pipeline archive-check` against a local copy (never the real release from a PC) |
| `infra/scheduler/` | `cd infra/scheduler && node --test` |
| Docs | the docs link check in skill `snow-wx-docs-update`; `pytest tests/test_no_business_content.py tests/test_ecmwf_wording.py` |
| Performance-sensitive UI | Lighthouse, median of ≥ 3 interleaved runs (CLAUDE.md "Reusable gotchas") |

On Windows use `C:/miniforge3/envs/snow-wx/python.exe`; elsewhere the `snow-wx` conda env from `environment.yml`.
In sandboxes without the full environment, some tests fail on missing `shapely`/`cartopy`/`pyproj`: compare against an
unmodified checkout before blaming your change, and say so in the MR.

## 8. Merge-request description template

```markdown
## What
<one paragraph> — Backlog: <ID(s)> · Area: <pipeline|api-infra|web-mobile>

## Why
<the problem, with the finding/spec reference>

## How
- <key change 1>
- <key change 2>

## Safety / hard rules
- [ ] Touches safety info? <no | yes: what was checked (AGENTS.md §6)>
- [ ] Percentiles/ranges? <no | yes: native windows only>
- [ ] New source/host? <no | yes: licence + privacy check>

## Tests
- Added: <tests>
- Ran: pytest <result>; browser <result>; other <…>

## Docs
- [ ] BACKLOG updated  - [ ] STATUS updated (if live behaviour changed)  - [ ] spec/about.html updated (if method changed)

## Rollout
<flag name and default | none>; how to verify after deploy; how to roll back
```

## 9. Working alongside other agents and people

- One agent per branch. Parallel agents work in separate worktrees on different owner areas.
- Hotspots — `web/js/area.js`, `pipeline/nbm/run.py`, `pipeline/__main__.py`, `config/settings.yml` — are edited by one
  branch at a time; check open MRs first.
- Subagents should return findings, not edits, unless their task is an edit. Reviews use the subagents in `.claude/agents/`.
- Leave the tree buildable at every commit.

## 10. Where things get recorded

| You produced | Put it in |
|---|---|
| A decision (or found one implicit in code) | `docs/DECISIONS.md` (top row); PLAN §3 only if it changes current work; ADR in `docs/adr/` if it has trade-offs |
| A new work item or bug | `docs/BACKLOG.md` (new ID, owner, effort, blocks) |
| A change to what's live | `docs/STATUS.md` |
| Session handoff for the next agent | the MR description (not CLAUDE.md); long-lived gotchas → CLAUDE.md "Reusable gotchas" (keep it short) |
| Measurements (sizes, runtimes, Lighthouse) | `docs/ops/budgets_baseline.md` |
| Anything business-related | nowhere in this repo — tell the owner |
