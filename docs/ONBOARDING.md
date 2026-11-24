---
status: current
owner: team
last_reviewed: 2026-11-23
read_when: you are new to the team, or setting up a new machine or AI agent
---

# Onboarding

Welcome. This gets a new developer (and their AI agents) productive in about a week. Read `README.md` first for what the site is.

## 0. Before day 1 — access (requested by the owner)

- [ ] Git host: GitHub repo `alexluke23/snow-wx` today (write access); the GitLab group once Phase 0 is done (`docs/ROADMAP.md` A-08).
- [ ] Cloudflare account membership with your own login and an environment-scoped API token (never a global key).
- [ ] The team's Claude Teams project (planning chats, business docs: private) and Claude Code.
- [ ] The team chat channel and the on-call rota (`docs/ROADMAP.md` §5).
- [ ] Your owner area (`CONTRIBUTING.md`): **pipeline**, **API + infra** or **web + mobile**.

## 1. Day 1 — set up and run it

**Windows (owner's setup):**
```powershell
conda env create -f environment.yml
conda activate snow-wx
pytest -q                                  # ~606 passed, 9 skipped
python -m pipeline build                   # 5–10 min (SNOTEL is slow)
python -m pipeline points                  # NBM forecasts, needs network
python -m http.server 8000 -d build        # http://localhost:8000
```
Without activating, call `C:/miniforge3/envs/snow-wx/python.exe` directly (`CLAUDE.md` explains the ecCodes PATH note).

**macOS / Linux:**
```bash
conda env create -f environment.yml        # or mamba / micromamba
conda activate snow-wx
python -m pytest -q
python -m pipeline build && python -m pipeline points --out build/data/points
python -m http.server 8000 -d build
```
`environment.yml` is not pinned yet (review H7, `docs/BACKLOG.md` MR 7). If a test fails with a numpy binary-compatibility warning or a
missing `shapely`/`cartopy`/`pyproj`, your environment drifted: recreate it, and tell Dev B so the lock file covers it.

**Browser checks** (web work): Chrome installed; copy `web/*` into `build/`, then
`PYTHONIOENCODING=utf-8 python tools/browser_check.py --quick`.

Done when: tests pass, the site runs locally, you can open an area page (e.g. Alta) and the obs map.

## 2. Day 1–2 — read (in this order, ~2 hours)

1. `docs/PLAN.md` — hard rules (§0), current decisions (§3), roadmap (§8).
2. `AGENTS.md` — how we (and our agents) work: never-do list, stop-and-ask rules, checks, MR template.
3. `docs/ARCHITECTURE.md` — the data flow and products; `docs/GLOSSARY.md` as needed.
4. `docs/STATUS.md` and `docs/BACKLOG.md` — what's live, what's broken, what's next.
5. `docs/ROADMAP.md` — timeline and your action items.
6. Your area's specs (`docs/INDEX.md` lists them by owner).
7. Skim the code review summary (`docs/reviews/2026-11-code-review.md` §1) — it's the best tour of where the risks are.

## 3. Days 2–5 — first contributions by role

| Role | Warm-up (½ day) | First real item | Then |
|---|---|---|---|
| **Pipeline (Dev A)** | Run `python -m pipeline points` for one cycle; compare TMP/Q06/SLV at 3 areas with the NBS text bulletin (skill `snow-wx-nbm-change`) | **H1** 6-h window fix (MR 5, with M3, M4) | MR 2 (pipeline half), MR 6 (plume sampling without maps) |
| **API + infra (Dev B)** | Read the six workflows and `infra/scheduler/`; run `node --test` | **H4** no silent empty deploy (MR 4) | MR 3 (archive durability), MR 7 (pin env), M14 + MR 8 → deploy scheduler; GitLab Phase 0 |
| **Web + mobile (Dev C)** | Run `tools/browser_check.py --quick`; open the area page at 375 px | **MR 1** safety display (C2, H2, M12, N1) | PR B frozen fixtures; MR 2 (web half); W1 cutover |

Each first item is small, has a failing-test description in the review, and touches safety or reliability — you'll learn the rules by applying them.

## 4. Working with Claude Code here

- `CLAUDE.md` loads automatically and imports `AGENTS.md`. Don't paste rules into prompts; point at the backlog ID.
- **Use the project skills** (`.claude/skills/`):
  - `snow-wx-backlog-fix` — "Fix H1" end to end (evidence → failing test → fix → docs → MR description).
  - `snow-wx-hard-rules` — run before any UI/summary/range change.
  - `snow-wx-nbm-change`, `snow-wx-plume-chart`, `snow-wx-pipeline-cutover`, `snow-wx-docs-update`.
- **Use the review subagents** (`.claude/agents/`): `safety-reviewer` (PASS/FAIL on safety and ranges), `docs-keeper` (are docs updated?).
- **Plan mode** (Shift+Tab) for anything bigger than half a day or touching safety info; approve the plan before edits.
- **Good prompt shape:** "Use the snow-wx-backlog-fix skill on M8. Branch pipeline/m8-gefs-atomic-cache. Stop after the failing test and show it to me."
- **One agent per branch**; parallel agents in separate worktrees on different owner areas. Hotspot files (`area.js`, `nbm/run.py`,
  `__main__.py`, `settings.yml`) one branch at a time.
- Agents must never flip flags, edit `.github/`, add business content or push to `main` — if one tries, stop it and tell the team.
- Review agent output like a colleague's: run the tests yourself, read the diff, check the hard rules.

## 5. Team rhythm

| When | What |
|---|---|
| Daily (async, 5 min) | Post: yesterday / today / blockers, with backlog IDs |
| Monday (30 min) | Plan the week from `docs/ROADMAP.md`; assign action items; check freezes and the weather (big storms = no risky deploys) |
| Friday (20 min) | Demo merged work; update STATUS and ROADMAP; note risks |
| Every MR | One reviewer (area owner); safety-related also `safety-reviewer` |
| Weekly (owner + Dev A) | Daily Snow summary review (`docs/ops/summary_review.md`) |
| On-call (weekly rotation) | Watch pipeline health (status page, alerts); first response within 2 h during the day in storm periods |

## 6. Where to ask

- Rules and decisions: `docs/DECISIONS.md`, then the owner.
- "Why is this code like this?": `git log -p <file>`, `docs/archive/ARCHIVE.md` (history), then the area owner.
- Business questions (names, pricing, partners): the owner, in the private project — never in the repo.
