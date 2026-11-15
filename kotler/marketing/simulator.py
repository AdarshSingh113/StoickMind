"""Customer response SIMULATOR: plays the customers so we can practise measuring campaigns.

!! This is not real customer behaviour. !!
We can't send thousands of real WhatsApp messages for free, and we have no real customers. So this
module decides, with randomness, who buys in the 14 days after a campaign. The ANALYSIS of the results
(kotler/marketing/stats.py) is exactly what you'd run on real orders; only the customers are simulated.

How a simulated customer decides (assumptions, stated openly):
- Everyone has a baseline chance to buy in the next 14 days, from the Phase 5 churn model:
      p_base = (1 - churn_risk) * 14/90 * 1.2   (clipped to 0.5%-60%)
  Control-group customers buy with exactly this probability: many people buy anyway.
- A message raises that chance by a hidden RELATIVE lift:
      journey effect: replenishment +45%, win-back +60%, cross-sell +25%, second order +50%, segment +30%
      offer:          +3% per discount point (10% off -> +30%)
      message:        +15% if it uses their first name AND the product; +10% for a Hinglish speaker getting
                      Hinglish; -20% for very long messages (> 280 characters)
- Converters spend about their average order value (minus the discount if they used the coupon).
The stats module never looks at these numbers: it has to DISCOVER the lift from noisy outcomes,
exactly like with real customers. Runs are reproducible (random seed = campaign id).
"""

from __future__ import annotations

import json
import random
from datetime import datetime

from kotler import db

JOURNEY_LIFT = {"replenishment": 0.45, "win_back": 0.60, "cross_sell": 0.25, "second_order": 0.50, "segment": 0.30}
WINDOW_DAYS = 14


def base_probability(churn_risk: float) -> float:
    return min(max((1 - churn_risk) * WINDOW_DAYS / 90 * 1.2, 0.005), 0.6)


def message_lift(template: str, journey: str, offer_pct: int, hinglish_match: bool) -> float:
    lift = JOURNEY_LIFT.get(journey, 0.3) + 0.03 * offer_pct
    if "{first_name}" in template and "{product}" in template:
        lift += 0.15
    if hinglish_match:
        lift += 0.10
    if len(template) > 280:
        lift -= 0.20
    return max(lift, 0.0)


def simulate(campaign_id: int) -> dict:
    camp = db.query_one("SELECT * FROM campaigns WHERE id = ?", (campaign_id,))
    if not camp or camp["status"] == "draft":
        raise ValueError("Send the campaign before measuring it.")
    templates = json.loads(camp["templates"])
    rng = random.Random(campaign_id)
    rows = db.query_df("SELECT customer_id, grp, aov, churn_risk, language FROM campaign_members "
                       "WHERE campaign_id = ? AND grp != 'excluded' ORDER BY customer_id", (campaign_id,))
    updates = []
    for r in rows.itertuples():
        p = base_probability(r.churn_risk)
        treated = r.grp in ("A", "B")
        if treated:
            lang = "en" if r.language == "en" else "hinglish"
            p *= 1 + message_lift(templates[r.grp][lang], camp["journey"], camp["offer_pct"], lang == "hinglish")
        converted = rng.random() < min(p, 0.95)
        revenue = 0.0
        if converted:
            spend = r.aov * rng.uniform(0.7, 1.3)
            if treated and camp["offer_pct"]:
                spend *= 1 - camp["offer_pct"] / 100
            revenue = round(spend, 0)
        updates.append((int(converted), revenue, campaign_id, int(r.customer_id)))
    with db.get_conn() as conn:
        conn.executemany("UPDATE campaign_members SET converted = ?, revenue = ? WHERE campaign_id = ? AND customer_id = ?",
                         updates)
        conn.execute("UPDATE campaigns SET status = 'measured', measured_at = ? WHERE id = ?",
                     (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), campaign_id))
    return {"simulated_customers": len(updates), "conversions": sum(u[0] for u in updates)}
