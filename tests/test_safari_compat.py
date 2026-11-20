"""dev21 Part 0a: Safari / iPhone guards on our own scripts and styles (vendor code excluded).

Safari has no requestIdleCallback, and iOS Safari's 100vh includes the hidden toolbar. These static checks keep every
use of the risky APIs behind a fallback; tools/browser_check.py `noidle` runs the pages with the APIs removed."""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
JS = [p for p in (WEB / "js").rglob("*.js")]
CSS = [p for p in (WEB / "css").rglob("*.css")]


def lines(paths):
    for p in paths:
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            yield p, n, line


def test_every_request_idle_callback_has_a_fallback_on_the_same_line():
    bad = []
    for p, n, line in lines(JS):
        if "requestIdleCallback" not in line or line.strip().startswith("//"):
            continue
        guarded = "typeof window.requestIdleCallback" in line
        if not guarded:
            bad.append(f"{p.name}:{n}: {line.strip()[:120]}")
    assert not bad, bad


def test_no_detached_idle_call():
    """`(window.requestIdleCallback || f)(...)` calls the API without its receiver"""
    rx = re.compile(r"\(\s*window\.requestIdleCallback\s*\|\|")
    assert not [f"{p.name}:{n}" for p, n, line in lines(JS) if rx.search(line)]


def test_no_api_safari_lacks_or_got_late():
    # structuredClone (Safari 15.4), Array.prototype.at (15.4), regex lookbehind (16.4), AbortSignal.timeout (16), findLast (15.4), toSorted (16)
    rx = re.compile(r"structuredClone\(|\.at\(-?\d|\(\?<[=!]|AbortSignal\.timeout|\.findLast(Index)?\(|\.toSorted\(|\.toReversed\(")
    hits = [f"{p.name}:{n}: {line.strip()[:100]}" for p, n, line in lines(JS) if rx.search(line) and not line.strip().startswith("//")]
    assert not hits, hits


def test_every_100vh_has_a_dynamic_viewport_override():
    bad = []
    for p, n, line in lines(CSS):
        if "100vh" in line and not re.search(r"100[sdl]vh", line):
            bad.append(f"{p.name}:{n}: {line.strip()[:100]}")
    assert not bad, bad


def test_matchmedia_listeners_use_the_safe_form():
    # MediaQueryList.addEventListener only from Safari 14; use addListener fallback or matches only
    rx = re.compile(r"matchMedia\([^)]*\)\.addEventListener")
    assert not [f"{p.name}:{n}" for p, n, line in lines(JS) if rx.search(line)]
