# Contributing to Snow-Wx

How the team of 3 developers works together. New here: `docs/ONBOARDING.md`. Platform details (GitLab, Cloudflare,
environments): `docs/specs/platform-transition.md`. Work list: `docs/BACKLOG.md`. Dates and action items: `docs/ROADMAP.md`.
AI agents follow `AGENTS.md` (same rules, plus a never-do list); use the skills in `.claude/skills/` and the review subagents in `.claude/agents/`.

## Ownership

Every area has a primary owner and a backup. The owner reviews changes in their area.

| Area | Paths | Primary | Backup |
|---|---|---|---|
| **Pipeline** — data sources, NBM, plumes, archive, verification, ML research | `pipeline/` (except the web-build files below), `config/models.yml`, `config/summary_rules.yml`, `data/`, `tools/nbm_*`, `docs/specs/data-pipeline.md`, `multi-model.md`, `daily-summaries.md`, `wind-exposure.md`, `ml-postprocessing.md`, `snow-ratio-ml.md`, `docs/verification.md` | Dev A | Dev B |
| **API + infra** — CI, scheduler, deploys, monitoring, archive storage, D1/R2, WX API, alerts backend | `infra/`, `.github/` (→ `.gitlab-ci.yml`), `pipeline/monitor.py`, `pipeline/archive*.py`, `pipeline/r2_plan.py`, `pipeline/alerts_backend.py`, `environment.yml`, `docs/specs/platform-transition.md`, `alerts-backend.md`, `docs/ops/` | Dev B | Dev A |
| **Web + mobile** — site, charts, maps, PWA, prerendered pages, share cards, browser tests, mobile apps | `web/`, `pipeline/pages.py`, `pipeline/pwa.py`, `pipeline/pwa_sw.js`, `pipeline/og.py`, `tools/browser_*.py`, `docs/DESIGN.md`, `docs/specs/pwa.md`, `hosting-seo.md`, `launch-readiness.md` | Dev C | Dev B |

Hotspots to split before big UI work: `web/js/area.js` (~1,360 lines) and `pipeline/nbm/run.py` (~860 lines).

## Branches and merge requests

- **Trunk-based.** `main` is protected; every change goes through a merge request (pull request until the GitLab move).
- Branches are short-lived (< 3 days), named `<area>/<short-topic>`, e.g. `pipeline/h1-window-fix`, `web/danger-chip-contrast`.
- **At least one reviewer**, normally the owner of the area touched. Safety-related changes (alerts, avalanche, snow level,
  freshness) need the reviewer to check the hard rules in `docs/PLAN.md` §0 explicitly.
- An MR should be reviewable in under 30 minutes. `docs/BACKLOG.md` §1 groups the code-review fixes that way.
- Tests must pass: `pytest -q` (offline) and, for web changes, `tools/browser_check.py --quick`. Add or update a test with every fix.
- Unfinished work ships behind a config flag (`config/settings.yml`), default **off**. Only the owner flips flags in production.
- Commit messages: imperative summary line (≤ 72 characters), then why. Reference the backlog ID (`H1`, `M15`, …) when there is one.

## Environments

`local` (Miniflare / `wrangler dev`, `python -m http.server`) → **preview per MR** (Workers Previews, after W1) → `staging` → `prod`.
Each environment has its own D1 databases, R2 buckets and scoped API tokens (`docs/specs/platform-transition.md` §4.4).

## Deploy freezes

Fixes only during: **Thanksgiving week**, **Dec 23 – Jan 2**, **Presidents' Day weekend (Feb 13–15)**.
Never cut over a pipeline job during a storm without a parallel (shadow) run.

## Docs

- Start at `docs/INDEX.md`. Keep `docs/PLAN.md` ≤ ~20 KB.
- A decision gets a row at the top of `docs/DECISIONS.md` (and in PLAN §3 if it changes current work). A decision with real
  trade-offs gets an ADR in `docs/adr/` (template `0000-template.md`).
- When an item lands, update `docs/BACKLOG.md` (✅ + MR + date) and `docs/STATUS.md` if what is live changed.
- Every doc starts with front matter: `status`, `owner`, `last_reviewed`, `read_when`.
- **Business planning is private and never goes in this repo** (`tests/test_no_business_content.py`). Write "set by owner"
  where a technical item waits on a business choice.

## Secrets

Never commit secrets. They live in the CI/CD secret store (GitHub Actions secrets today; GitLab masked + protected variables
and Cloudflare Workers secrets after the move). Use the narrowest token scope that works.
