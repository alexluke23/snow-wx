"""Share-card images (Open Graph, 1200 x 630 PNG) for the W2 area pages (dev20, PLAN W2; docs/specs/hosting-seo.md "Share cards").

BEHIND TWO FLAGS: `og_images.enabled` (this generator) and `pages.enabled` (pages.py references og:image only when BOTH are on). Brand-agnostic: the site
name and tagline come from config `site.name` / `site.tagline` (placeholders until the brand is chosen); nothing here hard-codes a brand.

One card per SKI AREA: name and state, the W3 summary headline exactly as the rules engine wrote it (hedged; a plain fallback when there is none), a small
bar chart of the next days' snowfall as NBM's "likely" range (p25-p75 of ONE native 24-h window per day; a day without a native range shows the expected
amount as a grey bar, never a made-up range), the issue time, the site name/tagline and "Data: NOAA/NWS". Sno-Parks and every other page share one
generic card (og/snopark.png, og/site.png).

Pure Pillow (already installed; no new package). Font: DejaVu Sans (pipeline/assets/fonts, Bitstream Vera / DejaVu licence in LICENSE_DEJAVU).
Text is fitted, never clipped: each block shrinks to its minimum size, then wraps, then (last resort) ends in an ellipsis; `render()` returns every text
box so tests check the boxes stay inside the card and their colour pairs reach 4.5:1. Output is deterministic (same input -> same bytes), quantized to a
small palette (< ~60 KB per card).
"""
from __future__ import annotations

import io
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from .common import REPO_ROOT

log = logging.getLogger("snow-wx.og")
W, H, M = 1200, 630, 56
FONTS = Path(__file__).resolve().parent / "assets" / "fonts"
REG, BOLD = FONTS / "DejaVuSans.ttf", FONTS / "DejaVuSans-Bold.ttf"
BG, INK, MUTED, BAND, BAND_INK, BAND_MUTED, PILL = "#ffffff", "#1d2733", "#4a5666", "#0f3b66", "#ffffff", "#d3e0ee", "#e6edf5"
GREY_BAR = "#9aa5b1"
DEFAULTS = {"enabled": False, "days": 5, "colors": 64}


def configure(cfg: dict | None) -> dict:
    out = dict(DEFAULTS)
    out.update((cfg or {}).get("og_images") or {})
    return out


def site_text(cfg: dict | None) -> tuple[str, str]:
    s = (cfg or {}).get("site") or {}
    return str(s.get("name") or "Site name"), str(s.get("tagline") or "")


# ---------------------------------------------------------------- colours (the ONE NWS snowfall table lives in web/js/colors.js)
def snowfall_table(path: Path = REPO_ROOT / "web" / "js" / "colors.js") -> tuple[list[float], list[str]]:
    js = path.read_text(encoding="utf-8")
    block = js[js.index("const SNOWFALL = {"):]
    bins = [float(x) for x in re.search(r"bins:\s*\[([^\]]+)\]", block).group(1).split(",")]
    colors = re.findall(r'"(#[0-9a-fA-F]{6})"', re.search(r"colors:\s*\[([^\]]+)\]", block).group(1))
    return bins, colors


def color_for(v: float | None, table) -> str | None:
    if v is None:
        return None
    bins, colors = table
    i = 0
    while i < len(bins) and v >= bins[i]:
        i += 1
    return colors[i]


def luminance(hex_: str) -> float:
    n = int(hex_.lstrip("#")[:6], 16)
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin((n >> 16) & 255) + 0.7152 * lin((n >> 8) & 255) + 0.0722 * lin(n & 255)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# ---------------------------------------------------------------- text fitting
def _font(path: Path, size: int):
    from PIL import ImageFont
    return ImageFont.truetype(str(path), size)


def _w(draw, text, font) -> float:
    return draw.textlength(text, font=font)


def wrap(draw, text: str, font, width: float) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for wd in words:
        t = f"{cur} {wd}".strip()
        if _w(draw, t, font) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = wd
    if cur:
        lines.append(cur)
    out = []
    for ln in lines:                                     # a single word wider than the box (a very long name): break it by characters
        while _w(draw, ln, font) > width and len(ln) > 1:
            k = len(ln)
            while k > 1 and _w(draw, ln[:k], font) > width:
                k -= 1
            out.append(ln[:k])
            ln = ln[k:]
        out.append(ln)
    return out


def fit(draw, text: str, path: Path, size: int, min_size: int, width: float, max_lines: int):
    """(font, lines): the largest size whose wrapped text fits in `max_lines`; at the minimum size the last line ends in an ellipsis instead of being cut"""
    for s in range(size, min_size - 1, -2):
        f = _font(path, s)
        lines = wrap(draw, text, f, width)
        if len(lines) <= max_lines:
            return f, lines
    f = _font(path, min_size)
    lines = wrap(draw, text, f, width)[:max_lines]
    last = lines[-1]
    while last and _w(draw, last + "…", f) > width:
        last = last[:-1].rstrip()
    lines[-1] = last + "…"
    return f, lines


class Card:
    def __init__(self):
        from PIL import Image, ImageDraw
        self.im = Image.new("RGB", (W, H), BG)
        self.d = ImageDraw.Draw(self.im)
        self.boxes: list[dict] = []

    def text(self, name, xy, lines, font, fg, bg, gap=1.18):
        x, y = xy
        asc, desc = font.getmetrics()
        lh = round((asc + desc) * gap)
        for i, ln in enumerate(lines):
            self.d.text((x, y + i * lh), ln, font=font, fill=fg)
            bb = self.d.textbbox((x, y + i * lh), ln, font=font)
            self.boxes.append({"name": name, "text": ln, "box": [round(v, 1) for v in bb], "fg": fg, "bg": bg})
        return y + len(lines) * lh

    def png(self, colors: int) -> bytes:
        from PIL import Image
        q = self.im.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        buf = io.BytesIO()
        q.save(buf, "PNG", optimize=True)
        return buf.getvalue()


def _band(c: Card, site: str, tagline: str):
    c.d.rectangle([0, 0, W, 76], fill=BAND)
    f, lines = fit(c.d, site, BOLD, 30, 20, 420, 1)
    c.text("site", (M, 20), lines, f, BAND_INK, BAND)
    if tagline:
        x0 = M + _w(c.d, lines[0], f) + 24
        ft, tl = fit(c.d, tagline, REG, 21, 14, W - M - x0, 1)
        c.text("tagline", (x0, 27), tl, ft, BAND_MUTED, BAND)


def _footer(c: Card, left: str):
    f = _font(REG, 19)
    credit = "Data: NOAA/NWS"
    cw = _w(c.d, credit, f)
    fl, ll = fit(c.d, left, REG, 19, 14, W - 2 * M - cw - 32, 1)
    c.text("issued", (M, H - 46), ll, fl, MUTED, BG)
    c.text("credit", (W - M - cw, H - 46), [credit], f, MUTED, BG)


def inch_label(lo, hi) -> str:
    a, b = round(lo), round(hi)
    if b == 0 and hi < 0.5:
        return "0″"
    if b <= 1 and hi < 1:
        return "<1″"
    return f"{a}″" if a == b else f"{a}–{b}″"


def chart_days(doc: dict, n: int) -> list[dict]:
    """the next `n` WHOLE 12Z-12Z days of the summit point: p25-p75 from one native NBM window when the points file has it, else the expected amount only"""
    days = [d for d in (((doc.get("points") or {}).get("summit") or {}).get("days") or []) if not d.get("partial")]
    return days[:n]


def _chart(c: Card, days: list[dict], box, table):
    x0, y0, x1, y1 = box
    ft = _font(BOLD, 21)
    c.text("chart-title", (x0, y0), [f"Snowfall, next {len(days)} days"], ft, INK, BG)
    fs = _font(REG, 16)
    c.text("chart-sub", (x0, y0 + 30), ["likely range (middle half of NBM's outcomes)"], fs, MUTED, BG)
    top, base = y0 + 96, y1 - 34
    vals = [d.get("snow_p75") if d.get("snow_p75") is not None else (d.get("snow_in") or 0) for d in days]
    vmax = max([4.0] + [v * 1.12 for v in vals if v is not None])
    sx = lambda v: base - (base - top) * min(v, vmax) / vmax        # noqa: E731
    n = max(1, len(days))
    slot = (x1 - x0) / n
    bw = min(60, slot * 0.55)
    c.d.line([x0, base, x1, base], fill="#8a96a3", width=2)
    fl, fd = _font(BOLD, 18), _font(REG, 16)
    for i, d in enumerate(days):
        cx = x0 + slot * (i + 0.5)
        lo, hi, med = d.get("snow_p25"), d.get("snow_p75"), d.get("snow_p50")
        if lo is not None and hi is not None:
            col = color_for(med if med is not None else (lo + hi) / 2, table) or "#ffffff"
            ya, yb = sx(hi), sx(lo)
            if yb - ya < 4:
                ya = yb - 4
            pale = contrast(col, BG) < 1.6
            c.d.rectangle([cx - bw / 2, ya, cx + bw / 2, yb], fill=col, outline=INK if pale else None, width=2 if pale else 0)
            lab = inch_label(lo, hi)
        else:
            exp = d.get("snow_in") or 0.0
            ya = min(sx(exp), base - 4)
            from PIL import Image, ImageDraw
            bx0, by0, bx1 = int(cx - bw / 2), int(ya), int(cx + bw / 2)
            hw, hh = max(1, bx1 - bx0), max(1, int(base) - by0)
            hatch = Image.new("RGB", (hw, hh), "#ffffff")                      # hatched grey: "expected amount, no range" (as on the area page)
            hd = ImageDraw.Draw(hatch)
            for k in range(-hh, hw, 9):
                hd.line([(k, hh), (k + hh, 0)], fill=GREY_BAR, width=2)
            c.im.paste(hatch, (bx0, by0))
            c.d.rectangle([bx0, by0, bx1, int(base)], outline=GREY_BAR, width=2)
            lab = "~" + inch_label(exp, exp)
        lw = _w(c.d, lab, fl)
        c.text(f"bar-label-{i}", (cx - lw / 2, ya - 26), [lab], fl, INK, BG)
        dl = str(d.get("label") or "")
        dw = _w(c.d, dl, fd)
        c.text(f"day-{i}", (cx - dw / 2, base + 8), [dl], fd, MUTED, BG)


def issued_text(doc: dict) -> str:
    try:
        from zoneinfo import ZoneInfo
        t = datetime.fromisoformat(str(doc["issued"]).replace("Z", "+00:00")).astimezone(ZoneInfo(doc.get("tz") or "UTC"))
        return f"NBM forecast issued {t:%a %b} {t.day}, {t.strftime('%I %p').lstrip('0')} {t.tzname()}"
    except Exception:  # noqa: BLE001
        return "NOAA/NWS National Blend of Models forecast"


def render(area: dict, doc: dict | None, cfg: dict | None, table=None) -> tuple[bytes, dict]:
    """one ski-area card -> (png bytes, layout {boxes, size})"""
    c = Card()
    site, tagline = site_text(cfg)
    oc = configure(cfg)
    table = table or snowfall_table()
    _band(c, site, tagline)
    fn, nl = fit(c.d, f"{area['name']}", BOLD, 58, 36, W - 2 * M, 2)
    y = c.text("name", (M, 104), nl, fn, INK, BG, gap=1.08)
    fm = _font(REG, 22)
    meta = ", ".join(x for x in (area.get("region"), area.get("state")) if x) + " · snow forecast"
    fm2, ml = fit(c.d, meta, REG, 22, 16, W - 2 * M, 1)
    y = c.text("meta", (M, y + 4), ml, fm2, MUTED, BG) + 22
    sm = (doc or {}).get("summary") or {}
    left_w = 560
    yy = y
    if sm.get("tag"):
        fp = _font(BOLD, 21)
        tw = _w(c.d, sm["tag"], fp)
        c.d.rounded_rectangle([M, yy, M + tw + 28, yy + 38], radius=19, fill=PILL)
        c.text("tag", (M + 14, yy + 6), [sm["tag"]], fp, INK, PILL)
        yy += 54
    sentence = sm.get("sentence") or f"Snow forecast for {area['name']}: NOAA/NWS National Blend of Models, with the likely range for every day."
    room = (H - 70) - yy
    fsent, sl = fit(c.d, sentence, REG, 28, 18, left_w, max(1, min(5, int(room // 34))))
    c.text("summary", (M, yy), sl, fsent, INK, BG)
    days = chart_days(doc or {}, int(oc["days"]))
    if days:
        _chart(c, days, (M + left_w + 48, y, W - M, H - 70), table)
    _footer(c, issued_text(doc) if doc else "NOAA/NWS National Blend of Models")
    return c.png(int(oc["colors"])), {"boxes": c.boxes, "size": [W, H]}


def render_generic(cfg: dict | None, title: str, sentence: str) -> tuple[bytes, dict]:
    c = Card()
    site, tagline = site_text(cfg)
    _band(c, site, tagline)
    ft, tl = fit(c.d, title, BOLD, 60, 36, W - 2 * M, 2)
    y = c.text("name", (M, 150), tl, ft, INK, BG, gap=1.08)
    fs, sl = fit(c.d, sentence, REG, 30, 20, W - 2 * M, 3)
    c.text("summary", (M, y + 30), sl, fs, INK, BG)
    _footer(c, "Forecasts: NOAA/NWS National Blend of Models")
    return c.png(int(configure(cfg)["colors"])), {"boxes": c.boxes, "size": [W, H]}


def run(cfg: dict, out: Path, *, force: bool = False, only: list[str] | None = None) -> int:
    """<out>/og/<area id>.png for every ski area + og/snopark.png + og/site.png. `out` is the SITE folder (data/ already merged)."""
    oc = configure(cfg)
    if not oc["enabled"] and not force:
        log.info("og: disabled (config og_images.enabled=false); nothing written")
        return 0
    out = Path(out)
    cat = out / "data" / "ski_areas.json"
    areas = json.loads((cat if cat.exists() else REPO_ROOT / "data" / "ski_areas.json").read_text(encoding="utf-8"))["areas"]
    if only:
        areas = [a for a in areas if a["id"] in only]
    dest = out / "og"
    dest.mkdir(parents=True, exist_ok=True)
    table = snowfall_table()
    t0, sizes = time.time(), []
    for a in areas:
        p = out / "data" / "points" / f"{a['id']}.json"
        try:
            doc = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            doc = None
        png, _ = render(a, doc, cfg, table)
        (dest / f"{a['id']}.png").write_bytes(png)
        sizes.append(len(png))
    for name, title, sentence in (("snopark", "Sno-Park forecasts", "Snow, wind, snow level and avalanche context for Sno-Parks and trailheads in the western US mountains."),
                                  ("site", "Mountain snow forecasts", "Open weather, snowpack and avalanche data for western US mountains: likely ranges, snow level and observations.")):
        png, _ = render_generic(cfg, title, sentence)
        (dest / f"{name}.png").write_bytes(png)
        sizes.append(len(png))
    secs = time.time() - t0
    log.info("og: %d cards in %.1f s, %.1f MB total, avg %.1f KB, max %.1f KB", len(sizes), secs, sum(sizes) / 1e6, sum(sizes) / max(1, len(sizes)) / 1024, max(sizes) / 1024)
    return 0
