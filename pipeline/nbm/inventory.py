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
T2, SFC, W10 = "2 m above ground", "surface", "10 m above ground"


def selections(fhour: int, cycle_hour: int) -> list[tuple[Sel, bool]]:
    """(selection, required) for one forecast hour. Optional ones are taken when
    the inventory has them (e.g. percentiles that stop near f048)."""
    h = fhour
    s: list[tuple[Sel, bool]] = []
    req = lambda *a, **k: s.append((Sel(*a, **k), True))   # noqa: E731
    opt = lambda *a, **k: s.append((Sel(*a, **k), False))  # noqa: E731
    req("t2m", "core", "TMP", T2, None)
    req("wind", "core", "WIND", W10, None)
    req("wdir", "core", "WDIR", W10, None)
    req("gust", "core", "GUST", W10, None)
    req("sky", "core", "TCDC", SFC, None)
    req("snowlvl", "core", "SNOWLVL", "0 m above mean sea level", None)
    req("slr", "core", "SNOWLR", SFC, None)
    opt("p_snow_type", "core", "PTYPE", SFC, None, "prob", ">=5 <7")
    opt("p_rain_type", "core", "PTYPE", SFC, None, "prob", ">=1 <2")
    for p in PCTS:
        opt(f"snowlvl_p{p}", "core", "SNOWLVL", SFC, None, "pct", p)
    if h <= 36:
        req("qpf1", "core", "APCP", SFC, 1)
        req("snow1", "core", "ASNOW", SFC, 1)
        opt("pop1", "core", "APCP", SFC, 1, "prob", ">0.254")
    if h % 6 == 0:
        req("qpf6", "core", "APCP", SFC, 6)
        req("snow6", "core", "ASNOW", SFC, 6)
        opt("pop6", "core", "APCP", SFC, 6, "prob", ">0.254")
        for p in PCTS:
            opt(f"snow6_p{p}", "core", "ASNOW", SFC, 6, "pct", p)
        if h == 6:
            for p in PCTS:
                req(f"qpf6_p{p}", "qmd", "APCP", SFC, 6, "pct", p)
        # 12-h day/night periods end at 00Z and 12Z
        if (cycle_hour + h) % 12 == 0 and h >= 12:
            for p in PCTS:
                req(f"qpf12_p{p}", "qmd", "APCP", SFC, 12, "pct", p)
        if (cycle_hour + h) % 12 == 0:
            opt("tmax12", "core", "TMAX", T2, 12, value=None)
            opt("tmin12", "core", "TMIN", T2, 12, value=None)
    for span, name in (((0, 24), "qpf_0_1d"), ((0, 72), "qpf_0_3d"), ((72, 120), "qpf_3_5d"),
                       ((120, 168), "qpf_5_7d"), ((168, 240), "qpf_7_10d")):
        if h == span[1]:
            for p in PCTS:
                req(f"{name}_p{p}", "qmd", "APCP", SFC, None, "pct", p, span=span)
    return s


def forecast_hours(max_h: int = 264) -> list[int]:
    """Hourly to 36 h, 3-hourly to 72 h, 6-hourly to max_h (PLAN.md §3 defaults)."""
    return list(range(1, 37)) + list(range(39, 73, 3)) + list(range(78, max_h + 1, 6))
