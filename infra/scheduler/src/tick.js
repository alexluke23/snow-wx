// One scheduler tick: list runs for the due candidates, dispatch what is still due. Separate from index.js so the Worker entry exports only its handler.
// Free-plan budget: <= 5 list calls + <= 5 dispatch calls (50 subrequests allowed), trivial CPU. The token (GH_DISPATCH_TOKEN) is never logged.
import { WINDOW_MIN, candidates, decide } from "./due.js";

const API = "https://api.github.com";
const TIMEOUT_MS = 8000;

function headers(token) {
  return {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "snow-wx-scheduler",
  };
}

/** a short, token-free description of a failed response */
async function problem(res) {
  let msg = "";
  try { msg = String((await res.json())?.message ?? "").slice(0, 120); } catch { /* not JSON */ }
  return `HTTP ${res.status}${msg ? ` (${msg})` : ""}`;
}

/** latest runs of one workflow on the ref -> array, or null on any error (logged) */
async function listRuns(file, env, f, log) {
  const url = `${API}/repos/${env.GH_REPOSITORY}/actions/workflows/${file}/runs?per_page=5&branch=${encodeURIComponent(env.GH_REF)}`;
  try {
    const res = await f(url, { headers: headers(env.GH_DISPATCH_TOKEN), signal: AbortSignal.timeout(TIMEOUT_MS) });
    if (!res.ok) { log(`[scheduler] ${file}: cannot list runs: ${await problem(res)}`); return null; }
    return (await res.json()).workflow_runs ?? [];
  } catch (e) {
    log(`[scheduler] ${file}: cannot list runs: ${e?.name ?? "error"}`);
    return null;
  }
}

async function dispatch(file, env, f, log) {
  const url = `${API}/repos/${env.GH_REPOSITORY}/actions/workflows/${file}/dispatches`;
  try {
    const res = await f(url, {
      method: "POST",
      headers: { ...headers(env.GH_DISPATCH_TOKEN), "Content-Type": "application/json" },
      body: JSON.stringify({ ref: env.GH_REF }),
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
    if (res.status === 204) { log(`[scheduler] ${file}: dispatched on ${env.GH_REF}`); return true; }
    log(`[scheduler] ${file}: dispatch failed: ${await problem(res)}`);
  } catch (e) {
    log(`[scheduler] ${file}: dispatch failed: ${e?.name ?? "error"}`);
  }
  return false;
}

/** one tick. `f` and `log` are injectable for tests. Never throws. */
export async function tick(now, env, f = fetch, log = console.log) {
  const stamp = new Date(now).toISOString().slice(0, 16) + "Z";
  const result = { dispatched: [], skipped: [], failed: [] };
  try {
    if (!env.GH_DISPATCH_TOKEN || !env.GH_REPOSITORY || !env.GH_REF) {
      log(`[scheduler] ${stamp} not configured (secret GH_DISPATCH_TOKEN or vars GH_REPOSITORY / GH_REF missing): nothing done`);
      return result;
    }
    const cands = candidates(now);
    if (!cands.length) { log(`[scheduler] ${stamp} no workflow has a slot in the last ${WINDOW_MIN} min`); return result; }
    const runs = {};
    for (const c of cands) runs[c.file] = await listRuns(c.file, env, f, log);
    for (const d of decide(now, runs)) {
      if (d.action !== "dispatch") { log(`[scheduler] ${stamp} ${d.file} slot ${d.slot.slice(11, 16)}Z: skip: ${d.reason}`); result.skipped.push(d.file); continue; }
      log(`[scheduler] ${stamp} ${d.file} slot ${d.slot.slice(11, 16)}Z: due (${d.reason})`);
      if (env.DRY_RUN === "true") { log(`[scheduler] ${d.file}: DRY_RUN, not dispatched`); result.skipped.push(d.file); continue; }
      (await dispatch(d.file, env, f, log) ? result.dispatched : result.failed).push(d.file);
    }
  } catch (e) {                                       // a bug must not turn into a failed cron run that hides the next ones
    log(`[scheduler] ${stamp} unexpected error: ${e?.message ?? e}`);
  }
  return result;
}
