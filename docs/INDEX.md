---
status: current
owner: team
last_reviewed: 2026-11-23
read_when: you need to find a doc, or check which docs are current
---

# Docs index

Every Markdown doc in the repo: where it is, whether it is current, who owns it and when to read it. Owners: **P** pipeline · **I** API + infra · **W** web + mobile · **T** team (`CONTRIBUTING.md`). Reorganised Nov 23 2026; history of the move in `docs/archive/ARCHIVE.md` ("Moved on Nov 23 2026").

## Start here

| Doc | Status | Owner | Read when |
|---|---|---|---|
| [`README.md`](../README.md) | current | T | first time in the repo: what the site is, setup, run, test |
| [`CLAUDE.md`](../CLAUDE.md) | current | T | Claude Code reads it every session (rules, commands, gotchas) |
| [`AGENTS.md`](../AGENTS.md) | current | T | every AI agent, every session (imported by CLAUDE.md): never-do list, stop-and-ask, checks, MR template |
| [`CONTRIBUTING.md`](../CONTRIBUTING.md) | current | T | ownership, branches, merge requests, freezes, docs rules |
| [`ONBOARDING.md`](ONBOARDING.md) | current | T | first week on the team: access, setup, reading order, first items, working with Claude Code |
| [`ROADMAP.md`](ROADMAP.md) | current | T | timeline, phases, action items (A-NN) with owners and dates, owner dependencies |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | current | T | data flow, CLI, data products and contracts, front end, target architecture |
| [`GLOSSARY.md`](GLOSSARY.md) | current | T | weather, data and project terms |
| [`PLAN.md`](PLAN.md) | current | T | every session: hard rules, current decisions, roadmap |
| [`STATUS.md`](STATUS.md) | current | T | what is live, flags on/off, known issues |
| [`DECISIONS.md`](DECISIONS.md) | current | T | the date and reason behind a rule; adding a decision |
| [`BACKLOG.md`](BACKLOG.md) | current | T | picking or closing work (review findings, merge-request order) |
| [`DESIGN.md`](DESIGN.md) | current | W | charts, legends, colours, layout, accessibility |

## Agent tooling (`.claude/`)

| File | Use |
|---|---|
| [`skills/snow-wx-hard-rules`](../.claude/skills/snow-wx-hard-rules/SKILL.md) | hard-rules check before any user-visible or range change |
| [`skills/snow-wx-backlog-fix`](../.claude/skills/snow-wx-backlog-fix/SKILL.md) | work a backlog/review item end to end |
| [`skills/snow-wx-nbm-change`](../.claude/skills/snow-wx-nbm-change/SKILL.md) | NBM fetch, decode, windows, point maths |
| [`skills/snow-wx-plume-chart`](../.claude/skills/snow-wx-plume-chart/SKILL.md) | multi-model and ensemble charts |
| [`skills/snow-wx-docs-update`](../.claude/skills/snow-wx-docs-update/SKILL.md) | docs after a change; docs checks |
| [`skills/snow-wx-pipeline-cutover`](../.claude/skills/snow-wx-pipeline-cutover/SKILL.md) | move a job to Cloudflare with shadow run + parity |
| [`agents/safety-reviewer.md`](../.claude/agents/safety-reviewer.md) | read-only PASS/FAIL review of safety and range changes |
| [`agents/docs-keeper.md`](../.claude/agents/docs-keeper.md) | checks docs match a change |

## Specs (`docs/specs/`)

| Spec | Status | Owner | Read when |
|---|---|---|---|
| [`platform-transition.md`](specs/platform-transition.md) | current | I | GitLab/Cloudflare move, D1/R2, WX API, search, AI agent, mobile apps |
| [`data-pipeline.md`](specs/data-pipeline.md) | current | P | catalog, NBM points, SNOTEL, monitoring, NWS layer (§5.1–5.3) |
| [`multi-model.md`](specs/multi-model.md) | current (focus area) | P | plumes, per-model sampling, agreement badge, ECMWF, GEFS (§5.5) |
| [`daily-summaries.md`](specs/daily-summaries.md) | current | P | summary rules engine (§5.7) |
| [`pwa.md`](specs/pwa.md) | current (built, off) | W | manifest, service worker, offline UX (§5.8) |
| [`wind-exposure.md`](specs/wind-exposure.md) | current (built, off) | P | W7 wind flag (§5.9) |
| [`hosting-seo.md`](specs/hosting-seo.md) | current | W | W1 domain move, prerendered pages, sitemap, share cards (§5.10) |
| [`alerts-backend.md`](specs/alerts-backend.md) | current (skeleton, off) | I | W6 alerts Worker, accounts, delivery (§5.11) |
| [`launch-readiness.md`](specs/launch-readiness.md) | current | W | sources/credits, legal drafts, analytics, link check, headers |
| [`ml-postprocessing.md`](specs/ml-postprocessing.md) | current (research) | P | M12: ML for QPF, snowfall, SLR; SNOTEL QC; NBM backfill |
| [`snow-ratio-ml.md`](specs/snow-ratio-ml.md) | current (research) | P | M11: snow-ratio ML (the SLR part of M12) |
| [`retired/model-maps.md`](specs/retired/model-maps.md) | retired Nov 23 | — | history only |
| [`retired/sno-parks.md`](specs/retired/sno-parks.md) | retired Nov 23 | — | history only |

## Reference

| Doc | Status | Owner | Read when |
|---|---|---|---|
| [`verification.md`](verification.md) | current | P | forecast archive files, columns, M9 scoring (path kept: code points to it) |
| [`nbm_inventory.md`](nbm_inventory.md) | reference (generated) | P | NBM GRIB layouts per cycle; regenerate with `tools/nbm_inventory.py` (path kept: the tool writes it) |
| [`reference/nbm_prob_consistency_2026110801.md`](reference/nbm_prob_consistency_2026110801.md) | reference | P | changing "Chance of ≥ X" |
| [`reference/nbm_validation_gsl_2026110801.md`](reference/nbm_validation_gsl_2026110801.md) | reference | P | validating NBM decodes against the GSL viewer |
| [`reference/verification_first_look.md`](reference/verification_first_look.md) | reference (Nov 17 snapshot) | P | what 4 days of archive could show |
| [`reference/sources_resort_snowfall.md`](reference/sources_resort_snowfall.md) | reference | — | resort-reported snowfall licensing (no build without a written licence) |
| [`reviews/2026-11-code-review.md`](reviews/2026-11-code-review.md) | current | T | detail behind a backlog finding |

## Operations (`docs/ops/`)

| Doc | Status | Owner | Read when |
|---|---|---|---|
| [`ops/w1_cutover_checklist.md`](ops/w1_cutover_checklist.md) | current | I | running the W1 domain cutover |
| [`ops/budgets_baseline.md`](ops/budgets_baseline.md) | reference (GitHub Pages baseline) | I | comparing sizes, runtimes, Lighthouse |
| [`ops/summary_review.md`](ops/summary_review.md) | current (log) | P | the weekly Daily Snow summary review |
| [`../infra/scheduler/README.md`](../infra/scheduler/README.md) | current | I | deploying the external scheduler (after M14/M10) |
| `workflow_snippets/` | reference | I | workflow text for the owner to apply (YAML, not Markdown) |

## Decisions and history

| Doc | Status | Read when |
|---|---|---|
| [`adr/0000-template.md`](adr/0000-template.md) | template | writing an architecture decision record |
| [`archive/ARCHIVE.md`](archive/ARCHIVE.md) | history | only when a task asks for history |
| [`archive/STATE_SNAPSHOT-2026-11-21.md`](archive/STATE_SNAPSHOT-2026-11-21.md) | superseded by `STATUS.md` | history only |
| [`archive/sources_recreation.md`](archive/sources_recreation.md) | retired with Sno-Parks | history only |
| `w1_cutover_checklist.md` | stub → `ops/` | (kept because `tools/w1_rehearsal.py` names the old path) |

## Not in this repo

Business planning (pricing, entity, positioning, partners) is private: never in tracked files (`tests/test_no_business_content.py`).
