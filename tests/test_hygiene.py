"""Repo hygiene: no e-mail address hard-coded in the web code (owner Nov 17): the feedback address lives only in config/settings.yml."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_no_email_address_in_web_pages_or_scripts():
    pat = re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}", re.I)
    hits = []
    for f in list((ROOT / "web").glob("*.html")) + list((ROOT / "web" / "js").rglob("*.js")) + list((ROOT / "web" / "css").glob("*.css")):
        for m in pat.finditer(f.read_text(encoding="utf-8")):
            hits.append(f"{f.name}: {m.group(0)}")
    assert not hits, hits


def test_feedback_links_use_the_shared_config_script():
    for f in ROOT.joinpath("web").glob("*.html"):
        s = f.read_text(encoding="utf-8")
        if 'class="site-feedback"' in s:
            assert "data-mailto" in s and "js/site-config.js" in s, f.name
