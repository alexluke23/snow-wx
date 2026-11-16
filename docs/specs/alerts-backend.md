# Spec: Alerts backend (W6)

> Read when working on the Worker, accounts, alert rules or push/email delivery.
> Part of Snow-Wx docs v1.0 (Nov 15 2026). Index and priorities: `PLAN.md`.
> Section numbers (§) are kept from the original single plan so cross-references still work.

---

### 5.11 Alerts backend (W6) — *new, business-enabling*
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
