"""Resilient HTTP fetcher for throttled public mirrors (dev19 Part 0/3): ECMWF open data and GEFS use it; other fetchers may adopt it (see docs/specs/data-pipeline.md "retry policy").

Why: the first live ECMWF run on a GitHub runner died on `HTTP 503 SlowDown` from the AWS mirror (the session's urllib3 retries raised `RetryError` after four quick attempts). Policy here:
  * a plain session WITHOUT urllib3 status retries (they hide the response and raise RetryError); every retry decision is ours and counted;
  * retry on 429/500/502/503/504 and on network errors (timeouts, resets, RetryError), at least `attempts` (default 8) tries, exponential backoff with FULL JITTER
    (random between half and the whole of min(cap, base * 2^k)), `Retry-After` (seconds or HTTP date) honoured up to `retry_after_cap`, and a TOTAL time cap per request (`max_total_s`);
  * adaptive throttling: a throttled answer opens a global cool-down that every worker honours and halves the allowed concurrency (it recovers after a run of successes);
    a modest global pacing (`min_interval` between request starts) applies always;
  * mirror failover with a per-run circuit breaker: after `trip_after` CONSECUTIVE failures on the current mirror the run switches to the next mirror for the rest of the run;
    each mirror may carry its own concurrency cap (the ECMWF portal asks for few connections); `stats()` records the mirror used, retries, switches and status counts;
  * 404 is an answer, not a failure: `get` returns None, `head` returns the response.
Pure logic is testable against a local fake HTTP server (tests/test_fetch_resilient.py); `sleep`, `clock` and `rng` are injectable.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

import requests
from requests.adapters import HTTPAdapter

log = logging.getLogger("snow-wx.fetch")
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
OK_STATUS = frozenset({200, 206})


class FetchError(RuntimeError):
    """a request that still failed after every retry / failover / the time cap"""


@dataclass
class Mirror:
    name: str
    base: str
    max_conc: int | None = None          # connections allowed at once on this mirror (None = the fetcher's worker count)


def plain_session(session=None) -> requests.Session:
    """a session with no urllib3 status retries; carries over the User-Agent of `session` when one is given. A non-requests object (a test fake) is returned unchanged."""
    if session is not None and not isinstance(session, requests.Session):
        return session
    s = requests.Session()
    for prefix in ("https://", "http://"):
        s.mount(prefix, HTTPAdapter(max_retries=0, pool_connections=8, pool_maxsize=16))
    if session is not None and getattr(session, "headers", None):
        s.headers.update(session.headers)
    return s


def retry_after_seconds(value, now=None) -> float | None:
    """Retry-After header (delta seconds or an HTTP date) -> seconds to wait, None if absent or unreadable"""
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        pass
    try:
        t = parsedate_to_datetime(str(value))
        import datetime as _dt
        ref = now or _dt.datetime.now(_dt.timezone.utc)
        return max(0.0, (t - ref).total_seconds())
    except (TypeError, ValueError):
        return None


class Fetcher:
    def __init__(self, mirrors: list[Mirror], *, session=None, attempts: int = 8, backoff: float = 1.0, backoff_cap: float = 30.0, max_total_s: float = 300.0,
                 trip_after: int = 6, workers: int = 3, min_interval: float = 0.03, retry_after_cap: float = 60.0, timeout: float = 60.0, sleep=None, clock=None,
                 rng: random.Random | None = None, headers: dict | None = None):
        if not mirrors:
            raise ValueError("at least one mirror")
        self.mirrors = list(mirrors)
        self.session = plain_session(session)
        self.attempts, self.backoff, self.backoff_cap, self.max_total_s = max(1, attempts), backoff, backoff_cap, max_total_s
        self.trip_after, self.min_interval, self.retry_after_cap, self.timeout = trip_after, min_interval, retry_after_cap, timeout
        self.workers = max(1, workers)
        self._sleep = sleep or (lambda s: time.sleep(s))                       # looked up at call time: tests patch time.sleep
        self._clock = clock or time.monotonic
        self._rng = rng or random.Random()
        self.headers = dict(headers or {})
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._cur = 0
        self._consec: dict[str, int] = {m.name: 0 for m in self.mirrors}
        self._tripped: set[str] = set()
        self._active = 0
        self._cap = self.workers                                               # adaptive concurrency (>= 1)
        self._ok_streak = 0
        self._cool_until = 0.0
        self._next_start = 0.0
        self.retries = 0
        self.requests = 0
        self.status_counts: dict[str, int] = {}
        self.used: dict[str, int] = {m.name: 0 for m in self.mirrors}
        self.switches: list[dict] = []

    # ------------------------------------------------------------------ state
    @property
    def mirror(self) -> Mirror:
        return self.mirrors[self._cur]

    def stats(self) -> dict:
        with self._lock:
            return {"mirror": self.mirrors[self._cur].name, "mirrors_used": {k: v for k, v in self.used.items() if v}, "requests": self.requests, "retries": self.retries,
                    "switches": list(self.switches), "status_counts": dict(sorted(self.status_counts.items())), "concurrency_now": self._cap}

    def _count(self, key: str) -> None:
        self.status_counts[key] = self.status_counts.get(key, 0) + 1

    def _note_failure(self, mirror: Mirror, reason: str) -> None:
        """per-run circuit breaker: `trip_after` consecutive failures on the current mirror switch the rest of the run to the next one"""
        self._consec[mirror.name] += 1
        if self._consec[mirror.name] >= self.trip_after and self.mirrors[self._cur].name == mirror.name:
            self._tripped.add(mirror.name)
            nxt = next((i for i, m in enumerate(self.mirrors) if m.name not in self._tripped), None)
            if nxt is None:                                                    # every mirror tripped once: start a new round, rotating on
                self._tripped = {mirror.name}
                nxt = (self._cur + 1) % len(self.mirrors)
            if nxt != self._cur:
                self.switches.append({"from": mirror.name, "to": self.mirrors[nxt].name, "reason": reason, "after_requests": self.requests})
                log.warning("fetch: %d consecutive failures on %s (%s): switching to %s for the rest of the run", self._consec[mirror.name], mirror.name, reason, self.mirrors[nxt].name)
                self._cur = nxt
            self._consec[mirror.name] = 0

    def _throttled(self, wait: float) -> None:
        """a throttled answer: a global cool-down every worker honours, and half the concurrency (never below 1)"""
        self._cool_until = max(self._cool_until, self._clock() + wait)
        self._cap = max(1, self._cap // 2)
        self._ok_streak = 0

    def _success(self, mirror: Mirror) -> None:
        self._consec[mirror.name] = 0
        self.used[mirror.name] += 1
        self._ok_streak += 1
        if self._ok_streak >= 25 and self._cap < self.workers:                  # recover slowly
            self._cap += 1
            self._ok_streak = 0

    # ------------------------------------------------------------------ gating
    def _acquire(self, mirror: Mirror) -> None:
        with self._cond:
            while True:
                limit = min(self._cap, mirror.max_conc or self.workers)
                now = self._clock()
                wait = max(self._cool_until - now, self._next_start - now)
                if self._active < limit and wait <= 0:
                    self._active += 1
                    self._next_start = now + self.min_interval
                    self.requests += 1
                    return
                self._cond.wait(timeout=max(0.01, min(wait, 0.25)) if wait > 0 else 0.05)

    def _release(self) -> None:
        with self._cond:
            self._active -= 1
            self._cond.notify_all()

    # ------------------------------------------------------------------ requests
    def _delay(self, attempt: int, response) -> float:
        ra = retry_after_seconds(response.headers.get("Retry-After")) if response is not None and getattr(response, "headers", None) else None
        if ra is not None:
            return min(ra, self.retry_after_cap)
        top = min(self.backoff_cap, self.backoff * (2 ** attempt))
        return self._rng.uniform(top / 2, top)                                  # full jitter within [top/2, top]

    def _request(self, method: str, rel: str, headers: dict | None):
        t0 = self._clock()
        last = "no attempt"
        for attempt in range(self.attempts):
            with self._lock:
                m = self.mirrors[self._cur]
            self._acquire(m)
            resp, err = None, None
            try:
                h = {**self.headers, **(headers or {})}
                fn = self.session.get if method == "GET" else self.session.head
                resp = fn(m.base.rstrip("/") + "/" + rel.lstrip("/"), headers=h, timeout=self.timeout)
            except requests.RequestException as exc:                            # timeouts, resets, RetryError from a foreign adapter ...
                err = f"{type(exc).__name__}"
            except OSError as exc:
                err = f"{type(exc).__name__}"
            finally:
                self._release()
            with self._lock:
                if resp is not None:
                    code = resp.status_code
                    self._count(str(code))
                    if code == 404:                                             # a 404 is a normal answer (the file is not there), never a failure
                        self._success(m)
                        return None if method == "GET" else resp
                    if code in OK_STATUS or (code < 400 and code not in RETRY_STATUS):
                        self._success(m)
                        return resp
                    if code not in RETRY_STATUS:                                # 4xx other than 429: not retryable
                        raise FetchError(f"{rel}: HTTP {code} from {m.name}")
                    last = f"HTTP {code} from {m.name}"
                else:
                    self._count("error")
                    last = f"{err} from {m.name}"
                delay = self._delay(attempt, resp)
                self.retries += 1
                if resp is None or resp.status_code in (429, 503):
                    self._throttled(min(delay, self.retry_after_cap))
                self._note_failure(m, last)
            if attempt == self.attempts - 1:
                break                                                           # out of attempts: no pointless sleep
            if self._clock() - t0 + delay > self.max_total_s:
                raise FetchError(f"{rel}: gave up after {attempt + 1} attempts / {self._clock() - t0:.0f} s ({last})")
            self._sleep(delay)
        raise FetchError(f"{rel}: {self.attempts} attempts failed ({last})")

    def get(self, rel: str, headers: dict | None = None):
        """200/206 response, or None on 404; FetchError after every retry/failover/time cap"""
        return self._request("GET", rel, headers)

    def head(self, rel: str):
        """the response (any non-retryable status, 404 included); FetchError when throttling/outage outlasts the policy"""
        return self._request("HEAD", rel, None)
