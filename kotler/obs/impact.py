"""Business impact in rupees: what is the AI worth to the business?

The rule here is HONESTY ABOUT EVIDENCE. Every number is tagged with how we know it:

  measured   counted from real activity in the database (conversations handled, actions taken)
  modelled   a model's prediction on historical data, under stated assumptions (RTO savings)
  simulated  from the Phase 6 customer simulator, not real customers (campaign profit)
  revenue    money customers paid (sales from AI chats). Revenue isn't profit, so it is never added to the total

Mixing these into one big "AI saved ₹X" headline is how dashboards mislead. We show them separately, with the
assumptions next to each number, and leave modelled and simulated values out of the "measured" total.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from kotler import db
from kotler.obs import metrics

# Assumptions, stated once and shown on the page.
HUMAN_COST_PER_CONVERSATION = 45.0   # ₹25,000/month agent ÷ (22 days × 25 conversations/day)
MINUTES_PER_HUMAN_CONVERSATION = 8


@dataclass
class Lever:
    lever: str
    inr: float
    period: str
    evidence: str            # measured | modelled | simulated
    how: str
    count: float | None = None


def support_automation(days: int = 30) -> Lever:
    tr = metrics.traces(days, include_eval=False, kind="agent_turn")
    asha = tr[tr.name == "asha"]
    convs = asha.groupby("conversation_id").escalated.max() if not asha.empty else pd.Series(dtype=int)
    handled = int((convs == 0).sum())
    try:
        tickets = db.query_one("SELECT COUNT(*) AS n FROM ai_ticket_runs WHERE outcome = 'resolved' AND created_at >= "
                               "datetime('now', 'localtime', ?)", (f"-{days} days",))["n"]
    except Exception:
        tickets = 0
    n = handled + tickets
    return Lever("Support handled by AI (no human needed)", n * HUMAN_COST_PER_CONVERSATION, f"last {days} days",
                 "measured", f"{handled} helpdesk conversations + {tickets} copilot tickets resolved without escalation "
                 f"× ₹{HUMAN_COST_PER_CONVERSATION:.0f} per human-handled conversation "
                 f"(≈ {n * MINUTES_PER_HUMAN_CONVERSATION / 60:.1f} agent hours)", n)


def rto_prevention() -> Lever | None:
    from kotler.ml import pipeline, rto
    m = pipeline.load_metrics()
    if not m or "rto_test_scores" not in m:
        return None
    scored = pd.DataFrame(m["rto_test_scores"])
    curve = rto.savings_curve(scored)
    best = curve.loc[curve.net_saving_inr.idxmax()]
    cod_month = db.query_one("""SELECT COUNT(*) / MAX((julianday(MAX(created_at)) - julianday(MIN(created_at))) / 30.0, 1)
                                AS n FROM orders WHERE payment_method = 'cod'""")["n"] or 0
    per_month = best.net_saving_inr / max(len(scored), 1) * cod_month
    return Lever("COD orders confirmed before shipping (RTO predictor)", per_month, "per month", "modelled",
                 f"At risk ≥ {best.threshold:.2f}: {int(best.rtos_caught)} of {int(scored.rto.sum())} refusals caught in "
                 f"the test period, net ₹{best.net_saving_inr:,.0f} on {len(scored)} COD orders, scaled to "
                 f"{cod_month:.0f} COD orders/month. Assumes ₹160 per RTO, half prevented, 5% of good buyers lost.",
                 float(best.rtos_caught))


def campaigns() -> Lever | None:
    from kotler.marketing import stats
    try:
        measured = db.query_df("SELECT id FROM campaigns WHERE status = 'measured'")
    except Exception:
        return None
    if measured.empty:
        return None
    profit, sig = 0.0, 0
    for cid in measured.id:
        try:
            r = stats.analyze(int(cid))
        except ValueError:
            continue
        if r["significant"]:          # only count campaigns with evidence they worked at all
            sig += 1
            profit += r["net_profit"]
    return Lever("Retention campaigns (incremental profit vs holdout)", profit, "campaigns to date", "simulated",
                 f"{sig} of {len(measured)} measured campaigns showed a significant uplift; their net profit after "
                 "message and discount costs. Customer responses come from the simulator.", sig)


def ai_sales(days: int = 30) -> Lever:
    from kotler import store
    s = store.ai_sales(days)
    shown = s["chats_shown_products"]
    rate = f"{s['chats_converted']} of {shown} chats that showed product cards bought" if shown else "no product cards shown yet"
    return Lever("Sales from AI chats (demo store checkout)", s["revenue"], f"last {days} days", "revenue",
                 f"{s['orders']} orders placed from a product card the AI recommended ({rate}). Counted only when the "
                 "signed link from the chat is intact; revenue, not profit, so it isn't added to the total.", s["orders"])


def ai_cost(days: int = 30) -> Lever:
    s = metrics.summary(days)
    return Lever("AI model cost (estimated at list price)", -s["cost_inr"], f"last {days} days", "measured",
                 f"{s['llm_calls']} LLM calls, {s['tokens']:,} tokens. On the free tier you actually pay ₹0.",
                 s["llm_calls"])


def impact(days: int = 30) -> pd.DataFrame:
    levers = [support_automation(days), ai_sales(days), rto_prevention(), campaigns(), ai_cost(days)]
    return pd.DataFrame([vars(x) for x in levers if x is not None])
