// node --test: the scheduling decisions (src/due.js) and the tick's error handling (src/tick.js) with a fake GitHub API. No network.
import test from "node:test";
import assert from "node:assert/strict";
import { SCHEDULES, candidates, decide, dueWorkflows, latestSlot, parseCron, expand } from "../src/due.js";
import { tick } from "../src/tick.js";

const at = (s) => Date.parse(s);                                   // "2026-11-21T12:20Z" -> ms
const run = (id, status, created) => ({ id, status, created_at: created, conclusion: status === "completed" ? "success" : null });
const files = (now, runs) => dueWorkflows(at(now), runs).map((d) => d.file);

test("the cron fields expand like GitHub's", () => {
  assert.deepEqual(expand("1-22/3", 0, 23), [1, 4, 7, 10, 13, 16, 19, 22]);
  assert.deepEqual(expand("8-13,20-23,0-1", 0, 23), [0, 1, 8, 9, 10, 11, 12, 13, 20, 21, 22, 23]);
  assert.deepEqual(expand("*", 0, 2), [0, 1, 2]);
  assert.deepEqual(parseCron("55 2,8,14,20 * * *"), { minutes: [55], hours: [2, 8, 14, 20] });
  assert.throws(() => parseCron("0 0 * * 1"));
  assert.throws(() => expand("25-3", 0, 23));
});

test("normal slot: update-site (:17) is due at :30, nothing else is", () => {
  assert.deepEqual(files("2026-11-21T12:30:00Z", { "update-site.yml": [run(1, "completed", "2026-11-21T11:19:00Z")] }), ["update-site.yml"]);
});

test("the slot must be at least GRACE_MIN old: GitHub's own event gets a head start", () => {
  const runs = { "update-site.yml": [run(1, "completed", "2026-11-21T11:19:00Z")] };
  assert.deepEqual(files("2026-11-21T12:19:00Z", runs), []);        // 2 min after the slot: wait
  assert.deepEqual(files("2026-11-21T12:21:00Z", runs), ["update-site.yml"]);   // 4 min: due
});

test("missed slot: nothing ran since, so it is dispatched at the next tick inside the 20-minute window, and not after it", () => {
  const runs = { "update-site.yml": [run(1, "completed", "2026-11-21T10:30:00Z")] };         // the 11:17 and 12:17 slots were both dropped by GitHub
  assert.deepEqual(files("2026-11-21T12:30:00Z", runs), ["update-site.yml"]);
  assert.deepEqual(files("2026-11-21T12:37:00Z", runs), ["update-site.yml"]);               // 20 min old: still due (inclusive)
  assert.deepEqual(files("2026-11-21T12:37:01Z", runs), []);                                // 20 min 1 s: the slot is lost, the next one (13:17) takes over
  assert.deepEqual(files("2026-11-21T12:40:00Z", runs), []);
});

test("already running: a queued or in-progress run blocks the dispatch (also one from an older slot)", () => {
  for (const st of ["queued", "in_progress", "waiting", "pending", "requested"]) {
    assert.deepEqual(files("2026-11-21T12:30:00Z", { "update-site.yml": [run(9, st, "2026-11-21T11:50:00Z")] }), [], st);
  }
  const d = decide(at("2026-11-21T12:30:00Z"), { "update-site.yml": [run(9, "in_progress", "2026-11-21T12:05:00Z")] });
  assert.equal(d[0].action, "skip");
  assert.match(d[0].reason, /in_progress/);
});

test("already ran: a run created after the slot (GitHub's own cron, a push, an earlier dispatch) satisfies it", () => {
  assert.deepEqual(files("2026-11-21T12:30:00Z", { "update-site.yml": [run(2, "completed", "2026-11-21T12:19:00Z")] }), []);
  assert.deepEqual(files("2026-11-21T12:30:00Z", { "update-site.yml": [run(2, "completed", "2026-11-21T12:17:00Z")] }), []);   // created exactly at the slot
  assert.deepEqual(files("2026-11-21T12:30:00Z", { "update-site.yml": [run(2, "completed", "2026-11-21T12:16:59Z")] }), ["update-site.yml"]);  // a second before: previous slot's run
});

test("duplicate protection (ecmwf 08:50 slot): dispatch at 09:00, then queued, running, finished: never again", () => {
  const before = { "ecmwf.yml": [run(1, "completed", "2026-11-21T01:50:00Z")] };
  assert.deepEqual(files("2026-11-21T09:00:00Z", before), ["ecmwf.yml"]);                  // tick 1 dispatches
  const queued = { "ecmwf.yml": [run(2, "queued", "2026-11-21T09:00:03Z"), ...before["ecmwf.yml"]] };
  assert.deepEqual(files("2026-11-21T09:10:00Z", queued), []);                              // tick 2: the dispatched run is queued
  const running = { "ecmwf.yml": [run(2, "in_progress", "2026-11-21T09:00:03Z"), ...before["ecmwf.yml"]] };
  assert.deepEqual(files("2026-11-21T09:10:00Z", running), []);
  const done = { "ecmwf.yml": [run(2, "completed", "2026-11-21T09:00:03Z"), ...before["ecmwf.yml"]] };
  assert.deepEqual(files("2026-11-21T09:10:00Z", done), []);                                // finished fast (nothing new): still no second dispatch
});

test("UTC boundary: the 23:50 slot of the previous day is still due at 00:00 and 00:10", () => {
  const runs = { "ecmwf.yml": [run(1, "completed", "2026-11-21T22:51:00Z")] };
  assert.deepEqual(files("2026-11-22T00:00:00Z", runs), ["ecmwf.yml"]);
  assert.deepEqual(files("2026-11-22T00:10:00Z", runs), ["ecmwf.yml"]);
  assert.deepEqual(files("2026-11-22T00:11:00Z", runs), []);                                // 21 min: lost
  const slot = latestSlot(at("2026-11-22T00:00:00Z"), ["50 8-13,20-23,0-1 * * *"]);
  assert.equal(new Date(slot).toISOString(), "2026-11-21T23:50:00.000Z");
});

test("UTC boundary: a slot of today at 00:xx after a late run of yesterday", () => {
  // the 00:50 ecmwf slot (hour 0 is in the list), run list shows yesterday's 23:51 run: older than the slot, so due at 01:00
  const runs = { "ecmwf.yml": [run(1, "completed", "2026-11-21T23:51:00Z")] };
  assert.deepEqual(files("2026-11-22T01:00:00Z", runs), ["ecmwf.yml"]);
});

test("ecmwf window: slots at :50 in hours 0-1, 8-13 and 20-23 only (across midnight)", () => {
  const ecm = SCHEDULES.find((w) => w.file === "ecmwf.yml").crons;
  const slotHours = new Set();
  for (let h = 0; h < 24; h++) {                                       // tick at hh:10: the :50 slot of the previous hour is exactly 20 min old
    const s = latestSlot(at(`2026-11-21T${String(h).padStart(2, "0")}:10:00Z`), ecm);
    if (s !== null) slotHours.add(new Date(s).getUTCHours());
  }
  assert.deepEqual([...slotHours].sort((x, y) => x - y), [0, 1, 8, 9, 10, 11, 12, 13, 20, 21, 22, 23]);
  assert.equal(latestSlot(at("2026-11-21T04:10:00Z"), ecm), null);       // nothing between 02:00 and 07:59 or 14:00 and 19:59
  assert.equal(latestSlot(at("2026-11-21T16:10:00Z"), ecm), null);
});

test("models.yml: both crons count (01:55, 04:55 ... and the extra 02:55, 08:55, 14:55, 20:55)", () => {
  const m = SCHEDULES.find((w) => w.file === "models.yml").crons;
  const slotHours = new Set();
  for (let h = 0; h < 24; h++) {                                       // tick at hh:05: the (h-1):55 slot is 10 min old
    const s = latestSlot(at(`2026-11-21T${String(h).padStart(2, "0")}:05:00Z`), m);
    if (s !== null) slotHours.add(new Date(s).getUTCHours());
  }
  assert.deepEqual([...slotHours].sort((x, y) => x - y), [1, 2, 4, 7, 8, 10, 13, 14, 16, 19, 20, 22]);
});

test("one workflow does not influence another", () => {
  const now = "2026-11-21T08:30:00Z";                                  // update-site slot 08:17 (run in progress) and gefs slot 08:10; models slot 07:55 is 35 min old (lost)
  const runs = { "update-site.yml": [run(1, "in_progress", "2026-11-21T08:00:00Z")], "gefs.yml": [run(2, "completed", "2026-11-20T20:20:00Z")] };
  assert.deepEqual(files(now, runs), ["gefs.yml"]);
});

test("verify.yml: the daily 15:25 slot", () => {
  const runs = { "verify.yml": [run(1, "completed", "2026-11-20T15:30:00Z")] };
  assert.deepEqual(files("2026-11-21T15:35:00Z", runs), ["verify.yml"]);
  assert.deepEqual(files("2026-11-21T15:35:00Z", { "verify.yml": [run(2, "completed", "2026-11-21T15:27:00Z"), ...runs["verify.yml"]] }), []);
});

test("a candidate whose run list could not be read is skipped, never dispatched blind", () => {
  const d = decide(at("2026-11-21T12:30:00Z"), { "update-site.yml": null });
  assert.equal(d.length, 1);
  assert.equal(d[0].action, "skip");
  assert.equal(candidates(at("2026-11-21T12:50:00Z")).length, 0);       // :50 is between slots of every workflow except ecmwf (hour 12 :50 is itself a slot, age 0 < grace)
});

// ---------------------------------------------------------------- tick() with a fake GitHub
function fakeGitHub({ lists = {}, posts = {} } = {}) {
  const calls = [];
  const f = async (url, init = {}) => {
    const method = init.method || "GET";
    calls.push({ url, method, headers: init.headers, body: init.body });
    const file = url.match(/workflows\/([\w.-]+)\//)[1];
    const table = method === "POST" ? posts : lists;
    const r = table[file] ?? (method === "POST" ? { status: 204 } : { status: 200, body: { workflow_runs: [] } });
    if (r === "throw") throw Object.assign(new Error("boom"), { name: "TimeoutError" });
    return { status: r.status, ok: r.status >= 200 && r.status < 300, json: async () => r.body ?? { message: r.message ?? "x" } };
  };
  return { f, calls };
}
const ENV = { GH_DISPATCH_TOKEN: "ghp_SECRETSECRETSECRET", GH_REPOSITORY: "alexluke23/snow-wx", GH_REF: "main" };

test("tick: dispatches only what is due, with ref main, and never logs the token", async () => {
  const { f, calls } = fakeGitHub();
  const logs = [];
  const res = await tick(at("2026-11-21T12:10:00Z"), ENV, f, (l) => logs.push(l));          // only the ecmwf 11:50 slot is in the window
  assert.deepEqual(res.dispatched, ["ecmwf.yml"]);
  const post = calls.filter((c) => c.method === "POST");
  assert.equal(post.length, 1);
  assert.match(post[0].url, /repos\/alexluke23\/snow-wx\/actions\/workflows\/ecmwf\.yml\/dispatches$/);
  assert.deepEqual(JSON.parse(post[0].body), { ref: "main" });
  assert.equal(post[0].headers.Authorization, "Bearer ghp_SECRETSECRETSECRET");
  assert.ok(calls.every((c) => c.method === "POST" || /per_page=5/.test(c.url)));
  assert.ok(logs.length >= 2 && logs.every((l) => !l.includes("SECRET")), logs.join("\n"));
});

test("tick: API errors are logged and the next workflow is still handled (401, 403, 404, 500, timeout)", async () => {
  for (const [code, bad] of [[401, { status: 401, message: "Bad credentials" }], [403, { status: 403, message: "forbidden" }], [404, { status: 404, message: "Not Found" }], [500, { status: 500 }], ["timeout", "throw"]]) {
    // 08:30 UTC: update-site (08:17 slot) and gefs (08:10 slot) are both due
    const { f, calls } = fakeGitHub({ lists: { "update-site.yml": bad } });
    const logs = [];
    const res = await tick(at("2026-11-21T08:30:00Z"), ENV, f, (l) => logs.push(l));
    assert.deepEqual(res.dispatched, ["gefs.yml"], String(code));
    assert.ok(logs.some((l) => l.includes("update-site.yml") && l.includes("cannot list runs")), String(code));
    assert.ok(!calls.some((c) => c.method === "POST" && c.url.includes("update-site.yml")), String(code));
    assert.ok(logs.every((l) => !l.includes("SECRET")), String(code));
  }
});

test("tick: a failed dispatch is logged and does not stop the others", async () => {
  const { f } = fakeGitHub({ posts: { "update-site.yml": { status: 403, message: "Resource not accessible by personal access token" } } });
  const logs = [];
  const res = await tick(at("2026-11-21T08:30:00Z"), ENV, f, (l) => logs.push(l));
  assert.deepEqual(res.failed, ["update-site.yml"]);
  assert.deepEqual(res.dispatched, ["gefs.yml"]);
  assert.ok(logs.some((l) => l.includes("dispatch failed: HTTP 403")));
});

test("tick: DRY_RUN decides and logs but dispatches nothing; a missing token does nothing and does not throw", async () => {
  const { f, calls } = fakeGitHub();
  const logs = [];
  const res = await tick(at("2026-11-21T12:10:00Z"), { ...ENV, DRY_RUN: "true" }, f, (l) => logs.push(l));
  assert.deepEqual(res.dispatched, []);
  assert.ok(calls.some((c) => c.method === "GET" && /ecmwf\.yml\/runs\?per_page=5/.test(c.url)));   // DRY_RUN still LISTS the runs (the decision is real) ...
  assert.ok(!calls.some((c) => c.method === "POST") && logs.some((l) => l.includes("DRY_RUN")));    // ... but never calls the dispatch endpoint
  const none = fakeGitHub();
  const res2 = await tick(at("2026-11-21T12:10:00Z"), { GH_REPOSITORY: "a/b", GH_REF: "main" }, none.f, (l) => logs.push(l));
  assert.deepEqual(res2.dispatched, []);
  assert.equal(none.calls.length, 0);
});

test("tick: subrequest budget (free plan: 50) holds even when every workflow is due at once", async () => {
  const everything = [{ file: "a.yml", crons: ["0 * * * *"] }, { file: "b.yml", crons: ["0 * * * *"] }];
  assert.equal(candidates(at("2026-11-21T12:10:00Z"), {}, everything).length, 2);
  assert.ok(SCHEDULES.length * 2 <= 50);
});
