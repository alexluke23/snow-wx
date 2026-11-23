// snow-wx external scheduler: a Cloudflare Worker with ONE cron trigger (every 10 minutes). On each tick it works out which GitHub Actions
// workflows are due (src/due.js), checks that none is already running or started since the slot (one "list workflow runs" call each), and dispatches
// only those (POST .../dispatches, ref main). GitHub's own schedules stay in the workflows as a backup; their concurrency groups prevent overlap.
//
// Free-plan budget: <= 5 list calls + <= 5 dispatch calls (50 subrequests allowed), trivial CPU. No HTTP handler: nothing can call this Worker.
// The token (secret GH_DISPATCH_TOKEN) is never logged. Any API error is logged and the loop moves on to the next workflow.
import { tick } from "./tick.js";

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(tick(event.scheduledTime, env));
  },
};
