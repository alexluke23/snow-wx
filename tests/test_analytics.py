"""dev18 Part 2c: the cookieless analytics abstraction (web/js/analytics.js + the loader in web/js/site-config.js + config `analytics`). Offline.
Guarantees tested: OFF by default; with it off the script is never injected and no provider host is contacted; Do Not Track and Global Privacy Control are honoured;
no cookies/storage/fingerprinting calls in the code; only the fixed event vocabulary and the two allowed labels leave the page; provider adapters build the right script;
the privacy page and sources register must name the provider before it is enabled."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from pipeline.__main__ import analytics_public
from pipeline.common import load_config

ROOT = Path(__file__).resolve().parents[1]
JS = (ROOT / "web" / "js" / "analytics.js").read_text(encoding="utf-8")


def _node():
    for p in (shutil.which("node"), r"C:\miniforge3\envs\tools\node.exe"):
        if p and os.path.exists(p):
            return p
    return None


def run_js(tmp_path, body: str):
    script = tmp_path / "t.js"
    script.write_text("const fs=require('fs'),vm=require('vm');const ctx={};vm.createContext(ctx);\n"
                      "vm.runInContext(fs.readFileSync(%s,'utf8')+'\\nthis.A=SnowWxAnalytics;',ctx);const A=ctx.A;\n%s" % (json.dumps(str(ROOT / "web" / "js" / "analytics.js")), body), encoding="utf-8")
    r = subprocess.run([_node(), str(script)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


# ---------------------------------------------------------------- config and meta.json (Python)
def test_default_config_is_off_and_meta_exposes_nothing_about_a_provider():
    a = load_config()["analytics"]
    assert a["enabled"] is False and a["provider"] == "none" and not a["site_id"]
    assert analytics_public(load_config()) == {"enabled": False}


@pytest.mark.parametrize("cfg,expect", [
    ({"enabled": True, "provider": "plausible", "site_id": "snow.example"}, {"enabled": True, "provider": "plausible", "site_id": "snow.example"}),
    ({"enabled": True, "provider": "goatcounter", "site_id": "snowwx", "script_url": "https://stats.example/count.js"}, {"enabled": True, "provider": "goatcounter", "site_id": "snowwx", "script_url": "https://stats.example/count.js"}),
    ({"enabled": True, "provider": "cloudflare", "site_id": "tok"}, {"enabled": True, "provider": "cloudflare", "site_id": "tok"}),
    ({"enabled": True, "provider": "plausible", "site_id": ""}, {"enabled": False}),                  # no site id: off
    ({"enabled": True, "provider": "none", "site_id": "x"}, {"enabled": False}),                      # no provider chosen: off
    ({"enabled": True, "provider": "google-analytics", "site_id": "x"}, {"enabled": False}),          # unknown provider: off
    ({"enabled": False, "provider": "plausible", "site_id": "x"}, {"enabled": False}),               # flag off wins
    ({"enabled": True, "provider": "plausible", "site_id": "x", "script_url": "http://insecure"}, {"enabled": True, "provider": "plausible", "site_id": "x"}),   # https only
])
def test_analytics_public_only_enables_a_complete_known_provider(cfg, expect):
    assert analytics_public({"analytics": cfg}) == expect


def test_meta_json_carries_the_analytics_block(tmp_path):
    from pipeline.__main__ import write_meta
    write_meta(load_config(), tmp_path, {})
    assert json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))["analytics"] == {"enabled": False}


# ---------------------------------------------------------------- static guarantees on the code
def test_the_code_sets_no_cookies_uses_no_storage_and_does_no_fingerprinting():
    for banned in ("document.cookie", "localStorage", "sessionStorage", "indexedDB", "canvas", "getContext", "fonts.check", "AudioContext", "enumerateDevices", "getBattery",
                   "screen.width", "hardwareConcurrency", "userAgent", "navigator.plugins", "RTCPeerConnection", "sendBeacon"):
        assert banned not in JS, f"analytics.js must not use {banned}"
    assert re.findall(r"https://[a-z0-9.-]+", JS) and all(h.split("//")[1] in ("plausible.io", "gc.zgo.at", "static.cloudflareinsights.com") or h.endswith(".goatcounter.com") or "${" in h
                                                          for h in re.findall(r"https://[a-z0-9.${}-]+", JS))


def test_site_config_loads_analytics_only_when_meta_enables_it():
    sc = (ROOT / "web" / "js" / "site-config.js").read_text(encoding="utf-8")
    assert "a.enabled !== true" in sc and 'a.provider === "none"' in sc and "queue.length = 0" in sc
    assert sc.count("${BASE}js/analytics.js") == 1             # the only place the file is requested
    for page in ("index", "area", "finder", "mine", "models", "about", "status", "sources", "privacy", "terms", "disclaimer", "404"):
        html = (ROOT / "web" / f"{page}.html").read_text(encoding="utf-8")
        assert not re.search(r"<script[^>]+(analytics|plausible|goatcounter|cloudflareinsights|zgo\.at)", html, re.I), f"{page}.html must not load analytics directly"


def test_events_are_wired_where_the_ui_exists():
    area = (ROOT / "web" / "js" / "area.js").read_text(encoding="utf-8")
    assert 'snowwxTrack("favorite_added"' in area and area.count('data-track="avalanche_click"') == 3 and (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8").count('data-track="avalanche_click"') == 1
    assert 'data-track=\\"table_view\\"' in (ROOT / "web" / "js" / "charts" / "theme.js").read_text(encoding="utf-8")
    assert 'snowwxTrack("favorite_added", { where: "finder" })' in (ROOT / "web" / "js" / "finder.js").read_text(encoding="utf-8")
    assert 'snowwxTrack("install"' in (ROOT / "web" / "js" / "pwa.js").read_text(encoding="utf-8")


def test_enabling_a_provider_requires_it_to_be_disclosed():
    """the day the owner enables analytics, the privacy page and the sources register must name the provider host (this fails until they do)"""
    cfg = load_config()
    if not cfg["analytics"]["enabled"]:
        return
    src = yaml.safe_load((ROOT / "config" / "sources.yml").read_text(encoding="utf-8"))
    hosts = {h for s in src["sources"] for h in (s.get("browser") or [])}
    host = {"plausible": "plausible.io", "goatcounter": "gc.zgo.at", "cloudflare": "static.cloudflareinsights.com"}[cfg["analytics"]["provider"]]
    assert host in hosts and f'<th scope="row">{host}</th>' in (ROOT / "web" / "privacy.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------- behaviour (Node)
@pytest.mark.skipif(_node() is None, reason="node not installed")
def test_do_not_track_and_global_privacy_control_are_honoured(tmp_path):
    out = run_js(tmp_path, """
const on = {enabled: true, provider: 'plausible', site_id: 'x.example'};
const r = {
  plain: !!A.plan(on, {}, {}),
  dnt1: !!A.plan(on, {doNotTrack: '1'}, {}), dntYes: !!A.plan(on, {doNotTrack: 'yes'}, {}), winDnt: !!A.plan(on, {}, {doNotTrack: '1'}), ms: !!A.plan(on, {msDoNotTrack: '1'}, {}),
  gpc: !!A.plan(on, {globalPrivacyControl: true}, {}), dnt0: !!A.plan(on, {doNotTrack: '0'}, {}), gpcFalse: !!A.plan(on, {globalPrivacyControl: false}, {}),
};
console.log(JSON.stringify(r));""")
    assert out == {"plain": True, "dnt1": False, "dntYes": False, "winDnt": False, "ms": False, "gpc": False, "dnt0": True, "gpcFalse": True}


@pytest.mark.skipif(_node() is None, reason="node not installed")
def test_disabled_or_incomplete_config_never_plans_a_script(tmp_path):
    out = run_js(tmp_path, """
const bad = [null, {}, {enabled: false, provider: 'plausible', site_id: 'x'}, {enabled: 'true', provider: 'plausible', site_id: 'x'}, {enabled: true, provider: 'none', site_id: 'x'},
  {enabled: true, provider: 'plausible', site_id: ''}, {enabled: true, provider: 'ga', site_id: 'x'}, {enabled: true, provider: 'plausible', site_id: 'x', script_url: 'http://x'}];
console.log(JSON.stringify(bad.map((c) => A.plan(c, {}, {}))));""")
    assert out == [None] * 8


@pytest.mark.skipif(_node() is None, reason="node not installed")
def test_providers_build_the_right_script_and_only_https(tmp_path):
    out = run_js(tmp_path, """
const p = (provider, site_id, script_url) => A.plan({enabled: true, provider, site_id, script_url}, {}, {});
console.log(JSON.stringify([p('plausible', 'snow.example'), p('goatcounter', 'snowwx'), p('goatcounter', 'https://stats.example/count'), p('cloudflare', 'tok123'), p('plausible', 'a.b', 'https://self.example/js/s.js')]));""")
    pl, gc, gc2, cf, own = out
    assert pl["src"] == "https://plausible.io/js/script.js" and pl["attrs"]["data-domain"] == "snow.example" and pl["events"] is True
    assert gc["src"] == "https://gc.zgo.at/count.js" and gc["attrs"]["data-goatcounter"] == "https://snowwx.goatcounter.com/count"
    assert gc2["attrs"]["data-goatcounter"] == "https://stats.example/count"
    assert cf["src"].endswith("beacon.min.js") and json.loads(cf["attrs"]["data-cf-beacon"]) == {"token": "tok123"} and cf["events"] is False      # no custom events there
    assert own["src"] == "https://self.example/js/s.js"


@pytest.mark.skipif(_node() is None, reason="node not installed")
def test_only_the_fixed_event_vocabulary_and_allowed_labels_leave_the_page(tmp_path):
    out = run_js(tmp_path, """
const sent = [];
ctx.window = ctx; ctx.plausible = (...a) => sent.push(a);
vm.runInContext("window.plausible = window.plausible", ctx);
const el = {setAttribute() {}, addEventListener() {}};
ctx.document = {createElement: () => el, head: {appendChild() {}}, addEventListener() {}, body: {dataset: {}}};
ctx.navigator = {};
A.init({enabled: true, provider: 'plausible', site_id: 'x.example'}, []);
const r = {
  ok: A.track('favorite_added', {where: 'area', kind: 'ski', id: 'alta-ski-area', name: 'Alta', email: 'a@b.c'}),
  bad: A.track('page_secret', {where: 'area'}), bad2: A.track('__proto__', {}), none: A.track('install'),
};
console.log(JSON.stringify({r, sent, san: A.sanitize({where: 'evil', kind: 'x', id: 1, where2: 'area'}), san2: A.sanitize({where: 'finder', kind: 'snotel'})}));""")
    assert out["r"] == {"ok": True, "bad": False, "bad2": False, "none": True}
    assert out["sent"][0] == ["favorite_added", {"props": {"where": "area", "kind": "ski"}}] and out["sent"][1] == ["install", None]        # no id, name or e-mail: dropped
    assert out["san"] == {} and out["san2"] == {"where": "finder", "kind": "snotel"}


@pytest.mark.skipif(_node() is None, reason="node not installed")
def test_cloudflare_ignores_events_and_a_disabled_module_sends_nothing(tmp_path):
    out = run_js(tmp_path, """
const el = {setAttribute() {}, addEventListener() {}};
ctx.window = ctx; ctx.document = {createElement: () => el, head: {appendChild() {}}, addEventListener() {}, body: {dataset: {}}}; ctx.navigator = {};
const before = A.track('install');                                  // never initialised: nothing
const started = A.init({enabled: false, provider: 'plausible', site_id: 'x'}, [['install', {}]]);
const cf = A.init({enabled: true, provider: 'cloudflare', site_id: 't'}, []);
console.log(JSON.stringify({before, started, cf, ev: A.track('install')}));""")
    assert out == {"before": False, "started": False, "cf": True, "ev": False}
