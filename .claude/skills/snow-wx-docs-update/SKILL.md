---
name: snow-wx-docs-update
description: Update the Snow-Wx docs after a code change or decision - BACKLOG status, STATUS, DECISIONS, specs, about.html, INDEX - and run the docs checks (links, business-content guard, wording tests, PLAN size). Use at the end of every merge request and whenever a decision is made or a doc is added or moved.
---

# Keep the docs true

Docs are read by agents at the start of every session; a stale line becomes a wrong action later. Update docs in the **same**
merge request as the change.

## What to update

| Event | Update |
|---|---|
| Backlog item done | `docs/BACKLOG.md`: status → `✅ <branch/MR> <YYYY-MM-DD>`; if it unblocks something, say so on that row |
| Item dropped | strike through the row and give the reason |
| New bug or task found | new row in `docs/BACKLOG.md` (next free ID in its section; roadmap actions use `A-NN` in `docs/ROADMAP.md`) |
| What's live changed (feature, flag, workflow, numbers) | `docs/STATUS.md` |
| Decision made | top row of `docs/DECISIONS.md` (date, decision, reason); mirror in `docs/PLAN.md` §3 only if it changes current work; ADR in `docs/adr/` for trade-offs |
| Behaviour/method changed | the feature spec in `docs/specs/`; `web/about.html` for user-facing methods; `docs/DESIGN.md` for UI rules |
| Roadmap date or owner changed | `docs/ROADMAP.md` (action item row + the timeline) |
| Doc added, moved or retired | `docs/INDEX.md`; retired docs go to `docs/archive/` or `docs/specs/retired/` with a banner saying why and what replaced them; use `git mv` |
| Long-lived gotcha | one short bullet in `CLAUDE.md` "Reusable gotchas" |

Every doc keeps its front matter (`status`, `owner`, `last_reviewed`, `read_when`); bump `last_reviewed` when you edit it.

## Rules

- **No business content** in tracked files (pricing, entity, positioning, brand/domain shortlists, partner strategy). Write "set by owner".
- Keep `docs/PLAN.md` ≤ ~20 KB (`wc -c docs/PLAN.md`). Move detail to STATUS / DECISIONS / BACKLOG / archive.
- Keep § numbers stable; other docs cite them.
- Never hard-code ensemble member counts ("51 members" fails `tests/test_ecmwf_wording.py`).
- Dates are absolute (`Nov 23 2026`), never "yesterday" or "next week".

## Checks (run before pushing)

```bash
python -m pytest -q tests/test_no_business_content.py tests/test_ecmwf_wording.py tests/test_scheduler.py
wc -c docs/PLAN.md            # ≤ ~20,000
python - <<'EOF'
import re, os, subprocess
files = subprocess.run(["git","ls-files","-co","--exclude-standard","*.md"], capture_output=True, text=True).stdout.split()
bad = []
for f in files:
    if not os.path.exists(f) or f.startswith(("docs/archive/", "docs/reviews/")):
        continue
    s = open(f, encoding="utf-8").read()
    for m in re.finditer(r"\]\(([^)#\s]+)(#[^)]*)?\)", s):
        t = m.group(1)
        if not re.match(r"[a-z]+:", t) and not os.path.exists(os.path.normpath(os.path.join(os.path.dirname(f), t))):
            bad.append((f, t))
print("broken links:", bad or "none")
EOF
```
`docs/archive/` and `docs/reviews/` are skipped on purpose: they keep historical paths verbatim.
