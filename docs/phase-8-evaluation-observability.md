# Phase 8: Evaluation, observability & "Ask your data"

An AI product you can't measure is a demo. This phase answers four questions a founder asks every week:
**Is the AI working? What does it cost? What is it worth? What's happening in my business?**

## What we built

| File | Role |
|---|---|
| `kotler/obs/trace.py` | Traces (one per AI task) and spans (LLM calls, tool calls, guards), stored in SQLite |
| `kotler/llm.py` (`_instrument`) | Wraps every provider's `chat()`: **every** LLM call is logged, automatically |
| `kotler/obs/metrics.py` | p50/p95 latency, error, guard, fallback and escalation rates, tokens and ₹ cost, per agent |
| `kotler/obs/evals.py` | Eval history in the database, full vs partial runs, regression detection |
| `kotler/obs/impact.py` | Business value in ₹, every number tagged *measured / modelled / simulated* |
| `kotler/analytics/ask.py` | Ask your data: guarded text-to-SQL, validated charts, number-checked answers |
| `kotler/evals/ask_data.py` | 12-case eval with **execution match**, including privacy cases |
| `views/ai_performance.py`, `views/ask_data.py` | The two new pages |
| `tests/test_phase8_observability.py` | 31 tests |

## 1. Tracing: instrument at the choke point

Every LLM call in Kotler goes through one method: a provider's `chat()`. `_instrument()` wraps that method once,
so every call is logged (model, latency, tokens, errors, which model *actually* answered). Code written next year
is measured too, without anyone remembering to add logging. That's the main lesson: **put instrumentation where
all traffic must pass, not at every call site.**

A **trace** groups the calls that belong to one task ("Kavya answered one message"): its LLM calls, its tool calls
with their duration and errors, and every safety check that fired. Traces nest (a copilot run contains an agent
turn) using a `ContextVar`: the LLM call deep inside the judge doesn't need a `trace_id` parameter, it asks "which
trace am I in?". ContextVars are per thread / per async task, so two customers chatting at once never mix (tested).

Rule: **observability must never break the product.** Every logging write swallows its own errors; a test makes
the database fail and checks the customer still gets an answer.

## 2. The metrics that matter

| Metric | Why |
|---|---|
| p50 / p95 reply time | the median wait, and the unluckiest 1 in 20. Averages hide the slow tail |
| guard rate | how often a safety check had to step in. Rises *before* customers complain |
| fail-safe rate | how often the AI couldn't be made truthful and handed over |
| fallback rate | how often the main model was overloaded and the backup answered |
| escalation rate | how much work still reaches humans |
| judge success | the LLM-judge's verdict on whole conversations: quality, not just "no error" |
| ₹ per conversation | tokens × list price. The free tier costs ₹0; this answers "what at 10,000 chats?" |

Eval traffic (`channel = 'eval'`) is excluded by default, so test runs don't pollute production numbers.

## 3. Offline evals vs online monitoring

- **Offline evals** (fixed cases, run on purpose) tell you if a change is better *before* customers see it.
- **Online monitoring** (traces) tells you what actually happens with real customers.

Every eval run is now stored. The page compares the latest **full** run with the previous one, case by case.
Partial re-runs (`--only`, checking one fix) are kept but not compared: "3/3" after "25/26" isn't an improvement.

**This found something real on day one.** The last two shopping runs both scored 25/26. Same headline, but
`en_ingredient` was fixed and `quiz_full_hinglish` broke. A pass-rate chart can't show that; a case-by-case diff can.

## 4. Business impact, honestly

| Lever | Evidence | How |
|---|---|---|
| Support handled by AI | **measured** | Asha conversations + copilot tickets with no escalation × ₹45 per human conversation |
| COD orders confirmed before shipping | **modelled** | RTO model's net saving on the test period at the best threshold, scaled per month |
| Retention campaigns | **simulated** | net profit of campaigns with a *significant* uplift vs holdout |
| AI cost | **measured** | tokens × list price (negative) |

Only *measured* values are added into the headline. Adding a model's prediction and a simulation to real counts
is how dashboards end up claiming ₹10 lakh of "AI savings" nobody can find in the bank account.

## 5. Ask your data

`question → SQL → guarded run → validated chart → summary → number check`

**Column-level access control.** Phase 5 allowed one anonymous table. Here many tables are allowed, so the
SQLite authorizer checks every **column** read: names, phones, emails, addresses and free-text messages are
blocked, even inside allowed tables, and even in a `WHERE` clause. That last part matters:
`SELECT COUNT(*) FROM customers WHERE phone LIKE '98%'` never *shows* a phone number, but repeated queries like
it could reveal one digit by digit. Blocked.

**Refuse, don't retry, writes.** A SQL error or a blocked column gets one chance to be fixed. An attempt to write
(DELETE, multiple statements) is refused outright, with the reason shown.

**Grounded summaries.** The model writes 1-3 sentences *after* seeing the result. Code then checks every number in
the summary against the result (allowing rounding, and 0.123 → 12.3%). If the model invents a total, it gets one
retry; then the summary is **withheld** and only the exact table is shown. People read the sentence and skip the
table, so a wrong sentence is worse than none.

**Charts are validated**: columns must exist, the value axis must be numeric; otherwise, a table.
**Incomplete periods** are flagged: the current month always looks like a crash.

## 6. Evaluating text-to-SQL: execution match

Comparing SQL text is useless (there are many correct queries). We run the model's SQL and a hand-written gold
SQL and compare the **values** they return, ignoring column names, row order and extra columns. Plus: was the
summary verified, and did privacy questions return no personal data?

```bash
GEMINI_API_KEY=... python -m kotler.evals.ask_data
```

## Bugs found while building

- A `DELETE` was rejected before running, but the model was then invited to "fix" it. Now writes are never retried.
- Months like `2026-03` were drawn as timestamps ("Nov 02" labels). Now an ordered axis.
- The trace waterfall cut off its first row; "1 regressions". Small, but they make a dashboard look untrustworthy.

## What you learned

Traces and spans, instrumenting at a choke point, context propagation, percentiles, guard/fallback/escalation
rates, LLM cost accounting, offline vs online evaluation, regression diffs, evidence levels for business impact,
column-level access control, execution-match evaluation, and grounding generated text in data.
