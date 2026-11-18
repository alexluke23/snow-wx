"""Daily Snow summaries (W3, docs/specs/daily-summaries.md): a deterministic rules engine, NOT an LLM.

summarize(doc, alerts, obs, rules) -> {tag, sentence, bullets, confidence, rule_ids, native}

`doc` is one area's NBM point file (points.summit / points.base or the single station point). Thresholds live in
config/summary_rules.yml. Hard rules (PLAN section 0, owner Nov 16):
- Rules that use p50 or P(>=X) need NATIVE NBM windows (exceedance windows are always native; totals only when
  `native` is true). When the window is composite (percentiles of several 6 h windows added) or missing, the rule is skipped
  and the summary says so with LOWER confidence; only expected amounts are used then.
- Never sum, scale or interpolate percentiles. Hedged language; "blower" is a labeled heuristic, never an accuracy claim.
- Safety information is never hidden: an active NWS winter alert (when `alerts` is given) outranks everything.
"""

from __future__ import annotations

from pathlib import Path

import yaml

RULES_PATH = Path(__file__).resolve().parent.parent / "config" / "summary_rules.yml"


SETTINGS_PATH = RULES_PATH.parent / "settings.yml"


def load_rules(path: Path | None = None) -> dict:
    """Rules file plus the ONE shared powder-quality thresholds from settings.yml (owner Nov 17)."""
    with open(path or RULES_PATH, encoding="utf-8") as f:
        rules = yaml.safe_load(f)
    with open(SETTINGS_PATH, encoding="utf-8") as f:
        rules["powder_quality"] = (yaml.safe_load(f) or {}).get("powder_quality") or {}
    return rules


def _num(v, d=0):
    return None if v is None else round(float(v), d)


def _inch(v) -> str:
    return "0" if v is None or v < 0.05 else ("<1" if v < 0.5 else f"{round(v)}")


def pick_point(doc: dict, which: str = "summit") -> tuple[str, dict] | tuple[None, None]:
    pts = doc.get("points") or {}
    for k in (which, "point", "summit", "base"):
        if k in pts:
            return k, pts[k]
    return None, None


def native_first_window(pt: dict, window: str) -> dict | None:
    """First exceedance window (always native NBM) of `window` ('24h'/'48h'/'72h'): {p50, p_ge: {thr: %}} or None."""
    ex = (pt.get("exceed") or {}).get(window)
    if not ex or not ex.get("end"):
        return None
    p50 = ((ex.get("pct") or {}).get("50") or [None])[0]
    thr = ex.get("thr") or []
    rows = ex.get("p") or []
    p_ge = {float(t): rows[0][i] for i, t in enumerate(thr)} if rows else {}
    return {"p50": p50, "p_ge": p_ge, "start": ex["start"][0], "end": ex["end"][0]}


def facts(doc: dict, rules: dict) -> dict:
    """The numbers the rules need, with their provenance (native or not)."""
    k, pt = pick_point(doc)
    kb, base = pick_point(doc, "base")
    f = {"point": k, "has_base": base is not None and kb == "base" and k != "base"}
    if pt is None:
        return f
    t24, t72 = (pt.get("totals") or {}).get("24h") or {}, (pt.get("totals") or {}).get("72h") or {}
    f["expected_24h"], f["expected_72h"] = t24.get("snow_in"), t72.get("snow_in")
    f["native_72h"] = bool(t72.get("native"))
    f["range_72h"] = (t72.get("snow_lo"), t72.get("snow_hi")) if f["native_72h"] else None
    w24, w72 = native_first_window(pt, "24h"), native_first_window(pt, "72h")
    f["w24"], f["w72"] = w24, w72
    per = pt.get("periods") or []
    first = [p for p in per if p.get("end") and p["end"] <= (w24 or {}).get("end", "")] if w24 else per[:2]
    snowy = [p for p in first if (p.get("snow_in") or 0) >= 0.5 and p.get("slr")]
    f["slr_24h"] = max((p["slr"] for p in snowy), default=None)
    gusts = [p["gust_max_mph"] for p in first if p.get("gust_max_mph") is not None]
    f["gust_24h"] = max(gusts, default=None)
    f["wind_snow"] = any((p.get("snow_type") or {}).get("wind") for p in per[:6])
    f["warm"] = [p for p in per[:6] if (p.get("qpf_in") or 0) >= rules["rain_base"]["min_qpf_in"] and (p.get("p_snow") is not None)
                 and p["p_snow"] < rules["rain_base"]["p_snow_max"]]
    if base is not None and kb == "base":
        f["base_warm"] = [p for p in (base.get("periods") or [])[:6] if (p.get("qpf_in") or 0) >= rules["rain_base"]["min_qpf_in"]
                          and p.get("p_snow") is not None and p["p_snow"] < rules["rain_base"]["p_snow_max"]]
    else:
        f["base_warm"] = []
    return f


def summarize(doc: dict, alerts: list[dict] | None = None, obs: dict | None = None, rules: dict | None = None) -> dict:
    rules = rules or load_rules()
    f = facts(doc, rules)
    fired: list[tuple[str, str, str]] = []              # (rule_id, tag, sentence)
    skipped_non_native = False
    if f.get("point") is None:
        return {"tag": "No forecast", "sentence": "No forecast is available for this place right now.", "bullets": [],
                "confidence": "low", "rule_ids": [], "native": False}

    # alert (safety first; only when the caller supplies alerts)
    winter = [a for a in (alerts or []) if a.get("relevant", True) is not False]
    if winter:
        names = ", ".join(sorted({a["event"] for a in winter}))
        fired.append(("alert", "Alert active", f"NWS alert in effect: {names}. See the alert and your local avalanche center."))

    # rain at the base: needs the modelled snow probability per period (NBM snow-level percentiles), not a percentile sum
    if f["base_warm"]:
        lv = [p["snowlvl_min_ft"] for p in f["base_warm"] if p.get("snowlvl_min_ft")]
        where = f" Snow level down to about {round(min(lv), -2):,.0f} ft." if lv else ""
        fired.append(("rain_base", "Rain at the base", f"Rain is likely at the base during part of this storm; snow above it.{where}"))

    # deep powder day: native p50 24 h + native P(>=12) + SLR + wind
    r = rules["deep_powder"]
    w24 = f["w24"]
    if w24 is None:
        skipped_non_native = True
    else:
        p12 = w24["p_ge"].get(12.0)
        if (w24["p50"] is not None and w24["p50"] >= r["p50_24h_in"] and p12 is not None and p12 >= r["p_ge12_pct"]
                and f["slr_24h"] is not None and f["slr_24h"] >= rules["powder_quality"]["blower_at"] and (f["gust_24h"] or 0) < r["gust_mph"]):
            fired.append(("deep_powder", "Deep powder day",
                          f"Deep, light snow likely: NBM's median for the next 24 h is {_inch(w24['p50'])} in with a {p12}% chance of 12 in or more"
                          f" (snow ratio about {round(f['slr_24h'])}:1, the Blower class, a heuristic), summit gusts under {r['gust_mph']} mph."))

    # storm cycle: native 72 h window (p50 and the native p10-p90 range); never a summed range
    r = rules["storm_cycle"]
    w72 = f["w72"]
    if w72 is None or not f["native_72h"]:
        skipped_non_native = True
    elif w72["p50"] is not None and w72["p50"] >= r["p50_72h_in"] and f["range_72h"] and None not in f["range_72h"]:
        lo, hi = f["range_72h"]
        fired.append(("storm_cycle", "Storm cycle",
                      f"Multi-day storm: {_inch(lo)}–{_inch(hi)} in likely at the {f['point'].replace('point', 'station')} over the next 72 h (NBM 10–90%)."))

    # wind-affected snow (summit gusts > threshold while snowing: from the snow-type flag)
    if f["wind_snow"] and (f.get("expected_72h") or 0) >= rules["wind"]["min_snow_72h_in"]:
        fired.append(("wind", "Wind-affected", "Wind-affected snow likely: summit gusts are high while it snows (a heuristic, see about)."))

    # dry stretch: native 72 h p50 under the limit (non-native: expected total only, lower confidence)
    r = rules["dry_stretch"]
    if w72 is not None and f["native_72h"] and w72["p50"] is not None:
        if w72["p50"] < r["p50_72h_in"]:
            fired.append(("dry", "Dry stretch", "Little new snow expected in the next 72 hours."))
    elif f.get("expected_72h") is not None and f["expected_72h"] < r["p50_72h_in"]:
        fired.append(("dry", "Dry stretch", "Little new snow expected in the next 72 hours (expected amount only: no NBM range available)."))
        skipped_non_native = True

    order = rules["priority"]
    fired.sort(key=lambda x: order.index(x[0]) if x[0] in order else 99)
    if not fired:                                           # baseline: the expected amount, hedged
        e = f.get("expected_72h")
        sentence = ("No snowfall forecast is available right now." if e is None
                    else "Little or no snow expected over the next 72 h." if e < 0.5
                    else f"Expected snowfall over the next 72 h: about {_inch(e)} in (NBM's average).")
        head = ("Snow expected" if (e or 0) >= 1 else "Little snow")
        fired.append(("baseline", head, sentence))
    tag, sentence = fired[0][1], fired[0][2]
    bullets = [x[2] for x in fired[1:4]]
    native = (f["w24"] is not None) and f["native_72h"]
    confidence = "high" if native else ("medium" if f["w24"] is not None else "low")
    if skipped_non_native and confidence == "high":
        confidence = "medium"
    return {"tag": tag, "sentence": sentence, "bullets": bullets, "confidence": confidence,
            "rule_ids": [x[0] for x in fired], "native": native}
