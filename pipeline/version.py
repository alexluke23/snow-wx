"""Code/config versions for "already published" checks.

A published product is identified by `<input key>-<version>` (the release asset is
`<product>-<key>-<version>.tar`). The version hashes the product's code and config
files, so a renderer or config change re-renders the current cycle instead of
waiting for the next one.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .common import REPO_ROOT

PRODUCT_FILES = {
    "models": ["config/models.yml", "pipeline/models/*.py"],
    "points": ["pipeline/nbm/*.py", "pipeline/points.py", "data/ski_areas.json", "data/snotel_points.json", "data/rec_points.json"],
    "nohrsc": ["pipeline/nohrsc.py", "pipeline/layers.py", "data/ski_areas.json", "data/rec_points.json"],
    "ndfd": ["pipeline/ndfd.py", "pipeline/points.py", "data/ski_areas.json", "data/snotel_points.json", "data/rec_points.json"],
}


def code_version(patterns: list[str], root: Path = REPO_ROOT) -> str:
    """8-hex hash over the files' contents (CRLF normalised so Windows/Linux agree)."""
    h = hashlib.sha1()
    for pat in patterns:
        for path in sorted(root.glob(pat)):
            h.update(path.relative_to(root).as_posix().encode())
            h.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:8]


def product_version(product: str) -> str:
    return code_version(PRODUCT_FILES[product])


def stamp(key: str, product: str) -> str:
    return f"{key}-{product_version(product)}"
