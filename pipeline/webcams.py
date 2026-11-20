"""Webcam LINKS (PLAN M10, links only; dev18 Part 1). `config/webcams.yml` lists, per area, up to three links to the PROVIDER's own webcam page
(resort official / state DOT / avalanche center / USFS). The site only ever renders them as plain outbound links (rel="noopener noreferrer"):
  * NO embedding, NO iframes, NO hotlinked images, NO caching of anyone's pictures, NO scraping of images or snow reports;
  * the link checker below fetches a page only to learn its HTTP status (HEAD, then a GET without reading the body when HEAD is refused),
    one request per URL, a polite pause per host.
`python -m pipeline webcams --check [--update]` reports dead links; the build writes the public `data/webcams.json` ({area id: [{label, url, type, host}]}).
Pure functions are tested offline (tests/test_webcams.py, fakes for the network).
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .common import REPO_ROOT, write_json

log = logging.getLogger("snow-wx.webcams")
CONFIG = REPO_ROOT / "config" / "webcams.yml"
TYPES = {"resort": "Resort", "dot": "State DOT", "avalanche_center": "Avalanche center", "usfs": "US Forest Service"}
CONFIDENCE = ("high", "low")
MAX_PER_AREA = 3
MEDIA = re.compile(r"\.(jpe?g|png|gif|webp|mp4|webm|m3u8|mjpe?g|mjpg|swf)(\?|$)", re.I)       # a link to a picture or a stream is hotlinking material: refused
HEADER = """# Webcam LINKS (PLAN M10, links only): where a visitor can look at the provider's own webcams. See pipeline/webcams.py.
#   NO embedding, NO iframes, NO hotlinked images, NO scraping: the area page shows these as plain outbound links.
# Per area (id from data/ski_areas.json or data/rec_points.json), at most 3 entries:
#   label: text of the link (<= 60 chars)        url: https only, the PROVIDER's webcam PAGE (never an image or stream file)
#   type: resort | dot | avalanche_center | usfs  last_checked: YYYY-MM-DD (the day a person or `pipeline webcams --check --update` confirmed it loads)
#   status: HTTP status at that check            confidence: high | low (low = flagged for owner review: only a generic page was found, or the page
#                                                 redirected somewhere unexpected, or it loads but the content could not be confirmed)
"""


def load(path: Path = CONFIG) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}


def host_of(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def validate(doc: dict, area_ids: set[str] | None = None) -> list[str]:
    """Every problem with the document, as readable strings (empty list = valid)."""
    errs: list[str] = []
    areas = doc.get("areas")
    if not isinstance(areas, dict) or not areas:
        return ["`areas` must be a non-empty mapping of area id -> list of links"]
    for aid, items in areas.items():
        if area_ids is not None and aid not in area_ids:
            errs.append(f"{aid}: not a known area id")
        if not isinstance(items, list) or not items:
            errs.append(f"{aid}: needs a list of 1-{MAX_PER_AREA} links")
            continue
        if len(items) > MAX_PER_AREA:
            errs.append(f"{aid}: {len(items)} links (max {MAX_PER_AREA})")
        seen = set()
        for k, e in enumerate(items):
            where = f"{aid}[{k}]"
            if not isinstance(e, dict):
                errs.append(f"{where}: must be a mapping")
                continue
            label, url = e.get("label"), e.get("url")
            if not isinstance(label, str) or not 3 <= len(label.strip()) <= 60:
                errs.append(f"{where}: label must be 3-60 characters")
            if not isinstance(url, str):
                errs.append(f"{where}: url missing")
            else:
                p = urlparse(url)
                if p.scheme != "https" or not p.hostname:
                    errs.append(f"{where}: url must be https ({url})")
                if p.username or p.password:
                    errs.append(f"{where}: url must not carry credentials")
                if MEDIA.search(p.path + ("?" + p.query if p.query else "")):
                    errs.append(f"{where}: url points at a picture/stream file, not a page ({url}); no hotlinking")
                if p.hostname and re.fullmatch(r"[\d.]+|\[.*\]", p.hostname):
                    errs.append(f"{where}: use a host name, not an IP address")
                if url in seen:
                    errs.append(f"{where}: duplicate url")
                seen.add(url)
            if e.get("type") not in TYPES:
                errs.append(f"{where}: type must be one of {sorted(TYPES)}")
            try:
                date.fromisoformat(str(e.get("last_checked")))
            except ValueError:
                errs.append(f"{where}: last_checked must be YYYY-MM-DD")
            if e.get("confidence", "high") not in CONFIDENCE:
                errs.append(f"{where}: confidence must be high or low")
            if "status" in e and not isinstance(e["status"], int):
                errs.append(f"{where}: status must be an integer HTTP status")
    return errs


def area_ids(repo: Path = REPO_ROOT) -> set[str]:
    ids: set[str] = set()
    for name, key in (("ski_areas.json", "areas"), ("rec_points.json", "points")):
        f = repo / "data" / name
        if f.exists():
            js = json.loads(f.read_text(encoding="utf-8"))
            ids |= {a["id"] for a in (js.get(key) or js.get("areas") or [])}
    return ids


def public(doc: dict) -> dict[str, list[dict]]:
    """what the page needs: {area id: [{label, url, type, host}]} (never more than MAX_PER_AREA, never anything but the validated fields)"""
    out = {}
    for aid, items in (doc.get("areas") or {}).items():
        out[aid] = [{"label": e["label"].strip(), "url": e["url"], "type": e["type"], "host": host_of(e["url"])} for e in items[:MAX_PER_AREA]]
    return out


def write_public(out: Path, doc: dict | None = None) -> int:
    """data/webcams.json for the site build; an invalid config raises (the build keeps the last good file instead)"""
    doc = doc if doc is not None else load()
    errs = validate(doc, area_ids() or None)
    if errs:
        raise ValueError("config/webcams.yml is invalid: " + "; ".join(errs[:5]))
    pub = public(doc)
    write_json(Path(out), pub)
    return len(pub)


# ---------------------------------------------------------------- link checker (network, thin)
SOFT_ERROR = re.compile(r"/(errors?|404|not-?found|page-?not-?found)(/|\?|$)", re.I)       # a server that answers 200 on its own error page


def soft_error(final: str | None) -> bool:
    return bool(final) and bool(SOFT_ERROR.search(urlparse(final).path + ("?" + urlparse(final).query if urlparse(final).query else "")))


def check_url(session, url: str, timeout: float = 20.0) -> dict:
    """{status, final, error}: HEAD first; one GET (stream=True: the body is never downloaded) when HEAD answers an error (some servers mishandle HEAD) or HEAD
    ends on what looks like the site's own error page (some servers answer HEAD badly). A link that STILL ends on an error page is dead (status 404)."""
    out = {"url": url, "status": None, "final": None, "error": None}
    try:
        r = session.head(url, timeout=timeout, allow_redirects=True)
        if r.status_code >= 400 or soft_error(getattr(r, "url", url)):                      # some servers answer HEAD with 404/405/403: one GET decides
            r = session.get(url, timeout=timeout, allow_redirects=True, stream=True)
            r.close()
        out["status"], out["final"] = r.status_code, getattr(r, "url", url)
        if out["status"] < 400 and soft_error(out["final"]):
            out["status"], out["error"] = 404, "ends on the site's own error page"
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{type(exc).__name__}: {str(exc)[:100]}"
    return out


def check_all(doc: dict, session, pause: float = 1.0, sleep=time.sleep) -> list[dict]:
    """one request per URL, at least `pause` seconds between requests to the same host. Returns a report row per link."""
    rows, last = [], {}
    for aid, items in (doc.get("areas") or {}).items():
        for e in items:
            h = host_of(e["url"])
            wait = pause - (time.monotonic() - last.get(h, -1e9))
            if wait > 0:
                sleep(wait)
            res = check_url(session, e["url"])
            last[h] = time.monotonic()
            res.update(area=aid, label=e["label"], moved_host=bool(res["final"]) and host_of(res["final"]) != host_of(e["url"]))
            res["ok"] = res["status"] is not None and 200 <= res["status"] < 400
            rows.append(res)
    return rows


def apply_report(doc: dict, rows: list[dict], today: str | None = None) -> dict:
    """copy the check into the config: status + last_checked for links that loaded; a dead link keeps its old date and gets confidence: low"""
    today = today or date.today().isoformat()
    by = {(r["area"], r["url"]): r for r in rows}
    for aid, items in (doc.get("areas") or {}).items():
        for e in items:
            r = by.get((aid, e["url"]))
            if not r:
                continue
            if r["ok"]:
                e["status"], e["last_checked"] = r["status"], today
            else:
                e["status"], e["confidence"] = r["status"] or 0, "low"
    return doc


def dump(doc: dict, path: Path = CONFIG) -> None:
    body = yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=160)
    Path(path).write_text(HEADER + body, encoding="utf-8")


def run_check(update: bool, session, report: Path | None = None, path: Path = CONFIG) -> int:
    doc = load(path)
    errs = validate(doc, area_ids() or None)
    if errs:
        for e in errs:
            log.error(e)
        return 2
    rows = check_all(doc, session)
    dead = [r for r in rows if not r["ok"]]
    moved = [r for r in rows if r["ok"] and r["moved_host"]]
    for r in dead:
        log.warning("DEAD %s %s -> %s %s", r["area"], r["url"], r["status"], r["error"] or "")
    for r in moved:
        log.info("moved host %s: %s -> %s", r["area"], r["url"], r["final"])
    log.info("webcams: %d links, %d dead, %d on a different host after redirects", len(rows), len(dead), len(moved))
    if report:
        write_json(report, rows)
    if update:
        dump(apply_report(doc, rows), path)
    return 1 if dead else 0
