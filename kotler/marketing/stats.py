"""Experiment statistics: did the campaign CAUSE extra purchases, and was it worth it?

Key ideas
---------
NAIVE vs INCREMENTAL: "312 messaged customers bought" sounds great, but many would have bought anyway.
  The control group tells us how many: incremental orders = (treated rate - control rate) x treated customers.
UPLIFT: treated conversion rate minus control conversion rate (absolute, in percentage points) and relative (%).
CONFIDENCE INTERVAL (Wilson): the range the true conversion rate plausibly lies in, given the sample size.
P-VALUE (two-proportion z-test): if the campaign did nothing, how often would we see a difference this big
  by luck? Below 0.05 we call it statistically significant (a convention, not a law).
SAMPLE SIZE: before running a test, ask how many customers you need to detect the effect you care about.
  Too few, and even a real effect looks like noise.
ROI: incremental gross profit minus the costs (messages + discounts given to EVERY converter who used the
  coupon, including those who'd have bought anyway: the "subsidy" cost).
"""

from __future__ import annotations

import math

import pandas as pd

from kotler import db

Z95 = 1.959964


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def two_proportion_z(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float]:
    """z statistic and two-sided p-value for H0: rate1 == rate2."""
    if min(n1, n2) == 0:
        return 0.0, 1.0
    p1, p2 = k1 / n1, k2 / n2
    pooled = (k1 + k2) / (n1 + n2)
    se = math.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n2))
    if se == 0:
        return 0.0, 1.0
    z = (p1 - p2) / se
    return z, math.erfc(abs(z) / math.sqrt(2))


def sample_size_per_group(base_rate: float, relative_lift: float, alpha: float = 0.05, power: float = 0.8) -> int:
    """Customers needed in EACH group to detect `relative_lift` over `base_rate` (two-sided test)."""
    p1, p2 = base_rate, base_rate * (1 + relative_lift)
    z_a = {0.05: 1.959964, 0.1: 1.644854, 0.01: 2.575829}.get(alpha, 1.959964)
    z_b = {0.8: 0.841621, 0.9: 1.281552}.get(power, 0.841621)
    p_bar = (p1 + p2) / 2
    num = (z_a * math.sqrt(2 * p_bar * (1 - p_bar)) + z_b * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))) ** 2
    return math.ceil(num / (p2 - p1) ** 2) if p2 != p1 else 10**9


def analyze(campaign_id: int, margin: float = 0.45, message_cost: float = 0.80) -> dict:
    camp = db.query_one("SELECT * FROM campaigns WHERE id = ?", (campaign_id,))
    m = db.query_df("SELECT grp, converted, revenue, aov FROM campaign_members WHERE campaign_id = ? AND grp != 'excluded'",
                    (campaign_id,))
    if m.converted.isna().all():
        raise ValueError("No results yet.")
    groups = []
    for g in ("A", "B", "control"):
        d = m[m.grp == g]
        k, n = int(d.converted.sum()), len(d)
        lo, hi = wilson(k, n)
        groups.append({"group": g, "customers": n, "conversions": k, "rate": k / n if n else 0.0, "ci_low": lo,
                       "ci_high": hi, "revenue": float(d.revenue.sum())})
    g = pd.DataFrame(groups).set_index("group")
    treated = m[m.grp.isin(["A", "B"])]
    ctrl = g.loc["control"]
    kt, nt = int(treated.converted.sum()), len(treated)
    rate_t = kt / nt if nt else 0.0
    z, p = two_proportion_z(kt, nt, int(ctrl.conversions), int(ctrl.customers))
    abs_uplift = rate_t - ctrl.rate
    inc_orders = abs_uplift * nt
    avg_order_t = treated.loc[treated.converted == 1, "revenue"].mean() if kt else 0.0
    inc_revenue = inc_orders * (avg_order_t if not math.isnan(avg_order_t) else 0.0)
    discount_cost = 0.0
    if camp["offer_pct"]:  # every treated converter used the coupon, including those who'd have bought anyway
        full_price = treated.loc[treated.converted == 1, "revenue"] / (1 - camp["offer_pct"] / 100)
        discount_cost = float((full_price - treated.loc[treated.converted == 1, "revenue"]).sum())
    costs = nt * message_cost + discount_cost
    profit = inc_revenue * margin - costs
    za, pa = two_proportion_z(int(g.loc["A", "conversions"]), int(g.loc["A", "customers"]),
                              int(g.loc["B", "conversions"]), int(g.loc["B", "customers"]))
    winner = None
    if pa < 0.05:
        winner = "A" if g.loc["A", "rate"] > g.loc["B", "rate"] else "B"
    needed = sample_size_per_group(max(ctrl.rate, 0.01), 0.3)
    return {
        "groups": g.reset_index(), "treated_rate": rate_t, "control_rate": float(ctrl.rate),
        "abs_uplift": abs_uplift, "rel_uplift": abs_uplift / ctrl.rate if ctrl.rate else None, "z": z, "p_value": p,
        "significant": p < 0.05 and abs_uplift > 0, "naive_orders": kt, "incremental_orders": inc_orders,
        "incremental_revenue": inc_revenue, "message_cost": nt * message_cost, "discount_cost": discount_cost,
        "net_profit": profit, "roi": profit / costs if costs else None,
        "ab": {"z": za, "p_value": pa, "winner": winner}, "sample_size_needed_per_group": needed,
        "control_size": int(ctrl.customers),
    }


def verdict(r: dict) -> str:
    if r["significant"] and r["net_profit"] > 0:
        return (f"The campaign worked and paid off: +{r['abs_uplift'] * 100:.1f} pts conversion vs control "
                f"(p = {r['p_value']:.3f}), about {r['incremental_orders']:.0f} extra orders, ₹{r['net_profit']:,.0f} net profit.")
    if r["significant"]:
        return (f"The campaign caused extra orders (p = {r['p_value']:.3f}), but the costs (mostly discounts given to "
                f"people who'd have bought anyway) outweigh the extra profit: ₹{r['net_profit']:,.0f}.")
    if r["control_size"] < r["sample_size_needed_per_group"]:
        return (f"Inconclusive: the difference could be luck (p = {r['p_value']:.2f}). The control group has "
                f"{r['control_size']} customers; detecting a 30% lift needs about {r['sample_size_needed_per_group']} per group.")
    return f"No evidence the campaign changed behaviour (p = {r['p_value']:.2f}). Try a different message or audience."
