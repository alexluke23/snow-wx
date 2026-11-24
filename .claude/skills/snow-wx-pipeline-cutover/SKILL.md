---
name: snow-wx-pipeline-cutover
description: Move one Snow-Wx pipeline job (verify, gefs, models-points, points, ecmwf, update-site) from GitHub Actions to Cloudflare Containers + Workflows with a shadow run, parity check and rollback. Use during platform Phase 2 or when containerising, scheduling or switching any pipeline job.
---

# Cut over one pipeline job

Plan: `docs/specs/platform-transition.md` §5 and §10 (Phase 2). Do jobs in this order: **verify → gefs → models-points → points →
ecmwf → update-site**. One job per merge request.

## Preconditions (all must be ✅ in `docs/BACKLOG.md`)

- H7 pinned environment / lock file (the image must be reproducible).
- M15 atomic outputs: write to a staging prefix, then flip a `latest` pointer; upload `index.json` last.
- M8 (GEFS) / M9 (ECMWF) kill-safe caches and partial-cycle handling for those jobs.
- H5 plume sampling decoupled from map rendering (for models-points).
- C1 archive cannot lose a month (for any job that touches the archive).
- Output and cache roots configurable (review §6: today `--out` defaults to `build/…` and caches sit under `REPO_ROOT/data_cache`).
- Not inside a deploy freeze (Thanksgiving week, Dec 23–Jan 2, Feb 13–15) and no active winter storm warning over a major region.

## Steps

1. **Container command.** The job runs as `python -m pipeline <cmd> --out <staging prefix> …` in the shared image. No GitHub-only
   coupling: replace `GITHUB_OUTPUT` with a JSON result on stdout (keep `--github-output` as an adapter), replace the
   "already published" release-tag lookup with the D1 `runs` table, and the Actions cache with an R2 prefix `cache/<product>/<cycle>/`.
2. **Schedule.** Add the job's cron to the Cron Trigger → Workflow entry point (from `infra/scheduler/`); the Workflow starts the
   container, waits, verifies outputs, writes a `runs` row, and alerts the on-call developer on failure.
3. **Shadow run ≥ 7 days** writing to the **staging** R2 bucket while GitHub Actions keeps producing production data.
4. **Parity check every cycle** (`tools/parity.py`, to be written in Phase 2): same file set, same point IDs, numeric fields
   equal within float tolerance, same `cycle`/`issued`. Record mismatches with examples.
5. **Reliability:** share of due cycles published on time; target ≥ 99 % (GitHub delivered ~13 % of hourly runs).
6. **Cut over by configuration** (which bucket/prefix the site reads), not by deleting anything.
7. **Disable, don't delete** the GitHub workflow for 2 weeks (owner action: editing `.github/` needs authorisation).
8. **Rollback:** switch the read prefix back; the GitHub workflow is still there to re-enable.

## Report (in the MR and `docs/STATUS.md`)

Job, shadow dates, cycles compared, parity mismatches (count + examples + cause), on-time share, container runtime and size
(feed `docs/ops/budgets_baseline.md`), cutover date, rollback tested (yes/no).
