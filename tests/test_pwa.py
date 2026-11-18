"""W4 PWA build step (pipeline/pwa.py): flag, manifest, versioned worker, injection, kill switch. Offline behaviour: tools/browser_check.py `pwa`."""

import json

from pipeline import pwa


def site(tmp_path):
    (tmp_path / "css").mkdir()
    (tmp_path / "js" / "charts").mkdir(parents=True)
    (tmp_path / "vendor" / "leaflet-1.9.4").mkdir(parents=True)
    (tmp_path / "css" / "style.css").write_text("a{}", encoding="utf-8")
    (tmp_path / "js" / "pwa.js").write_text("//", encoding="utf-8")
    (tmp_path / "js" / "charts" / "theme.js").write_text("//", encoding="utf-8")
    (tmp_path / "vendor" / "leaflet-1.9.4" / "leaflet.js").write_text("//", encoding="utf-8")
    for n in ("index", "mine", "area"):
        (tmp_path / f"{n}.html").write_text("<html><head><title>x</title></head><body></body></html>", encoding="utf-8")
    return tmp_path


CFG = {"site": {"origin": "https://example.test", "base_path": "/snow-wx"}, "pwa": {"enabled": False}}


def test_disabled_writes_nothing(tmp_path):
    site(tmp_path)
    before = (tmp_path / "mine.html").read_text(encoding="utf-8")
    assert pwa.run(CFG, tmp_path) == 0
    assert not (tmp_path / "sw.js").exists() and not (tmp_path / "manifest.json").exists() and (tmp_path / "mine.html").read_text(encoding="utf-8") == before


def test_enabled_writes_manifest_worker_icons_and_injects_pages(tmp_path):
    site(tmp_path)
    assert pwa.run({**CFG, "pwa": {"enabled": True}}, tmp_path) == 0
    m = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert m["start_url"] == "/snow-wx/mine.html?source=pwa" and m["scope"] == "/snow-wx/" and m["display"] == "standalone"
    assert {i["sizes"] for i in m["icons"]} == {"192x192", "512x512"} and any(i.get("purpose") == "maskable" for i in m["icons"])
    assert all((tmp_path / "icons" / f).exists() for f in ("icon-192.png", "icon-512.png", "icon-maskable-512.png", "apple-touch-icon.png"))
    sw = (tmp_path / "sw.js").read_text(encoding="utf-8")
    assert 'const BASE = "/snow-wx"' in sw and '"mine.html"' in sw and '"js/charts/theme.js"' in sw and "__" not in sw.split("const SHELL")[0].split("const VERSION")[1]
    assert "example.test" not in sw and "alexluke23" not in sw               # no hard-coded origin
    assert '"data/' not in sw.split("const SHELL = ")[1].split(";")[0]        # the shell list holds no data files
    h = (tmp_path / "mine.html").read_text(encoding="utf-8")
    assert 'rel="manifest" href="/snow-wx/manifest.json"' in h and "SNOWWX_PWA" in h and 'src="js/pwa.js"' in h
    assert pwa.run({**CFG, "pwa": {"enabled": True}}, tmp_path) == 0           # idempotent: injected once
    assert (tmp_path / "mine.html").read_text(encoding="utf-8").count("snowwx-pwa") == 1


def test_cache_version_changes_when_the_shell_changes(tmp_path):
    site(tmp_path)
    v1 = pwa.version_of(tmp_path, pwa.shell_files(tmp_path))
    (tmp_path / "css" / "style.css").write_text("a{color:red}", encoding="utf-8")
    assert pwa.version_of(tmp_path, pwa.shell_files(tmp_path)) != v1


def test_kill_switch_writes_only_a_self_removing_worker(tmp_path):
    site(tmp_path)
    assert pwa.run({**CFG, "pwa": {"enabled": True, "kill": True}}, tmp_path) == 0
    sw = (tmp_path / "sw.js").read_text(encoding="utf-8")
    assert "unregister()" in sw and 'startsWith("snowwx-")' in sw
    assert not (tmp_path / "manifest.json").exists() and "SNOWWX_PWA" not in (tmp_path / "mine.html").read_text(encoding="utf-8")
