"""dev23 Part 4: the NDFD forecast files (build/data/ndfd/, ~1,446 files) are not part of the deployed site.

Proof that removing them cannot break anything the site requests: no browser code, service worker / PWA precache list, page / sitemap generator or link checker names them; the only
mentions in web/ are display labels and prose. And the one workflow edit is exactly one step that deletes the folder AFTER the archive step (which reads it) and BEFORE the Pages upload,
with the NDFD fetch, its release-asset unpack and the archive untouched. The browser suite's `nondfd` check does the same proof in a real browser."""
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
WF = ROOT / ".github" / "workflows" / "update-site.yml"


def steps():
    return yaml.safe_load(WF.read_text(encoding="utf-8"))["jobs"]["build"]["steps"]


def test_no_browser_code_builds_an_ndfd_url():
    bad = []
    for p in WEB.rglob("*"):
        if p.is_file() and p.suffix in (".js", ".html", ".css", ".json", ".webmanifest") and "vendor" not in p.parts:
            t = p.read_text(encoding="utf-8", errors="replace")
            for m in re.finditer(r"[^\n]*ndfd[^\n]*", t, re.I):
                line = m.group(0)
                if re.search(r"ndfd/|ndfd\.json|ndfd\"\s*\)|data/ndfd|\$\{[^}]*\}/ndfd|['\"`]ndfd['\"`]\s*\]", line, re.I) and "label" not in line.lower():
                    bad.append((str(p.relative_to(ROOT)), line.strip()[:120]))
    # the only code mentions are the status labels (keys of the health table), checked below
    assert bad == [], bad


def test_the_only_ndfd_words_in_web_are_labels_and_prose():
    allowed = {"web/js/app.js": 1, "web/js/status.js": 2, "web/sources.html": 1, "web/about.html": 3}
    got = {}
    for p in WEB.rglob("*"):
        if p.is_file() and p.suffix in (".js", ".html") and "vendor" not in p.parts:
            n = len(re.findall(r"[^\n]*ndfd[^\n]*", p.read_text(encoding="utf-8", errors="replace"), re.I))
            if n:
                got[str(p.relative_to(ROOT)).replace("\\", "/")] = n
    # the verification panel files (dev23 Part 3) no longer mention it either
    assert got == allowed, got
    status = (WEB / "js" / "status.js").read_text(encoding="utf-8")
    assert "ndfd:" in status and 'ORDER = ["points", "ndfd"' in status               # a health row read from meta.json, not a file fetch
    assert "ndfd" not in re.sub(r"\bndfd: \"[^\"]*\"|\"ndfd\",", "", status)


def test_pwa_pages_sitemap_and_linkcheck_do_not_know_the_folder():
    for rel in ("pipeline/pwa.py", "pipeline/pwa_sw.js", "pipeline/pages.py", "pipeline/linkcheck.py", "pipeline/stub.py", "pipeline/og.py"):
        p = ROOT / rel
        if p.exists():
            assert "ndfd" not in p.read_text(encoding="utf-8").lower(), rel
    pwa = (ROOT / "pipeline" / "pwa.py").read_text(encoding="utf-8")
    assert 'out.glob("*.html")' in pwa and "data" not in re.search(r"files = sorted.*?\n(?:.*\n){0,3}", pwa).group(0)     # the precache list: html, css, js, leaflet; never data/


def test_the_workflow_step_removes_the_folder_after_the_archive_and_before_the_upload():
    names = [s.get("name") or s.get("uses") for s in steps()]
    i_arc = names.index("Forecast archive (verification release)")
    i_rm = names.index("Leave the NDFD forecast files out of the deployed site")
    i_up = next(i for i, s in enumerate(steps()) if str(s.get("uses", "")).startswith("actions/upload-pages-artifact"))
    assert i_arc + 1 == i_rm and i_rm < i_up
    assert steps()[i_rm]["run"].strip() == "rm -rf build/data/ndfd"
    assert "continue-on-error" not in steps()[i_rm]


def test_the_ndfd_fetch_unpack_and_archive_are_untouched():
    text = WF.read_text(encoding="utf-8")
    assert "case \"$m\" in points|nohrsc|ndfd) dest=build/data ;; esac" in text               # the unpack loop still extracts ndfd (the archive reads it)
    assert "python -m pipeline archive --data build/data" in text
    assert "ndfd" in (ROOT / ".github" / "workflows" / "models.yml").read_text(encoding="utf-8")   # the fetch job is unchanged
    on = yaml.safe_load(text)[True]
    assert on["schedule"] == [{"cron": "17 * * * *"}] and "workflow_dispatch" in on and on["push"] == {"branches": ["main"]}
    d = yaml.safe_load(text)
    assert d["concurrency"] == {"group": "pages", "cancel-in-progress": False}
