# snow-wx external scheduler (Cloudflare Worker)

**Status: built and tested, NOT deployed.** **Before deploying (code review, Nov 23 2026):** fix M14 (each slot must dispatch its own inputs, and queued-safe workflows may be dispatched while a run is active) and M10 (validate `workflow_dispatch` inputs) — `docs/BACKLOG.md`. After the GitLab move this Worker becomes the Cron → Workflows entry point (`docs/specs/platform-transition.md` §5.1). GitHub drops most scheduled workflow runs on this repository (Nov 19-20 2026: about 6 of 46 hourly `update-site` runs, 1 `ecmwf` run, none for `gefs` / `verify`); a manual "Run workflow" always works. This Worker does the manual dispatch for us, on time.

## What it does
One cron trigger fires every 10 minutes (UTC). For each workflow whose slot passed in the last 20 minutes (at least 4 minutes ago, so GitHub's own event can still arrive first) it asks GitHub for the workflow's latest 5 runs. It dispatches (`POST /repos/alexluke23/snow-wx/actions/workflows/<file>/dispatches`, `ref: main`) **only if** no run of that workflow is queued or in progress **and** none was created since the slot. So a slot is dispatched at most once; if GitHub's own schedule already ran it, the Worker does nothing.

| Workflow | Slots (UTC; copied from the workflow's own `schedule:`) |
|---|---|
| `update-site.yml` | `17 * * * *` |
| `models.yml` | `55 1-22/3 * * *` and `55 2,8,14,20 * * *` |
| `ecmwf.yml` | `50 8-13,20-23,0-1 * * *` |
| `gefs.yml` | `10 6,8,18,20 * * *` |
| `verify.yml` | `25 15 * * *` |

The schedules in the workflows stay as a backup (their concurrency groups already stop overlapping runs). `tests/test_scheduler.py` fails if a workflow's cron and the table in `src/due.js` drift apart.

Free-plan fit: 1 cron trigger (limit 5), at most 10 subrequests per tick (limit 50), a few ms of CPU (limit 10), no public URL (`workers_dev = false`, no fetch handler).

## Owner steps (about 10 minutes, once)
1. **Create the token.** GitHub > Settings > Developer settings > Personal access tokens > *Fine-grained tokens* > Generate. Resource owner: you. **Only select repositories: `snow-wx`** (this one repo). Repository permissions: **Actions: Read and write** (Metadata: Read-only is added automatically); nothing else. Expiry: the longest GitHub allows; put the date in your calendar. Copy the token (shown once).
2. **Store it as a Worker secret** (never in a file or in git). From this folder: `npx wrangler@4 secret put GH_DISPATCH_TOKEN`, paste the token. (Wrangler asks you to log in to Cloudflare the first time.)
3. **Deploy:** `npx wrangler@4 deploy`. Optional first: set `DRY_RUN = "true"` in `wrangler.toml` to log decisions without dispatching, watch two ticks (step 4), set it back to `"false"` and deploy again.
4. **Check it.** `npx wrangler@4 tail` shows one line per decision every 10 minutes, e.g. `update-site.yml slot 12:17Z: due (...)` then `dispatched on main`, or `skip: run 123 already started at ...`. On GitHub, Actions > *Update site* shows runs with the event **workflow_dispatch**. No log line mentions the token.
5. **Disable it.** Either `npx wrangler@4 delete` (removes the Worker and its cron), or in the Cloudflare dashboard open the Worker > Settings > Triggers > delete the cron trigger. GitHub's own schedules keep running as before.
6. **Rotate the token.** Create a new fine-grained token as in step 1, run `npx wrangler@4 secret put GH_DISPATCH_TOKEN` with it (takes effect immediately, no redeploy), then delete the old token on GitHub. A `401`/`403` line in `wrangler tail` ("Bad credentials", "Resource not accessible") means the token expired or lost its permission: do this step.

## Failure behaviour
Every decision is one log line. A GitHub error (401, 403, 404, 5xx, timeout) while listing runs or dispatching is logged and the Worker continues with the next workflow; it never dispatches a workflow whose run list it could not read, and a bug cannot make the cron run fail. A missing token is logged and nothing else happens.

## Develop
`node --test` (in this folder; Node 18+; no dependencies) runs the decision tests (`test/due.test.js`). `pytest tests/test_scheduler.py` wraps them and skips when Node is missing. Logic: `src/due.js` (pure), `src/tick.js` (GitHub calls), `src/index.js` (the Worker entry).
