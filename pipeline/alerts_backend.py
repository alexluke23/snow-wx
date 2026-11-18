"""W6 alerts backend, OFFLINE SKELETON (docs/specs/alerts-backend.md, dev17). Pure functions with injectable fakes; NOT deployed, no secrets, no network.

What exists here is the logic the Cloudflare Worker will implement (the Worker is JavaScript; this Python reference is what the offline tests pin down):
  - signed, expiring, purpose-bound tokens (confirm / unsubscribe / magic-link login),
  - double opt-in: request -> pending -> confirm -> active; nothing is ever sent to a pending address except the confirmation,
  - one-click unsubscribe (RFC 8058 `List-Unsubscribe` + `List-Unsubscribe-Post`), idempotent, works without a login and never expires,
  - rate limits: sign-up requests per e-mail and per IP, alerts per subscriber per day, and at most one alert per area per storm,
  - rule matching against the pipeline's own `exceed_summary.json` (NBM's NATIVE exceedance probabilities and the snow level while precip is
    likely). No percentile is read, summed, scaled or interpolated here; alerts are never produced from stale or missing data.
Everything sits behind config `alerts_backend.enabled` (false): `Service` refuses to run while it is off, and nothing in the site calls it.

Injected: `store` (MemoryStore below; the Worker uses D1/KV), `clock`, `secret(s)`, `outbox` (collects e-mails; the Worker calls the mail provider). The owner
decisions this needs (provider, Cloudflare account, sender domain, postal address, ...) are listed in the spec.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

DEFAULTS = {
    "enabled": False,
    "confirm_ttl_h": 48,            # a confirmation link works for 48 h
    "login_ttl_min": 15,            # magic-link login: 15 minutes, single use
    "resend_confirm_after_min": 10,  # a pending address is re-mailed at most this often
    "signups_per_email_per_h": 3,
    "signups_per_ip_per_h": 20,
    "alerts_per_day": 3,            # per subscriber, all areas
    "storm_gap_h": 12,              # a new alert for the same area needs a trigger window starting this long after the last alerted window ended
    "max_rules": 10,
    "max_data_age_h": 18,           # never alert from an exceedance file older than this (stale = no alert)
    "postal_address": "",           # CAN-SPAM: required in every e-mail; empty = refuse to send anything
    "base_url": "",                 # https://<domain>/alerts  (confirm / unsubscribe endpoints)
    "from_name": "Snow-Wx",
}
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9.\-]{1,255}\.[A-Za-z]{2,24}$")
WINDOWS = ("24h", "48h", "72h")           # native NBM exceedance windows (never composite)
FOOTER = ("This is an automatic notification from open model guidance, not a forecast from a person and not an avalanche forecast. "
          "Before backcountry travel read your avalanche center's forecast.")


class Disabled(RuntimeError):
    """alerts_backend.enabled is false"""


class TokenError(ValueError):
    """bad / expired / wrong-purpose token (the message is safe to show)"""


def configure(cfg: dict | None) -> dict:
    out = dict(DEFAULTS)
    out.update({k: v for k, v in ((cfg or {}).get("alerts_backend") or {}).items() if k in DEFAULTS})
    return out


# ------------------------------------------------------------------ tokens
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign_token(secret: bytes, purpose: str, subject: str, now: datetime, ttl: timedelta | None = None) -> str:
    """`v1.<payload>.<mac>`: payload {p: purpose, s: subject, e: expiry epoch or 0}; HMAC-SHA256 over the payload. A token is only valid for its purpose."""
    payload = _b64(json.dumps({"p": purpose, "s": subject, "e": int((now + ttl).timestamp()) if ttl else 0}, separators=(",", ":")).encode())
    mac = _b64(hmac.new(secret, f"v1.{payload}".encode(), hashlib.sha256).digest())
    return f"v1.{payload}.{mac}"


def verify_token(secrets_: bytes | list[bytes], token: str, purpose: str, now: datetime) -> str:
    """The token's subject, or TokenError. Accepts several secrets (rotation). Constant-time MAC compare; purpose and expiry are enforced."""
    keys = [secrets_] if isinstance(secrets_, (bytes, bytearray)) else list(secrets_)
    try:
        ver, payload, mac = str(token).split(".")
        if ver != "v1":
            raise ValueError
        ok = any(hmac.compare_digest(_unb64(mac), hmac.new(k, f"v1.{payload}".encode(), hashlib.sha256).digest()) for k in keys)
        body = json.loads(_unb64(payload))
    except Exception as exc:                       # any malformed token is just "invalid"
        raise TokenError("invalid link") from exc
    if not ok:
        raise TokenError("invalid link")
    if body.get("p") != purpose:
        raise TokenError("this link is for something else")
    if body.get("e") and now.timestamp() > body["e"]:
        raise TokenError("this link has expired")
    return body["s"]


# ------------------------------------------------------------------ store (fake; D1/KV in the Worker)
class MemoryStore:
    """Dict-backed store with the small interface the Worker's D1/KV adapter will provide."""

    def __init__(self):
        self.subs: dict[str, dict] = {}
        self.hits: dict[str, list[float]] = {}
        self.used_tokens: set[str] = set()

    def by_email(self, email: str) -> dict | None:
        return next((s for s in self.subs.values() if s["email"] == email and s["status"] != "unsubscribed"), None) or \
            next((s for s in self.subs.values() if s["email"] == email), None)


@dataclass
class Outbox:
    """Collects e-mails instead of sending (fake provider)."""
    sent: list[dict] = field(default_factory=list)

    def send(self, msg: dict) -> None:
        self.sent.append(msg)


# ------------------------------------------------------------------ rate limits
def allow(store: MemoryStore, key: str, limit: int, window_s: int, now: datetime) -> bool:
    """Sliding-window limiter: records a hit and returns True while fewer than `limit` hits fall in the last `window_s` seconds."""
    t = now.timestamp()
    hits = [x for x in store.hits.get(key, []) if t - x < window_s]
    if len(hits) >= limit:
        store.hits[key] = hits
        return False
    hits.append(t)
    store.hits[key] = hits
    return True


def normalize_email(email: str) -> str | None:
    e = (email or "").strip().lower()
    return e if EMAIL_RE.match(e) and ".." not in e else None


# ------------------------------------------------------------------ rules
def validate_rule(rule: dict) -> dict:
    """Normalised rule or ValueError. Kinds: "snow" {area, window, thr_in, min_prob, elev} and "level" {area, window, below_ft, elev}.
    Only native exceedance windows (24h/48h/72h) exist, so a rule can never ask for a summed or interpolated amount."""
    if not isinstance(rule, dict) or not re.fullmatch(r"[a-z0-9\-]{1,80}", str(rule.get("area", ""))):
        raise ValueError("rule needs an area id")
    kind, window, elev = rule.get("kind"), rule.get("window", "24h"), rule.get("elev", "summit")
    if window not in WINDOWS or elev not in ("summit", "base"):
        raise ValueError("window must be 24h, 48h or 72h; elev summit or base")
    if kind == "snow":
        thr, p = float(rule.get("thr_in", 0)), float(rule.get("min_prob", 0))
        if not (1 <= thr <= 48) or not (10 <= p <= 100):
            raise ValueError("thr_in must be 1-48 in and min_prob 10-100 %")
        return {"kind": "snow", "area": rule["area"], "window": window, "elev": elev, "thr_in": thr, "min_prob": p}
    if kind == "level":
        below = float(rule.get("below_ft", 0))
        if not (0 < below < 20000):
            raise ValueError("below_ft out of range")
        return {"kind": "level", "area": rule["area"], "window": window, "elev": elev, "below_ft": below}
    raise ValueError("unknown rule kind")


def preset_rules(areas: list[str]) -> list[dict]:
    """The free preset (spec 5.11): >= 50 % chance of >= 8 in in 24 h at each favorite's summit."""
    return [validate_rule({"kind": "snow", "area": a, "window": "24h", "thr_in": 8, "min_prob": 50}) for a in areas]


def _nearest_thr(thresholds: list[float], thr: float) -> int | None:
    """index of the threshold column equal to the requested one (the file has fixed native thresholds; no interpolation between them)"""
    for i, t in enumerate(thresholds):
        if abs(t - thr) < 1e-6:
            return i
    return None


def match_rule(rule: dict, ex: dict, now: datetime, max_age_h: float = 18) -> dict | None:
    """First native window (by start time) of the area's exceedance record that meets the rule, or None.
    `ex` is exceed_summary.json: {issued, windows: {L: {start, end, thr}}, areas: {id: {elev: {L: [[p per thr] per window], pop: {L: [..]}, sl: {L: [..]}}}}}.
    Stale or missing data never matches."""
    try:
        issued = datetime.strptime(ex["issued"], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        return None
    if (now - issued).total_seconds() > max_age_h * 3600:
        return None
    rec = ((ex.get("areas") or {}).get(rule["area"]) or {}).get(rule["elev"])
    w = (ex.get("windows") or {}).get(rule["window"])
    if not rec or not w or rule["window"] not in rec:
        return None
    if rule["kind"] == "snow":
        col = _nearest_thr(w["thr"], rule["thr_in"])
        if col is None:
            return None                                     # the file has no such native threshold: no alert (never interpolate)
        for i, row in enumerate(rec[rule["window"]]):
            p = row[col] if col < len(row) else None
            if p is not None and p >= rule["min_prob"] and datetime.strptime(w["end"][i], "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc) > now:
                return {"rule": rule, "start": w["start"][i], "end": w["end"][i], "prob": p, "thr_in": rule["thr_in"], "issued": ex["issued"]}
        return None
    sl, pop = (rec.get("sl") or {}).get(rule["window"]) or [], (rec.get("pop") or {}).get(rule["window"]) or []
    for i, level in enumerate(sl):
        if level is not None and level <= rule["below_ft"] and (pop[i] if i < len(pop) else 0) >= 50:
            return {"rule": rule, "start": w["start"][i], "end": w["end"][i], "snow_level_ft": level, "issued": ex["issued"]}
    return None


# ------------------------------------------------------------------ the service
class Service:
    """The whole W6 flow with fakes. Construct with `Service(cfg, store, secret, outbox, clock)`; raises Disabled unless `alerts_backend.enabled`."""

    def __init__(self, cfg: dict, store: MemoryStore, secret: bytes | list[bytes], outbox: Outbox, clock=lambda: datetime.now(timezone.utc), rng=secrets):
        self.c = configure(cfg)
        if not self.c["enabled"]:
            raise Disabled("alerts_backend.enabled is false")
        self.store, self.secret, self.out, self.clock, self.rng = store, secret, outbox, clock, rng

    @property
    def _key(self) -> bytes:
        return self.secret if isinstance(self.secret, (bytes, bytearray)) else self.secret[0]

    def _can_send(self) -> bool:
        return bool(self.c["postal_address"] and self.c["base_url"])          # CAN-SPAM: no postal address / no unsubscribe URL = no e-mail

    def _url(self, path: str, token: str) -> str:
        return f"{self.c['base_url'].rstrip('/')}/{path}?t={token}"

    # -- double opt-in ----------------------------------------------------
    def subscribe(self, email: str, rules: list[dict], ip: str = "") -> dict:
        """Start (or restart) a subscription. ALWAYS answers the same way for valid input (no account enumeration); only a pending/new address is mailed."""
        now = self.clock()
        e = normalize_email(email)
        if not e:
            return {"ok": False, "error": "enter a valid e-mail address"}
        if not rules or len(rules) > self.c["max_rules"]:
            return {"ok": False, "error": f"choose 1-{self.c['max_rules']} alert rules"}
        try:
            norm = [validate_rule(r) for r in rules]
        except (ValueError, TypeError) as exc:
            return {"ok": False, "error": str(exc)}
        if not allow(self.store, f"su-email:{e}", self.c["signups_per_email_per_h"], 3600, now) or \
                (ip and not allow(self.store, f"su-ip:{ip}", self.c["signups_per_ip_per_h"], 3600, now)):
            return {"ok": False, "error": "too many requests, try again later", "limited": True}
        generic = {"ok": True, "message": "If this address can receive alerts, a confirmation e-mail is on its way. Alerts start only after you confirm."}
        sub = self.store.by_email(e)
        if sub and sub["status"] == "active":
            return generic                                              # nothing sent, nothing revealed
        if sub and sub["status"] == "pending" and (now - sub["confirm_sent_at"]) < timedelta(minutes=self.c["resend_confirm_after_min"]):
            return generic
        if not sub or sub["status"] == "unsubscribed":                  # a fresh opt-in is required after unsubscribing
            sid = self.rng.token_hex(8)
            sub = {"id": sid, "email": e, "rules": norm, "status": "pending", "created": now, "confirm_sent_at": now, "last_alert": {}, "sent_log": []}
            self.store.subs[sid] = sub
        else:
            sub["rules"], sub["confirm_sent_at"] = norm, now
        if self._can_send():
            tok = sign_token(self._key, "confirm", sub["id"], now, timedelta(hours=self.c["confirm_ttl_h"]))
            self.out.send(self._confirm_mail(sub, tok))
        return generic

    def confirm(self, token: str) -> dict:
        now = self.clock()
        try:
            sid = verify_token(self.secret, token, "confirm", now)
        except TokenError as exc:
            return {"ok": False, "error": str(exc)}
        sub = self.store.subs.get(sid)
        if not sub:
            return {"ok": False, "error": "unknown subscription"}
        if sub["status"] == "unsubscribed":
            return {"ok": False, "error": "this subscription was cancelled; sign up again"}      # a stale confirm link can never undo an unsubscribe
        if sub["status"] != "active":
            sub["status"], sub["confirmed_at"] = "active", now
        return {"ok": True, "status": "active"}

    # -- one-click unsubscribe -------------------------------------------
    def unsubscribe(self, token: str) -> dict:
        """Works with no login, never expires, idempotent (RFC 8058: the mail client POSTs `List-Unsubscribe=One-Click` to the same URL)."""
        try:
            sid = verify_token(self.secret, token, "unsub", self.clock())
        except TokenError as exc:
            return {"ok": False, "error": str(exc)}
        sub = self.store.subs.get(sid)
        if sub and sub["status"] != "unsubscribed":
            sub["status"], sub["unsubscribed_at"] = "unsubscribed", self.clock()
        return {"ok": True, "status": "unsubscribed"}            # unknown ids answer the same: nothing to reveal

    # -- magic-link login (single use) ------------------------------------
    def request_login(self, email: str, ip: str = "") -> dict:
        now, e = self.clock(), normalize_email(email)
        generic = {"ok": True, "message": "If this address has an account, a sign-in link is on its way."}
        if not e or not allow(self.store, f"login-email:{e}", self.c["signups_per_email_per_h"], 3600, now) or \
                (ip and not allow(self.store, f"login-ip:{ip}", self.c["signups_per_ip_per_h"], 3600, now)):
            return generic if e else {"ok": False, "error": "enter a valid e-mail address"}
        sub = self.store.by_email(e)
        if sub and sub["status"] == "active" and self._can_send():
            tok = sign_token(self._key, "login", sub["id"], now, timedelta(minutes=self.c["login_ttl_min"]))
            self.out.send({"to": e, "kind": "login", "subject": "Your Snow-Wx sign-in link", "headers": {},
                           "text": f"Sign in (valid {self.c['login_ttl_min']} minutes, one use): {self._url('login', tok)}\n\n{self.c['postal_address']}"})
        return generic

    def redeem_login(self, token: str) -> dict:
        now = self.clock()
        try:
            sid = verify_token(self.secret, token, "login", now)
        except TokenError as exc:
            return {"ok": False, "error": str(exc)}
        if token in self.store.used_tokens:
            return {"ok": False, "error": "this link was already used"}
        self.store.used_tokens.add(token)
        return {"ok": True, "subscription": sid}

    # -- e-mail -----------------------------------------------------------
    def _headers(self, sub: dict, now: datetime) -> tuple[dict, str]:
        unsub = self._url("unsubscribe", sign_token(self._key, "unsub", sub["id"], now))
        return {"List-Unsubscribe": f"<{unsub}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}, unsub

    def _confirm_mail(self, sub: dict, token: str) -> dict:
        now = self.clock()
        headers, unsub = self._headers(sub, now)
        return {"to": sub["email"], "kind": "confirm", "subject": "Confirm your Snow-Wx alerts", "headers": headers,
                "text": (f"Someone (hopefully you) asked for snow alerts at this address.\nConfirm: {self._url('confirm', token)}\n"
                         f"The link works for {self.c['confirm_ttl_h']} hours. If you did not ask for this, ignore this e-mail: nothing will be sent.\n"
                         f"Unsubscribe any time: {unsub}\n\n{self.c['postal_address']}")}

    def _alert_mail(self, sub: dict, hits: list[dict], now: datetime) -> dict:
        headers, unsub = self._headers(sub, now)
        lines = []
        for h in hits:
            r = h["rule"]
            what = (f"{h['prob']:.0f}% chance of at least {r['thr_in']:.0f} in of snow ({r['window']} window, NBM)" if r["kind"] == "snow"
                    else f"snow level near {h['snow_level_ft']:.0f} ft with precipitation likely")
            lines.append(f"- {r['area']} ({r['elev']}): {what}; window {h['start']} to {h['end']}")
        return {"to": sub["email"], "kind": "alert", "subject": f"Snow-Wx alert: {len(hits)} of your areas", "headers": headers,
                "text": ("\n".join(lines) + f"\n\nNBM issued {hits[0]['issued']}. {FOOTER}\nManage or stop alerts: {unsub}\n\n{self.c['postal_address']}")}

    # -- evaluation after every points run --------------------------------
    def run(self, ex: dict) -> list[dict]:
        """Evaluate every ACTIVE subscription against the new exceedance file and send at most one combined e-mail each. Returns the mails sent."""
        now, sent = self.clock(), []
        if not self._can_send():
            return sent
        for sub in self.store.subs.values():
            if sub["status"] != "active":
                continue
            hits = []
            for rule in sub["rules"]:
                m = match_rule(rule, ex, now, self.c["max_data_age_h"])
                if not m:
                    continue
                key = f"{rule['area']}|{rule['kind']}"
                last_end = sub["last_alert"].get(key)
                if last_end and datetime.strptime(m["start"], "%Y-%m-%dT%H:%MZ") < datetime.strptime(last_end, "%Y-%m-%dT%H:%MZ") + timedelta(hours=self.c["storm_gap_h"]):
                    continue                                     # same storm: one alert per area per storm
                hits.append(m)
            if not hits:
                continue
            today = [t for t in sub["sent_log"] if now - t < timedelta(hours=24)]
            if len(today) >= self.c["alerts_per_day"]:
                continue
            msg = self._alert_mail(sub, hits, now)
            self.out.send(msg)
            sent.append(msg)
            sub["sent_log"] = today + [now]
            for m in hits:
                sub["last_alert"][f"{m['rule']['area']}|{m['rule']['kind']}"] = m["end"]
        return sent
