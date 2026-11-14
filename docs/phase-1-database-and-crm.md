# Phase 1: Database & CRM

## What we built

1. A **SQLite database** for a D2C skincare brand.
2. A **data generator** that fills it with 12 months of realistic activity.
3. A **CRM query layer** (`kotler/crm.py`) that turns raw rows into business metrics.
4. A **Streamlit dashboard** with four pages: Overview, Customer 360, Products and Support tickets.

## Why start here, not with AI?

An AI agent is only as useful as the data and actions it can reach. When a customer asks
*"where is my order KTL-102345?"*, the LLM doesn't know the answer. It has to call a
function that queries a database. So we build the database and those functions first.
In Phase 2–3 the functions in `crm.py` (`get_order`, `get_customer`, ...) become the
agent's **tools**.

## The schema, table by table

| Table | Why it exists | Used later by |
|---|---|---|
| `pincodes` | City and tier for each delivery location. Tier is a strong RTO signal. | RTO predictor |
| `products` | Catalogue with skin types, concerns, ingredients and descriptions written in natural language | Shopping agent (search and RAG) |
| `customers` | Profile, skin type, preferred language, acquisition channel | CRM, personalization, language handling |
| `orders` | Payment method, address quality, status, courier, dates | Support agent, RTO model, KPIs |
| `order_items` | Which products are in each order, **at the price paid then** | Revenue, recommendations |
| `support_tickets` | Real-style messages in English and Hinglish, with category, priority and resolution | Support agent training and evaluation |

Design decisions worth explaining in an interview:

- **`order_items.unit_price` is copied, not looked up.** Prices change. If you recompute
  last year's revenue from today's prices, your numbers are wrong.
- **`order_number` ≠ `id`.** Customers see `KTL-100245`; the database uses integer ids.
  Never expose internal ids, and never let customers guess them.
- **Statuses are constrained with `CHECK`.** The database rejects `"deliverd"` (a typo) instead of
  letting dirty data in. Data quality starts at the schema.
- **Indexes on `customer_id`, `created_at`, `phone`.** These are the columns we filter by.
  Without an index, SQLite scans every row.
- **No ORM.** We write plain SQL so you learn SQL, which every data and AI role tests.

## Why simulate data, and what we planted in it

Public datasets don't have COD, Indian pincodes, RTO or Hinglish tickets. So we
**simulate**, and deliberately plant patterns we know are true in Indian D2C:

| Planted pattern | How | Who should rediscover it |
|---|---|---|
| Hidden customer personas (loyal 12%, regular 28%, one-time 45%, churned 15%) | Different purchase rates, and churners stop buying after 1.5–5 months | RFM / churn model |
| COD RTO risk | Base 8%, plus tier-3 city, first order, poor address, order over ₹1,500, ordering between midnight and 5 am; minus past successful deliveries | **RTO predictor** |
| Seasonality | Diwali (Oct–Nov) ×1.35–1.5, January sale ×1.25 | Forecasting |
| Skin-type matching and replenishment | 75% of picks match skin type; repeat buyers re-buy favourites | Recommendations |
| Language by city tier | Tier 3: 50% Hinglish, 20% Hindi | Multilingual agents |

**The key idea:** if a model can't find a pattern *you know* is there, it won't find
patterns you don't know about. Simulated data with known ground truth is how you test
an ML pipeline before trusting it on real data.

Two techniques used in `generate.py`:

- **Poisson process for purchases.** The time between orders is drawn from an exponential
  distribution (`rng.expovariate`). That's the standard model for random events
  happening at an average rate.
- **Thinning for seasonality.** Generate candidate orders at the peak rate, then keep each one
  with probability `season[month] / peak`. The result is a rate that changes by month.

`seed=42` makes it **reproducible**: the same seed always gives the same data, which a test checks.

## Metric definitions

| Metric | Definition | Why it matters |
|---|---|---|
| GMV | Value of all non-cancelled orders | Demand. What people *tried* to buy |
| Net revenue | Value of **delivered and kept** orders only | Money actually earned |
| AOV | GMV ÷ orders | Raising it (bundles, kits) grows revenue without new customers |
| Repeat purchase rate | % of buyers with 2+ orders | The health of a D2C brand. Acquisition is expensive |
| COD RTO rate | RTO ÷ finished COD shipments | Every RTO costs two-way shipping and blocks stock |

In our data: **16.8% COD RTO, about ₹2.8 lakh lost in a year.** That number is what the
Phase 4 model has to reduce.

## Tests (`tests/test_phase1.py`)

- Same seed gives the same data.
- `subtotal − discount + shipping = total`, and the items add up to the subtotal.
- No dates in the future; nothing delivered before it was ordered.
- The RTO pattern exists: COD tier 3 > COD tier 1 > any prepaid.
- KPIs are in realistic ranges.
- Phone lookup accepts `+91 98765 43210`, and order lookup is case-insensitive (customers type messily).

## Try it yourself (exercises)

1. Add a query for the **top 5 cities by net revenue** and show it on the Overview page.
2. Which acquisition channel has the **highest repeat rate**? (Hint: join `customers` and `orders`, then group by.)
3. Change the RTO formula in `_outcome()` to make late-night orders much riskier, regenerate,
   and check the effect on the dashboard.
4. In SQLite, run `EXPLAIN QUERY PLAN SELECT * FROM orders WHERE customer_id = 5;`, then drop the
   index and run it again. What changed?

## Interview questions you can now answer

- *"Why is net revenue lower than GMV?"* Cancellations aren't counted, and RTO, returns and in-transit orders aren't revenue yet.
- *"How would you store prices so historical reports stay correct?"*
- *"How did you test your ML pipeline without real data?"* Planted patterns with known ground truth.
- *"What is RTO and why does it matter for Indian e-commerce?"*
