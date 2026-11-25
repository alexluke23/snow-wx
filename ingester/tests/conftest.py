"""Make the ingester importable from any working directory: its package lives in ../src, and the pipeline it wraps
lives at the repository root (two levels up from this file)."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
for path in (HERE.parent / "src", HERE.parent.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
