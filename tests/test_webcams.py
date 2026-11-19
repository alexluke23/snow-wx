"""Webcam LINKS (dev18 Part 1, PLAN M10): schema, https only, no iframe / <img> / embed from webcam hosts anywhere in web/, every referenced area exists, the link
checker (offline, fakes), and the public data file. Link-out only: no embedding, hotlinking, caching or scraping."""
import json
import re
from pathlib import Path

import pytest

from pipeline import webcams as W

REPO = Path(__file__).resolve().parents[1]


def good():
    return {"areas": {"alta-ski-area": [
        {"label": "Alta webcams (resort site)", "url": "https://www.alta.com/weather", "type": "resort", "last_checked": "2026-11-18", "status": 200, "confidence": "low"},
        {"label": "UDOT road cameras", "url": "https://udottraffic.utah.gov/", "type": "dot", "last_checked": "2026-11-18"}]}}


# ---------------------------------------------------------------- the real config
def test_the_real_config_is_valid_and_covers_the_major_areas():
    doc = W.load()
    ids = W.area_ids()
    assert W.validate(doc, ids) == []
    major = {a["id"] for a in json.loads((REPO / "data" / "ski_areas.json").read_text(encoding="utf-8"))["areas"] if a.get("major")}
    assert major <= set(doc["areas"]), f"major areas without a webcam entry: {sorted(major - set(doc['areas']))}"
    assert len(doc["areas"]) >= 60
    for aid, items in doc["areas"].items():
        assert 1 <= len(items) <= W.MAX_PER_AREA
    low = [(a, e["url"]) for a, items in doc["areas"].items() for e in items if e.get("confidence") == "low"]
    assert all(e.get("status") == 200 and e.get("last_checked") for items in doc["areas"].values() for e in items if e.get("confidence", "high") == "high")
    assert len(low) < len(doc["areas"])                                                     # the low-confidence list is the short exception, not the rule


def test_every_url_is_https_and_a_page_not_a_picture_or_stream():
    for aid, items in W.load()["areas"].items():
        for e in items:
            assert e["url"].startswith("https://") and not W.MEDIA.search(e["url"]), (aid, e["url"])


# ---------------------------------------------------------------- schema validation
def test_valid_document_passes_and_public_view_has_only_safe_fields():
    assert W.validate(good(), {"alta-ski-area"}) == []
    pub = W.public(good())
    assert pub == {"alta-ski-area": [{"label": "Alta webcams (resort site)", "url": "https://www.alta.com/weather", "type": "resort", "host": "alta.com"},
                                      {"label": "UDOT road cameras", "url": "https://udottraffic.utah.gov/", "type": "dot", "host": "udottraffic.utah.gov"}]}


@pytest.mark.parametrize("mutate,needle", [
    (lambda e: e.update(url="http://www.alta.com/weather"), "must be https"),
    (lambda e: e.update(url="https://user:pw@www.alta.com/weather"), "credentials"),
    (lambda e: e.update(url="https://www.alta.com/cam/live.jpg"), "picture/stream file"),
    (lambda e: e.update(url="https://www.alta.com/cam/stream.m3u8"), "picture/stream file"),
    (lambda e: e.update(url="https://192.168.1.5/cam"), "IP address"),
    (lambda e: e.update(type="private"), "type must be one of"),
    (lambda e: e.update(last_checked="yesterday"), "last_checked"),
    (lambda e: e.update(label="x"), "label must be 3-60"),
    (lambda e: e.update(confidence="sure"), "confidence"),
    (lambda e: e.update(status="ok"), "status must be an integer"),
    (lambda e: e.pop("url"), "url missing"),
])
def test_invalid_entries_are_reported(mutate, needle):
    doc = good()
    mutate(doc["areas"]["alta-ski-area"][0])
    errs = W.validate(doc, {"alta-ski-area"})
    assert any(needle in e for e in errs), errs


def test_unknown_area_too_many_links_duplicates_and_empty_documents():
    doc = good()
    assert any("not a known area" in e for e in W.validate(doc, {"other"}))
    doc["areas"]["alta-ski-area"] += [dict(doc["areas"]["alta-ski-area"][0]), dict(doc["areas"]["alta-ski-area"][1], url="https://x.example/a"), dict(doc["areas"]["alta-ski-area"][1], url="https://x.example/b")]
    errs = W.validate(doc, {"alta-ski-area"})
    assert any("max 3" in e for e in errs) and any("duplicate url" in e for e in errs)
    assert W.validate({}, None) and W.validate({"areas": {"a": []}}, None)


def test_write_public_refuses_an_invalid_config_and_writes_a_valid_one(tmp_path):
    bad = good()
    bad["areas"]["alta-ski-area"][0]["url"] = "http://insecure.example/"
    with pytest.raises(ValueError, match="invalid"):
        W.write_public(tmp_path / "w.json", bad)
    assert not (tmp_path / "w.json").exists()
    assert W.write_public(tmp_path / "w.json", good()) == 1 and json.loads((tmp_path / "w.json").read_text(encoding="utf-8"))["alta-ski-area"][0]["host"] == "alta.com"


# ---------------------------------------------------------------- nothing is embedded, hotlinked or cached
def test_no_iframe_embed_or_image_from_a_webcam_host_anywhere_in_the_site():
    hosts = {W.host_of(e["url"]) for items in W.load()["areas"].values() for e in items}
    offenders = []
    for p in list((REPO / "web").glob("*.html")) + list((REPO / "web" / "js").glob("*.js")):
        txt = p.read_text(encoding="utf-8")
        if re.search(r"<iframe|<embed|<object|<video\b", txt, re.I):
            offenders.append(f"{p.name}: iframe/embed/video")
        for h in hosts:
            if re.search(r"(src|srcset|poster|data)\s*=\s*[\"'`]?https?://[^\"'`> ]*" + re.escape(h), txt, re.I):
                offenders.append(f"{p.name}: loads {h}")
    assert not offenders, offenders
    area = (REPO / "web" / "js" / "area.js").read_text(encoding="utf-8")
    row = area[area.index("function webcamRow"):area.index("const safeUrl")]
    assert "<img" not in row and "iframe" not in row and 'rel="noopener noreferrer"' in row and 'target="_blank"' in row and "slice(0, 3)" in row


def test_the_service_worker_never_caches_webcam_pages():
    sw = (REPO / "pipeline" / "pwa_sw.js").read_text(encoding="utf-8")
    assert "webcam" not in sw.lower()


# ---------------------------------------------------------------- the link checker, offline
class R:
    def __init__(self, status=200, url=None):
        self.status_code, self.url, self.closed = status, url, False

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def _ans(self, kind, url):
        self.calls.append((kind, url))
        r = self.routes.get((kind, url)) or self.routes.get(url)
        if isinstance(r, Exception):
            raise r
        return r if r is not None else R(200, url)

    def head(self, url, **k):
        return self._ans("HEAD", url)

    def get(self, url, **k):
        assert k.get("stream") is True, "a GET must never download the body"
        return self._ans("GET", url)


def test_check_url_head_first_and_get_only_when_head_is_refused():
    s = FakeSession({})
    assert W.check_url(s, "https://a.example/cams")["status"] == 200 and s.calls == [("HEAD", "https://a.example/cams")]
    s = FakeSession({("HEAD", "https://a.example/cams"): R(405, "https://a.example/cams"), ("GET", "https://a.example/cams"): R(200, "https://a.example/cams")})
    r = W.check_url(s, "https://a.example/cams")
    assert r["status"] == 200 and [c[0] for c in s.calls] == ["HEAD", "GET"]


def test_a_site_error_page_behind_a_redirect_is_a_dead_link_unless_get_works():
    u = "https://a.example/four-mountains/cams"
    err = "https://a.example/errors/error?aspxerrorpath=/four-mountains/cams"
    s = FakeSession({("HEAD", u): R(200, err), ("GET", u): R(200, u)})                          # HEAD is mishandled, GET is fine -> alive
    assert W.check_url(s, u)["status"] == 200
    s = FakeSession({("HEAD", u): R(200, err), ("GET", u): R(200, err)})                        # both end on the error page -> dead
    r = W.check_url(s, u)
    assert r["status"] == 404 and "error page" in r["error"]


def test_network_errors_are_reported_not_raised_and_the_report_flags_dead_links(tmp_path):
    doc = good()
    s = FakeSession({"https://www.alta.com/weather": R(404, "https://www.alta.com/weather"), "https://udottraffic.utah.gov/": RuntimeError("boom")})
    rows = W.check_all(doc, s, pause=0, sleep=lambda x: None)
    assert [r["ok"] for r in rows] == [False, False] and rows[1]["error"].startswith("RuntimeError") and rows[0]["status"] == 404
    out = W.apply_report(doc, rows, today="2026-11-20")
    first = out["areas"]["alta-ski-area"][0]
    assert first["status"] == 404 and first["confidence"] == "low" and first["last_checked"] == "2026-11-18"        # a dead link keeps its old date


def test_good_links_get_status_and_todays_date_and_the_pause_per_host_is_honoured():
    doc = good()
    doc["areas"]["alta-ski-area"].append({"label": "More Alta", "url": "https://www.alta.com/other", "type": "resort", "last_checked": "2026-11-01"})
    sleeps = []
    rows = W.check_all(doc, FakeSession({}), pause=1.0, sleep=sleeps.append)
    assert len(rows) == 3 and all(r["ok"] for r in rows) and len(sleeps) == 1 and 0 < sleeps[0] <= 1.0      # only the second alta.com request waits
    out = W.apply_report(doc, rows, today="2026-11-20")
    assert [e["last_checked"] for e in out["areas"]["alta-ski-area"]] == ["2026-11-20"] * 3 and out["areas"]["alta-ski-area"][2]["status"] == 200


def test_run_check_exit_codes_and_roundtrip(tmp_path, monkeypatch):
    cfg = tmp_path / "webcams.yml"
    W.dump(good(), cfg)
    monkeypatch.setattr(W, "area_ids", lambda *a, **k: {"alta-ski-area"})
    monkeypatch.setattr(W.time, "sleep", lambda s: None)
    assert W.run_check(True, FakeSession({}), tmp_path / "rep.json", path=cfg) == 0
    assert json.loads((tmp_path / "rep.json").read_text(encoding="utf-8"))[0]["ok"] is True
    assert W.load(cfg)["areas"]["alta-ski-area"][0]["status"] == 200 and cfg.read_text(encoding="utf-8").startswith("# Webcam LINKS")
    assert W.run_check(False, FakeSession({"https://www.alta.com/weather": R(500, "x")}), None, path=cfg) == 1       # a dead link -> exit 1
    cfg.write_text("areas: {nope: []}", encoding="utf-8")
    assert W.run_check(False, FakeSession({}), None, path=cfg) == 2                                                  # invalid config -> exit 2, no requests
