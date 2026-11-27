"""snow-wx ingester: fetch forecast and observation data from public sources and store it as JSON (+ model PNGs) in a
local folder or Cloudflare R2. It is standalone: the fetch code lives in `ingester/fetch/`, its settings in
`ingester/config/`, and its point lists in `ingester/data/`. See `python -m ingester --help` and docs/specs/ingest-r2.md.
"""

import os
import sys
from pathlib import Path


def _windows_conda_dll_path() -> None:
    """Let ecCodes find eccodes.dll when the env's python.exe is run directly (cfgrib and Herbie need it)."""
    if os.name != "nt":
        return
    lib_bin = Path(sys.prefix) / "Library" / "bin"
    if lib_bin.is_dir() and str(lib_bin) not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{lib_bin}{os.pathsep}{os.environ.get('PATH', '')}"
        try:
            os.add_dll_directory(str(lib_bin))
        except (AttributeError, OSError):
            pass


_windows_conda_dll_path()
