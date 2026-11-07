"""snow-wx data pipeline: fetches open weather/snow data and writes static
JSON/GeoJSON files that the website reads."""

import os
import sys
from pathlib import Path

__version__ = "0.2.0"


def _windows_conda_dll_path() -> None:
    """Let ecCodes find eccodes.dll when the env's python.exe is run directly.

    `conda activate` normally puts <env>/Library/bin on PATH; calling
    C:/miniforge3/envs/snow-wx/python.exe without activating does not, and then
    `import eccodes` (used by cfgrib and Herbie) fails with "Cannot find the
    ecCodes library".
    """
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
