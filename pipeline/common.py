"""Shared helpers: config loading, HTTP session, JSON writing."""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger("snow-wx")

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config" / "settings.yml"


def load_config(path: str | Path | None = None) -> dict:
    with open(path or DEFAULT_CONFIG, encoding="utf-8") as f:
        return yaml.safe_load(f)


def make_session(cfg: dict) -> requests.Session:
    """A requests session with polite retries and a descriptive User-Agent."""
    s = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.headers["User-Agent"] = cfg.get("http", {}).get("user_agent", "snow-wx")
    s.request_timeout = cfg.get("http", {}).get("timeout", 60)  # type: ignore[attr-defined]
    return s


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def clean(value: Any, ndigits: int = 2) -> Any:
    """Make values JSON-safe: NaN/inf -> None, round floats."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, ndigits)
    if isinstance(value, dict):
        return {k: clean(v, ndigits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v, ndigits) for v in value]
    return value


def write_json(path: Path, obj: Any, ndigits: int = 2) -> None:
    """Compact JSON; floats rounded to ndigits (2 suits data values; pass more for
    coordinates or grid definitions)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(clean(obj, ndigits), f, separators=(",", ":"), allow_nan=False)


def feature(lon: float, lat: float, props: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(lon, 5), round(lat, 5)]},
        "properties": props,
    }


def feature_collection(features: list[dict], **extra: Any) -> dict:
    return {"type": "FeatureCollection", "features": features, **extra}
