"""Latest NWS Area Forecast Discussion per forecast office (PLAN.md M5 part 2).

Offices = every WFO that issues the forecast for a ski area or SNOTEL site (catalog
`nws.<pt>.wfo`, about 30). Two api.weather.gov calls per office per run: the product
list (newest first) and the product text. Runs in every hourly build as an obs source.

Output (<out>/afd/):
  index.json  {generated_at, offices: {WFO: {issued, office}}}
  <WFO>.json  {wfo, office, issued, id, link, text}   (loaded by an area page on demand)
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .common import REPO_ROOT, utcnow, write_json

log = logging.getLogger("snow-wx.afd")
LIST_URL = "https://api.weather.gov/products/types/AFD/locations/{wfo}"
# stable human link to the current AFD on forecast.weather.gov
LINK = "https://forecast.weather.gov/product.php?site=NWS&issuedby={wfo}&product=AFD&format=txt&version=1"
MAX_TEXT = 40000


def offices(repo: Path = REPO_ROOT) -> list[str]:
    """Every WFO responsible for a ski area (summit or base) or a SNOTEL forecast point."""
    out = set()
    cat = json.loads((repo / "data" / "ski_areas.json").read_text(encoding="utf-8"))
    for a in cat["areas"]:
        for pt in (a.get("nws") or {}).values():
            if pt and pt.get("wfo"):
                out.add(pt["wfo"])
    sp = repo / "data" / "snotel_points.json"
    if sp.exists():
        for s in json.loads(sp.read_text(encoding="utf-8"))["points"]:
            w = (s.get("nws") or {}).get("wfo")
            if w:
                out.add(w)
    return sorted(out)


def parse(text: str) -> tuple[str | None, str]:
    """Product text -> (office name, discussion body). Drops the WMO header lines
    above "Area Forecast Discussion" and everything after the final "$$"."""
    lines = (text or "").replace("\r", "").split("\n")
    start = next((i for i, ln in enumerate(lines) if ln.strip().lower() == "area forecast discussion"), 0)
    body = lines[start:]
    office = None
    for ln in body[1:4]:
        m = re.match(r"\s*National Weather Service (.+)", ln)
        if m:
            office = m.group(1).strip()
            break
    s = "\n".join(body)
    if "$$" in s:
        s = s[: s.rindex("$$")]
    return office, s.strip()[:MAX_TEXT]


def fetch(session, wfo: str) -> dict | None:
    r = session.get(LIST_URL.format(wfo=wfo), headers={"Accept": "application/ld+json"}, timeout=30)
    r.raise_for_status()
    graph = r.json().get("@graph") or []
    if not graph:
        return None
    latest = graph[0]
    p = session.get(latest["@id"], headers={"Accept": "application/ld+json"}, timeout=30)
    p.raise_for_status()
    office, body = parse(p.json().get("productText") or "")
    return {"wfo": wfo, "office": office or f"NWS {wfo}", "issued": latest.get("issuanceTime"),
            "id": latest.get("id"), "link": LINK.format(wfo=wfo), "text": body}


def run(cfg: dict, session, outdir: Path) -> dict:
    wfos = offices()
    out = outdir / "afd"
    index, failed = {}, []

    def one(w):
        try:
            return w, fetch(session, w)
        except Exception as e:  # noqa: BLE001 - one office failing must not stop the rest
            log.warning("AFD %s: %s", w, e)
            return w, None

    with ThreadPoolExecutor(4) as ex:
        for w, doc in ex.map(one, wfos):
            if doc is None:
                failed.append(w)
                continue
            write_json(out / f"{w}.json", doc)
            index[w] = {"issued": doc["issued"], "office": doc["office"]}
    write_json(out / "index.json", {"generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                                    "source": "NOAA/NWS Area Forecast Discussions (api.weather.gov)",
                                    "offices": index})
    log.info("AFD: %d of %d offices%s", len(index), len(wfos), f" (failed: {','.join(failed)})" if failed else "")
    if not index:
        raise RuntimeError("no AFD fetched")
    return {"count": len(index), "unit": "discussions", "detail": f"{len(index)} offices"}
