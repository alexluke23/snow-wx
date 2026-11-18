"""Active NWS alerts matched to ski areas and SNOTEL sites (PLAN.md M5 part 1).

One call per run: api.weather.gov/alerts/active?area=<western states>. Most winter
alerts carry only zone codes (geocode.UGC, e.g. UTZ111) and no polygon, so matching
uses each point's NWS forecast zone and county (stored in the catalogs from
api.weather.gov /points), plus point-in-polygon when an alert has a geometry.

Output (<out>/alerts/):
  index.json   {generated_at, count, alerts: {aid: summary}, areas: {id: [ref]}, points: {id: [ref]}}
  details.json {aid: {description, instruction}} (loaded only when a banner is expanded)
  hazard_text.json {generated_at, alerts: {aid: {e, h, o, f, x, a, d, i}}} the text of EVERY active alert of the winter event types the obs-map
               hazards layer draws (config `hazards` include/exclude), also those touching no ski area or SNOTEL site, so a map popup can show the
               NWS text from our own files (dev17: only ~31 % of the layer's polygons were in index.json; the rest needed a live api.weather.gov call).
               Built from the same /alerts/active response; no extra request.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from .common import plural, REPO_ROOT, utcnow, write_json

log = logging.getLogger("snow-wx.alerts")
URL = "https://api.weather.gov/alerts/active"

# badge levels (CSS classes) by the last word of the event name
LEVEL = {"Warning": "warning", "Watch": "watch", "Advisory": "advisory", "Statement": "statement"}


def short_name(event: str) -> str:
    """'Winter Storm Warning' -> 'Winter Storm Warn.' (badge text)."""
    return (event.replace("Warning", "Warn.").replace("Advisory", "Adv.").replace("Statement", "Stmt.")
            .replace("Special Weather", "Spec. Wx"))


# Mountain-relevant alerts list first (owner S4); every other alert is still shown.
RELEVANT = ("winter", "snow", "blizzard", "ice storm", "freez", "avalanche", "wind", "cold", "chill", "frost")


def relevant(event: str) -> bool:
    e = (event or "").lower()
    return any(w in e for w in RELEVANT)


def alert_key(alert_id: str) -> str:
    return hashlib.sha1(alert_id.encode()).hexdigest()[:10]


def summarize(feature: dict) -> dict:
    p = feature["properties"]
    ev = p.get("event") or "Alert"
    return {"event": ev, "short": short_name(ev), "level": LEVEL.get(ev.split()[-1], "other"),
            "severity": p.get("severity"), "headline": p.get("headline"), "sender": p.get("senderName"),
            "area": p.get("areaDesc"), "effective": p.get("effective"), "onset": p.get("onset"),
            "ends": p.get("ends") or p.get("expires"), "expires": p.get("expires")}


def is_hazard_event(event: str, include: list[str], exclude: list[str]) -> bool:
    """True when the event name matches the hazards layer's winter patterns (config `hazards.include` / `exclude`, case-insensitive substrings
    or regexes), mirroring pipeline/hazards.py `winter_products`; only watch / warning / advisory levels."""
    import re
    e = (event or "").strip()
    if not re.search(r"\b(watch|warning|advisory)$", e, re.I):
        return False
    return any(re.search(p, e, re.I) for p in include) and not any(re.search(p, e, re.I) for p in exclude)


def hazard_texts(features: list[dict], include: list[str], exclude: list[str], now=None) -> dict:
    """{alert key: compact record} for every current alert of a hazard-layer event type. Keys are alert_key(alert id), the same lookup the
    page uses (sha1 of the urn, 10 hex chars). Field names are short to keep the file small: e event, h headline, o sender, f effective,
    x expires, a areaDesc, d description, i instruction. Text is stored as received (the page renders it with textContent only)."""
    out: dict[str, dict] = {}
    for f in features:
        p = f.get("properties") or {}
        if p.get("status") not in (None, "Actual") or not p.get("id") or not is_hazard_event(p.get("event"), include, exclude):
            continue
        rec = {"e": p.get("event"), "h": p.get("headline"), "o": p.get("senderName"), "f": p.get("effective"),
               "x": p.get("ends") or p.get("expires"), "a": (p.get("areaDesc") or "")[:500],
               "d": (p.get("description") or "")[:4000], "i": (p.get("instruction") or "")[:2000]}
        out[alert_key(p["id"])] = {k: v for k, v in rec.items() if v}
    return out


def match(features: list[dict], sites: list[dict]) -> dict[str, list[str]]:
    """sites: [{id, codes: set(UGC), lonlat: [(lon, lat)]}] -> {site id: [alert keys]}."""
    from shapely.geometry import Point, shape
    out: dict[str, list[str]] = {}
    for f in features:
        p = f.get("properties") or {}
        if p.get("status") not in (None, "Actual"):
            continue
        ugc = set((p.get("geocode") or {}).get("UGC") or [])
        geom = shape(f["geometry"]) if f.get("geometry") else None
        key = alert_key(p.get("id") or json.dumps(p.get("geocode")))
        for s in sites:
            hit = bool(ugc & s["codes"]) or (geom is not None and any(geom.contains(Point(x, y)) for x, y in s["lonlat"]))
            if hit:
                out.setdefault(s["id"], [])
                if key not in out[s["id"]]:
                    out[s["id"]].append(key)
    return out


def load_sites(repo: Path = REPO_ROOT) -> tuple[list[dict], list[dict]]:
    """(ski-area sites, SNOTEL sites) with their UGC zone/county codes and locations."""
    areas, points = [], []
    from .common import forecast_areas          # ski areas + Sno-Parks (M4.5)
    for a in forecast_areas(repo):
        codes = {c for k in ("summit", "base") for c in ((a.get("nws") or {}).get(k) or {}).values()
                 if isinstance(c, str) and len(c) == 6 and c[2] in "ZC"}
        areas.append({"id": a["id"], "codes": codes,
                      "lonlat": [(a[k]["lon"], a[k]["lat"]) for k in ("summit", "base")]})
    sp = repo / "data" / "snotel_points.json"
    if sp.exists():
        for s in json.loads(sp.read_text(encoding="utf-8"))["points"]:
            codes = {c for c in ((s.get("nws") or {}).get("zone"), (s.get("nws") or {}).get("county")) if c}
            points.append({"id": s["id"], "codes": codes, "lonlat": [(s["lon"], s["lat"])]})
    return areas, points


def build(features: list[dict], areas: list[dict], points: list[dict]) -> tuple[dict, dict]:
    m_areas, m_points = match(features, areas), match(features, points)
    used = {k for v in list(m_areas.values()) + list(m_points.values()) for k in v}
    alerts, details = {}, {}
    for f in features:
        p = f.get("properties") or {}
        k = alert_key(p.get("id") or json.dumps(p.get("geocode")))
        if k in used:
            alerts[k] = summarize(f)
            details[k] = {"description": (p.get("description") or "")[:6000],
                          "instruction": (p.get("instruction") or "")[:3000]}

    def refs(m):        # warnings first, then watches, advisories
        order = {"warning": 0, "watch": 1, "advisory": 2, "statement": 3, "other": 4}
        return {sid: sorted(({"id": k, "event": alerts[k]["event"], "short": alerts[k]["short"],
                              "level": alerts[k]["level"], "ends": alerts[k]["ends"],
                              "relevant": relevant(alerts[k]["event"])} for k in ks),
                            key=lambda r: (not r["relevant"], order[r["level"]])) for sid, ks in m.items()}
    index = {"generated_at": utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"), "count": len(alerts),
             "source": "NOAA/NWS active alerts (api.weather.gov)", "alerts": alerts,
             "areas": refs(m_areas), "points": refs(m_points)}
    return index, details


def run(cfg: dict, session, outdir: Path) -> dict:
    states = cfg["region"]["states"]
    r = session.get(URL, params={"area": ",".join(states)}, headers={"Accept": "application/geo+json"}, timeout=60)
    r.raise_for_status()
    js = r.json()
    if not isinstance(js, dict) or not isinstance(js.get("features"), list):          # a 200 without a feature list is a broken answer, not "no alerts"
        raise RuntimeError("alerts: unexpected payload (no features list); keeping the last good files")
    features = js["features"]
    areas, points = load_sites()
    index, details = build(features, areas, points)
    out = outdir / "alerts"
    write_json(out / "index.json", index)
    write_json(out / "details.json", details)
    hc = cfg.get("hazards") or {}
    texts = hazard_texts(features, hc.get("include", []), hc.get("exclude", [])) if hc.get("enabled", True) else {}
    write_json(out / "hazard_text.json", {"generated_at": index["generated_at"], "source": index["source"], "alerts": texts})
    log.info("alerts: hazard_text.json carries %d alerts of the layer's event types", len(texts))
    log.info("alerts: %d active in %s; %d affect %d ski areas and %d SNOTEL sites", len(features), ",".join(states),
             index["count"], len(index["areas"]), len(index["points"]))
    return {"count": index["count"], "unit": "alerts", "detail": f"{plural(len(index['areas']), 'ski area')} affected",
            "areas": len(index["areas"]), "points": len(index["points"])}
