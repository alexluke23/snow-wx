# Snow-Wx — Business Plan, Positioning, Legal & Review Notes

> **Claude Code: do not read this file unless the task is explicitly about business, pricing, legal or go-to-market.**
> Part of Snow-Wx docs v1.0 (Nov 15 2026). Dev priorities: `PLAN.md`.
> Not legal, tax or financial advice. Section numbers (§) kept from the original plan.

---

## 1.1 Positioning vs OpenSnow (re-checked Nov 15 2026)

| | OpenSnow | Snow-Wx |
|---|---|---|
| Price | Free tier; **Base $49.99/yr**; **Premium $99.99/yr** (family plans higher) | Free core; low-cost optional supporter tier (§9) |
| Forecast | One blended forecast driven by proprietary PEAKS 2.0 (now powering 15-day) | Transparent: NBM probabilistic range **+** NWS official (NDFD) **+** raw models side by side |
| Multi-model comparison | **Premium only** ("Forecast Range") | **Free** (M7/M8) — a headline differentiator |
| Alerts | Snow-forecast alerts are a **Base+** feature; snow-report alerts are free | Free preset email alert; custom thresholds/push in supporter tier |
| Uncertainty | Forecast range view (Premium) | Percentile ranges (10/50/90) everywhere, by default |
| Rain/snow line | — | Snow level vs base/summit elevation for every area |
| Context | Avalanche forecasts (free), webcams, snow reports, slope/aspect overlays (new, free) | Avalanche danger, nearest SNOTEL/ASOS obs, NWS alerts + forecaster discussion, Sno-Parks |
| Trust | Accuracy claims | **Public verification** vs SNOTEL |
| Offline | 3D/offline maps (Base+) | Offline-first PWA: last forecast cached for favorites (free) |
| Native apps | iOS + Android | Web/PWA only (deliberate, §1.2) |

Where OpenSnow leads (don't try to match yet): terrain downscaling (~50 ft),
human local forecasters, resort snow reports, webcams, 3D maps, native apps.
2026–27 additions: PEAKS 2.0, webcam map + live streams, shareable favorite
lists, slope/aspect overlays, a "Powder Finder Map" (Base+). Our long-term answer
to PEAKS is transparent station-based bias correction (M9). **Competitor reality
check:** never claim we beat them on accuracy without our own published
verification; don't claim features they have.

---

## 9. Business plan

> Not legal, tax or financial advice. Items touching entity, tax, insurance and
> contracts need a CPA/attorney in the owner's state.

### 9.1 Model summary
Free core + (later) **supporter subscription** for convenience features, plus
**B2B embeds/feeds** and **sponsors**. Annual plans preferred (seasonal usage).

| | Free (forever) | Supporter (paid, hypothesis) |
|---|---|---|
| Forecasts, probabilities, snow level, model comparison | ✅ | ✅ |
| Avalanche danger, NWS alerts, data freshness | ✅ (never gated) | ✅ |
| Offline cache of favorites (PWA) | ✅ (≤ ~5) | ✅ more |
| Daily Snow summaries, Finder, obs map | ✅ | ✅ |
| One preset email alert | ✅ | ✅ |
| **Custom alerts** (thresholds, snow level, multi-area), **web push** | — | ✅ |
| **Unlimited saved places / multi-location dashboard** | ~5 | ✅ |
| **Exports** (CSV/JSON of your places) / light API | — | ✅ |
| Early access to new features; name on supporters page | — | ✅ |
| SMS alerts | — | optional later add-on |

### 9.2 Pricing hypotheses (to test, not assume)
- **Anchor:** OpenSnow Base is $49.99/yr and Premium $99.99/yr; Base gates
  snow-forecast alerts and offline maps, Premium gates multi-model comparison.
  We have no human forecasters, so pricing below Base is defensible; offering
  multi-model free is the wedge.
- **Founding Supporter:** ~**$20/yr**, locked for life, capped (e.g., 200–500
  seats), sold only after alerts really work. **Standard:** ~**$29–39/yr**;
  optional monthly ~$4. Group/family plan later.
- **Transaction fees** (published rates; confirm at checkout): Stripe card ≈
  2.9% + $0.30 (plus roughly 0.5% if using Stripe Tax); merchant-of-record
  providers (Paddle/Lemon Squeezy class) ≈ 5% + $0.50.

| Price | Stripe fee | MoR fee |
|---|---|---|
| $20 | $0.88 (4.4%) | $1.50 (7.5%) |
| $29 | $1.14 (3.9%) | $1.95 (6.7%) |
| $39 | $1.43 (3.7%) | $2.45 (6.3%) |

- **Why a merchant of record first:** it becomes the legal seller and handles
  sales tax/VAT filing; the ~3-point premium is cheap insurance for a solo
  founder. Revisit at scale. Note Lemon Squeezy is now part of Stripe (Stripe
  Managed Payments, announced Jan 2026) **[verify current offering]**.
- **Web/PWA avoids app-store fees** (15–30% on native in-app purchases
  **[verify]**).

### 9.3 Unit economics & scenarios (illustrative — assumptions, not forecasts)

| Paying subscribers | Gross/yr at $29 | Net after MoR fees | Active users needed at 2% / 5% conversion |
|---|---|---|---|
| 100 | $2,900 | ~$2,700 | 5,000 / 2,000 |
| 500 | $14,500 | ~$13,500 | 25,000 / 10,000 |
| 1,500 | $43,500 | ~$40,600 | 75,000 / 30,000 |
| 5,000 | $145,000 | ~$135,000 | 250,000 / 100,000 |

Reading: subscriptions alone make a meaningful *side income* at a few thousand
engaged users and a salary only at tens of thousands — hence the push on
**owned audience, SEO and B2B/sponsors**, which scale per account rather than
per consumer. Conversion rates (2–5%) are a generic assumption for niche consumer
subscriptions; measure ours. Revenue is seasonal (Oct–Mar): annual plans and
pre-season launch matter.

### 9.4 Costs (expected at launch; verify before budgeting)

| Item | Cost / note |
|---|---|
| Domain | ~$10–20/yr (typical; check registrar) |
| Cloudflare Pages (site) | $0 on free plan; static bandwidth unmetered; 500 git builds/mo; 20,000 files |
| Workers/Functions | Free 100,000 req/day; Workers Paid starts at $5/mo if exceeded |
| R2 data storage | Free tier exists; far above our size needs **[verify pricing]** |
| GitHub Actions | $0 for public repos; private repo would cost — estimate before switching |
| Email sending/newsletter | Free tiers exist **[evaluate providers]** |
| Web push | $0 (browser push services) |
| **SMS (if ever)** | Twilio ≈ $0.0083/segment + carrier fees ≈ $0.0035–0.005 → **≈ $0.012–0.013/message**; ≈ $1.10–1.30/user/yr at 8 texts/month; plus 10DLC registration (roughly $20–60 one-time; ~$1.50–10/mo campaign fee) |
| Payment fees | §9.2 |
| Entity, accounting, insurance | State-specific — get quotes (**B1**) |
| ECMWF/NOAA data | $0 (open licenses) |

Target: **monthly run-rate < $50 until revenue exists.**

### 9.5 Go-to-market (organic first)
1. **SEO on ~600 prerendered pages** (W2). Each page carries the live daily
   summary; "<Area> snow forecast" is a long-tail query. Expect months, not
   weeks — start now.
2. **Owned audience:** email capture on every page; a weekly (and big-storm)
   **Storm Outlook** generated from the rules engine, reviewed by the owner.
3. **Communities:** be useful in storm threads (model-agreement and snow-level
   context) and read each subreddit/forum's self-promotion rules first; ask mods;
   don't spam. Post when big cycles hit.
4. **Partnerships:** avalanche centers/education providers (link to their
   forecasts, ask for feedback), local ski shops, clubs, guides, Nordic/snowmobile
   groups (Sno-Parks fill a gap).
5. **Shareable content:** "Forecast report card" (verification), "which model won
   this storm", storm-total recaps — all from data we already archive.
6. **Product-led sharing:** OG cards, share links, shareable favorite lists.
7. **Don't** claim "more accurate than OpenSnow" without our published
   verification.

### 9.6 B2B, sponsors & affiliate (after audience exists — mostly 2027)
- **Embeds:** a small iframe/JS widget for lodging, shops, guides, clubs, with a
  "Powered by" backlink; free-with-attribution first, then a paid white-label tier
  (~$10–30/mo hypothesis). Needs a stable domain and an embed-safe CSS/JS bundle.
- **Data feeds:** custom JSON for ski patrols, clubs, small ski areas.
- **Sponsors:** local shops/avalanche education — a quiet "Presented by" line, no
  banner ads on safety UI.
- **Affiliate:** evaluate outdoor-retail networks **[verify which programs exist]**;
  keep out of safety/avalanche UI; FTC-compliant disclosure; low expected revenue.
- **Ads** make the site clearly commercial for some data/API terms — decide
  deliberately, not by default.

### 9.7 KPIs & decision gates
Instrument in W5. **Targets below are placeholders — reset after two weeks of
baseline (Gate 2).**

| Metric | Why |
|---|---|
| Weekly active users; **returning-visitor rate** | Product value |
| Organic search clicks (Search Console) | SEO working |
| PWA installs; offline-cache usage | Retention/alerts funnel |
| Email subscribers; open rate | Owned audience |
| Alert signups (free preset) | Demand for the paid core |
| Paid-waitlist joins (% of email list) | Willingness to pay |
| Forecast verification scores | Credibility |

**Gates**
- **Gate 1 (Dec 13):** domain live, analytics firing, pages indexed.
- **Gate 2 (Jan 10):** baseline established; scope alerts MVP from observed demand.
- **Gate 3 (Feb 15):** proceed with a capped Founding Supporter soft launch only if
  alerts are reliable (no missed/false storms in testing), a measurable email
  list + free-alert signups exist, and a waitlist/willingness-to-pay signal is
  present (placeholder: ≥ 3–5% of the email list joins the paid waitlist).
  Otherwise stay free and keep building audience; launch pre-season.

### 9.8 Longer-term phases (aligned to Gemini's phases, dated)
- **Phase 1 — Nov 2026–Apr 2027:** free; trust + audience (this plan).
- **Phase 2 — May–Aug 2027 (off-season):** harden paid infrastructure; publish the
  season verification report; B2B pilots; tune summaries/wind; choose final
  name/brand assets if not done.
- **Phase 2b — Sep–Oct 2027:** pre-season paid launch (Founding Supporters
  grandfathered); partner promotions.
- **Phase 3 — 2027–28 season on:** B2B embeds/white-label, affiliate, ensemble
  plumes, wind Phase B, more observation networks.

### 9.9 Risks & mitigations
| Risk | Mitigation |
|---|---|
| A forecast bust damages trust | Show uncertainty; publish verification; "report a bust" loop |
| Safety/liability (avalanche, travel) | Disclaimers; always link official avalanche forecasts; no "slab risk"; insurance quote; counsel review |
| Competitor response (e.g., OpenSnow cuts multi-model gating) | Differentiate on transparency, verification, Sno-Parks, price |
| Data/source changes (NBM versions, AWS buckets, RRFS status, API changes) | Sources fail independently; monitoring; tests with fixtures; reduce single-source dependence |
| Hosting/platform limits | W1 limit checks; R2 for bulk data; alternatives evaluated |
| GitHub cron unreliability | External trigger; data-status page |
| iOS PWA friction (users expect an app) | Install coach mark; measure installs; revisit native only if demand is clear |
| Seasonality/churn | Annual plans; pre-season launch; off-season content |
| Single-owner capacity | Cut list (§8.2); automate; avoid scope creep |
| SEO slower than hoped | Start now; email list as the hedge |

---

---

## 10. Legal, compliance & data licensing

### 10.1 Commercial-readiness checklist
- [ ] **Name/brand:** trademark + domain + handles; **retire "Powder Finder"**
  (OpenSnow now has a "Powder Finder Map").
- [ ] **Entity & accounts:** decide sole prop vs LLC with a CPA/attorney (state-
  specific); business bank account; separate payment account.
- [ ] **Terms of Use, Privacy Policy, safety/avalanche disclaimer** reviewed for a
  paid product; cookieless analytics reduces privacy burden — verify applicable
  state privacy laws.
- [ ] **Email (CAN-SPAM):** unsubscribe + physical postal address; double opt-in.
- [ ] **SMS (if ever):** carrier 10DLC brand/campaign registration, explicit opt-in,
  STOP/HELP handling (TCPA).
- [ ] **Sales tax/VAT:** merchant of record or Stripe Tax; CPA confirmation.
- [ ] **Insurance:** quote for general/professional (E&O)/cyber liability.
- [ ] **Attribution:** NOAA/NWS credit (no implied endorsement/logos); ECMWF CC BY
  4.0 statement; ODbL "© OpenStreetMap contributors"; publish derived catalog
  under ODbL; avalanche.org display rules.
- [ ] **Hosting terms:** GitHub Pages is not for online businesses — move before
  charging (W1); review Cloudflare terms for image-heavy content **[verify]**.
- [ ] **Avalanche data:** avalanche.org's commercial-use terms are not clear in
  public docs — **email the avalanche.org/National Avalanche Center and the
  relevant centers (nonprofits) before launching anything paid**; centers'
  own sites can restrict automated scraping, so use only the sanctioned API per
  its terms and seek written permission; prefer partnership.
- [ ] **Basemap tiles:** verify OpenTopoMap (CC-BY-SA + fair-use policy) at
  commercial traffic, or move to self-hosted/paid tiles; USGS basemaps are public
  domain.

---

## Appendix A — 4. Review of the Gemini feedback

Gemini's review was useful. Verdicts below are Claude's, grounded in sources
checked on Nov 15 2026 (see Sources).

| # | Gemini idea | Verdict | Our take |
|---|---|---|---|
| 1 | **Multi-model dispersion** (NBM vs ECMWF vs HRRR; model selector) | **Adopt — reshape** | Multi-model comparison is gated behind OpenSnow's $99.99 Premium, so offering it free is a real wedge. But **don't use Open-Meteo**: its free API is *non-commercial only* (commercial needs a paid subscription), and we'd add a dependency for data we already sample directly. ECMWF's entire real-time catalogue has been open under **CC BY 4.0 since Oct 1 2025** (commercial reuse allowed with attribution; IFS 0.1° added Oct 20 2026; AIFS single + ensemble open). So: sample ECMWF GRIB ourselves (M8). A selector alone isn't enough — add a **model-agreement meter** and per-model plume (§5.5). |
| 2 | **Offline-first PWA** | **Adopt — high priority** | Great fit for a static-JSON architecture. Changes: (a) do it *after* the domain move (origin = install identity); (b) staleness warnings are mandatory; (c) **offline stays free**; (d) don't promise offline basemap tiles (provider terms); (e) iOS push needs Add-to-Home-Screen (§5.8). |
| 3 | **Phase 1: stay free 6 months for distribution** | **Adopt** | The 6 months *are* this winter. Use it to build an **owned audience (email)**, instrumentation and verification — not just pageviews. |
| 4 | **Phase 2: "coffee-tier" $3–5/mo or $25/yr** | **Adopt — adjust** | Market anchor is OpenSnow Base at $49.99/yr (which already gates snow-forecast alerts). $25 is under-anchored: use **Founding price (~$20/yr, locked for life, capped seats)** then **~$29–39/yr** **[hypothesis to test]**. Gate list changes: custom alerts, push, unlimited saved places, exports/API — **not** offline. Free users get ~5 favorites (retention). |
| 5 | **Phase 3: B2B widgets, affiliate** | **Adopt — later** | Embeds with a "Powered by" attribution link also build backlinks. Affiliate revenue is usually small: keep it out of safety UI, disclose per FTC rules, evaluate networks **[verify]**. |
| 6 | **Aspect/elevation wind-drift correction + "Slab Risk" badge** | **Reshape — do not ship as proposed** | Grid-scale winds (2.5–3 km) don't validate terrain-scale loading; an unverified "Slab Risk" badge reads as avalanche guidance and is a liability and trust risk. Ship an informational **wind-exposure flag** linking to the avalanche center forecast; defer numeric redistribution until M9 (§5.9). |
| 7 | **Automated Daily Snow plain-English summaries** | **Adopt — top priority** | Highest ROI item: cheap, deterministic, and doubles as SEO text, social cards, email/push copy. Caveat: it replaces the *glance*, not local human expertise — don't market it as "80% of a forecaster". Use probabilistic language from NBM percentiles (§5.7). |

---

---

## Appendix B — Sources (checked Nov 15 2026)

- OpenSnow plans & features: https://support.opensnow.com/subscription/free-vs-base-vs-premium-features ; https://opensnow.com/weblink/allaccess ; 2026–27 release: https://opensnow.com/news/post/2026-2027-winter-release
- Open-Meteo terms/pricing: https://open-meteo.com/en/terms ; https://open-meteo.com/en/pricing
- ECMWF open data & licence: https://www.ecmwf.int/node/37688 ; https://www.ecmwf.int/node/28188 ; https://www.ecmwf.int/node/29497
- iOS web push requirements: https://developer.apple.com/forums/thread/732594 ; https://www.magicbell.com/blog/pwa-ios-limitations-safari-support-complete-guide
- Twilio SMS pricing & carrier fees: https://static1.twilio.com/en-us/sms/pricing/us ; https://support.twilio.com/hc/en-us/articles/1260803965530
- Cloudflare Pages limits: https://developers.cloudflare.com/pages/platform/limits ; Pages Functions pricing: https://developers.cloudflare.com/pages/functions/pricing/index.md
- Payments (Stripe vs merchant-of-record fee comparisons): https://dev.to/jettfu/stripe-vs-paddle-vs-lemon-squeezy-fee-comparison-2026-2c77 ; https://alexcloudstar.com/md/blog/merchant-of-record-indie-saas-2026/
- Avalanche data context: https://avalanche.state.co.us/terms-use (CAIC site terms)
- Earlier plan sources: NBM v4.1 elements https://weather.gov/media/mdl/nbm/docs_v41/new_nbm_v4.1_wx_elements.pdf ; NBM docs https://blend.mdl.nws.noaa.gov/nbm-documentation ; NWS snow level (0.5 °C wet-bulb) https://ams.confex.com/ams/104ANNUAL/webprogram/Handout/Paper434400/Integrating%20Probabilistic%20Data%20into%20Operations%20for%20a%20Deterministic%20Forecast%20Process.pdf ; OpenSkiMap/ODbL https://wiki.openstreetmap.org/wiki/OpenSkiMap ; OpenSnow PEAKS https://opensnow.com/peaks
