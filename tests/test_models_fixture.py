"""dev18 Part 0a: the synthetic model-frame fixture (tools/model_fixture.py) matches the published layout, and the index carries per-field pixel sizes."""
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from model_fixture import png, write_fixture  # noqa: E402

from pipeline.models.run import frame_sizes, png_size  # noqa: E402


def test_png_size_reads_the_header_and_rejects_junk(tmp_path):
    p = tmp_path / "a.png"
    p.write_bytes(png(900, 640))
    assert png_size(p) == [900, 640]
    (tmp_path / "b.png").write_bytes(b"not a png at all, just text bytes")
    assert png_size(tmp_path / "b.png") is None and png_size(tmp_path / "missing.png") is None


def test_frame_sizes_first_frame_per_field_and_domain(tmp_path):
    ok = []
    for dom, h in (("west", 700), ("wasatch", 640)):
        for f in (1, 2):
            q = tmp_path / "qpf_total" / dom / f"f{f:03d}.png"
            q.parent.mkdir(parents=True, exist_ok=True)
            q.write_bytes(png(900, h))
            ok.append({"field": "qpf_total", "domain": dom, "f": f})
    assert frame_sizes(tmp_path, ok) == {"qpf_total": {"west": [900, 700], "wasatch": [900, 640]}}


def test_fixture_writes_the_catalog_the_viewer_reads(tmp_path):
    cat = write_fixture(tmp_path / "models", cycle=datetime(2026, 11, 18, 6))
    assert list(cat["models"]) == ["hrrr", "rrfs", "gfs"]
    h = cat["models"]["hrrr"]
    assert h["base"] == "hrrr/" and h["path"] == "2026111806/{field}/{domain}/f{fhour}.png"
    assert h["fields"]["qpf_total"]["size"] == {"west": [900, 700], "wasatch": [900, 640]}
    first = h["fields"]["qpf_total"]["fhours"][0]
    assert (tmp_path / "models" / "hrrr" / "2026111806" / "qpf_total" / "west" / f"f{first:03d}.png").exists()
    old = write_fixture(tmp_path / "old", with_sizes=False)                 # an old-style catalog has no size and must still load
    assert "size" not in old["models"]["hrrr"]["fields"]["qpf_total"]
    assert json.loads((tmp_path / "models" / "index.json").read_text(encoding="utf-8"))["models"]["gfs"]["cycle"] == "2026111806"
