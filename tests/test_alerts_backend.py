"""W6 alerts backend skeleton (pipeline/alerts_backend.py): offline, fakes only (MemoryStore, Outbox, fixed clock, fixed secret). Nothing is sent or deployed."""

from datetime import datetime, timedelta, timezone

import pytest

from pipeline import alerts_backend as AB

SECRET = b"test-secret-not-a-real-key-0123456789"
T0 = datetime(2026, 11, 18, 14, 0, tzinfo=timezone.utc)
CFG = {"alerts_backend": {"enabled": True, "postal_address": "Snow-Wx, 1 Example Way, Salt Lake City, UT 84101", "base_url": "https://example.test/alerts"}}


class Clock:
    def __init__(self, t=T0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


class Rng:                                         # deterministic ids
    n = 0

    def token_hex(self, _):
        Rng.n += 1
        return f"{Rng.n:016x}"


def mk(cfg=CFG, clock=None):
    clock = clock or Clock()
    return AB.Service(cfg, AB.MemoryStore(), SECRET, AB.Outbox(), clock, Rng()), clock


def token_from(msg: dict, key: str) -> str:
    return msg["text"].split(f"/{key}?t=")[1].split()[0]


def exceed(issued="2026-11-18T13:00Z", p=60, sl=4500, pop=80):
    """a minimal exceed_summary.json: one area, 24h windows ending 12Z on Nov 19 and Nov 20, thresholds 1/4/8/12"""
    return {"issued": issued, "windows": {"24h": {"start": ["2026-11-18T12:00Z", "2026-11-19T12:00Z", "2026-11-20T12:00Z"],
                                                   "end": ["2026-11-19T12:00Z", "2026-11-20T12:00Z", "2026-11-21T12:00Z"], "thr": [1.0, 4.0, 8.0, 12.0]}},
            "areas": {"alta-ski-area": {"summit": {"24h": [[90, 70, p, 10], [50, 20, 5, 1], [90, 70, p, 10]], "pop": {"24h": [pop, 40, pop]},
                                                   "sl": {"24h": [sl, 6000, sl]}}}}}


RULE = {"kind": "snow", "area": "alta-ski-area", "window": "24h", "thr_in": 8, "min_prob": 50}


def active_sub(svc, email="a@example.com", rules=(RULE,)):
    svc.subscribe(email, list(rules))
    msg = svc.out.sent[-1]
    assert svc.confirm(token_from(msg, "confirm"))["ok"]
    return svc.store.by_email(email)


# ---------------------------------------------------------------- flag
def test_everything_is_off_unless_the_flag_is_on():
    assert AB.DEFAULTS["enabled"] is False
    with pytest.raises(AB.Disabled):
        AB.Service({}, AB.MemoryStore(), SECRET, AB.Outbox())
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load((Path(__file__).resolve().parents[1] / "config" / "settings.yml").read_text(encoding="utf-8"))
    assert cfg["alerts_backend"]["enabled"] is False


# ---------------------------------------------------------------- tokens
def test_tokens_are_signed_purpose_bound_and_expire():
    tok = AB.sign_token(SECRET, "confirm", "sub1", T0, timedelta(hours=1))
    assert AB.verify_token(SECRET, tok, "confirm", T0 + timedelta(minutes=59)) == "sub1"
    with pytest.raises(AB.TokenError, match="expired"):
        AB.verify_token(SECRET, tok, "confirm", T0 + timedelta(hours=2))
    with pytest.raises(AB.TokenError, match="something else"):
        AB.verify_token(SECRET, tok, "unsub", T0)                        # a confirm link can never unsubscribe (or log in)
    v, p, m = tok.split(".")
    with pytest.raises(AB.TokenError):
        AB.verify_token(SECRET, f"{v}.{p}.{m[:-2]}xx", "confirm", T0)    # tampered MAC
    with pytest.raises(AB.TokenError):
        AB.verify_token(b"other-secret", tok, "confirm", T0)
    for junk in ("", "x", "v1.a.b", "v2.a.b", "v1..", None):
        with pytest.raises(AB.TokenError):
            AB.verify_token(SECRET, junk, "confirm", T0)
    assert AB.verify_token([b"new", SECRET], tok, "confirm", T0) == "sub1"      # secret rotation: the old key still verifies
    forever = AB.sign_token(SECRET, "unsub", "sub1", T0)
    assert AB.verify_token(SECRET, forever, "unsub", T0 + timedelta(days=3650)) == "sub1"      # unsubscribe links never expire


# ---------------------------------------------------------------- double opt-in
def test_nothing_but_the_confirmation_goes_to_a_pending_address():
    svc, clock = mk()
    r = svc.subscribe("Me@Example.com ", [RULE])
    assert r["ok"] and len(svc.out.sent) == 1 and svc.out.sent[0]["kind"] == "confirm" and svc.out.sent[0]["to"] == "me@example.com"
    assert svc.store.by_email("me@example.com")["status"] == "pending"
    assert svc.run(exceed()) == [] and len(svc.out.sent) == 1             # an alert is due, but the address never confirmed
    svc.confirm(token_from(svc.out.sent[0], "confirm"))
    assert len(svc.run(exceed())) == 1


def test_confirm_is_idempotent_expires_and_cannot_undo_an_unsubscribe():
    svc, clock = mk()
    svc.subscribe("a@example.com", [RULE])
    tok = token_from(svc.out.sent[0], "confirm")
    assert svc.confirm(tok)["ok"] and svc.confirm(tok)["ok"]
    svc2, clock2 = mk()
    svc2.subscribe("b@example.com", [RULE])
    tok2 = token_from(svc2.out.sent[0], "confirm")
    clock2.advance(hours=49)
    assert svc2.confirm(tok2) == {"ok": False, "error": "this link has expired"}
    # unsubscribe, then an old confirm link is replayed
    svc3, _ = mk()
    sub = active_sub(svc3)
    old = token_from(svc3.out.sent[0], "confirm")
    assert svc3.unsubscribe(token_from_headers(svc3.out.sent[0]))["ok"]
    assert svc3.confirm(old)["ok"] is False and sub["status"] == "unsubscribed"


def token_from_headers(msg: dict) -> str:
    return msg["headers"]["List-Unsubscribe"].strip("<>").split("?t=")[1]


def test_responses_do_not_reveal_whether_an_address_is_subscribed():
    svc, clock = mk()
    first = svc.subscribe("a@example.com", [RULE])
    svc.confirm(token_from(svc.out.sent[0], "confirm"))
    again = svc.subscribe("a@example.com", [RULE])                        # already active
    unknown = svc.subscribe("zz@example.com", [RULE])
    assert first == again == unknown and len(svc.out.sent) == 2          # nothing mailed to the active address a second time
    assert svc.subscribe("not-an-email", [RULE])["ok"] is False


def test_pending_confirmation_is_re_mailed_at_most_every_10_minutes():
    svc, clock = mk()
    svc.subscribe("a@example.com", [RULE]); svc.subscribe("a@example.com", [RULE])
    assert len(svc.out.sent) == 1
    clock.advance(minutes=11)
    svc.subscribe("a@example.com", [RULE])
    assert len(svc.out.sent) == 2


def test_no_postal_address_or_base_url_means_no_email_at_all():
    for missing in ({"postal_address": ""}, {"base_url": ""}):
        svc, _ = mk({"alerts_backend": {**CFG["alerts_backend"], **missing}})
        assert svc.subscribe("a@example.com", [RULE])["ok"] and svc.out.sent == []       # CAN-SPAM: refuse to mail without both


# ---------------------------------------------------------------- unsubscribe
def test_one_click_unsubscribe_headers_idempotent_and_stops_alerts():
    svc, clock = mk()
    sub = active_sub(svc)
    alert = svc.run(exceed())[0]
    assert alert["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click" and alert["headers"]["List-Unsubscribe"].startswith("<https://example.test/alerts/unsubscribe?t=")
    assert "1 Example Way" in alert["text"] and "unsubscribe?t=" in alert["text"] and "not an avalanche forecast" in alert["text"]
    tok = token_from_headers(alert)
    clock.advance(days=400)                                              # never expires
    assert svc.unsubscribe(tok) == {"ok": True, "status": "unsubscribed"} and svc.unsubscribe(tok)["ok"]
    assert sub["status"] == "unsubscribed" and svc.run(exceed(issued=(clock() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%MZ"))) == []
    assert svc.unsubscribe("garbage")["ok"] is False
    assert svc.unsubscribe(AB.sign_token(SECRET, "unsub", "no-such-id", clock()))["ok"] is True     # unknown ids answer the same


def test_a_new_opt_in_is_required_after_unsubscribing():
    svc, _ = mk()
    active_sub(svc)
    sid = svc.store.by_email("a@example.com")["id"]
    svc.unsubscribe(AB.sign_token(SECRET, "unsub", sid, T0))
    svc.subscribe("a@example.com", [RULE])
    new = svc.store.by_email("a@example.com")
    assert new["status"] == "pending" and new["id"] != sid and svc.out.sent[-1]["kind"] == "confirm"


# ---------------------------------------------------------------- rate limits
def test_signup_rate_limits_per_email_and_per_ip():
    svc, clock = mk()
    got = [svc.subscribe("a@example.com", [RULE]).get("limited") for _ in range(5)]
    assert got == [None, None, None, True, True]                         # 3 per e-mail per hour
    clock.advance(hours=1, minutes=1)
    assert svc.subscribe("a@example.com", [RULE]).get("limited") is None
    svc2, _ = mk()
    res = [svc2.subscribe(f"u{i}@example.com", [RULE], ip="203.0.113.9").get("limited") for i in range(22)]
    assert res.count(True) == 2 and res[19] is None and res[20] is True  # 20 per IP per hour


def test_alerts_per_day_cap_and_one_alert_per_area_per_storm():
    svc, clock = mk()
    active_sub(svc)
    assert len(svc.run(exceed())) == 1
    assert svc.run(exceed()) == []                                       # same storm: the same windows do not alert again
    # a later run whose only matching window starts < 12 h after the alerted window ended is still the same storm
    ex = exceed(issued="2026-11-19T01:00Z", p=60)
    clock.t = datetime(2026, 11, 19, 2, tzinfo=timezone.utc)
    assert svc.run(ex) == []
    # a clearly later window (a new storm) alerts again, within the daily cap
    ex2 = exceed(issued="2026-11-20T13:00Z", p=5)
    ex2["windows"]["24h"] = {"start": ["2026-11-23T12:00Z"], "end": ["2026-11-24T12:00Z"], "thr": [1.0, 4.0, 8.0, 12.0]}
    ex2["areas"]["alta-ski-area"]["summit"]["24h"] = [[90, 70, 80, 10]]
    clock.t = datetime(2026, 11, 20, 14, tzinfo=timezone.utc)
    assert len(svc.run(ex2)) == 1
    # the daily cap: several areas / storms, at most 3 e-mails per 24 h
    svc2, clock2 = mk({"alerts_backend": {**CFG["alerts_backend"], "alerts_per_day": 1}})
    active_sub(svc2)
    assert len(svc2.run(exceed())) == 1
    sub = svc2.store.by_email("a@example.com"); sub["last_alert"].clear()
    assert svc2.run(exceed()) == []                                       # cap reached within 24 h


# ---------------------------------------------------------------- matching
def test_matching_uses_native_thresholds_windows_and_fresh_data_only():
    ex = exceed()
    m = AB.match_rule(AB.validate_rule(RULE), ex, T0)
    assert m["prob"] == 60 and m["start"] == "2026-11-18T12:00Z" and m["thr_in"] == 8
    # a threshold that is not a native column (5 in) is not interpolated between 4 and 8: no match
    assert AB.match_rule(AB.validate_rule({**RULE, "thr_in": 5}), ex, T0) is None
    assert AB.match_rule(AB.validate_rule({**RULE, "min_prob": 70}), ex, T0) is None            # 60 % < 70 %
    assert AB.match_rule(AB.validate_rule(RULE), exceed(p=49), T0) is None
    # stale file (issued 19 h ago) never alerts; a missing area never alerts; a window already over is skipped
    assert AB.match_rule(AB.validate_rule(RULE), ex, T0 + timedelta(hours=19)) is None
    assert AB.match_rule(AB.validate_rule({**RULE, "area": "nowhere"}), ex, T0) is None
    late = datetime(2026, 11, 19, 20, tzinfo=timezone.utc)
    ex_late = exceed(issued="2026-11-19T19:00Z")
    assert AB.match_rule(AB.validate_rule(RULE), ex_late, late)["start"] == "2026-11-20T12:00Z"   # the first window ended at 12Z Nov 19
    assert AB.match_rule(AB.validate_rule(RULE), {"windows": {}, "areas": {}}, T0) is None


def test_snow_level_rule_needs_likely_precipitation():
    r = AB.validate_rule({"kind": "level", "area": "alta-ski-area", "window": "24h", "below_ft": 5000})
    assert AB.match_rule(r, exceed(sl=4500, pop=80), T0)["snow_level_ft"] == 4500
    assert AB.match_rule(r, exceed(sl=4500, pop=20), T0) is None                  # low snow level but a dry window
    assert AB.match_rule(r, exceed(sl=5500, pop=80), T0) is None


def test_rule_validation_and_the_free_preset():
    assert AB.preset_rules(["alta-ski-area"]) == [{"kind": "snow", "area": "alta-ski-area", "window": "24h", "elev": "summit", "thr_in": 8.0, "min_prob": 50.0}]
    for bad in ({}, {"kind": "snow", "area": "x"}, {**RULE, "window": "7d"}, {**RULE, "thr_in": 0}, {**RULE, "min_prob": 5}, {**RULE, "area": "../etc"},
                {"kind": "level", "area": "a", "below_ft": -1}, {"kind": "other", "area": "a"}):
        with pytest.raises(ValueError):
            AB.validate_rule(bad)
    svc, _ = mk()
    assert svc.subscribe("a@example.com", [])["ok"] is False and svc.subscribe("a@example.com", [RULE] * 11)["ok"] is False
    assert svc.subscribe("a@example.com", [{**RULE, "window": "7d"}])["ok"] is False


# ---------------------------------------------------------------- magic link
def test_magic_link_login_is_single_use_short_lived_and_generic():
    svc, clock = mk()
    active_sub(svc)
    r1, r2 = svc.request_login("a@example.com"), svc.request_login("nobody@example.com")
    assert r1 == r2 and len(svc.out.sent) == 2 and svc.out.sent[-1]["kind"] == "login"         # unknown address: same answer, no mail
    tok = token_from(svc.out.sent[-1], "login")
    assert svc.redeem_login(tok)["ok"] and svc.redeem_login(tok) == {"ok": False, "error": "this link was already used"}
    svc.request_login("a@example.com")
    tok2 = token_from(svc.out.sent[-1], "login")
    clock.advance(minutes=16)
    assert svc.redeem_login(tok2)["ok"] is False
    assert svc.redeem_login(AB.sign_token(SECRET, "confirm", "x", clock()))["ok"] is False       # wrong purpose


def test_no_secret_or_address_is_hard_coded_in_the_module():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "pipeline" / "alerts_backend.py").read_text(encoding="utf-8")
    assert "@gmail" not in src and "sk_live" not in src and 'SECRET = b"' not in src
