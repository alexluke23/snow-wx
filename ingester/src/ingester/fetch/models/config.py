"""config/models.yml loading and pure expansion helpers (no network)."""

from __future__ import annotations

from pathlib import Path

import yaml

from ..common import REPO_ROOT

MODELS_CONFIG = REPO_ROOT / "config" / "models.yml"

# Field metadata shared by the plots and the web index.
FIELD_INFO = {
    "h500":      {"label": "500 mb heights & absolute vorticity", "group": "Upper air"},
    "t700":      {"label": "700 mb temperature, heights & wind", "group": "Upper air"},
    "qpf1":      {"label": "1-hr precipitation (in)", "group": "Precipitation"},
    "qpf6":      {"label": "6-hr precipitation (in)", "group": "Precipitation"},
    "qpf24":     {"label": "24-hr precipitation (in)", "group": "Precipitation"},
    "qpf_total": {"label": "Total precipitation since init (in)", "group": "Precipitation"},
    "snow":      {"label": "Snowfall since init: 10:1 vs Kuchera (in)", "group": "Snow"},
    "snowlevel": {"label": "Snow level vs terrain (ft MSL)", "group": "Snow",
                  "note": "Snow level ≈ wet-bulb 0 °C height (computed from model T/Td)."},
    "t2m":       {"label": "2-m temperature (°F)", "group": "Surface"},
    "gust":      {"label": "Surface wind gust (kt)", "group": "Surface"},
}

# Precipitation windows (hours) computed by differencing run-total QPF.
QPF_WINDOWS = {"qpf1": 1, "qpf6": 6, "qpf24": 24}
# Fields accumulated since initialization: undefined at f000.
SINCE_INIT = {"qpf_total", "snow"}


def load_models_config(path: str | Path | None = None) -> dict:
    with open(path or MODELS_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def expand_fhours(spec) -> list[int]:
    """[[0, 18, 1], [21, 48, 3]] -> [0, 1, ..., 18, 21, 24, ..., 48] (inclusive)."""
    hours: set[int] = set()
    for item in spec:
        if isinstance(item, int):
            hours.add(item)
            continue
        start, stop, step = item
        hours.update(range(int(start), int(stop) + 1, int(step)))
    return sorted(hours)


def field_domains(cfg: dict, model: str, field: str) -> list[str]:
    """Domains a model's field is drawn on (model domains limited by field_domains)."""
    allowed = (cfg.get("field_domains") or {}).get(field)
    return [d for d in cfg["models"][model]["domains"] if allowed is None or d in allowed]


def field_fhours(field: str, fhours: list[int]) -> list[int]:
    """Forecast hours at which `field` can be produced from frames at `fhours`."""
    have = set(fhours)
    if field in QPF_WINDOWS:
        n = QPF_WINDOWS[field]
        return [f for f in fhours if f >= n and (f - n) in have]
    if field in SINCE_INIT:
        return [f for f in fhours if f > 0]
    return list(fhours)


def image_count(cfg: dict, model: str) -> int:
    m = cfg["models"][model]
    fh = expand_fhours(m["fhours"])
    return sum(len(field_fhours(f, fh)) * len(field_domains(cfg, model, f)) for f in m["fields"])


def total_image_count(cfg: dict, enabled_only: bool = False) -> int:
    return sum(image_count(cfg, name) for name, m in cfg["models"].items()
               if m.get("enabled", True) or not enabled_only)
