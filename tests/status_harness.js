// Runs web/js/status.js (the public status page logic) against a meta.json in Node with a tiny fake DOM and prints the rows it would draw as JSON:
//   node tests/status_harness.js <path to meta.json>   ->   [{"name": "NWS alerts", "cls": "st-ok"}, ...]
// Used by tests/test_failure_modes.py to check that the status page and pipeline/monitor.py agree for each failing source.
const fs = require("fs"), vm = require("vm"), path = require("path");
const meta = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const els = {};
const el = (id) => (els[id] ||= { id, hidden: true, textContent: "", innerHTML: "", style: {} });
const ctx = {
  document: { getElementById: el }, console, Date, Math, Number, String, Object, Array, JSON, Promise, Intl,
  fetch: () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(meta) }),
};
ctx.window = ctx;
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(__dirname, "..", "web", "js", "status.js"), "utf8"), ctx);
setTimeout(() => {
  const html = els["st-table"] ? els["st-table"].innerHTML : "";
  const rows = [...html.matchAll(/<tr class="(st-[a-z]+)"><th scope="row">([^<]*)<\/th>/g)].map((m) => ({ cls: m[1], name: m[2].replace(/&amp;/g, "&") }));
  console.log(JSON.stringify({ rows, banner: els["st-banner"] ? (els["st-banner"].hidden ? "" : els["st-banner"].textContent) : "" }));
}, 50);
