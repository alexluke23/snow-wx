// Pure scheduling logic for the snow-wx external scheduler (no network, no Cloudflare APIs: tested with `node --test`).
//
// SCHEDULES mirrors the `schedule:` crons of the five workflows VERBATIM (tests/test_scheduler.py fails if a workflow's cron changes and this table does not).
// A workflow is DUE when
//   - one of its slots has passed within the last WINDOW_MIN minutes (and at least GRACE_MIN minutes ago, so GitHub's own cron event gets a head start), and
//   - none of its latest runs is queued / in progress, and
//   - none of its latest runs was created at or after that slot (it already ran, or GitHub's own delayed cron / an earlier dispatch started it).
// So a slot is dispatched at most once, however often the Worker ticks.

export const WINDOW_MIN = 20;   // a slot stays "due" for this long
export const GRACE_MIN = 4;     // ... but only once it is this old (GitHub's own event may still arrive)

export const SCHEDULES = [
  { file: "update-site.yml", crons: ["17 * * * *"] },
  { file: "models.yml", crons: ["55 1-22/3 * * *", "55 2,8,14,20 * * *"] },
  { file: "ecmwf.yml", crons: ["50 8-13,20-23,0-1 * * *"] },
  { file: "gefs.yml", crons: ["10 6,8,18,20 * * *"] },
  { file: "verify.yml", crons: ["25 15 * * *"] },
];

const MIN = 60 * 1000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

/** one cron field ("*", "5", "1-22/3", "8-13,20-23,0-1") -> sorted unique numbers within [lo, hi] */
export function expand(field, lo, hi) {
  const out = new Set();
  for (const part of String(field).split(",")) {
    const [range, stepText] = part.split("/");
    const step = stepText === undefined ? 1 : Number(stepText);
    let a, b;
    if (range === "*") { a = lo; b = hi; }
    else if (range.includes("-")) { [a, b] = range.split("-").map(Number); }
    else { a = Number(range); b = stepText === undefined ? a : hi; }
    if (![a, b, step].every(Number.isInteger) || step < 1 || a < lo || b > hi || a > b) throw new Error(`bad cron field "${field}"`);
    for (let v = a; v <= b; v += step) out.add(v);
  }
  return [...out].sort((x, y) => x - y);
}

/** "m h * * *" -> {minutes, hours}; day / month / weekday must be "*" (all the workflows are daily patterns, UTC) */
export function parseCron(expr) {
  const f = String(expr).trim().split(/\s+/);
  if (f.length !== 5 || f.slice(2).some((x) => x !== "*")) throw new Error(`unsupported cron "${expr}" (only minute and hour fields)`);
  return { minutes: expand(f[0], 0, 59), hours: expand(f[1], 0, 23) };
}

/** every slot (ms epoch, UTC) of the cron on the UTC day starting at dayStart */
function slotsOfDay(cron, dayStart) {
  const { minutes, hours } = parseCron(cron);
  return hours.flatMap((h) => minutes.map((m) => dayStart + h * HOUR + m * MIN));
}

/** latest slot s of the crons with graceMin <= now - s <= windowMin (looks at today and yesterday, so it works across midnight UTC); null if none */
export function latestSlot(now, crons, { windowMin = WINDOW_MIN, graceMin = GRACE_MIN } = {}) {
  const t = now instanceof Date ? now.getTime() : now;
  const today = t - (((t % DAY) + DAY) % DAY);
  let best = null;
  for (const cron of crons) {
    for (const dayStart of [today - DAY, today]) {
      for (const s of slotsOfDay(cron, dayStart)) {
        const age = t - s;
        if (age >= graceMin * MIN && age <= windowMin * MIN && (best === null || s > best)) best = s;
      }
    }
  }
  return best;
}

/** workflows with a slot in the window, before looking at their runs: [{file, slot}] (the Worker lists runs only for these) */
export function candidates(now, opts = {}, schedules = SCHEDULES) {
  return schedules.map((w) => ({ file: w.file, slot: latestSlot(now, w.crons, opts) })).filter((c) => c.slot !== null);
}

const ACTIVE = (r) => r.status !== "completed";

/**
 * Decide for every candidate. runsByWorkflow: {file: [GitHub run objects, newest first] | null/undefined when the list could not be read}.
 * -> [{file, slot (ISO), action: "dispatch" | "skip", reason}]
 */
export function decide(now, runsByWorkflow, opts = {}, schedules = SCHEDULES) {
  return candidates(now, opts, schedules).map(({ file, slot }) => {
    const iso = new Date(slot).toISOString();
    const runs = runsByWorkflow?.[file];
    if (!Array.isArray(runs)) return { file, slot: iso, action: "skip", reason: "run list unavailable (API error): not dispatching blind" };
    const active = runs.find(ACTIVE);
    if (active) return { file, slot: iso, action: "skip", reason: `run ${active.id} is ${active.status}` };
    const since = runs.find((r) => Date.parse(r.created_at) >= slot);
    if (since) return { file, slot: iso, action: "skip", reason: `run ${since.id} already started at ${since.created_at} (after the slot)` };
    return { file, slot: iso, action: "dispatch", reason: "slot passed, no run queued, running or started since" };
  });
}

/** the workflow files to dispatch now */
export function dueWorkflows(now, runsByWorkflow, opts = {}, schedules = SCHEDULES) {
  return decide(now, runsByWorkflow, opts, schedules).filter((d) => d.action === "dispatch").map((d) => ({ file: d.file, slot: d.slot }));
}
