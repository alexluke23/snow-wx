# Spec: Alerts backend (W6)

> Read when working on the Worker, accounts, alert rules or push/email delivery.
> Part of Snow-Wx docs v1.0 (Nov 15 2026). Index and priorities: `PLAN.md`.
> Section numbers (§) are kept from the original single plan so cross-references still work.

---

### 5.11 Alerts backend (W6) — *new*
Smallest thing that works:
- **Worker + store:** Cloudflare Worker with Cron Trigger + D1/KV (free-plan
  limits **[verify]**). Pipeline publishes `summary.json`; the Worker evaluates
  each user's rules after every points run and sends **email + web push**.
- **Identity:** passwordless email magic link; no passwords.
- **Rules:** "area X, window 24 h/72 h, P(≥ N in) ≥ p, or snow level below Y"; a
  free preset ("≥ 50% chance of ≥ 8 in at my favorites"), custom thresholds in the
  supporter tier. Rate-limit (≤ 1 alert/area/storm).
- **Entitlements:** payment-provider webhook sets `tier` on the account.
- **Compliance:** double opt-in, one-click unsubscribe, physical address in
  email (CAN-SPAM); SMS later only with 10DLC registration and STOP handling (§10).

---

### Offline skeleton (dev17) — logic and tests only, NOT deployed
`pipeline/alerts_backend.py` + `tests/test_alerts_backend.py` (16 tests) pin down the behaviour the Worker must reproduce. Config `alerts_backend.enabled: false`; `Service` raises `Disabled`
while off; nothing on the site calls it; no secret, address or network call exists in the module. The Worker is JavaScript on Cloudflare: port the functions one to one and keep the tests as the
acceptance list (or re-run them against a Node port).

| Piece | Behaviour implemented and tested |
|---|---|
| Tokens | `v1.<payload>.<HMAC-SHA256>`; purpose-bound (confirm / unsub / login), expiring (confirm 48 h, login 15 min), unsubscribe never expires; constant-time compare; secret rotation (list of keys) |
| Double opt-in | subscribe → `pending` → confirm → `active`; only the confirmation is mailed to a pending address; identical answer for new / active / unknown addresses (no account enumeration); re-send at most every 10 min; an old confirm link cannot undo an unsubscribe; a new opt-in is needed after unsubscribing |
| Unsubscribe | one click, no login, idempotent; `List-Unsubscribe` + `List-Unsubscribe-Post: List-Unsubscribe=One-Click` (RFC 8058) on every e-mail; unknown ids answer the same |
| Compliance | no e-mail at all unless a postal address and the base URL are configured (CAN-SPAM); every e-mail carries the address, the unsubscribe link and "not an avalanche forecast, read your avalanche center" |
| Rate limits | sign-ups 3 / e-mail / h and 20 / IP / h; ≤ 3 alert e-mails / subscriber / 24 h; ≤ 1 alert per area per storm (a new alert needs a trigger window starting ≥ 12 h after the last alerted window ended) |
| Matching | on `exceed_summary.json` only: NBM's NATIVE exceedance probability for a native threshold column (a threshold that is not a column, e.g. 5 in, never matches: no interpolation) in a native 24/48/72 h window; or "snow level ≤ X while precipitation is likely (PoP ≥ 50 %)"; windows already over are skipped; data older than 18 h or missing never alerts. No percentile is read, summed or scaled. |
| Changing rules | re-submitting an ACTIVE address with different rules does not change anything until the address owner confirms (a confirmation e-mail with the new rules pending; the answer is the same generic one), so nobody can alter someone else's alerts by typing their address |
| Caps | the daily cap (3 mails) holds alerts back: windows that end meanwhile are never sent late (matching requires the window to still be ahead); each rule has its own storm clock (area, kind, window, elevation); the snow-level rule's "precipitation likely" threshold is per rule (`min_pop`, default 50 %) |
| Magic link | single use (token recorded), 15 min, same answer for unknown addresses |
| Free preset | ≥ 50 % chance of ≥ 8 in in 24 h at each favorite's summit (`preset_rules`) |

**Not built (needs the decisions below):** the Worker/cron, D1/KV schema, web-push (VAPID, subscription storage, service-worker `push` handler), the mail provider adapter, bounce/complaint
webhooks, a preferences page, the supporter-tier entitlement webhook, SMS.

**Owner decisions needed before W6 can ship**
1. **E-mail provider** (Resend, Postmark, Amazon SES, Mailgun, …): price at ~5–50 k mails/month, free tier, one-click-unsubscribe support, bounce/complaint webhooks, EU/US data location.
2. **Cloudflare account** (the W1 account): Workers + Cron Triggers + D1/KV on the free plan limits **[verify]**, or paid Workers ($5/mo) for headroom; which zone/domain hosts `/alerts/*`.
3. **Sender domain and authentication:** the domain from W1, SPF + DKIM + DMARC records (and a `mail.` sub-domain so alert mail never harms the main domain's reputation).
4. **Physical postal address** for the CAN-SPAM footer (a PO box or virtual address is allowed; set by owner) and a monitored reply-to / abuse address.
5. **Privacy policy + terms** covering stored e-mail addresses, retention (suggest: delete 30 days after unsubscribe), deletion on request, and processors (the mail provider, Cloudflare). B2 legal review.
6. **Secrets handling:** where the HMAC secret and provider key live (Worker secrets), who can rotate them; the token secret needs a rotation plan (the code already verifies a list of keys).
7. **Web push:** VAPID key pair and applicationServerKey; push only for installed PWAs (W4 must be enabled first, which waits for W1); whether to build push in S5 or ship e-mail first.
8. **Numbers to confirm:** sign-up limits (3 / e-mail / h, 20 / IP / h), 3 alert mails per day, the storm gap (12 h), the freshness limit (18 h), the free preset (≥ 50 % of ≥ 8 in) and what supporters may customise.
9. **Abuse controls:** whether to add a CAPTCHA/Turnstile to the sign-up form (Cloudflare Turnstile is free) and whether disposable-address domains are blocked.
10. **Email copy:** the confirmation and alert wording (the skeleton's text is plain and hedged; a human should approve it), and whether alerts may link to the area page (needs the W2 URLs).
