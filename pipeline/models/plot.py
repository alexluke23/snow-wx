"""Map rendering (Cartopy + Matplotlib, no pyplot).

Speed/size design: for each (model grid, domain) a Canvas is built once per
worker process. It holds the figure, map axes and basemap lines, plus a
precomputed bilinear sampling map from every output pixel to fractional
model-grid indices. Shading a field is then `map_coordinates` + `imshow` in
the map's own projection (no per-image reprojection), contour lines are drawn
on the same pixel grid, and the per-image artists are removed after saving.
Frames are pixel-identical in size, so loops don't jump.
"""

from __future__ import annotations

import io
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
from matplotlib import patheffects  # noqa: E402
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.cm import ScalarMappable  # noqa: E402
from matplotlib.colors import BoundaryNorm, LinearSegmentedColormap, ListedColormap  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from scipy.ndimage import map_coordinates  # noqa: E402

log = logging.getLogger("snow-wx.models")

matplotlib.rcParams["hatch.linewidth"] = 0.5
TRANSPARENT = (0, 0, 0, 0)
HALO = [patheffects.withStroke(linewidth=2.2, foreground="white")]


# ---------------------------------------------------------------- color scales

@dataclass
class Scale:
    levels: list
    colors: list
    under: object = TRANSPARENT
    over: object = None
    ticks: list | None = None
    fmt: str = "{:g}"
    units: str = ""

    def cmap_norm(self):
        cmap = ListedColormap(self.colors).with_extremes(
            under=self.under, over=self.over if self.over is not None else self.colors[-1],
            bad=TRANSPARENT)
        return cmap, BoundaryNorm(self.levels, len(self.colors))

    @property
    def extend(self):
        lo = self.under is not None and self.under != TRANSPARENT
        hi = self.over is not None
        return {(True, True): "both", (True, False): "min", (False, True): "max"}.get((lo, hi), "neither")


def ramp(anchors: list[tuple[float, str]], levels: list[float]) -> list:
    """One color per interval, sampled at interval midpoints from anchor colors."""
    v0, v1 = anchors[0][0], anchors[-1][0]
    cmap = LinearSegmentedColormap.from_list("r", [((v - v0) / (v1 - v0), c) for v, c in anchors])
    return [cmap(np.clip(((a + b) / 2 - v0) / (v1 - v0), 0, 1)) for a, b in zip(levels[:-1], levels[1:])]


QPF = Scale(
    levels=[0.01, 0.05, 0.1, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10],
    colors=["#c7e9c0", "#7fcd76", "#31a354", "#006d2c", "#a6cee3", "#4f9bd9", "#1f62b4", "#0b2f73",
            "#cbbfe6", "#9e86c9", "#7646a8", "#4c1b80", "#f7b1c8", "#e8608a", "#c51b4b", "#7a0019"],
    over="#ffd23f", units="in",
)
SNOW = Scale(
    levels=[0.1, 1, 2, 3, 4, 6, 8, 12, 18, 24, 30, 36, 48, 60, 72],
    colors=["#bdd7e7", "#6baed6", "#3182bd", "#08519c", "#082694", "#ffff96", "#ffc400", "#ff8700",
            "#db1400", "#9e0000", "#690000", "#ccccff", "#9f8ccd", "#7c52a5"],
    over="#561c72", units="in",
)
_T2M_LEVELS = list(range(-20, 105, 5))
T2M = Scale(
    levels=_T2M_LEVELS,
    colors=ramp([(-20, "#4b0063"), (-5, "#9a4fb5"), (5, "#c7a4e0"), (12, "#2a3f9e"), (22, "#3b8ad9"),
                 (30, "#a5d8f5"), (32.5, "#e9f7f1"), (40, "#a8dca0"), (50, "#4fa85a"), (60, "#f2e35a"),
                 (70, "#f6a03e"), (80, "#e2482c"), (90, "#a50f15"), (100, "#5c0000")], _T2M_LEVELS),
    under="#2d0040", over="#3a0000", ticks=list(range(-20, 105, 10)), units="°F",
)
_T700_LEVELS = list(range(-30, 17, 1))
T700 = Scale(
    levels=_T700_LEVELS,
    colors=ramp([(-30, "#3f007d"), (-22, "#6a51a3"), (-16, "#2b3f9e"), (-10, "#4292c6"), (-4, "#a6d6f0"),
                 (0, "#f2f7f2"), (4, "#c7e5a0"), (8, "#f2d45a"), (12, "#f08a3c"), (16, "#c0281c")],
                _T700_LEVELS),
    under="#25004d", over="#7a0000", ticks=list(range(-30, 17, 4)), units="°C",
)
AT_GROUND = "#e6ebf3"
VORT = Scale(
    levels=[16, 18, 20, 22, 24, 26, 28, 30, 34, 38, 42, 50],
    colors=["#fff3a8", "#ffe066", "#ffc233", "#ff9d1f", "#ff7417", "#f04a1a", "#d62a20", "#b0102c",
            "#8a0a4a", "#6b0a73", "#4b0b8a"],
    over="#2c0659", units="10⁻⁵ s⁻¹",
)
GUST = Scale(
    levels=[15, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 100],
    colors=["#d4eef7", "#9fd3ea", "#5fa8d3", "#2e6fb5", "#ffe08a", "#fdb24e", "#f7792f", "#df3b23",
            "#b10f22", "#7b0a3f", "#5a0a6b"],
    over="#32004d", units="kt",
)
_SL_LEVELS = list(range(0, 15000, 1000))
SNOWLEVEL = Scale(
    levels=_SL_LEVELS,
    colors=[matplotlib.colormaps["turbo"](x) for x in np.linspace(0.08, 0.95, len(_SL_LEVELS) - 1)],
    under="#30123b", over="#7a0403", ticks=_SL_LEVELS[::2], fmt="{:,.0f}", units="ft MSL",
)


# ---------------------------------------------------------------- geometry

def crs_from_params(p: dict):
    import cartopy.crs as ccrs
    if p["kind"] == "lcc":
        globe = ccrs.Globe(ellipse=None, semimajor_axis=p["radius"], semiminor_axis=p["radius"])
        return ccrs.LambertConformal(central_longitude=p["lon0"], central_latitude=p["lat0"],
                                     standard_parallels=(p["lat1"], p["lat2"]), globe=globe)
    return ccrs.PlateCarree()


class SourceGrid:
    """Cropped model grid as an affine grid in its native CRS."""

    def __init__(self, lat, lon, crs_params: dict, uv_rel: bool):
        import cartopy.crs as ccrs
        self.lat, self.lon, self.uv_rel = lat, lon, uv_rel
        self.crs = crs_from_params(crs_params)
        ny, nx = lat.shape
        pts = self.crs.transform_points(ccrs.PlateCarree(),
                                        np.array([lon[0, 0], lon[0, -1], lon[-1, 0]]),
                                        np.array([lat[0, 0], lat[0, -1], lat[-1, 0]]))
        self.x0, self.y0 = pts[0, 0], pts[0, 1]
        self.dx = (pts[1, 0] - pts[0, 0]) / (nx - 1)
        self.dy = (pts[2, 1] - pts[0, 1]) / (ny - 1)

    @classmethod
    def load(cls, path: str) -> "SourceGrid":
        z = np.load(path)
        return cls(z["lat"], z["lon"], json.loads(str(z["crs"])), bool(z["uv_rel"]))


def domain_projection(extent):
    import cartopy.crs as ccrs
    w, e, s, n = extent
    return ccrs.LambertConformal(central_longitude=(w + e) / 2, central_latitude=(s + n) / 2,
                                 standard_parallels=(s + (n - s) * 0.25, n - (n - s) * 0.25))


def _projected_box(proj, extent):
    import cartopy.crs as ccrs
    w, e, s, n = extent
    t = np.linspace(0, 1, 80)
    blon = np.concatenate([w + (e - w) * t, np.full_like(t, e), e - (e - w) * t, np.full_like(t, w)])
    blat = np.concatenate([np.full_like(t, s), s + (n - s) * t, np.full_like(t, n), n - (n - s) * t])
    b = proj.transform_points(ccrs.PlateCarree(), blon, blat)
    return b[:, 0].min(), b[:, 0].max(), b[:, 1].min(), b[:, 1].max()


def map_lonlat_bounds(extents: list, pad_deg: float = 0.75) -> list[float]:
    """[w, e, s, n] covering every map rectangle (Lambert boxes reach past the
    lat/lon extent at their corners), so the model grid is cropped wide enough."""
    import cartopy.crs as ccrs
    w, e, s, n = 180.0, -180.0, 90.0, -90.0
    for extent in extents:
        proj = domain_projection(extent)
        x0, x1, y0, y1 = _projected_box(proj, extent)
        t = np.linspace(0, 1, 80)
        bx = np.concatenate([x0 + (x1 - x0) * t, np.full_like(t, x1), x1 - (x1 - x0) * t, np.full_like(t, x0)])
        by = np.concatenate([np.full_like(t, y0), y0 + (y1 - y0) * t, np.full_like(t, y1), y1 - (y1 - y0) * t])
        ll = ccrs.PlateCarree().transform_points(proj, bx, by)
        w, e = min(w, ll[:, 0].min()), max(e, ll[:, 0].max())
        s, n = min(s, ll[:, 1].min()), max(n, ll[:, 1].max())
    return [w - pad_deg, e + pad_deg, s - pad_deg, n + pad_deg]


# Reference places drawn on subregion maps (lon, lat, name).
PLACES = [
    (-122.33, 47.61, "Seattle"), (-122.68, 45.52, "Portland"), (-121.31, 44.06, "Bend"),
    (-121.41, 47.42, "Snoqualmie Pass"), (-121.69, 45.37, "Mt Hood"), (-120.66, 47.75, "Stevens Pass"),
    (-121.49, 38.58, "Sacramento"), (-119.81, 39.53, "Reno"), (-120.00, 39.10, "Lake Tahoe"),
    (-118.97, 37.65, "Mammoth"), (-116.20, 43.62, "Boise"), (-114.35, 43.68, "Sun Valley"),
    (-114.00, 46.87, "Missoula"), (-111.04, 45.68, "Bozeman"), (-110.76, 43.48, "Jackson"),
    (-111.89, 40.76, "Salt Lake City"), (-111.65, 40.58, "Alta"), (-111.50, 40.65, "Park City"),
    (-111.97, 41.22, "Ogden"), (-110.40, 40.20, "Uintas"), (-104.99, 39.74, "Denver"),
    (-106.83, 39.19, "Aspen"), (-106.37, 39.64, "Vail"), (-107.81, 37.94, "Telluride"),
    (-106.81, 40.48, "Steamboat"), (-105.94, 39.68, "Loveland Pass"), (-107.88, 37.27, "Durango"),
    (-117.43, 47.66, "Spokane"), (-113.99, 48.70, "Glacier NP"), (-110.70, 44.60, "Yellowstone"),
]


class Canvas:
    HEADER_IN, CBAR_IN, FOOT_IN, GAP_IN, SIDE_IN = 0.60, 0.56, 0.22, 0.08, 0.06

    def __init__(self, dom_key: str, dom: dict, src: SourceGrid, panels: int = 1,
                 width_px: int = 900, dpi: int = 100, basemap: bool = True):
        import cartopy.crs as ccrs
        pc = ccrs.PlateCarree()
        self.dom_key, self.dom, self.src, self.panels, self.dpi = dom_key, dom, src, panels, dpi
        self.proj = proj = domain_projection(dom["extent"])
        x0, x1, y0, y1 = _projected_box(proj, dom["extent"])

        panel_px = width_px if panels == 1 else int(width_px * 0.72)
        h_px = int(round(panel_px * (y1 - y0) / (x1 - x0)))
        yc, half = (y0 + y1) / 2, (x1 - x0) * h_px / panel_px / 2   # exact pixel aspect
        y0, y1 = yc - half, yc + half
        self.bbox = (x0, x1, y0, y1)
        self.shape = (h_px, panel_px)

        map_w, map_h = panel_px / dpi, h_px / dpi
        fig_w = panels * map_w + (panels - 1) * self.GAP_IN + 2 * self.SIDE_IN
        fig_h = self.HEADER_IN + map_h + self.CBAR_IN + self.FOOT_IN
        self.fig_size = (fig_w, fig_h)
        self.fig = Figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor="white")
        FigureCanvasAgg(self.fig)
        self.axes = []
        small = dom_key != "west"
        for i in range(panels):
            left = self.SIDE_IN + i * (map_w + self.GAP_IN)
            ax = self.fig.add_axes([left / fig_w, (self.CBAR_IN + self.FOOT_IN) / fig_h,
                                    map_w / fig_w, map_h / fig_h], projection=proj)
            ax.set_extent([x0, x1, y0, y1], crs=proj)
            ax.set_facecolor("#fbfbf8")
            ax.spines["geo"].set_linewidth(0.6)
            if basemap:   # tests turn this off (Natural Earth would download)
                add_basemap(ax, small)
            if small:
                add_places(ax, proj, dom["extent"])
            self.axes.append(ax)

        xs = x0 + (np.arange(panel_px) + 0.5) * (x1 - x0) / panel_px
        ys = y0 + (np.arange(h_px) + 0.5) * (y1 - y0) / h_px
        self.xs, self.ys = xs, ys
        xx, yy = np.meshgrid(xs, ys)
        self.coords = self._src_index(xx.ravel(), yy.ravel()).reshape(2, h_px, panel_px)

        step = 44 if not small else 52
        bx, by = np.meshgrid(xs[step // 2::step], ys[step // 2::step])
        self.barb_xy = (bx.ravel(), by.ravel())
        self.barb_idx = self._src_index(bx.ravel(), by.ravel())
        vec_crs = src.crs if src.uv_rel else pc
        v = vec_crs.transform_points(proj, bx.ravel(), by.ravel())
        self.barb_vec = (vec_crs, v[:, 0], v[:, 1])
        self._base = None

    def _src_index(self, x, y):
        s = self.src.crs.transform_points(self.proj, x, y)
        cols = (s[:, 0] - self.src.x0) / self.src.dx
        rows = (s[:, 1] - self.src.y0) / self.src.dy
        return np.stack([rows, cols]).astype(np.float32)

    def sample(self, field: np.ndarray, order: int = 1) -> np.ndarray:
        return map_coordinates(np.asarray(field, np.float32), self.coords, order=order,
                               mode="constant", cval=np.nan, prefilter=False)

    # --- drawing primitives -------------------------------------------------
    def shade(self, ax, field, scale: Scale):
        img = self.sample(field)
        cmap, norm = scale.cmap_norm()
        ax.imshow(img, origin="lower", extent=self.bbox, transform=self.proj, cmap=cmap, norm=norm,
                  interpolation="nearest", zorder=1)
        return img

    def contour(self, ax, img, levels, labels=True, fmt="{:.0f}", **kw):
        data = np.ma.masked_invalid(img)
        if data.count() == 0:
            return None
        lo, hi = np.nanmin(img), np.nanmax(img)
        levels = [lv for lv in levels if lo <= lv <= hi]
        if not levels:
            return None
        kw.setdefault("colors", "#111")
        kw.setdefault("linewidths", 0.9)
        kw.setdefault("zorder", 4)
        cs = ax.contour(self.xs, self.ys, data, levels=levels, transform=self.proj, **kw)
        if labels:
            fmt_fn = fmt if callable(fmt) else (lambda v: fmt.format(v))
            txt = ax.clabel(cs, fmt=fmt_fn, fontsize=7, inline=True, inline_spacing=2)
            for t in txt:
                t.set_path_effects(HALO)
        return cs

    def barbs(self, ax, u, v):
        us = map_coordinates(np.asarray(u, np.float32), self.barb_idx, order=1, cval=np.nan)
        vs = map_coordinates(np.asarray(v, np.float32), self.barb_idx, order=1, cval=np.nan)
        ok = np.isfinite(us) & np.isfinite(vs)
        if not ok.any():
            return
        vec_crs, vx, vy = self.barb_vec
        um, vm = self.proj.transform_vectors(vec_crs, vx[ok], vy[ok], us[ok], vs[ok])
        bx, by = self.barb_xy
        ax.barbs(bx[ok], by[ok], um, vm, length=5.0, linewidth=0.5, color="#111",
                 transform=self.proj, zorder=7, sizes={"emptybarb": 0.12})

    def add_terrain(self, orog_ft: np.ndarray | None):
        """Faint model-terrain contours, drawn once (static like the basemap)."""
        if orog_ft is None:
            return
        img = self.sample(orog_ft)
        levels = [6000] if self.dom_key == "west" else [4000, 6000, 8000, 10000, 12000]
        for ax in self.axes:   # above shading (1), below hatching (3) and field contours (4)
            self.contour(ax, img, levels, labels=False, colors="#8f8f8f", linewidths=0.35, zorder=2.5)

    def snapshot(self):
        self._base = ({ax: set(ax.get_children()) for ax in self.axes},
                      set(self.fig.texts), set(self.fig.axes))

    def reset(self):
        from matplotlib.contour import ContourSet
        axes_kids, texts, fig_axes = self._base
        for ax in self.axes:
            # Contour sets first: they take their inline labels with them.
            for a in [a for a in ax.get_children() if isinstance(a, ContourSet)]:
                if a not in axes_kids[ax]:
                    a.remove()
            for a in set(ax.get_children()) - axes_kids[ax]:
                a.remove()
        for t in set(self.fig.texts) - texts:
            t.remove()
        for a in set(self.fig.axes) - fig_axes:
            a.remove()


def add_basemap(ax, small: bool):
    import cartopy.feature as cfeature
    lw = 0.75 if small else 0.55
    for cat, name, width in (("cultural", "admin_1_states_provinces_lines", lw),
                             ("cultural", "admin_0_boundary_lines_land", lw * 1.4),
                             ("physical", "coastline", lw * 1.2)):
        ax.add_feature(cfeature.NaturalEarthFeature(cat, name, "50m"), facecolor="none",
                       edgecolor="#1a1a1a", linewidth=width, zorder=5)
    ax.add_feature(cfeature.NaturalEarthFeature("physical", "lakes", "50m"), facecolor="none",
                   edgecolor="#1a1a1a", linewidth=lw * 0.7, zorder=5)


def add_places(ax, proj, extent):
    import cartopy.crs as ccrs
    w, e, s, n = extent
    for lon, lat, name in PLACES:
        if w + 0.1 < lon < e - 0.1 and s + 0.1 < lat < n - 0.1:
            ax.plot(lon, lat, "o", ms=2.6, color="#111", mec="white", mew=0.6,
                    transform=ccrs.PlateCarree(), zorder=8)
            ax.text(lon, lat, f" {name}", fontsize=6.8, color="#111", va="bottom", ha="left",
                    transform=ccrs.PlateCarree(), zorder=8, path_effects=HALO)


def ensure_basemap_data() -> None:
    """Download Natural Earth files once in the parent before workers start."""
    import cartopy.feature as cfeature
    for cat, name in (("cultural", "admin_1_states_provinces_lines"),
                      ("cultural", "admin_0_boundary_lines_land"),
                      ("physical", "coastline"), ("physical", "lakes")):
        next(iter(cfeature.NaturalEarthFeature(cat, name, "50m").geometries()), None)


# ---------------------------------------------------------------- fields

def _max_note(ax, img, units, fmt="{:.1f}"):
    if np.isfinite(img).any() and np.nanmax(img) > 0:
        ax.text(0.99, 0.01, f"max {fmt.format(np.nanmax(img))} {units}", transform=ax.transAxes,
                ha="right", va="bottom", fontsize=7.5, zorder=9, path_effects=HALO)


def draw_h500(c: Canvas, d: dict):
    ax = c.axes[0]
    c.shade(ax, d["vort500"], VORT)
    c.contour(ax, c.sample(d["h500_dam"]), range(480, 612, 6), linewidths=1.0)
    return VORT, "500 mb heights (dam) & absolute vorticity (10⁻⁵ s⁻¹)"


def draw_t700(c: Canvas, d: dict):
    ax = c.axes[0]
    img = c.shade(ax, d["t700_c"], T700)
    c.contour(ax, img, [0], labels=False, colors="#b2182b", linewidths=1.5)
    c.contour(ax, img, [-10], labels=False, colors="#2166ac", linewidths=1.5)
    c.contour(ax, c.sample(d["h700_dam"]), range(240, 340, 3), linewidths=0.8)
    c.barbs(ax, d["u700_kt"], d["v700_kt"])
    return T700, "700 mb temperature (°C; 0 and −10 bold), heights (dam), wind (kt)"


def _draw_qpf(key, title):
    def draw(c: Canvas, d: dict):
        img = c.shade(c.axes[0], d[key], QPF)
        _max_note(c.axes[0], img, "in", "{:.2f}")
        return QPF, title
    return draw


def draw_snow(c: Canvas, d: dict):
    for ax, key, name in ((c.axes[0], "snow10", "10:1"), (c.axes[1], "snowku", "Kuchera")):
        img = c.shade(ax, d[key], SNOW)
        ax.text(0.015, 0.985, name, transform=ax.transAxes, ha="left", va="top", fontsize=11,
                fontweight="bold", zorder=9, path_effects=HALO)
        _max_note(ax, img, "in")
    return SNOW, "Snowfall since init (in): 10:1 vs Kuchera ratio, frozen precip only"


def draw_snowlevel(c: Canvas, d: dict):
    """Snow level where it is above the terrain; one flat color where it is at or
    below ground (no terrain-shaped noise); hatching where precip is falling."""
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    ax = c.axes[0]
    ground = np.nan_to_num(c.sample(d["snow_at_sfc"])) >= 0.5
    sl = c.sample(d["snowlevel_ft"])
    sl[ground] = np.nan
    cmap, norm = SNOWLEVEL.cmap_norm()
    ax.imshow(sl, origin="lower", extent=c.bbox, transform=c.proj, cmap=cmap, norm=norm,
              interpolation="nearest", zorder=1)
    ax.imshow(np.where(ground, 1.0, np.nan), origin="lower", extent=c.bbox, transform=c.proj,
              cmap=ListedColormap([AT_GROUND]), vmin=0, vmax=2, interpolation="nearest", zorder=1)
    handles = [Patch(facecolor=AT_GROUND, edgecolor="#777", lw=0.5, label="at/below ground")]
    if "precip_now" in d:
        pm = np.nan_to_num(c.sample(d["precip_now"]))
        if pm.max() >= 0.5:
            ax.contourf(c.xs, c.ys, pm, levels=[0.5, 1.5], colors="none", hatches=["////"],
                        transform=c.proj, zorder=3)
        handles.append(Patch(facecolor="none", edgecolor="#333", hatch="////", lw=0.5,
                             label="precipitating"))
    if "fzl_ft" in d:
        c.contour(ax, c.sample(d["fzl_ft"]), range(2000, 18001, 2000), colors="#222",
                  linewidths=0.8, linestyles="--", fmt=lambda v: f"{v / 1000:.0f}k")
        handles.append(Line2D([], [], color="#222", lw=0.8, ls="--", label="freezing level"))
    leg = ax.legend(handles=handles, loc="lower left", fontsize=7, framealpha=0.9,
                    handlelength=1.6, borderpad=0.4, labelspacing=0.3)
    leg.set_zorder(9)
    return SNOWLEVEL, "Snow level: lowest wet-bulb 0 °C height (ft MSL)"


def draw_t2m(c: Canvas, d: dict):
    ax = c.axes[0]
    img = c.shade(ax, d["t2m_f"], T2M)
    c.contour(ax, img, [32], labels=False, colors="#1d2f8f", linewidths=1.2)
    return T2M, "2-m temperature (°F; 32 °F line)"


def draw_gust(c: Canvas, d: dict):
    img = c.shade(c.axes[0], d["gust_kt"], GUST)
    _max_note(c.axes[0], img, "kt", "{:.0f}")
    return GUST, "Surface wind gust (kt)"


DRAW = {
    "h500": draw_h500, "t700": draw_t700,
    "qpf1": _draw_qpf("qpf1", "1-hr precipitation (in)"),
    "qpf6": _draw_qpf("qpf6", "6-hr precipitation (in)"),
    "qpf24": _draw_qpf("qpf24", "24-hr precipitation (in)"),
    "qpf_total": _draw_qpf("qpf_total", "Total precipitation since init (in)"),
    "snow": draw_snow, "snowlevel": draw_snowlevel, "t2m": draw_t2m, "gust": draw_gust,
}
PANELS = {"snow": 2}


# ---------------------------------------------------------------- frame annotation

def _hour(dt: datetime) -> str:
    return dt.strftime("%I %p").lstrip("0")


def annotate(c: Canvas, meta: dict, title: str, f: int, scale: Scale):
    fig = c.fig
    fw, fh = c.fig_size
    init: datetime = meta["cycle"]
    valid = init + timedelta(hours=f)
    local = valid.astimezone(ZoneInfo(c.dom.get("tz", "America/Denver")))
    top = 1 - 0.10 / fh
    left, right = c.SIDE_IN / fw + 0.002, 1 - c.SIDE_IN / fw - 0.002
    fig.text(left, top, f"{meta['label']}  ·  {title}", ha="left", va="top", fontsize=10.5,
             fontweight="bold")
    fig.text(left, top - 0.26 / fh, f"Init {init:%HZ %a %d %b %Y}", ha="left", va="top", fontsize=9)
    fig.text(right, top - 0.26 / fh,
             f"F{f:03d}   Valid {valid:%HZ %a %d %b}  ({_hour(local)} {local:%Z %a})",
             ha="right", va="top", fontsize=9, fontweight="bold")
    fig.text(left, 0.05 / fh, f"snow-wx · {c.dom['label']}", ha="left", va="bottom",
             fontsize=7, color="#555")
    fig.text(right, 0.05 / fh, meta.get("attribution", ""), ha="right", va="bottom",
             fontsize=7, color="#555")

    cmap, norm = scale.cmap_norm()
    cw = 0.80
    cax = fig.add_axes([(1 - cw) / 2, (c.FOOT_IN + 0.20) / fh, cw, 0.15 / fh])
    cb = fig.colorbar(ScalarMappable(norm=norm, cmap=cmap), cax=cax, orientation="horizontal",
                      ticks=scale.ticks or scale.levels, extend=scale.extend, extendfrac=0.03,
                      spacing="uniform")
    cb.ax.set_xticklabels([scale.fmt.format(t) for t in (scale.ticks or scale.levels)])
    cb.ax.tick_params(labelsize=7.5, length=2, pad=1.5)
    cb.outline.set_linewidth(0.5)
    fig.text(cw + (1 - cw) / 2 + 0.005, (c.FOOT_IN + 0.20) / fh, scale.units, ha="left", va="bottom",
             fontsize=7.5)


def save_png(fig: Figure, path: Path, colors: int = 128) -> int:
    from PIL import Image
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=fig.dpi, facecolor="white")
    buf.seek(0)
    im = Image.open(buf).convert("RGB")
    q = im.quantize(colors=colors, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    path.parent.mkdir(parents=True, exist_ok=True)
    q.save(path, format="PNG", optimize=True)
    return path.stat().st_size


def render_field(c: Canvas, field: str, data: dict, meta: dict, f: int, path: Path,
                 colors: int = 128) -> int:
    if c._base is None:
        c.add_terrain(data.get("orog_ft"))
        c.snapshot()
    try:
        scale, title = DRAW[field](c, data)
        annotate(c, meta, title, f, scale)
        return save_png(c.fig, path, colors)
    finally:
        c.reset()


# ---------------------------------------------------------------- worker entry

_GRIDS: dict[str, SourceGrid] = {}
_CANVASES: dict[tuple, Canvas] = {}


def render_task(grid_path: str, frame_path: str, dom: str, fields: list[str], f: int,
                run_dir: str, meta: dict) -> list[dict]:
    """Render `fields` for one frame and domain (runs in a worker process)."""
    if grid_path not in _GRIDS:
        _GRIDS.clear()
        _CANVASES.clear()
        _GRIDS[grid_path] = SourceGrid.load(grid_path)
    src = _GRIDS[grid_path]
    img = meta.get("image", {})
    data = dict(np.load(frame_path))
    out = []
    for field in fields:
        t0 = time.time()
        key = (dom, PANELS.get(field, 1))
        rec = {"field": field, "domain": dom, "f": f}
        try:
            if key not in _CANVASES:
                _CANVASES[key] = Canvas(dom, meta["domains"][dom], src, panels=key[1],
                                        width_px=img.get("width_px", 900), dpi=img.get("dpi", 100))
            path = Path(run_dir) / field / dom / f"f{f:03d}.png"
            rec["bytes"] = render_field(_CANVASES[key], field, data, meta, f, path,
                                        img.get("colors", 128))
            rec["ok"] = True
        except Exception as exc:  # report, keep going
            rec.update(ok=False, error=f"{type(exc).__name__}: {exc}")
        rec["seconds"] = round(time.time() - t0, 2)
        out.append(rec)
    return out
