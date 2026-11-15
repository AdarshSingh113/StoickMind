# Phase 6: Retention journeys & AI campaigns

## What we built

| File | Role |
|---|---|
| `kotler/marketing/journeys.py` | Four retention journeys: replenishment, win-back, complete-your-routine, second order |
| `kotler/marketing/campaigns.py` | Campaign engine: A/B/holdout split, guardrails, AI-written templates, personalised messages, outbox |
| `kotler/marketing/simulator.py` | **Simulated customers** that respond (or not) over 14 days. Assumptions stated openly |
| `kotler/marketing/stats.py` | Uplift, confidence intervals, significance, sample size, incremental revenue, ROI |
| `views/campaigns.py` | Campaigns page: Journeys, New campaign, Results, Outbox |
| `tests/test_phase6_campaigns.py` | 26 tests |

**Honesty first:** we can't send thousands of real WhatsApp messages for free, and we have no real customers.
The journeys, guardrails, templates and statistics are real. Only the customers' responses are simulated,
and the page says so on every result. Phase 7 sends real messages to your own test numbers.

## 1. Journeys: who should hear from us today

| Journey | Rule | Today |
|---|---|---|
| Replenishment | product bought ≈ one refill cycle ago (face wash 45 d, serum 40 d…) | 331 customers |
| Win-back | segment At risk / Can't lose them / Need attention, 45-240 days since last order | 230 |
| Complete your routine | buys category A, never bought its complement (serum → sunscreen…) | 717 |
| Second order | one order, 10-30 days ago | 61 |

Every row carries the product, price and reason **from the database**. Out-of-stock products are never promoted.
**Bug the tests caught:** a customer was offered sunscreen although they had ordered one. That order was returned,
and the journey only counted kept orders. Now "already has it" counts every non-cancelled order.

## 2. The holdout group: the most important idea in marketing analytics

"312 customers we messaged bought something!" Many of them would have bought anyway. The only way to know how
many is to **not message a random share of the audience** (the holdout / control group) and compare:

```
incremental orders = (treated buying rate − control buying rate) × treated customers
```

Our first test campaign: **53 messaged customers bought (naive), but only ≈ 10 orders were caused by the campaign.**

Assignment is random but **deterministic**: a hash of (campaign, customer). It's reproducible and auditable, with no
"accidentally" putting the best customers in the treated group.

## 3. AI writes the words, code fills in the facts

Gemini writes two variants (A/B) in English and Hinglish using placeholders: `{first_name}`, `{product}`, `{price}`,
`{days}` (and `{discount}`, `{code}` when there's an offer). Our code renders each message from the database.
Templates are **rejected** if they contain a raw price ("₹299"), a raw percentage ("20% off"), an unknown
placeholder, or no `{product}`. If the AI is unavailable or its output fails validation, **built-in templates**
take over, so campaigns never depend on the free-tier quota.

## 4. Marketing guardrails (in code)

- Max **one marketing message per customer per 7 days**, across all campaigns
- **No promotions to customers with an open support ticket** (don't sell to someone who's upset)
- Campaign discounts capped at **15%**
- Holdout between 5% and 50% (no holdout = no way to measure)

## 5. The statistics

| Concept | What it answers |
|---|---|
| Conversion rate + **Wilson 95% interval** | How sure are we about each group's rate? |
| **Uplift** (pts and %) | How much more did messaged customers buy? |
| **p-value** (two-proportion z-test) | If the campaign did nothing, how often would luck produce a gap this big? |
| **Sample size** | How many customers do we need to detect a 30% lift? |
| **Incremental revenue, costs, ROI** | Did it make money? |

Verified against textbook values: z = 2.19 (60/300 vs 40/300), Wilson 21.9–39.6% (30/100), 1,774 per group to
detect +30% on a 10% base.

### Three lessons the first campaigns taught
1. **Naive attribution overstates.** 53 or 72 "orders from the campaign" vs 10 or 16 incremental.
2. **Small tests can't tell.** Our audiences (60–700 customers) give control groups of 12–150, but detecting a 30% lift
   needs about 1,800 per group. The page runs a **power check before you send**, and the verdict says "inconclusive"
   instead of pretending. A profit estimate from a non-significant uplift is labelled "not reliable", not shown as
   a green ROI.
3. **Discounts subsidise people who'd buy anyway.** A 10% coupon cost ₹5,004 to win ≈ 10 extra orders, so the campaign
   lost money (ROI −26%). Discounts must earn their keep.

### Does the analysis actually work? Test it against a known truth
The simulator plants a known effect (e.g. win-back + personalised = +75% relative lift). On a large synthetic audience
(20,000 customers) the analysis must rediscover it: significant (p < 0.001), and the absolute uplift within 3 standard
errors of the truth.
Lesson from writing that test: **relative uplift is much noisier than it looks**. Across 5 random seeds it ranged
0.65–0.96 around the true 0.75, because the small control rate sits in the denominator. Judge experiments by the
absolute uplift and its confidence interval.

## Try it
1. **Campaigns → New campaign**: pick *Complete your routine*, 0% discount, 20% holdout. Read the power check, preview the
   messages (Hinglish customers get Hinglish), send it, then **Results → Measure**.
2. Repeat with a 15% discount. Compare incremental orders and net profit.
3. Send a second campaign to the same journey right away. Check the **Outbox**: the frequency cap excluded everyone.
4. Use a **saved segment** from Customer Intelligence as an audience.

## Exercises
1. What holdout size would make the replenishment campaign conclusive? Is it worth "losing" that many messages?
2. Change the simulator so discounts have no effect. Does the analysis notice?
3. Write an A/B pair where B is deliberately worse (very long). Run it on the biggest journey. Does B lose significantly?
4. Why can't you just compare this month's sales with last month's to measure a campaign?

## Interview questions you can now answer
- *How do you measure whether a marketing campaign worked?* Randomised holdout, incremental lift, significance, ROI.
- *What's wrong with "X customers who got the message bought"?* Naive attribution: they might have bought anyway.
- *How big should an A/B test be?* Power analysis: base rate, minimum detectable effect, α, power.
- *How do you use an LLM to write marketing messages safely?* Templates with placeholders, facts from the database, validation, fallbacks.
- *When do discounts destroy value?* When they subsidise customers who would have bought anyway.
- *How do you know your experiment analysis is correct?* Test it on simulated data with a known effect.
