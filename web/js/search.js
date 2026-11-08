// Site-wide search (header of every page) + the shared ranking used by the obs-map panel search.
// Index: data/search.json (pipeline/search.py), loaded the first time the box is used.
// Accessible combobox: input[role=combobox] + listbox, aria-activedescendant, ↑/↓/Enter/Esc;
// on narrow screens the box collapses to a search button. Selecting opens the forecast page.

// eslint-disable-next-line no-unused-vars
const SnowSearch = (() => {
  /** Rank records {name, ids[]}: exact id, then name/id prefix, then word prefix, then substring. */
  function rank(index, query, limit = 10) {
    const q = String(query || "").trim().toLowerCase();
    if (!q) return [];
    const hits = [];
    for (const s of index) {
      const ids = s.ids.map((x) => String(x).toLowerCase()), name = s.name.toLowerCase();
      let score = -1;
      if (ids.includes(q)) score = 0;
      else if (name.startsWith(q) || ids.some((x) => x.startsWith(q))) score = 1;
      else if (name.split(/[\s\-/()]+/).some((w) => w.startsWith(q))) score = 2;
      else if (name.includes(q)) score = 3;
      if (score >= 0) hits.push([score, s]);
    }
    hits.sort((a, b) => a[0] - b[0] || a[1].name.localeCompare(b[1].name));
    return hits.slice(0, limit).map((h) => h[1]);
  }

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  let indexP = null;
  const loadIndex = () => (indexP ||= fetch("data/search.json", { cache: "no-cache" })
    .then((r) => (r.ok ? r.json() : { items: [] }))
    .then((d) => (d.items || []).map((x) => ({ kind: x.k, id: x.id, name: x.n, sub: x.s, ids: [x.id, ...(x.x || [])],
      url: `area.html#${encodeURIComponent(x.id)}` })))
    .catch(() => []));

  function header() {
    const form = document.querySelector(".site-search");
    if (!form) return;
    const input = form.querySelector("input"), list = form.querySelector("[role=listbox]"),
      toggle = form.querySelector(".ss-toggle");
    let results = [], active = -1;
    const setOpen = (on) => {
      form.classList.toggle("open", on);
      toggle?.setAttribute("aria-expanded", String(on));
      if (on) { input.focus(); loadIndex(); } else close();
    };
    const close = () => {
      list.hidden = true; active = -1;
      input.setAttribute("aria-expanded", "false"); input.removeAttribute("aria-activedescendant");
    };
    const render = () => {
      if (!input.value.trim()) return close();
      list.innerHTML = results.length
        ? results.map((s, i) => `<li role="option" id="ss-opt-${i}" aria-selected="${i === active}" data-i="${i}"
            class="${i === active ? "active" : ""}">${esc(s.name)}<span class="kind">${esc(s.sub)}</span></li>`).join("")
        : `<li class="empty" role="option" aria-disabled="true">No match</li>`;
      list.hidden = false;
      input.setAttribute("aria-expanded", "true");
      if (active >= 0) input.setAttribute("aria-activedescendant", `ss-opt-${active}`);
      else input.removeAttribute("aria-activedescendant");
    };
    const choose = (i) => {
      const s = results[i];
      if (!s) return;
      close();
      input.value = "";
      setOpen(false);
      location.href = s.url;
    };
    input.addEventListener("focus", () => loadIndex());
    input.addEventListener("input", async () => {
      const idx = await loadIndex();
      results = rank(idx, input.value, 8);
      active = results.length ? 0 : -1;
      render();
    });
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        if (!results.length) return;
        e.preventDefault();
        active = (active + (e.key === "ArrowDown" ? 1 : results.length - 1)) % results.length;
        render();
        list.querySelector("li.active")?.scrollIntoView({ block: "nearest" });
      } else if (e.key === "Enter") {
        e.preventDefault();
        choose(active >= 0 ? active : 0);
      } else if (e.key === "Escape") {
        if (!list.hidden) close(); else setOpen(false);
      }
    });
    list.addEventListener("mousedown", (e) => {          // mousedown: before the input blurs
      const li = e.target.closest("li[data-i]");
      if (li) { e.preventDefault(); choose(Number(li.dataset.i)); }
    });
    input.addEventListener("blur", () => setTimeout(() => { if (!form.contains(document.activeElement)) { close(); form.classList.remove("open"); toggle?.setAttribute("aria-expanded", "false"); } }, 150));
    toggle?.addEventListener("click", () => setOpen(!form.classList.contains("open")));
    form.addEventListener("submit", (e) => { e.preventDefault(); choose(active >= 0 ? active : 0); });
    // "/" focuses the search (like many sites), unless typing somewhere already
    document.addEventListener("keydown", (e) => {
      const t = e.target;
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|SELECT|TEXTAREA)$/.test(t.tagName) || t.isContentEditable) return;
      e.preventDefault();
      setOpen(true);
    });
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", header);
  else header();
  return { rank, loadIndex };
})();
