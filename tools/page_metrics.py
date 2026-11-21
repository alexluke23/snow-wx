"""Area-page metrics on the FROZEN fixtures (dev22): scroll height and CLS at 375x812 and 1280x800, optional per-section screenshots.

    C:/miniforge3/envs/snow-wx/python.exe tools/page_metrics.py [--area grand-targhee-resort] [--out data_cache/metrics.json] [--shots DIR] [--build build]

Runs on a private copy of the build (browser_fixtures.freeze) so the numbers do not depend on live data. The scroll height is measured after every lazy chart
has drawn (the placeholders reserve their height, so it should match). CLS is measured with the 4x CPU slowdown the browser suite uses.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import browser_check as BC  # noqa: E402

OBS = """(() => { window.__cls = 0; try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) window.__cls += e.value; })
  .observe({type: 'layout-shift', buffered: true}); } catch (e) { window.__cls = -1; } })()"""


def measure(area: str, build: Path, shots: Path | None) -> dict:
    out: dict = {}
    tmp = Path(tempfile.mkdtemp(prefix="pm-site-"))
    BC.prepare_site(build, tmp)
    BC.base_dir_holder["path"] = str(tmp)
    with BC.serve(tmp) as base:
        b = BC.Browser(BC.find_chrome())
        try:
            sid = b.cmd("Page.addScriptToEvaluateOnNewDocument", source=OBS)["identifier"]
            for width, height in ((375, 812), (1280, 800)):
                b.cmd("Emulation.setCPUThrottlingRate", rate=4)
                b.open(f"{base}/area.html#{area}", width=width, height=height, wait=12)
                with contextlib.suppress(BC.Fail):
                    BC.wait_for(b, "[...document.querySelectorAll('a[data-mailto]')].every(a => a.dataset.wired === '1')", 6)
                b.settle(1.0)
                cls_first = b.eval("+window.__cls.toFixed(4)")
                b.cmd("Emulation.setCPUThrottlingRate", rate=1)
                BC._draw_all(b)
                b.eval("window.scrollTo(0, 0)")
                b.settle(0.8)
                r = b.eval("""({h: document.documentElement.scrollHeight, cls: +window.__cls.toFixed(4),
                  textChars: [...document.querySelectorAll('main p, main .note, main .hint, main .chart-note')].map(e => e.textContent.trim().length).reduce((a, c) => a + c, 0),
                  sections: [...document.querySelectorAll('#area > *')].map(s => [(s.id || s.className.toString().slice(0, 24) || s.tagName), Math.round(s.getBoundingClientRect().height)])})""")
                r["cls_first_paint"] = cls_first
                out[f"{width}"] = r
                if shots:
                    shots.mkdir(parents=True, exist_ok=True)
                    ids = b.eval("[...document.querySelectorAll('main section[id], main [data-shot]')].map(e => e.id || e.dataset.shot)")
                    for sid_ in ids:
                        clip = b.eval(f"""(() => {{ const e = document.getElementById({json.dumps(sid_)}) || document.querySelector('[data-shot={json.dumps(sid_)}]');
                          if (!e) return null; e.scrollIntoView(); const r = e.getBoundingClientRect(); return {{x: r.left + scrollX, y: r.top + scrollY, width: r.width, height: Math.min(r.height, 1600)}}; }})()""")
                        if not clip or clip["height"] < 20:
                            continue
                        b.settle(0.5)
                        data = b.cmd("Page.captureScreenshot", format="png", clip={**clip, "scale": 1})["data"]
                        (shots / f"{area}-{width}-{sid_}.png").write_bytes(base64.b64decode(data))
            b.cmd("Page.removeScriptToEvaluateOnNewDocument", identifier=sid)
            out["errors"] = list(b.errors)
        finally:
            b.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--area", default="grand-targhee-resort")
    ap.add_argument("--build", default="build")
    ap.add_argument("--out")
    ap.add_argument("--shots")
    a = ap.parse_args()
    res = measure(a.area, Path(a.build), Path(a.shots) if a.shots else None)
    txt = json.dumps(res, indent=1)
    print(txt)
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(txt, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
