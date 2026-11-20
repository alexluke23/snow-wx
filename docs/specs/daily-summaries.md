# Spec: Daily Snow summaries (W3)

> Read when working on `pipeline/summary.py` and `config/summary_rules.yml`.
> Part of Snow-Wx docs v1.0 (Nov 15 2026). Index and priorities: `PLAN.md`.
> Section numbers (§) are kept from the original single plan so cross-references still work.

---

### 5.7 Daily Snow summaries (W3) — *new*
A deterministic rules engine, **not** an LLM, run in the points pipeline.

- **Module:** `pipeline/summary.py` — pure function
  `summarize(point, obs, alerts) -> {tag, sentence, bullets, confidence, rule_ids}`;
  rules live in `config/summary_rules.yml` (versioned; thresholds tunable).
- **Where it shows (dev14):** top of every area card (full sentence + bullets), **Finder rows** (headline tag; sentence in the
  tooltip; `summary.json` rows carry `sm: [tag, sentence]`), **"My mountains"** cards (sentence + "Report a bad summary");
  still to do: page `<meta description>` and OG share card (W2/SEO); email/push alert body (W6).
- **Alert tag is client-side (owner Nov 17):** points files and `summary.json` never contain alerts. `web/js/summary-ui.js`
  (`SnowSummary.withAlerts`) reads the live `alerts/index.json` and, when the place has an ACTIVE winter-relevant alert
  (`relevant !== false`, not past `ends`), puts "Alert active: <names>" on top of the stored summary (which becomes a bullet).
  An alert always outranks every stored summary and is never hidden by it.
- **Language:** probabilistic and hedged ("50% chance of ≥ 8 in at the summit by
  Thursday 6 AM"); always next to the numbers; superlatives only when rules
  fire; "Blower" stays a labeled heuristic (§5.2). **Ranges read "likely X–Y in"** = NBM's native p25–p75 of one window
  ("the middle half of NBM's outcomes": about a 1-in-4 chance of more than the high number and of less than the low number;
  owner Nov 17). No inline "NBM 10–90%"; no "NBM's" labels in sentences (source + issue time stay in the run line). If no
  single native window covers a span, the sentence uses the expected amount only. Tests assert "likely", no "10–90", no "NBM".
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
  powder day > storm cycle > dry stretch > wind-affected > baseline; owner Nov 17: Dry stretch outranks Wind-affected, and wind keeps its 3 in expected-snow bar), bullets for the rest. Unit tests with fixtures
  for every rule and for conflicts.
- **Quality loop:** a **"Report a bad summary"** link (area card and My mountains) opens a prefilled e-mail (place, page,
  tag, rule ids, text). **Weekly review (10 min, owner):** every Monday pick 10 places (the 5 busiest ski areas plus 5 from the
  inbox or at random), compare each summary with the NWS AFD/forecast discussion and the previous week's observed SNOTEL/NOHRSC
  totals, and write one line per summary in `docs/summary_review.md` (date, place, rule ids, "ok / too bold / too timid / wrong",
  note). Tune `config/summary_rules.yml` only after the same miss appears twice; record the change in PLAN §3. Not built yet: the
  "Low confidence" rule (needs M7 model agreement) and the `<meta description>` (W2).
