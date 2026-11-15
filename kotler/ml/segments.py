"""RFM segmentation: the classic, explainable way to group customers.

R = Recency   (days since last order: lower is better)
F = Frequency (number of orders)
M = Monetary  (delivered spend)

Each gets a 1-5 score. Recency and Monetary use quintiles (each score holds ~20% of customers).
Frequency uses FIXED bins, because most D2C customers have exactly 1 order: quintiles would
split identical one-order customers into different scores at random.

Scores map to named segments that marketing can act on, e.g. "At risk" = used to buy
often and spend well, but hasn't bought in a long time -> win-back campaign.
"""

from __future__ import annotations

import pandas as pd

SEGMENTS = {  # name -> (description, suggested action)
    "Champions": ("Bought recently, buy often, spend the most.", "Reward them: early access, referral program."),
    "Loyal": ("Buy regularly and spend well.", "Upsell kits and new launches."),
    "Potential loyalists": ("Recent customers with a few orders.", "Membership / replenishment reminders."),
    "New customers": ("First order very recently.", "Onboarding: how-to-use tips, second-order nudge."),
    "Promising": ("Recent single order.", "Personalised recommendation for the second order."),
    "Need attention": ("Average on all three; slipping.", "Limited-time offer on their favourite category."),
    "About to sleep": ("Below average recency and value.", "Re-engage with bestsellers and reviews."),
    "At risk": ("Used to buy often and spend well, but not lately.", "Win-back: personal message + offer."),
    "Can't lose them": ("Top spenders who have gone quiet.", "Call or personal outreach; best offer."),
    "Hibernating": ("Low value, long time ago.", "Low-cost reactivation; seasonal sale."),
    "Lost": ("Lowest recency, frequency and value.", "Don't spend much; include in big sale blasts only."),
}


def _quintile(series: pd.Series, reverse: bool = False) -> pd.Series:
    ranks = series.rank(method="first", ascending=not reverse)
    return pd.qcut(ranks, 5, labels=[1, 2, 3, 4, 5]).astype(int)


def frequency_score(freq: pd.Series) -> pd.Series:
    return pd.cut(freq, bins=[0, 1, 2, 3, 5, 10**6], labels=[1, 2, 3, 4, 5]).astype(int)


def segment_for(r: int, f: int, m: int) -> str:
    fm = round((f + m) / 2)
    if r >= 4 and fm >= 4:
        return "Champions"
    if r == 5 and f == 1:
        return "New customers"
    if r == 4 and f == 1:
        return "Promising"
    if r >= 3 and fm >= 4:
        return "Loyal"
    if r >= 4 and fm >= 2:
        return "Potential loyalists"
    if r == 1 and m == 5:
        return "Can't lose them"
    if r <= 2 and fm >= 3:
        return "At risk"
    if r == 3 and fm >= 2:
        return "Need attention"
    if r == 3:
        return "About to sleep"
    if r == 2:
        return "Hibernating"
    return "Lost"


def rfm(features: pd.DataFrame) -> pd.DataFrame:
    df = features[["customer_id", "recency_days", "frequency", "monetary"]].copy()
    df["r"] = _quintile(df.recency_days, reverse=True)   # recent = high score
    df["f"] = frequency_score(df.frequency)
    df["m"] = _quintile(df.monetary)
    df["rfm"] = df.r.astype(str) + df.f.astype(str) + df.m.astype(str)
    df["segment"] = [segment_for(r, f, m) for r, f, m in zip(df.r, df.f, df.m)]
    return df[["customer_id", "r", "f", "m", "rfm", "segment"]]


def segment_summary(features: pd.DataFrame, seg: pd.DataFrame) -> pd.DataFrame:
    df = features.merge(seg, on="customer_id")
    out = df.groupby("segment").agg(customers=("customer_id", "count"), avg_recency=("recency_days", "mean"),
                                    avg_orders=("frequency", "mean"), revenue=("monetary", "sum"),
                                    avg_value=("monetary", "mean")).round(1)
    out["revenue_share"] = (out.revenue / out.revenue.sum()).round(3)
    out["description"] = [SEGMENTS[s][0] for s in out.index]
    out["action"] = [SEGMENTS[s][1] for s in out.index]
    order = list(SEGMENTS)
    return out.loc[[s for s in order if s in out.index]].reset_index()
