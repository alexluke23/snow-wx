# Spec: Daily Snow summaries (W3)

> Read when working on `pipeline/summary.py` and `config/summary_rules.yml`.
> Part of Snow-Wx docs v1.0 (Nov 15 2026). Index and priorities: `PLAN.md`.
> Section numbers (§) are kept from the original single plan so cross-references still work.

---

### 5.7 Daily Snow summaries (W3) — *new, from Gemini #7*
A deterministic rules engine, **not** an LLM, run in the points pipeline.

- **Module:** `pipeline/summary.py` — pure function
  `summarize(point, obs, alerts) -> {tag, sentence, bullets, confidence, rule_ids}`;
  rules live in `config/summary_rules.yml` (versioned; thresholds tunable).
- **Where it shows:** top of every area card; Finder rows; "My mountains"; page
  `<meta description>` and OG share card (SEO); email/push alert body.
- **Language:** probabilistic and hedged ("50% chance of ≥ 8 in at the summit by
  Thursday 6 AM"); always next to the numbers; superlatives only when rules
  fire; "Blower" stays a labeled heuristic (§5.2).
- **Starter rules** (tune against verification and feedback):

| Tag | Condition (starting point) | Copy intent |
|---|---|---|
| Deep powder day | p50 24 h ≥ 8" **and** P(≥ 12") ≥ 30% **and** snow ratio in the Blower class (`powder_quality.blower_at`, 15:1 — the one shared definition, `config/settings.yml`) **and** summit gust < 25 mph | "Deep, light snow likely…" |
| Storm cycle | 72 h p50 ≥ 18" | "Multi-day storm: X–Y in by …" |

> **Native windows only (owner Nov 16):** any summary rule that uses p50 or P(≥X) must require a native NBM window
> (`totals[...]["native"] === true` for 24/48/72 h; `days[].range_window` set; `exceed` windows are always native).
> When the window is composite (`native: false`: percentiles of several 6 h windows added, as on fallback cycles) or
> beyond 72 h, lower the rule's confidence or skip it and use the expected total only.
>
> **Storm cycle copy:** use NBM's native 72 h snowfall window (`totals["72h"]`, its p10/p50/p90 from the native
> `snow72` percentiles) for "X–Y in". Never a range built by adding day or 6 h percentiles (owner decision Nov 16).
> The 7/10-day ranges no longer exist; use the expected total for longer spans.
| Rain at the base | P(snow level > base elev) ≥ 50% during precip | "Rain at the base, snow above X ft" |
| Mixed / crust risk | Snow level above summit, or warm spell after snow | "Warm: expect rain/crust" |
| Wind-affected | Ridge-top gusts > 30 mph during/after snow | "Wind-affected snow likely" (§5.9) |
| Low confidence | Model agreement = Low (§5.5) | "Models disagree: 3–14 in" |
| Alert active | NWS winter alert for the zone | Show the alert name + link |
| Dry stretch | 72 h p50 < 1" | "Little new snow; …" |

- **Priority & conflicts:** one headline tag by priority (alert > rain-at-base >
  powder day > storm cycle > …), bullets for the rest. Unit tests with fixtures
  for every rule and for conflicts.
- **Quality loop:** weekly review of 10 summaries vs the NWS AFD and observed
  totals; a "Report a bad summary" link.
