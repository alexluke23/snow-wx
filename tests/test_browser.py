"""Real-browser regression checks (tools/browser_check.py). Opt-in: they need Chrome, a
built site in build/ and ~2 minutes, so they run only with SNOWWX_BROWSER=1."""

import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

pytestmark = pytest.mark.skipif(os.environ.get("SNOWWX_BROWSER") != "1",
                                reason="set SNOWWX_BROWSER=1 (needs Chrome + a built site)")


@pytest.mark.parametrize("check", ["basemap", "fallback", "layout", "search", "charts", "snoparks", "forecast"])
def test_site_in_headless_chrome(check):
    pytest.importorskip("websocket")
    import browser_check
    if not browser_check.find_chrome():
        pytest.skip("Chrome not found")
    assert browser_check.main(["--only", check, "--build", str(REPO / "build")]) == 0
