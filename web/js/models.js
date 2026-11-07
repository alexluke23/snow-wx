// Model map viewer: reads models/index.json (written by `python -m pipeline build`
// from each model's index) and plays the PNG frames. No build step.

(() => {
  "use strict";

  const BASE = "models/";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pad3 = (n) => String(n).padStart(3, "0");

  let catalog = null;
  const state = { m: null, f: null, d: null, h: null };
  let hours = [];          // forecast hours for the current field
  let idx = 0;             // position in `hours`
  let timer = null;
  const cache = new Map(); // url -> Image (keeps preloaded frames alive)

  const model = () => catalog.models[state.m];
  const field = () => model().fields[state.f];

  function frameUrl(h) {
    const m = model();
    return BASE + m.base + m.path.replace("{field}", state.f).replace("{domain}", state.d)
      .replace("{fhour}", pad3(h));
  }

  const initDate = () => new Date(model().init);   // "2026-11-07T06:00Z"

  function fmtUTC(d) {
    return `${String(d.getUTCHours()).padStart(2, "0")}Z ${d.toLocaleDateString("en-US",
      { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" })}`;
  }

  function fmtLocal(d, tz) {
    try {
      return d.toLocaleString("en-US", { weekday: "short", hour: "numeric", timeZone: tz, timeZoneName: "short" });
    } catch (e) {
      return "";
    }
  }

  // ---------------------------------------------------------------- hash state
  function readHash() {
    const q = new URLSearchParams(location.hash.replace(/^#/, ""));
    return { m: q.get("m"), f: q.get("f"), d: q.get("d"), h: q.has("h") ? Number(q.get("h")) : null };
  }

  function writeHash() {
    const h = `#m=${state.m}&f=${state.f}&d=${state.d}&h=${state.h}`;
    if (h !== location.hash) history.replaceState(null, "", h);
  }

  // ---------------------------------------------------------------- selects
  function fillModels() {
    $("model").innerHTML = Object.entries(catalog.models).map(([k, m]) =>
      `<option value="${esc(k)}">${esc(m.label)} ${esc(m.cycle.slice(8, 10))}Z</option>`).join("");
    $("model").value = state.m;
  }

  function fillFields() {
    const groups = {};
    for (const [k, f] of Object.entries(model().fields)) (groups[f.group] ||= []).push([k, f]);
    $("field").innerHTML = Object.entries(groups).map(([g, items]) =>
      `<optgroup label="${esc(g)}">${items.map(([k, f]) =>
        `<option value="${esc(k)}">${esc(f.label)}</option>`).join("")}</optgroup>`).join("");
    $("field").value = state.f;
  }

  function fillDomains() {
    $("domain").innerHTML = field().domains.map((d) =>
      `<option value="${esc(d)}">${esc(model().domains[d]?.label || d)}</option>`).join("");
    $("domain").value = state.d;
  }

  // Keep the user's choices when they still exist in the new model/field.
  function settle(want = {}) {
    const ms = Object.keys(catalog.models);
    state.m = ms.includes(want.m) ? want.m : ms.includes(state.m) ? state.m : ms[0];
    const fs = Object.keys(model().fields);
    state.f = fs.includes(want.f) ? want.f : fs.includes(state.f) ? state.f : fs[0];
    const ds = field().domains;
    state.d = ds.includes(want.d) ? want.d : ds.includes(state.d) ? state.d : ds[0];
    hours = field().fhours;
    const target = want.h ?? state.h ?? hours[0];
    idx = nearestIndex(target);
    fillModels(); fillFields(); fillDomains();
    $("hour").max = String(hours.length - 1);
    show(idx);
    preload();
  }

  function nearestIndex(h) {
    let best = 0;
    hours.forEach((x, i) => { if (Math.abs(x - h) < Math.abs(hours[best] - h)) best = i; });
    return best;
  }

  // ---------------------------------------------------------------- frames
  function show(i) {
    idx = Math.max(0, Math.min(hours.length - 1, i));
    state.h = hours[idx];
    const url = frameUrl(state.h);
    const img = $("frame");
    img.classList.remove("missing");
    img.src = url;
    img.alt = `${model().label} ${field().label}, ${model().domains[state.d]?.label}, F${pad3(state.h)}`;
    $("hour").value = String(idx);
    const valid = new Date(initDate().getTime() + state.h * 3600e3);
    const tz = model().domains[state.d]?.tz || "America/Denver";
    $("hour-label").innerHTML = `<strong>F${pad3(state.h)}</strong> · ${esc(fmtUTC(valid))}` +
      `<span class="local"> · ${esc(fmtLocal(valid, tz))}</span>`;
    writeHash();
  }

  function preload() {
    const urls = hours.map(frameUrl);
    let done = 0;
    const total = urls.length;
    const tick = () => {
      done++;
      $("loading").textContent = done < total ? `loading ${done}/${total}` : "";
    };
    $("loading").textContent = `loading 0/${total}`;
    for (const u of urls) {
      let im = cache.get(u);
      if (im && im.complete) { tick(); continue; }
      if (!im) { im = new Image(); cache.set(u, im); im.src = u; }
      im.addEventListener("load", tick, { once: true });
      im.addEventListener("error", tick, { once: true });
    }
    if (cache.size > 600) {               // don't hold every frame of every combo forever
      for (const k of [...cache.keys()].slice(0, cache.size - 600)) cache.delete(k);
    }
  }

  function step(delta) { show((idx + delta + hours.length) % hours.length); }

  function play(on) {
    clearTimeout(timer);
    timer = null;
    $("play").textContent = on ? "❚❚ Pause" : "▶ Play";
    $("play").setAttribute("aria-label", on ? "Pause" : "Play");
    if (!on) return;
    const loop = () => {
      const next = (idx + 1) % hours.length;
      const im = cache.get(frameUrl(hours[next]));
      if (!im || im.complete) step(1);           // wait for frames still loading
      const dwell = idx === hours.length - 1 ? 3 : 1;
      timer = setTimeout(loop, Number($("speed").value) * dwell);
    };
    timer = setTimeout(loop, Number($("speed").value));
  }

  // ---------------------------------------------------------------- wiring
  $("model").addEventListener("change", (e) => settle({ m: e.target.value }));
  $("field").addEventListener("change", (e) => settle({ f: e.target.value }));
  $("domain").addEventListener("change", (e) => settle({ d: e.target.value }));
  $("hour").addEventListener("input", (e) => { play(false); show(Number(e.target.value)); });
  $("prev").addEventListener("click", () => { play(false); step(-1); });
  $("next").addEventListener("click", () => { play(false); step(1); });
  $("play").addEventListener("click", () => play(timer === null));
  $("frame").addEventListener("error", (e) => {
    e.target.classList.add("missing");
    $("caption").textContent = `Frame F${pad3(state.h)} is missing for this region.`;
  });
  $("frame").addEventListener("load", () => {
    const m = model();
    $("caption").textContent = `${m.label} run ${m.init.replace("T", " ")} · ${m.attribution || ""}`;
  });

  document.addEventListener("keydown", (e) => {
    const t = e.target;
    if (t.tagName === "SELECT" || (t.tagName === "INPUT" && t.type !== "range")) return;
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") {
      if (t.type === "range") return;              // the slider handles its own arrows
      e.preventDefault(); play(false); step(e.key === "ArrowRight" ? 1 : -1);
    } else if (e.key === " " || e.code === "Space") {
      e.preventDefault(); play(timer === null);
    } else if (e.key === "Home") {
      e.preventDefault(); play(false); show(0);
    } else if (e.key === "End") {
      e.preventDefault(); play(false); show(hours.length - 1);
    }
  });

  window.addEventListener("hashchange", () => {
    const h = readHash();
    if (h.m !== state.m || h.f !== state.f || h.d !== state.d) settle(h);
    else if (h.h !== null && h.h !== state.h) show(nearestIndex(h.h));
  });

  async function load() {
    try {
      const r = await fetch(`${BASE}index.json?v=${Date.now()}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      catalog = await r.json();
    } catch (e) {
      catalog = { models: {} };
    }
    const names = Object.keys(catalog.models || {});
    if (!names.length) {
      $("updated").textContent = "No model runs yet";
      $("empty").hidden = false;
      document.querySelector(".frame").hidden = true;
      return;
    }
    $("updated").textContent = "Runs: " + names.map((k) => {
      const m = catalog.models[k];
      return `${m.label} ${m.cycle.slice(8, 10)}Z ${m.cycle.slice(6, 8)}/${m.cycle.slice(4, 6)}`;
    }).join(" · ");
    settle(readHash());
  }

  load();
})();
