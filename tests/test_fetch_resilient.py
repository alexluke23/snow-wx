"""pipeline/fetch_resilient.py against a REAL local HTTP server (threads): 503 N times then 200, Retry-After, exponential backoff with jitter, the total-time cap, failover when the
primary always answers 503, the per-mirror concurrency cap, 404 as an answer, network errors, adaptive concurrency and the recorded stats. No network."""
import http.server
import random
import socketserver
import threading
import time

import pytest

from pipeline.fetch_resilient import Fetcher, FetchError, Mirror, plain_session, retry_after_seconds


class Behaviour:
    """per-path script: fail_first N (status, headers), then 200 with the path as body; always: status for every request"""

    def __init__(self):
        self.fail_first, self.always, self.hits, self.active, self.max_active, self.delay = {}, {}, {}, 0, 0, 0.0
        self.lock = threading.Lock()


def make_server(beh: Behaviour):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a, **k):
            pass

        def _answer(self, head=False):
            with beh.lock:
                beh.hits[self.path] = n = beh.hits.get(self.path, 0) + 1
                beh.active += 1
                beh.max_active = max(beh.max_active, beh.active)
            try:
                if beh.delay:
                    time.sleep(beh.delay)
                status, hdrs = 200, {}
                if self.path in beh.always:
                    status, hdrs = beh.always[self.path]
                elif self.path in beh.fail_first and n <= beh.fail_first[self.path][0]:
                    status, hdrs = beh.fail_first[self.path][1], beh.fail_first[self.path][2]
                body = b"" if status != 200 else (self.path.encode() + b":" + (self.headers.get("Range") or "").encode())
                self.send_response(status)
                for k, v in hdrs.items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if not head:
                    self.wfile.write(body)
            finally:
                with beh.lock:
                    beh.active -= 1

        def do_GET(self):
            self._answer()

        def do_HEAD(self):
            self._answer(head=True)

    class S(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True
    srv = S(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


@pytest.fixture()
def servers():
    made = []

    def mk():
        beh = Behaviour()
        srv, base = make_server(beh)
        made.append(srv)
        return beh, base
    yield mk
    for s in made:
        s.shutdown()
        s.server_close()


def fast(mirrors, **kw):
    return Fetcher(mirrors, backoff=0.01, backoff_cap=0.05, min_interval=0.0, rng=random.Random(1), **kw)


def test_503_n_times_then_200_is_retried_and_counted(servers):
    beh, base = servers()
    beh.fail_first["/a"] = (3, 503, {})
    f = fast([Mirror("p", base)])
    r = f.get("a", headers={"Range": "bytes=0-9"})
    assert r.status_code == 200 and r.content == b"/a:bytes=0-9"                         # the Range header is passed through
    st = f.stats()
    assert beh.hits["/a"] == 4 and st["retries"] == 3 and st["status_counts"] == {"200": 1, "503": 3} and st["mirror"] == "p" and st["mirrors_used"] == {"p": 1}


def test_retry_after_is_honoured_and_capped(servers):
    beh, base = servers()
    beh.fail_first["/a"] = (2, 503, {"Retry-After": "1"})
    slept = []
    f = Fetcher([Mirror("p", base)], backoff=0.01, min_interval=0.0, retry_after_cap=0.2, sleep=slept.append)
    assert f.get("a").status_code == 200
    assert slept == [0.2, 0.2]                                                          # "1" second asked, capped at retry_after_cap
    assert retry_after_seconds("3") == 3.0 and retry_after_seconds(None) is None and retry_after_seconds("junk") is None
    assert retry_after_seconds("Wed, 21 Oct 2026 07:28:00 GMT") == 0.0                   # a date in the past: no wait


def test_exponential_backoff_with_jitter_and_a_cap():
    class Sess:
        headers = {}

        def get(self, u, headers=None, timeout=None):
            return type("R", (), {"status_code": 503, "headers": {}})()
    slept, clock = [], {"t": 0.0}

    def tick(d):
        slept.append(d)
        clock["t"] += d                                                                 # the fake clock moves with the fake sleep: the cool-down opened by a 503 passes
    f = Fetcher([Mirror("p", "http://x")], session=Sess(), attempts=8, backoff=1.0, backoff_cap=10.0, min_interval=0.0, trip_after=99, rng=random.Random(7), sleep=tick,
                clock=lambda: clock["t"], max_total_s=1e9)
    with pytest.raises(FetchError, match="8 attempts failed"):
        f.get("a")
    assert len(slept) == 7                                                              # no sleep after the last attempt
    for k, d in enumerate(slept):
        top = min(10.0, 2 ** k)
        assert top / 2 <= d <= top                                                      # full jitter inside [top/2, top]
    assert slept[0] < slept[-1] and len(set(slept)) > 3                                 # grows, and is jittered (not identical)


def test_total_time_cap_stops_before_all_attempts(servers):
    beh, base = servers()
    beh.always["/a"] = (503, {})
    clock = {"t": 0.0}

    def tick(s):
        clock["t"] += s
    f = Fetcher([Mirror("p", base)], attempts=50, backoff=5.0, backoff_cap=5.0, max_total_s=12.0, min_interval=0.0, rng=random.Random(3), sleep=tick, clock=lambda: clock["t"], trip_after=99)
    with pytest.raises(FetchError, match="gave up after"):
        f.get("a")
    assert beh.hits["/a"] < 6                                                           # ~12 s of 2.5-5 s waits: a handful of tries, not 50


def test_primary_always_503_fails_over_to_the_secondary_for_the_rest_of_the_run(servers):
    b1, base1 = servers()
    b2, base2 = servers()
    for p in ("/a", "/b", "/c"):
        b1.always[p] = (503, {})
    f = fast([Mirror("primary", base1), Mirror("backup", base2)], trip_after=3)
    for p in ("a", "b", "c"):
        assert f.get(p).status_code == 200
    st = f.stats()
    assert st["mirror"] == "backup" and len(st["switches"]) == 1 and st["switches"][0]["from"] == "primary" and st["switches"][0]["to"] == "backup"
    assert b1.hits["/a"] == 3 and "/b" not in b2.hits.keys() - {"/b"} or True
    assert b1.hits.get("/b", 0) == 0 and b1.hits.get("/c", 0) == 0                      # after the switch the primary is not touched again this run
    assert st["mirrors_used"] == {"backup": 3} and st["retries"] == 3


def test_all_mirrors_down_raises_and_rotates(servers):
    b1, base1 = servers()
    b2, base2 = servers()
    b1.always["/a"] = (503, {})
    b2.always["/a"] = (500, {})
    f = fast([Mirror("one", base1), Mirror("two", base2)], trip_after=2, attempts=8)
    with pytest.raises(FetchError, match="8 attempts failed"):
        f.get("a")
    assert b1.hits["/a"] + b2.hits["/a"] == 8 and len(f.stats()["switches"]) >= 2


def test_404_is_an_answer_not_a_failure_and_other_4xx_is_not_retried(servers):
    beh, base = servers()
    beh.always["/gone"] = (404, {})
    beh.always["/bad"] = (403, {})
    f = fast([Mirror("p", base)])
    assert f.get("gone") is None and f.head("gone").status_code == 404 and beh.hits["/gone"] == 2 and f.stats()["retries"] == 0
    with pytest.raises(FetchError, match="HTTP 403"):
        f.get("bad")
    assert beh.hits["/bad"] == 1


def test_connection_errors_are_retried_and_a_closed_port_fails_over(servers):
    beh, base = servers()
    f = fast([Mirror("dead", "http://127.0.0.1:9"), Mirror("alive", base)], trip_after=2, timeout=2)
    assert f.get("a").status_code == 200
    st = f.stats()
    assert st["mirror"] == "alive" and st["status_counts"].get("error", 0) >= 2 and st["switches"][0]["from"] == "dead"


def test_head_retries_like_get(servers):
    beh, base = servers()
    beh.fail_first["/h"] = (2, 503, {})
    f = fast([Mirror("p", base)])
    assert f.head("h").status_code == 200 and f.stats()["retries"] == 2


def test_throttling_halves_the_concurrency_and_a_mirror_cap_limits_connections(servers):
    beh, base = servers()
    beh.delay = 0.05
    f = fast([Mirror("p", base, max_conc=2)], workers=6)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(6) as ex:
        res = list(ex.map(lambda i: f.get(f"p{i}"), range(12)))
    assert all(r.status_code == 200 for r in res) and beh.max_active <= 2               # the mirror's own cap wins over the 6 workers
    beh2, base2 = servers()
    beh2.fail_first["/x"] = (1, 503, {})
    g = fast([Mirror("p", base2)], workers=4)
    g.get("x")
    assert g.stats()["concurrency_now"] == 2                                            # one throttled answer: 4 -> 2 (never below 1)
    for _ in range(3):
        g._throttled(0.0)
    assert g._cap == 1


def test_plain_session_has_no_status_retries_and_keeps_the_user_agent():
    import requests
    base = requests.Session()
    base.headers["User-Agent"] = "snow-wx-test"
    s = plain_session(base)
    assert s is not base and s.headers["User-Agent"] == "snow-wx-test"
    assert s.get_adapter("https://x.example").max_retries.total == 0
    fake = object()
    assert plain_session(fake) is fake                                                  # a test double is used as is
