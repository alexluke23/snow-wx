"""Pure meteorological calculations on 2-D numpy arrays (unit-tested, no I/O).

Conventions: temperatures in K unless the name says _c/_f; heights in m MSL;
pressure in Pa for surface pressure and hPa (mb) for level labels.
"""

from __future__ import annotations

import numpy as np

KUCHERA_T0 = 271.16   # K
OMEGA = 7.2921e-5     # s^-1


# ---------------------------------------------------------------- units

def k_to_c(k):
    return k - 273.15


def k_to_f(k):
    return (k - 273.15) * 9.0 / 5.0 + 32.0


def ms_to_kt(ms):
    return ms * 1.943844


def m_to_ft(m):
    return m * 3.28084


def mm_to_in(mm):
    """kg m^-2 of water == mm."""
    return mm / 25.4


# ---------------------------------------------------------------- precipitation

def qpf_window(totals: dict[int, np.ndarray], f: int, hours: int) -> np.ndarray | None:
    """Precipitation over (f-hours, f] from run-total accumulations, or None."""
    if f not in totals or (f - hours) not in totals:
        return None
    return np.maximum(totals[f] - totals[f - hours], 0.0)


def frozen_fraction(cpofp: np.ndarray | None = None, csnow: np.ndarray | None = None) -> np.ndarray:
    """Fraction of precipitation falling as snow.

    CPOFP is the model's percent frozen precipitation (negative = no precip);
    CSNOW is the 0/1 categorical snow flag, used when CPOFP is unavailable.
    """
    if cpofp is not None:
        return np.clip(cpofp, 0.0, 100.0) / 100.0
    if csnow is not None:
        return (csnow >= 0.5).astype(np.float32)
    raise ValueError("need CPOFP or CSNOW")


def kuchera_slr(tmax_k: np.ndarray, cap: float = 30.0) -> np.ndarray:
    """Kuchera snow-to-liquid ratio from the column maximum temperature (K).

    SLR = 12 + 2 (271.16 - Tmax) where Tmax > 271.16 K, else 12 + (271.16 - Tmax);
    clipped to [0, cap].
    """
    d = KUCHERA_T0 - tmax_k
    slr = np.where(tmax_k > KUCHERA_T0, 12.0 + 2.0 * d, 12.0 + d)
    return np.clip(slr, 0.0, cap)


def column_tmax(t2m: np.ndarray, level_t: dict[int, np.ndarray], psfc_pa: np.ndarray,
                level_z: dict[int, np.ndarray] | None = None,
                orog: np.ndarray | None = None, top_hpa: int = 500) -> np.ndarray:
    """Max temperature from 2 m up to `top_hpa`, ignoring below-ground levels.

    A pressure level is below ground where its pressure exceeds the surface
    pressure, or (if heights are given) where its height is below the terrain.
    Those levels hold extrapolated values and would bias Kuchera warm.
    """
    tmax = np.array(t2m, dtype=np.float64, copy=True)
    for p, t in level_t.items():
        if p < top_hpa:
            continue
        below = psfc_pa < p * 100.0
        if level_z is not None and orog is not None and p in level_z:
            below = below | (level_z[p] < orog)
        tmax = np.where(below, tmax, np.maximum(tmax, t))
    return tmax


def accumulate(prev_total: np.ndarray | None, increment: np.ndarray) -> np.ndarray:
    return increment.copy() if prev_total is None else prev_total + increment


# ---------------------------------------------------------------- moisture / snow level

def rh_from_dewpoint(t_c, td_c):
    """Relative humidity (%) from temperature and dewpoint (°C), Bolton (1980)."""
    es = 6.112 * np.exp(17.67 * t_c / (t_c + 243.5))
    e = 6.112 * np.exp(17.67 * td_c / (td_c + 243.5))
    return np.clip(100.0 * e / es, 1.0, 100.0)


def wetbulb_stull(t_c, rh):
    """Wet-bulb temperature (°C) from T (°C) and RH (%), Stull (2011).

    Empirical fit at ~1013 hPa; error grows aloft in very dry air (see CLAUDE.md).
    """
    rh = np.clip(rh, 1.0, 100.0)
    return (t_c * np.arctan(0.151977 * np.sqrt(rh + 8.313659))
            + np.arctan(t_c + rh) - np.arctan(rh - 1.676331)
            + 0.00391838 * rh ** 1.5 * np.arctan(0.023101 * rh)
            - 4.686035)


def height_lnp(z_lo, p_lo, z_hi, p_hi, p):
    """Height at pressure p by interpolating linearly in ln(p) between two levels."""
    return z_lo + (z_hi - z_lo) * np.log(p_lo / p) / np.log(p_lo / p_hi)


def wetbulb_zero_height(z_sfc: np.ndarray, tw_sfc: np.ndarray,
                        levels: list[tuple[int, np.ndarray, np.ndarray]],
                        psfc_pa: np.ndarray) -> np.ndarray:
    """Lowest height (m MSL) at which the wet-bulb temperature reaches 0 °C.

    Scans upward from the surface. Where surface Tw <= 0 the result is the
    terrain height (snow level at/below ground). Levels below ground are
    skipped. NaN where Tw stays above 0 through the top level.
    `levels` is [(p_hPa, height_m, tw_c), ...] in any order.
    """
    out = np.where(tw_sfc <= 0.0, z_sfc, np.nan)
    prev_z = np.array(z_sfc, dtype=np.float64, copy=True)
    prev_tw = np.array(tw_sfc, dtype=np.float64, copy=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        for p, z, tw in sorted(levels, key=lambda x: -x[0]):
            above = (psfc_pa >= p * 100.0) & (z > z_sfc)
            cross = above & np.isnan(out) & (prev_tw > 0.0) & (tw <= 0.0)
            frac = prev_tw / (prev_tw - tw)
            out = np.where(cross, prev_z + frac * (z - prev_z), out)
            prev_z = np.where(above, z, prev_z)
            prev_tw = np.where(above, tw, prev_tw)
    return out


def cap_at(values: np.ndarray, ceiling: np.ndarray) -> np.ndarray:
    """min(values, ceiling) where both are finite; values elsewhere."""
    with np.errstate(invalid="ignore"):
        return np.where(np.isfinite(ceiling) & (ceiling < values), ceiling, values)


# ---------------------------------------------------------------- dynamics

def coriolis(lat_deg):
    return 2.0 * OMEGA * np.sin(np.deg2rad(lat_deg))


def relative_vorticity(u, v, dx: float, dy: float, map_factor=None):
    """dv/dx - du/dy on a regular projected grid (dx, dy in m; +row = +y).

    With grid-relative winds on the grid's own axes this is exact up to the
    map factor, which scales the finite differences.
    """
    zeta = np.gradient(v, dx, axis=1) - np.gradient(u, dy, axis=0)
    if map_factor is not None:
        zeta = zeta * map_factor
    return zeta


def absolute_vorticity(u, v, lat_deg, dx: float, dy: float, map_factor=None):
    return relative_vorticity(u, v, dx, dy, map_factor) + coriolis(lat_deg)


def smooth(field: np.ndarray, sigma_px: float) -> np.ndarray:
    """Gaussian smoothing (sigma in grid points); returns input when sigma <= 0."""
    if sigma_px <= 0:
        return field
    from scipy.ndimage import gaussian_filter
    return gaussian_filter(field, sigma_px, mode="nearest")
