"""Synthetic model-map frames for layout checks (dev18 Part 0a): writes <out>/models/index.json + <model>/<cycle>/<field>/<domain>/fNNN.png
in exactly the layout the pipeline publishes (the per-model index comes from the real `build_index`, the catalog from the real `collect`).
The PNGs are flat colour with a coarse grid, 900 px wide and a per-domain height like the real renders; no matplotlib, PIL or network.
Used by tools/browser_check.py (check `models`) and tests/test_models_fixture.py.

    python tools/model_fixture.py build/models      # write a fixture next to a local build (never commit the output)
"""
from __future__ import annotations

import struct
import sys
import zlib
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

# (field, domains, fhours): real field names so FIELD_INFO labels/groups apply; heights mimic the real per-domain aspect ratios
SPEC = {"hrrr": {"qpf_total": (["west", "wasatch"], list(range(1, 19)) + [21, 24, 27, 30, 33, 36, 39, 42, 45, 48]),
                 "t2m": (["west"], list(range(0, 19)))},
        "rrfs": {"qpf_total": (["west"], list(range(1, 19)) + [21, 24, 27, 30, 33, 36, 39, 42, 45, 48])},
        "gfs": {"qpf_total": (["west"], list(range(3, 49, 3)))}}
HEIGHT = {"west": 700, "wasatch": 640, "pnw": 760, "sierra": 820, "nrockies": 680, "colorado": 660}


def png(width: int, height: int, rgb=(214, 226, 240)) -> bytes:
    """a valid RGB PNG, flat colour with a 50-px grid (so a viewer screenshot is recognisable)"""
    raw = bytearray()
    line = bytearray(rgb * width)
    for x in range(0, width, 50):
        line[x * 3:x * 3 + 3] = bytes((120, 130, 150))
    grid = bytes(120 for _ in range(width * 3))
    for y in range(height):
        raw.append(0)
        raw += (grid if y % 50 == 0 else line)

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))


def write_fixture(models_dir: Path, cycle: datetime | None = None, with_sizes: bool = True, spec: dict | None = None) -> dict:
    """returns the catalog; with_sizes=False writes an OLD-style index (no per-field `size`) to test the fallback layout"""
    import json

    from pipeline.models.catalog import write_catalog
    from pipeline.models.config import load_models_config
    from pipeline.models.run import build_index, frame_sizes
    cfg = load_models_config()
    cycle = cycle or datetime(2026, 11, 18, 6)
    cid = cycle.strftime("%Y%m%d%H")
    models_dir = Path(models_dir)
    for model, fields in (spec or SPEC).items():
        mdir = models_dir / model
        ok = []
        for field, (domains, fhours) in fields.items():
            for dom in domains:
                for f in fhours:
                    p = mdir / cid / field / dom / f"f{f:03d}.png"
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(png(900, HEIGHT.get(dom, 700)) if (f == fhours[0] or f % 6 == 0) else b"")
                    ok.append({"field": field, "domain": dom, "f": f, "bytes": p.stat().st_size, "ok": True})
        # every frame needs bytes: reuse the first valid one (only sizes matter for layout)
        for r in ok:
            p = mdir / cid / r["field"] / r["domain"] / f"f{r['f']:03d}.png"
            if p.stat().st_size == 0:
                first = next(q for q in p.parent.glob("f*.png") if q.stat().st_size)
                p.write_bytes(first.read_bytes())
        idx = build_index(cfg, model, cycle, ok, frame_sizes(mdir / cid, ok) if with_sizes else None)
        (mdir / "index.json").write_text(json.dumps(idx), encoding="utf-8")
    return write_catalog(models_dir, list(SPEC))


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else REPO / "build" / "models")
    cat = write_fixture(out)
    print("fixture:", ", ".join(f"{m} {i['cycle']}" for m, i in cat["models"].items()), "->", out)
