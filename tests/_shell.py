"""Find a bash that really runs, for the tests that execute workflow shell snippets.

`shutil.which("bash")` is not enough on Windows: C:\\Windows\\System32\\bash.exe is the WSL launcher stub and fails when no distro is installed. A candidate counts
only if `bash -c "echo ok"` succeeds and prints `ok`. Order: bash on PATH, then Git for Windows (bin, usr/bin). Tests skip (never fail) when none works."""
import functools
import os
import shutil
import subprocess

GIT_BASH_CANDIDATES = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
)
SKIP_REASON = "no working bash (PATH bash missing or a WSL stub; Git for Windows bash not found)"


def works(path):
    try:
        r = subprocess.run([path, "-c", "echo ok"], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and r.stdout.strip() == "ok"


@functools.lru_cache(maxsize=1)
def find_bash():
    """absolute path of a bash that runs, or None"""
    candidates = [shutil.which("bash"), *(GIT_BASH_CANDIDATES if os.name == "nt" else ())]
    for c in candidates:
        if c and os.path.exists(c) and works(c):
            return c
    return None


BASH = find_bash()
