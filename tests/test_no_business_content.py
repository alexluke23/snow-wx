"""Guardrail: business planning is private and never part of this PUBLIC repo (CLAUDE.md, PLAN.md header).

Fails when
  * a tracked path lives under private/ or is named BUSINESS* (any case, any folder);
  * private/ is not gitignored;
  * a tracked text file (outside tests/ and licence files) contains one of a small list of generic business terms.

Offline and fast: reads `git ls-files` and the working-tree copies. Skips when git or the .git folder is missing (e.g. a source tarball).
"""
from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Small and generic on purpose; word boundaries so "evaluation" or "business planning is private" do not match.
TERMS = ["pricing tier", "subscription price", r"\bLLC\b", r"\bvaluation\b", r"\binvestors?\b", "revenue target", r"\bbusiness plans?\b"]
PATTERN = re.compile("|".join(f"(?:{t})" for t in TERMS), re.IGNORECASE)

# Licence texts are third-party legal wording, not ours (e.g. BSD "BUSINESS INTERRUPTION" clauses).
LICENCE_NAMES = re.compile(r"^(licen[cs]e|copying|notice)([._-].*)?$|_licen[cs]e|licen[cs]e_", re.IGNORECASE)

# Explicit exceptions: tracked path -> why it may contain a term. Keep this list short; add a reason for every entry.
EXCEPTIONS: dict[str, str] = {
    # (none today)
}

BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".gz", ".tar", ".zip", ".npz", ".pdf", ".ttf", ".woff", ".woff2", ".grib2"}


def tracked_files() -> list[str]:
    if not shutil.which("git") or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True).stdout
    return [p for p in out.decode("utf-8", "replace").split("\0") if p]


def scanned(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return not (path.startswith("tests/") or LICENCE_NAMES.search(name) or Path(name).suffix.lower() in BINARY_EXT or path in EXCEPTIONS)


def test_the_term_list_matches_what_it_should_and_nothing_else():
    for hit in ("Acme LLC", "pricing tier", "Subscription price", "our valuation", "an investor deck", "Revenue target", "the business plan"):
        assert PATTERN.search(hit), hit
    for miss in ("evaluation", "re-evaluation of NBM", "business planning is private", "llcs-free", "small business interruption"):
        assert not PATTERN.search(miss), miss


def test_no_private_or_business_files_are_tracked():
    bad = [p for p in tracked_files() if p.startswith("private/") or fnmatch.fnmatch(p.rsplit("/", 1)[-1].lower(), "business*")]
    assert bad == [], f"business files must stay out of the repo (keep them in the gitignored private/): {bad}"


def test_private_folder_is_gitignored():
    lines = [ln.strip() for ln in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    assert "private/" in lines or "/private/" in lines


def test_tracked_text_files_have_no_business_terms():
    hits = []
    for path in tracked_files():
        f = ROOT / path
        if not scanned(path) or not f.is_file():
            continue
        raw = f.read_bytes()
        if b"\0" in raw[:8192]:
            continue                                   # binary
        for n, line in enumerate(raw.decode("utf-8", "replace").splitlines(), 1):
            m = PATTERN.search(line)
            if m:
                hits.append(f"{path}:{n}: {m.group(0)!r}")
    assert hits == [], "business wording in tracked files (business planning is private; see CLAUDE.md):\n" + "\n".join(hits)


def test_exceptions_still_exist():
    tracked = set(tracked_files())
    assert all(p in tracked for p in EXCEPTIONS), "remove stale entries from EXCEPTIONS"
