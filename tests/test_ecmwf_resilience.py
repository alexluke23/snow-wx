"""ECMWF job resilience (dev19 Part 0), end to end against a REAL local HTTP server that imitates the mirrors: 503 N times then 200, a primary that always answers 503 while the
secondary works, lost steps (partial plume drawn with gaps and labelled, partial release tag), too many lost steps (exit 0, new=false, nothing written), resume from the per-cycle
cache, cache invalidation, and the fetch health fields written to index.json. No network, no eccodes (decode is patched)."""
import http.server
import json
import re
import socketserver
import threading
from datetime import datetime, timezone

import numpy as np
import pytest

from pipeline import ecmwf as E
from pipeline.version import stamp

CYC = datetime(2026, 11, 18, 0, tzinfo=timezone.utc)
PTS = [{"id": "alta", "lat": 40.57, "lon": -111.63, "elev_ft": 10556}]
MEMBERS = 6
MAXH = 144                                                                              # 24 planned steps: fast, and 90 % = 22 steps
IDX_RX = re.compile(r"/(\d{8})/(\d\d)z/(?:ifs|aifs-single)/0p25/(oper|enfo)/\d+-(\d+)h-[a-z-]+\.(index|grib2)$")


class FakeMirror:
    """serves .index (JSON lines) and byte ranges; `rules` = list of (predicate(path, hit_number) -> status | None); counts every request by kind"""

    def __init__(self):
        self.rules, self.hits, self.lock, self.paths = [], {}, threading.Lock(), []
        h = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a, **k):
                pass

            def _go(self, head=False):
                with h.lock:
                    h.hits[self.path] = n = h.hits.get(self.path, 0) + 1
                    h.paths.append(self.path)
                for rule in h.rules:
                    st = rule(self.path, n)
                    if st:
                        self.send_response(st)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                m = IDX_RX.search(self.path)
                if not m:
                    self.send_response(404), self.send_header("Content-Length", "0"), self.end_headers()
                    return
                step, stream, ext = int(m.group(4)), m.group(3), m.group(5)
                if ext == "index":
                    rows, off = [], 0
                    if stream == "oper":
                        for p in ("tp", "sf") + (("z",) if step == 0 else ()):
                            rows.append({"type": "fc", "levtype": "sfc", "step": str(step), "param": p, "_offset": off, "_length": 10})
                            off += 10
                    else:
                        for p in ("tp", "sf"):
                            for k in range(1, MEMBERS + 1):
                                rows.append({"type": "pf", "levtype": "sfc", "number": str(k), "step": str(step), "param": p, "_offset": off, "_length": 10})
                                off += 10
                    body = "\n".join(json.dumps(r) for r in rows).encode()
                else:
                    body = b"G" * 10
                self.send_response(200 if ext == "index" else 206)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if not head:
                    self.wfile.write(body)

            def do_GET(self):
                self._go()

            def do_HEAD(self):
                self._go(head=True)

        class S(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True
        self.srv = S(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.srv.server_address[1]}"

    def count(self, pattern: str) -> int:
        return sum(1 for p in self.paths if re.search(pattern, p))

    def close(self):
        self.srv.shutdown()
        self.srv.server_close()


@pytest.fixture()
def mirrors():
    made = []

    def mk():
        m = FakeMirror()
        made.append(m)
        return m
    yield mk
    for m in made:
        m.close()


@pytest.fixture(autouse=True)
def no_repo_cache(monkeypatch, tmp_path):
    """dev20: a run without cache_dir must never write the REAL data_cache/ecmwf (mirror preference, pruning)"""
    monkeypatch.setattr(E, "REPO_ROOT", tmp_path / "repo")


@pytest.fixture(autouse=True)
def quick(monkeypatch):
    monkeypatch.setitem(E.DEFAULTS, "min_interval_s", 0.0)
    monkeypatch.setitem(E.DEFAULTS, "backoff_s", 0.001)
    monkeypatch.setattr(E, "decode", lambda blob: np.full((721, 1440), 0.002, dtype="float32"))


def go(tmp_path, bases, cache=None, published=None, out="o", points=None, **extra):
    cfg = {"ecmwf": {"enabled": True, "max_step_h": MAXH, "workers": 3, "attempts": 4, "trip_after": 2, "max_request_s": 30,
                     "mirrors": [{"name": n, "base": b} for n, b in bases], **extra}}
    gh = tmp_path / "gh.txt"
    res = E.run(cfg, None, tmp_path / out, cycle=CYC, points=points or PTS, github_output=str(gh), cache_dir=cache if cache is not None else False, published=published)
    return res, gh.read_text(encoding="utf-8") if gh.exists() else ""


def plume(tmp_path, out="o"):
    return json.loads((tmp_path / out / "ecmwf" / "plume" / "alta.json").read_text(encoding="utf-8"))


def test_503_a_few_times_then_200_the_run_completes_and_reports_retries(tmp_path, mirrors):
    m = mirrors()
    m.rules.append(lambda p, n: 503 if (p.endswith("-12h-enfo-ef.index") and n <= 3) or (p.endswith("-30h-oper-fc.grib2") and n <= 2) else None)
    res, gh = go(tmp_path, [("aws", m.base)])
    assert res["ok"] and res["steps_missing"] == [] and res["fetch"]["retries"] >= 5 and res["fetch"]["mirror"] == "aws" and res["fetch"]["status_counts"]["503"] >= 5
    assert "new=true" in gh and f"cycle={stamp('2026111800', 'ecmwf')}" in gh and res["partial"] is False
    assert plume(tmp_path)["steps_missing"] == [] and plume(tmp_path)["n_members"] == MEMBERS


def test_a_throttled_answer_is_followed_by_a_backoff_wait_in_a_real_run(tmp_path, mirrors, monkeypatch):
    m = mirrors()
    m.rules.append(lambda p, n: 503 if p.endswith("-6h-enfo-ef.index") and n == 1 else None)
    slept = []
    monkeypatch.setattr(E.time, "sleep", slept.append)
    res, _ = go(tmp_path, [("aws", m.base)])
    assert res["ok"] and res["fetch"]["retries"] == 1 and len(slept) == 1                # one 503, one wait (no Retry-After header from this fake: jittered backoff)


def test_primary_always_503_the_secondary_serves_the_rest_of_the_run(tmp_path, mirrors):
    a, b = mirrors(), mirrors()
    a.rules.append(lambda p, n: 503)
    res, gh = go(tmp_path, [("aws", a.base), ("google", b.base)])
    f = res["fetch"]
    assert res["ok"] and f["mirror"] == "google" and f["switches"][0]["from"] == "aws" and f["switches"][0]["to"] == "google" and f["mirrors_used"].keys() == {"google"}
    assert a.count(r".") <= 4 and b.count(r"\.grib2") > 100                              # the primary was tried only until the breaker tripped
    assert "Mirror" not in res["source"] and "google" in res["source"]                    # the index records the mirror used


def test_one_lost_step_publishes_a_partial_plume_with_a_gap_and_a_partial_tag(tmp_path, mirrors):
    m = mirrors()
    m.rules.append(lambda p, n: 503 if "-138h-enfo-ef.index" in p else None)             # step 138 never comes: dropped for all members and HRES (a tail step, > 120 h)
    res, gh = go(tmp_path, [("aws", m.base)])
    assert res["ok"] and res["steps_missing"] == [138] and res["partial"] is True and res["fetch"]["steps_missing"] == [138]
    tag = stamp("2026111800", "ecmwf")
    assert f"cycle={E.partial_tag(tag)}" in gh and E.partial_tag(tag) != tag and re.fullmatch(r"\d{10}-[0-9a-f]{8}", E.partial_tag(tag))
    d = plume(tmp_path)
    i = d["hours"].index(138)
    assert d["steps_missing"] == [138] and all(v is None for v in d["tp"][i]) and all(v is not None for v in d["tp"][i - 1]) and d["hres_tp"][i] is None   # a gap, never interpolated
    assert json.loads((tmp_path / "o" / "ecmwf" / "precip.json").read_text(encoding="utf-8"))["areas"]["alta"]["q"][i] is None


def test_two_tail_steps_lost_is_still_enough_but_three_is_not_exit_0_new_false_nothing_written(tmp_path, mirrors):
    m = mirrors()
    m.rules.append(lambda p, n: 503 if re.search(r"-(132|138)h-enfo-ef\.index", p) else None)
    res, _ = go(tmp_path, [("aws", m.base)])
    assert res["ok"] and res["steps_missing"] == [132, 138]                                # 22 of 24 = 91.7 %: published as partial
    m2 = mirrors()
    m2.rules.append(lambda p, n: 503 if re.search(r"-(132|138|144)h-enfo-ef\.index", p) else None)
    res, gh = go(tmp_path, [("aws", m2.base)], out="o2")
    assert res["ok"] and res["skipped"] == "incomplete" and res["fetch"]["steps_missing"] == [132, 138, 144]       # 21 of 24 = 87.5 % < 90 %
    assert "new=false" in gh and not (tmp_path / "o2").exists()


def test_a_hole_in_the_first_120_hours_means_nothing_is_published(tmp_path, mirrors):
    m = mirrors()
    m.rules.append(lambda p, n: 503 if "-60h-enfo-ef.index" in p else None)              # 23 of 24 steps (96 %) but step 60 is inside the first 120 h
    res, gh = go(tmp_path, [("aws", m.base)])
    assert res["skipped"] == "incomplete" and res["fetch"]["steps_missing"] == [60] and "new=false" in gh and not (tmp_path / "o").exists()


def test_resume_the_next_attempt_reuses_the_cached_steps_and_completes_the_cycle(tmp_path, mirrors):
    cache = tmp_path / "cache"
    m = mirrors()
    m.rules.append(lambda p, n: 503 if "-60h-enfo-ef.index" in p else None)
    res1, _ = go(tmp_path, [("aws", m.base)], cache=cache)
    assert res1["skipped"] == "incomplete" and (cache / "ecmwf" / "2026111800" / "step_006.npz").exists() and not (cache / "ecmwf" / "2026111800" / "step_060.npz").exists()
    m2 = mirrors()                                                                         # the mirror recovered: a fresh server with nothing failing
    res2, gh = go(tmp_path, [("aws", m2.base)], cache=cache, published=None)
    assert res2["ok"] and res2["steps_missing"] == [] and res2["fetch"]["steps_cached"] == 23
    assert m2.count(r"-6h-enfo-ef\.grib2") == 0 and m2.count(r"-60h-enfo-ef\.grib2") == MEMBERS * 2 and f"cycle={stamp('2026111800', 'ecmwf')}" in gh   # only the missing step was downloaded
    res3, _ = go(tmp_path, [("aws", m2.base)], cache=cache, out="o3")                      # a third attempt: everything from the cache, no ensemble download at all
    assert res3["fetch"]["steps_cached"] == 24 and m2.count(r"-60h-enfo-ef\.grib2") == MEMBERS * 2


def test_a_partial_release_does_not_block_the_completing_attempt_but_a_full_one_does(tmp_path, mirrors):
    tag = stamp("2026111800", "ecmwf")
    m = mirrors()
    res, gh = go(tmp_path, [("aws", m.base)], published=E.partial_tag(tag))             # the partial asset is on the release: still run (and replace it)
    assert res["ok"] and "new=true" in gh and f"cycle={tag}" in gh
    res, gh = go(tmp_path, [("aws", m.base)], published=tag, out="o4")                    # the full asset: nothing to do
    assert res["skipped"] == "published" and "new=false" in gh and not (tmp_path / "o4").exists()


def test_the_cache_is_discarded_for_other_points_and_other_cycles_are_removed(tmp_path, mirrors):
    cache = tmp_path / "cache"
    m = mirrors()
    go(tmp_path, [("aws", m.base)], cache=cache)
    older, oldest = cache / "ecmwf" / "2026111712", cache / "ecmwf" / "2026111700"
    for d in (older, oldest):
        d.mkdir(parents=True)
        (d / "step_006.npz").write_bytes(b"x")
    other = [{"id": "alta", "lat": 41.0, "lon": -111.0, "elev_ft": 9000}]
    m2 = mirrors()
    res, _ = go(tmp_path, [("aws", m2.base)], cache=cache, points=other, out="o5")
    # dev20: the newest 2 cycles stay (the current one + the newest older one), anything older goes; sizes are reported
    assert res["fetch"]["steps_cached"] == 0 and m2.count(r"\.grib2") > 100 and older.exists() and not oldest.exists()
    assert "2026111700" in res["fetch"]["cache"]["pruned"] and set(res["fetch"]["cache"]["cycles"]) == {"2026111712", CYC.strftime("%Y%m%d%H")}


def test_everything_unreachable_is_exit_0_new_false_not_an_error(tmp_path, mirrors):
    m = mirrors()
    m.rules.append(lambda p, n: 503)
    res, gh = go(tmp_path, [("aws", m.base)])
    assert res["ok"] and res["skipped"] == "unreachable" and "new=false" in gh and not (tmp_path / "o").exists()


def test_index_json_carries_the_fetch_health_the_status_page_shows(tmp_path, mirrors):
    m = mirrors()
    m.rules.append(lambda p, n: 503 if (p.endswith("-12h-enfo-ef.index") and n == 1) else None)
    go(tmp_path, [("aws", m.base)])
    idx = json.loads((tmp_path / "o" / "ecmwf" / "index.json").read_text(encoding="utf-8"))
    assert idx["fetch"]["mirror"] == "aws" and idx["fetch"]["retries"] == 1 and idx["steps_missing"] == [] and idx["fetch"]["steps_planned"] == 24
    from pipeline.__main__ import ecmwf_status
    out = tmp_path / "site"
    (out / "models").mkdir(parents=True)
    import shutil
    shutil.copytree(tmp_path / "o" / "ecmwf", out / "models" / "ecmwf")
    st = ecmwf_status(out, {"ecmwf": {"enabled": True}})
    assert st["ok"] is True and "mirror aws" in st["detail"] and "1 retries" in st["detail"] and "0 of 24 steps missing" in st["detail"]
    assert {k: st["fetch"][k] for k in ("mirror", "retries", "steps_missing", "partial")} == {"mirror": "aws", "retries": 1, "steps_missing": [], "partial": False}
    assert st["fetch"]["preferred"] == "aws" and st["fetch"]["cache_mb"] == 0.0          # cache_dir=False in these tests: nothing stored


def test_status_detail_names_the_missing_steps(tmp_path, mirrors):
    m = mirrors()
    m.rules.append(lambda p, n: 503 if "-138h-enfo-ef.index" in p else None)
    go(tmp_path, [("aws", m.base)])
    from pipeline.__main__ import ecmwf_status
    import shutil
    out = tmp_path / "site"
    (out / "models").mkdir(parents=True)
    shutil.copytree(tmp_path / "o" / "ecmwf", out / "models" / "ecmwf")
    st = ecmwf_status(out, {"ecmwf": {"enabled": True}})
    assert "1 of 24 steps missing (138 h)" in st["detail"] and st["fetch"]["partial"] is True


def test_a_throttled_cycle_probe_is_exit_0_new_false_and_a_normal_probe_finds_the_cycle(tmp_path, mirrors):
    """newest_cycle goes through the same retries; a mirror that stays 503 means "cannot tell" (new=false), not a crash"""
    m = mirrors()
    m.rules.append(lambda p, n: 503)
    gh = tmp_path / "gh.txt"
    cfg = {"ecmwf": {"enabled": True, "max_step_h": MAXH, "attempts": 3, "trip_after": 9, "mirrors": [{"name": "aws", "base": m.base}]}}
    now = datetime(2026, 11, 18, 20, 30, tzinfo=timezone.utc)
    res = E.run(cfg, None, tmp_path / "o", points=PTS, now=now, github_output=str(gh), cache_dir=False)
    assert res["ok"] and res["skipped"] == "not-released" and "new=false" in gh.read_text(encoding="utf-8") and not (tmp_path / "o").exists()
    ok = mirrors()
    cfg["ecmwf"]["mirrors"] = [{"name": "aws", "base": ok.base}]
    c = E.configure(cfg)
    assert E.newest_cycle(E.make_fetcher(c, None), c, now) == datetime(2026, 11, 18, 12, tzinfo=timezone.utc)


# ---------------------------------------------------------------- dev20: mirror preference + cache bounds
def test_the_mirror_that_worked_is_remembered_and_tried_first_next_run(tmp_path, mirrors):
    bad, good = mirrors(), mirrors()
    bad.rules.append(lambda p, n: 503)
    cache = tmp_path / "cache"
    res, _ = go(tmp_path, [("aws", bad.base), ("google", good.base)], cache=cache)
    assert res["fetch"]["mirror"] == "google" and res["fetch"]["preferred_after"] == "google"
    pref = json.loads((cache / "ecmwf" / "mirror_pref.json").read_text(encoding="utf-8"))
    assert pref["mirror"] == "google" and pref["at"] and pref["probed_at"]
    n_bad = bad.count(".")
    (cache / "ecmwf" / CYC.strftime("%Y%m%d%H")).rename(cache / "ecmwf" / "x")          # force a full re-fetch
    import shutil
    shutil.rmtree(cache / "ecmwf" / "x")
    res2, _ = go(tmp_path, [("aws", bad.base), ("google", good.base)], cache=cache, out="o2")
    assert res2["fetch"]["first_mirror"] == "google" and not res2["fetch"]["probe"] and bad.count(".") == n_bad      # aws not touched at all


def test_order_mirrors_probes_the_others_once_a_day():
    from datetime import datetime, timezone
    from pipeline.fetch_resilient import Mirror
    ms = [Mirror("aws", "a"), Mirror("google", "g"), Mirror("ecmwf", "e")]
    now = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
    fresh = {"mirror": "google", "probed_at": "2026-11-20T00:00:00Z"}
    old = {"mirror": "google", "probed_at": "2026-11-19T11:00:00Z"}
    assert [m.name for m in E.order_mirrors(ms, fresh, now)[0]] == ["google", "aws", "ecmwf"] and E.order_mirrors(ms, fresh, now)[1] is False
    assert [m.name for m in E.order_mirrors(ms, old, now)[0]] == ["aws", "google", "ecmwf"] and E.order_mirrors(ms, old, now)[1] is True
    assert [m.name for m in E.order_mirrors(ms, {}, now)[0]] == ["aws", "google", "ecmwf"]
    assert [m.name for m in E.order_mirrors(ms, {"mirror": "gone"}, now)[0]] == ["aws", "google", "ecmwf"]


def test_a_preferred_mirror_that_fails_is_replaced_within_the_run(tmp_path, mirrors):
    from datetime import datetime, timezone
    bad, good = mirrors(), mirrors()
    bad.rules.append(lambda p, n: 503)
    cache = tmp_path / "cache"
    (cache / "ecmwf").mkdir(parents=True)
    (cache / "ecmwf" / "mirror_pref.json").write_text(json.dumps({"mirror": "google", "at": "x", "probed_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}), encoding="utf-8")
    res, _ = go(tmp_path, [("aws", good.base), ("google", bad.base)], cache=cache)
    assert res["ok"] and res["fetch"]["first_mirror"] == "google" and res["fetch"]["mirror"] == "aws" and res["fetch"]["preferred_after"] == "aws"


def test_nothing_worked_keeps_the_old_preference(tmp_path):
    from datetime import datetime, timezone
    old = {"mirror": "google", "at": "2026-11-19T00:00:00Z", "probed_at": "2026-11-19T00:00:00Z"}
    root = tmp_path / "ecmwf"
    out = E.save_pref(root, old, {"mirrors_used": {}}, datetime(2026, 11, 20, tzinfo=timezone.utc), True, "aws")
    assert out == old and not (root / "mirror_pref.json").exists()


def test_prune_cycles_bounds_the_total_size(tmp_path):
    root = tmp_path / "ecmwf"
    for name, mb in (("2026111800", 1), ("2026111812", 2), ("2026111900", 2)):
        (root / name).mkdir(parents=True)
        (root / name / "step_006.npz").write_bytes(b"x" * int(mb * 1e6))
    (root / "mirror_pref.json").write_text("{}", encoding="utf-8")
    assert E.prune_cycles(root, "2026111900", keep=2, max_mb=300) == ["2026111800"]
    assert sorted(d.name for d in root.iterdir()) == ["2026111812", "2026111900", "mirror_pref.json"]
    assert E.prune_cycles(root, "2026111900", keep=2, max_mb=3) == ["2026111812"]          # over the size cap: older cycles go, the current never
    assert E.cache_sizes(root)["cycles"] == {"2026111900": 2.0}
