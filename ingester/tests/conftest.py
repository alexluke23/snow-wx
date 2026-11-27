"""Make the ingester importable from any working directory: its package lives in ../src. Nothing here imports the
repository's website pipeline: the ingester is standalone."""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
