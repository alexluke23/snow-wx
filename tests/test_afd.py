"""AFD text parsing (offline)."""

from pipeline import afd

TEXT = """
000
FXUS65 KSLC 080505
AFDSLC

Area Forecast Discussion
National Weather Service Salt Lake City UT
1005 PM MST Sat Nov 7 2026

.KEY MESSAGES...
- Dry through the week.

&&

.DISCUSSION...Snow returns to the Wasatch next weekend.

&&

$$

Forecaster X
"""


def test_parse_keeps_discussion_and_office():
    office, body = afd.parse(TEXT)
    assert office == "Salt Lake City UT"
    assert body.startswith("Area Forecast Discussion") and "Wasatch" in body
    assert "FXUS65" not in body and "Forecaster" not in body and "$$" not in body


def test_offices_cover_catalog():
    w = afd.offices()
    assert "SLC" in w and "REV" in w and len(w) >= 20
