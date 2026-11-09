"""Parse NBM .idx inventories and pick the messages a run needs (pure, no network).

Inventory facts (checked 7 Nov 2026, core + qmd, blend v4.x on AWS):
- core runs every hour to f264: hourly f001-f048, 3-hourly to f192, 6-hourly to f264.
  qmd (QPF/T/wind percentiles) exists only for 00/06/12/18Z.
- Snowfall (ASNOW 1-h and 6-h) percentiles 1..99 exist only to f048 (6-h to f054);
  SNOWLVL and SNOWLR percentiles only to f048. Beyond that NBM gives the
  deterministic value only.
- QPF percentiles (qmd, 0..100 by 5): 6-h and 12-h windows every 6 h, 24-h day
  windows ("0-1 day" ...) and 2-3-day blocks ("0-3 day", "3-5 day", "5-7 day",
  "7-10 day") to f264.
- No terrain field in either file.
- core messages use alternativeRowScanning=1 (odd rows stored east-to-west; ecCodes
  returns storage order), qmd does not: see run.flat_index. Decoded values were
  checked against the NBS text bulletins (TMP, Q06, SLV) at 8 airports.
- SNOWLVL is metres MSL; SNOWLR is ~0 where no snow falls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_WIN = re.compile(r"^(\d+)-(\d+) (hour|day) (acc|max|min|ave)")
_INST = re.compile(r"^(\d+) hour fcst")


@dataclass(frozen=True)
class Msg:
    var: str
    level: str
    start: int | None      # window start (h); None for an instantaneous field
    end: int               # valid / window end (h)
    stat: str | None       # acc | max | min | ave | None
    kind: str              # det | pct | prob | std | other
    value: str | int | None  # percentile (int) or probability threshold (str)
    offset: int
    length: int | None     # None for the last message in the file


def parse_idx(text: str) -> list[Msg]:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    offs = [int(ln.split(":")[1]) for ln in lines]
    out = []
    for n, ln in enumerate(lines):
        parts = ln.split(":")
        var, level, trange = parts[3], parts[4], parts[5]
        rest = ":".join(parts[6:]).strip()
        m = _WIN.match(trange)
        if m:
            mult = 24 if m.group(3) == "day" else 1
            start, end, stat = int(m.group(1)) * mult, int(m.group(2)) * mult, m.group(4)
        else:
            mi = _INST.match(trange)
            start, end, stat = None, (int(mi.group(1)) if mi else 0), None
        if rest.endswith("% level"):
            kind, value = "pct", int(rest.split("%")[0].split(":")[-1])
        elif rest.startswith("prob "):
            kind, value = "prob", rest.split(":")[0][5:]
        elif "std dev" in rest:
            kind, value = "std", None
        elif rest == "":
            kind, value = "det", None
        else:
            kind, value = "other", rest
        length = offs[n + 1] - offs[n] if n + 1 < len(lines) else None
        out.append(Msg(var, level, start, end, stat, kind, value, offs[n], length))
    return out


@dataclass(frozen=True)
class Sel:
    key: str               # name in our output, e.g. "snow6_p50"
    file: str              # core | qmd
    var: str
    level: str
    hours: int | None      # window length; None = instantaneous
    kind: str = "det"
    value: str | int | None = None
    span: tuple | None = None   # explicit (start, end) window, e.g. (0, 72)


def find(msgs: list[Msg], sel: Sel, fhour: int) -> Msg | None:
    for m in msgs:
        if m.var != sel.var or m.level != sel.level or m.kind != sel.kind or m.value != sel.value:
            continue
        if sel.span is not None:
            if (m.start, m.end) == tuple(sel.span):
                return m
        elif sel.hours is None:
            if m.start is None and m.end == fhour:
                return m
        elif m.start is not None and m.end == fhour and m.end - m.start == sel.hours:
            return m
    return None


PCTS = (10, 50, 90)
SNOW_PCTS = (10, 25, 50, 75, 90)   # snowfall: 25/75 = the "likely" band (owner S10)
QPF_PCTS = (10, 25, 50, 75, 90)   # qmd QPF: 10/90 to 48 h, 25/75 = "likely range" beyond (owner S3)
T2, SFC, W10 = "2 m above ground", "surface", "10 m above ground"


FULL_SUITE_CYCLES = (1, 7, 13, 19)   # core carries ASNOW 6/24/48/72-h percentiles + exceedances to f263
SYNOPTIC_CYCLES = (0, 6, 12, 18)     # qmd (QPF percentiles) exists only here; snow percentiles to ~f054
DAY_SPANS = {(0, 24): "qpf_0_1d", (0, 72): "qpf_0_3d", (48, 72): "qpf_2_3d", (72, 120): "qpf_3_5d",
             (120, 168): "qpf_5_7d", (168, 240): "qpf_7_10d"}
BASICS = ("t2m", "wind", "wdir", "gust", "sky", "snowlvl", "slr")


def synoptic_end(h: int, cycle_hour: int, step: int = 6) -> bool:
    """True when forecast hour h is valid at 00/06/12/18Z (step 6) or every 3 h (step 3)."""
    return (cycle_hour + h) % step == 0


def required_keys(h: int, cycle_hour: int) -> set[str]:
    """Fields the forecast cannot do without at hour h (fail-soft accounting). Every
    percentile, probability and qmd field is optional: cycles differ in what they carry."""
    req = set(BASICS)
    if h <= 36:
        req |= {"qpf1", "snow1"}
    if h >= 6 and synoptic_end(h, cycle_hour):
        req |= {"qpf6", "snow6"}
    return req


def classify(m: Msg, h: int, cycle_hour: int, product: str) -> str | None:
    """Our field key for message m in file f<h>, or None. Inventory-driven: whatever the
    cycle carries is used; only windows ending at this file's hour count (later files
    repeat some earlier windows, sometimes with different values)."""
    win = None if m.start is None else m.end - m.start
    if m.start is not None and m.end != h:
        return None
    if product == "qmd":
        if m.var != "APCP" or m.level != SFC or m.kind != "pct" or m.value not in QPF_PCTS:
            return None
        if (m.start, m.end) in DAY_SPANS:                    # 1-day and multi-day blocks
            return f"{DAY_SPANS[(m.start, m.end)]}_p{m.value}"
        if win == 12 and h >= 12 and synoptic_end(h, cycle_hour, 12):
            return f"qpf12_p{m.value}"                        # 12-h day/night periods
        if win == 6 and m.start == 0:
            return f"qpf6_p{m.value}"                         # partial first period (06/18Z cycles)
        return None
    v, lev, k = m.var, m.level, m.kind
    if win is None:
        if k == "det":
            return {("TMP", T2): "t2m", ("WIND", W10): "wind", ("WDIR", W10): "wdir", ("GUST", W10): "gust",
                    ("TCDC", SFC): "sky", ("SNOWLVL", "0 m above mean sea level"): "snowlvl",
                    ("SNOWLR", SFC): "slr"}.get((v, lev))
        if v == "SNOWLVL" and lev == SFC and k == "pct" and m.value in PCTS:
            return f"snowlvl_p{m.value}"
        if v == "SNOWLR" and lev == SFC and k == "pct" and m.value in (10, 90):
            return f"slr_p{m.value}"                          # snow-ratio band (owner S10)
        if v == "PTYPE" and k == "prob":
            return {">=5 <7": "p_snow_type", ">=1 <2": "p_rain_type"}.get(m.value)
        return None
    if v in ("TMAX", "TMIN") and lev == T2 and win == 12 and k == "det":
        return "tmax12" if v == "TMAX" else "tmin12"
    if lev != SFC or v not in ("APCP", "ASNOW"):
        return None
    if win == 1 and h <= 36:
        if k == "det":
            return "qpf1" if v == "APCP" else "snow1"
        if v == "APCP" and k == "prob" and m.value == ">0.254":
            return "pop1"
    if win == 6 and synoptic_end(h, cycle_hour):
        if k == "det":
            return "qpf6" if v == "APCP" else "snow6"
        if v == "APCP" and k == "prob" and m.value == ">0.254":
            return "pop6"
        if v == "ASNOW" and k == "pct" and m.value in SNOW_PCTS:
            return f"snow6_p{m.value}"
    if v == "ASNOW" and win in (24, 48, 72) and k == "pct" and m.value in SNOW_PCTS and synoptic_end(h, cycle_hour):
        return f"snow{win}_p{m.value}"
    if v == "ASNOW" and win in (24, 48, 72) and k == "prob" and synoptic_end(h, cycle_hour, 12):
        t = threshold_in(m.value)
        return None if t is None else f"snow{win}_gt{t}"
    return None


def threshold_in(value: str) -> str | None:
    """'>0.1016' (metres) -> '4' (inches, as NBM's thresholds are round inches; 0.1 kept)."""
    m = re.match(r">([0-9.eE+-]+)", value or "")
    if not m:
        return None
    x = float(m.group(1)) * 39.3701
    return "0.1" if x < 0.5 else str(int(round(x)))


def select(inv: list[Msg], h: int, cycle_hour: int, product: str) -> dict:
    """{Msg: key} for one idx (first occurrence of each key wins)."""
    out, seen = {}, set()
    for m in inv:
        k = classify(m, h, cycle_hour, product)
        if k and k not in seen:
            seen.add(k)
            out[m] = k
    return out


def sample_hours(available: list[int], cycle_hour: int, max_h: int = 264) -> list[int]:
    """Hourly to 36 h, then every 3 h of valid time to 72 h, then 00/06/12/18Z valid times
    (works for 3-hourly synoptic-cycle files and hourly odd-cycle files alike)."""
    return [h for h in sorted(available) if 1 <= h <= max_h and
            (h <= 36 or (h <= 72 and synoptic_end(h, cycle_hour, 3)) or synoptic_end(h, cycle_hour))]


def forecast_hours(max_h: int = 264) -> list[int]:
    """Synoptic-cycle default (hourly to 36 h, 3-hourly to 72 h, 6-hourly after)."""
    return list(range(1, 37)) + list(range(39, 73, 3)) + list(range(78, max_h + 1, 6))
