"""W1 cutover (dev18 stretch 1): the github.io redirect stub (pipeline/stub.py) and the rehearsal (tools/w1_rehearsal.py) that builds for a placeholder domain. Offline."""
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import w1_rehearsal  # noqa: E402

from pipeline import stub  # noqa: E402

AREAS = [{"id": "alta-ski-area", "state": "UT"}, {"id": "taos-ski-valley", "state": "NM"}]


def test_stub_pages_map_ids_and_never_use_inline_scripts_or_the_old_host(tmp_path):
    info = stub.build({}, tmp_path, "https://snowwx.example", AREAS, ["sp-wing-mountain"], "")
    assert info == {"pages": len(stub.OLD_PAGES) + 1, "ids": 3}
    idx = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://snowwx.example/">' in idx and 'content="0; url=https://snowwx.example/"' in idx and 'name="robots" content="noindex"' in idx
    assert 'href="https://snowwx.example/finder.html"' in (tmp_path / "finder.html").read_text(encoding="utf-8")
    area = (tmp_path / "area.html").read_text(encoding="utf-8")
    assert 'src="js/stub-redirect.js"' in area and "http-equiv" not in area                       # script only: a meta refresh would drop the #id
    js = (tmp_path / "js" / "stub-redirect.js").read_text(encoding="utf-8")
    m = json.loads(re.search(r"var m=(\{.*?\});", js).group(1))
    assert m["alta-ski-area"] == "https://snowwx.example/ski/ut/alta-ski-area/" and m["sp-wing-mountain"] == "https://snowwx.example/area.html#sp-wing-mountain"
    assert 'var f="https://snowwx.example/area.html"' in js                                        # unknown ids (SNOTEL sites): the new interactive page with the same hash
    blob = "".join(p.read_text(encoding="utf-8") for p in tmp_path.rglob("*") if p.is_file())
    assert "github.io" not in blob and "<script>" not in blob


def test_stub_with_a_base_path_and_trailing_slashes(tmp_path):
    stub.build({}, tmp_path, "https://snowwx.example/", AREAS, [], "/app/")
    assert 'href="https://snowwx.example/app/"' in (tmp_path / "index.html").read_text(encoding="utf-8")
    assert "https://snowwx.example/app/ski/nm/taos-ski-valley/" in (tmp_path / "js" / "stub-redirect.js").read_text(encoding="utf-8")


def test_the_stub_covers_every_page_the_live_site_serves():
    live = sorted(p.name for p in (REPO / "web").glob("*.html") if p.name != "404.html")
    assert set(live) <= set(stub.OLD_PAGES), f"pages missing from stub.OLD_PAGES: {sorted(set(live) - set(stub.OLD_PAGES))}"


def test_w1_rehearsal_passes_for_the_root_and_a_nested_base_path():
    for base in ("", "/app"):
        res = w1_rehearsal.run("https://snowwx.example", base)
        failed = [(n, d) for n, ok, d in res if not ok]
        assert not failed, f"base {base!r}: {failed}"
        assert len(res) >= 14
