"""Interactive map layers (PLAN.md §5.4): regrid to Web Mercator and value-encode as PNG.

A layer is a PNG on a regular EPSG:3857 grid (so Leaflet can place it as an image
overlay without distortion) whose pixels *encode values*, not colours:
  code = round((value - offset) / scale), 0..65535;  R = code >> 8, G = code & 255,
  B = 0, A = 255 (A = 0: no data).
The browser decodes the PNG once, colourizes it with the site palettes and reads the
exact value under the cursor. Pure functions; no network.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass

import numpy as np

R_EARTH = 6378137.0


def merc_x(lon):
    return R_EARTH * np.radians(lon)


def merc_y(lat):
    return R_EARTH * np.log(np.tan(np.pi / 4 + np.radians(lat) / 2))


def lat_of_y(y):
    return np.degrees(2 * np.arctan(np.exp(np.asarray(y) / R_EARTH)) - np.pi / 2)


def lon_of_x(x):
    return np.degrees(np.asarray(x) / R_EARTH)


@dataclass(frozen=True)
class TargetGrid:
    """Regular EPSG:3857 grid; (x0, y0) is the top-left corner, rows run south."""
    x0: float
    y0: float
    res: float
    nx: int
    ny: int

    @classmethod
    def from_bbox(cls, west, south, east, north, res):
        x0, x1 = float(merc_x(west)), float(merc_x(east))
        y0, y1 = float(merc_y(north)), float(merc_y(south))
        return cls(x0, y0, res, int(math.ceil((x1 - x0) / res)), int(math.ceil((y0 - y1) / res)))

    def center_lons(self):
        return lon_of_x(self.x0 + (np.arange(self.nx) + 0.5) * self.res)

    def center_lats(self):
        return lat_of_y(self.y0 - (np.arange(self.ny) + 0.5) * self.res)

    def bounds_latlon(self):
        """[[south, west], [north, east]] of the outer edges (Leaflet image bounds)."""
        s = float(lat_of_y(self.y0 - self.ny * self.res))
        n = float(lat_of_y(self.y0))
        w = float(lon_of_x(self.x0))
        e = float(lon_of_x(self.x0 + self.nx * self.res))
        return [[round(s, 6), round(w, 6)], [round(n, 6), round(e, 6)]]

    def meta(self):
        return {"crs": "EPSG:3857", "x0": round(self.x0, 3), "y0": round(self.y0, 3), "res": self.res,
                "width": self.nx, "height": self.ny, "bounds": self.bounds_latlon()}


def nearest_index(centers, targets):
    """Index of the nearest source cell for each target coordinate on a regular,
    monotonic 1-D axis of cell centres; -1 outside the axis (beyond half a cell)."""
    centers = np.asarray(centers, dtype="float64")
    step = (centers[-1] - centers[0]) / (len(centers) - 1)
    idx = np.rint((np.asarray(targets, dtype="float64") - centers[0]) / step).astype(int)
    return np.where((idx >= 0) & (idx < len(centers)), idx, -1)


def regrid_regular(src, src_lats, src_lons, grid: TargetGrid):
    """Nearest-neighbour resample of a regular lat/lon array (rows = src_lats) onto
    the target grid. Separable: one index per target row and column. NaN outside."""
    iy = nearest_index(src_lats, grid.center_lats())
    ix = nearest_index(src_lons, grid.center_lons())
    out = np.asarray(src, dtype="float32")[np.clip(iy, 0, None)][:, np.clip(ix, 0, None)]
    out = np.array(out, dtype="float32")
    out[iy < 0, :] = np.nan
    out[:, ix < 0] = np.nan
    return out


def encode(values, scale: float, offset: float = 0.0) -> np.ndarray:
    """float array (NaN = no data) -> uint8 RGBA (h, w, 4)."""
    v = np.asarray(values, dtype="float64")
    ok = np.isfinite(v)
    code = np.zeros(v.shape, dtype="int64")
    code[ok] = np.clip(np.rint((v[ok] - offset) / scale), 0, 65535)
    rgba = np.zeros(v.shape + (4,), dtype="uint8")
    rgba[..., 0] = (code >> 8).astype("uint8")
    rgba[..., 1] = (code & 255).astype("uint8")
    rgba[..., 3] = np.where(ok, 255, 0).astype("uint8")
    return rgba


def decode(rgba, scale: float, offset: float = 0.0) -> np.ndarray:
    rgba = np.asarray(rgba)
    code = rgba[..., 0].astype("int64") * 256 + rgba[..., 1]
    out = code * scale + offset
    return np.where(rgba[..., 3] > 0, out, np.nan)


def png_bytes(rgba) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(rgba), mode="RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def sample(src, src_lats, src_lons, lat, lon):
    """Value of the source cell containing (lat, lon), or None."""
    iy = int(nearest_index(src_lats, [lat])[0])
    ix = int(nearest_index(src_lons, [lon])[0])
    if iy < 0 or ix < 0:
        return None
    v = float(np.asarray(src)[iy, ix])
    return None if not math.isfinite(v) else v
