# Phase 5: Customer Intelligence (CDP + machine learning)

## What we built

| File | Role |
|---|---|
| `kotler/ml/features.py` | Feature store: one row per customer **as of any date**, using only earlier data |
| `kotler/ml/segments.py` | RFM scores and 11 named segments, each with a suggested action |
| `kotler/ml/customer_models.py` | Churn (no order in 90 days) and 90-day value models, with time-based backtests |
| `kotler/ml/rto.py` | COD refusal predictor, per-order reasons, rupee-based threshold |
| `kotler/ml/segment_builder.py` | Plain English → SQL → customers, with guardrails in code |
| `kotler/ml/pipeline.py` | Trains everything (≈ 7 s), saves models + metrics, writes `customer_scores` and `customer_features` |
| `views/intelligence.py` | Customer Intelligence page: Segments, Churn & value, COD risk (with savings simulator), Segment builder |
| `views/customers.py` | Customer 360 now shows segment, churn risk and predicted value |
| `tests/test_phase5_ml.py` | 39 tests: leakage, planted-pattern recovery, baselines, savings logic, SQL guardrails |

Run: `python -m kotler.ml.pipeline` (the app also retrains by itself when there are new orders).

## 1. Data leakage: the #1 way ML projects fool themselves

If a churn model is trained with features that include the very orders it's trying to predict, it scores
brilliantly in testing and is useless in production. Every feature here is computed **as of** a date, from
earlier data only. Test: add an order *after* the snapshot date, and the snapshot's features must not change.

Subtler leak, in the RTO model: "this customer refused 2 parcels before" is only knowable if those parcels'
outcomes were known when the new order was placed. So a past RTO counts only if its expected delivery date had passed.

## 2. RFM segmentation

| Score | Meaning | How |
|---|---|---|
| R | Recency: days since last order | quintiles (5 = most recent) |
| F | Frequency: number of orders | **fixed bins** (1, 2, 3, 4-5, 6+), because most customers have exactly 1 order, and quintiles would split identical customers at random |
| M | Monetary: delivered spend | quintiles |

Scores map to segments like *Champions*, *At risk*, *Can't lose them*. Our data: **Champions are 21% of customers
and 50% of revenue**, the classic Pareto pattern.

## 3. Time-based backtests and baselines

Random train/test splits mix time periods and flatter the model. We **train on the past and test on a later period**:

```
train: customers as of T-180, T-210, T-240, T-270  ->  labels from the following 90 days (all end before T-90)
test:  customers as of T-90                        ->  labels from (T-90, T]
final: retrain on T-90 … T-180 snapshots, score everyone as of today
```

Stacking several snapshots is a standard trick for **small data**: 544 → 1,484 training rows.

**Every model must beat a one-line rule**, or the rule wins:

| Model | Baseline | Result |
|---|---|---|
| Churn (AUC) | "longest since last order" 0.780 | logistic regression **0.805** (gradient boosting 0.778) |
| 90-day value (MAE, ₹) | "same as last 90 days" ₹893 | gradient boosting **₹723**; top 10% of predictions = 23% of next-quarter revenue |
| COD RTO (AUC) | "tier-3 cities are risky" 0.645 | logistic regression **0.751**; riskiest 10% have a 45% RTO rate vs 20% average |

Honest lessons:
- **Recency does most of the work for churn.** ML adds ≈ +0.03 AUC. That's normal: don't oversell.
- **Gradient boosting lost to logistic regression** in all three. With ~1,500 rows, simpler models generalise better.
  The RTO pipeline prefers the simpler model unless the complex one wins by more than 0.01 AUC.
- AUC alone means little. Always report it **next to a baseline** and in business terms (top-decile rate, ₹).

## 4. The RTO predictor: from model to money

- **Features available at checkout only**: city tier, first order, past deliveries and refusals (known ones),
  order value, items, coupon, night-time order, vague address.
- **No fake signals**: the simulated `address_quality` score isn't used. A real store doesn't have one. "Vague address"
  is derived from the address **text** (no house number or no pincode).
- **Bug we hit, and two lessons:**
  1. Four overlapping address features (length, house number, pincode, landmark-only) split the effect between
     them, and one even got the wrong sign ("vague address lowers risk"). That's **multicollinearity**. One clear
     feature fixed it, with no loss of accuracy.
  2. Per-order reasons said "vague address" for a perfect address, because a feature's *absence* can push the score
     up mathematically. Reasons are now written from the feature's **actual value**.
- **Threshold by rupees, not accuracy.** The savings simulator models: cost of one RTO (₹160), share of RTOs an
  intervention prevents (50%), genuine buyers lost to the extra step (5%), gross margin (45%). Best threshold: **0.35**.
  Flag 56% of COD orders, catch 87% of refusals, **net saving ≈ ₹2,800 on 425 test orders**. Change the assumptions
  and the best threshold moves. That conversation with the business is the real deliverable.
- Recommended actions depend on status: still in the warehouse → "Call before shipping"; already with the
  courier → "Call before delivery attempt".

## 5. Plain-English segments (text-to-SQL) with guardrails

The LLM writes SQL from a request like *"tier-3 customers with oily skin who haven't ordered in 60 days"*.
Guardrails, all in code:
1. The model may only query `customer_features`, a table **with no names, phones, emails or addresses**.
2. **Read-only** connection.
3. A **SQLite authorizer** checks every operation: only SELECT and reading `customer_features` are allowed.
   This blocked a JOIN to `customers` to read phone numbers, reading `sqlite_master`, PRAGMA, ATTACH, extensions.
4. One statement; 5,000-row cap; queries stopped after 2 seconds.
5. SQL errors → one self-correction attempt. **Forbidden** queries are never retried.
6. The SQL and the AI's interpretation are always shown.

## Exercises
1. Change `HORIZON` to 60 days. Does churn get easier or harder to predict? Why?
2. Add a feature "days since last support ticket" to the churn model. Does it beat the current AUC? Keep it only if it does.
3. In the savings simulator, find the assumptions under which flagging *nothing* is best.
4. Write a request the segment builder misunderstands. How would you make the prompt or columns clearer?

## Interview questions you can now answer
- *What is data leakage? Give an example and how you'd test for it.*
- *Why use a time-based split instead of a random one?*
- *Your model has AUC 0.80. Is that good?* Compared to what baseline, and what's it worth in ₹?
- *Why might logistic regression beat gradient boosting?* Small data, overfitting, explainability.
- *What's multicollinearity and how did it show up?*
- *How do you choose a classification threshold?* By business cost and benefit, not 0.5.
- *How do you let an LLM query your database safely?* Least privilege (anonymous view), read-only, authorizer, limits, transparency.
