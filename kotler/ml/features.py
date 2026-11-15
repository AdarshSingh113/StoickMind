"""Customer feature store: one row per customer, computed AS OF a point in time.

The most important rule in this whole phase: features may only use data from BEFORE `as_of`.
If a churn model sees an order from the future it's predicting, it looks brilliant in testing
and is useless in production. That mistake is called DATA LEAKAGE, and it's the most common
way ML projects fool themselves. Every model here is trained on features "as of 90 days ago"
and checked against what happened in the following 90 days.

The same function serves three uses:
- today's features   -> segments, churn/CLV scores, the segment builder
- features 90d ago   -> training data for churn and CLV
- the customer_features table -> what the plain-English segment builder may query
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from kotler import db

LIVE = "status != 'cancelled'"


def store_now() -> datetime:
    t = db.query_one("SELECT MAX(created_at) AS t FROM orders")["t"]
    return datetime.fromisoformat(t)


def _orders_before(as_of: datetime) -> pd.DataFrame:
    df = db.query_df(f"""
        SELECT o.id, o.customer_id, o.created_at, o.status, o.payment_method, o.total, o.coupon_code
        FROM orders o WHERE o.created_at < ? AND o.{LIVE}""", (as_of.strftime("%Y-%m-%d %H:%M:%S"),))
    df["created_at"] = pd.to_datetime(df.created_at)
    return df


def customer_features(as_of: datetime | None = None) -> pd.DataFrame:
    as_of = as_of or (store_now() + timedelta(seconds=1))
    cut = as_of.strftime("%Y-%m-%d %H:%M:%S")
    o = _orders_before(as_of)
    if o.empty:
        return pd.DataFrame()

    o["delivered_value"] = np.where(o.status == "delivered", o.total, 0.0)
    o["is_cod"] = (o.payment_method == "cod").astype(int)
    o["is_rto"] = (o.status == "rto").astype(int)
    o["is_return"] = (o.status == "returned").astype(int)
    o["used_coupon"] = o.coupon_code.notna().astype(int)
    o["in_30d"] = (o.created_at >= as_of - timedelta(days=30)).astype(int)
    o["in_90d"] = (o.created_at >= as_of - timedelta(days=90)).astype(int)
    o["spend_90d"] = np.where(o.in_90d == 1, o.delivered_value, 0.0)

    g = o.groupby("customer_id")
    f = pd.DataFrame({
        "first_order_at": g.created_at.min(),
        "last_order_at": g.created_at.max(),
        "frequency": g.size(),
        "monetary": g.delivered_value.sum().round(0),
        "aov": g.total.mean().round(0),
        "orders_30d": g.in_30d.sum(),
        "orders_90d": g.in_90d.sum(),
        "spend_90d": g.spend_90d.sum().round(0),
        "cod_share": g.is_cod.mean().round(2),
        "rto_count": g.is_rto.sum(),
        "returns_count": g.is_return.sum(),
        "coupon_share": g.used_coupon.mean().round(2),
    })
    f["recency_days"] = ((as_of - f.last_order_at).dt.total_seconds() / 86400).round(0).astype(int)
    f["tenure_days"] = ((as_of - f.first_order_at).dt.total_seconds() / 86400).round(0).astype(int)
    f["avg_days_between_orders"] = np.where(f.frequency > 1, (f.tenure_days - f.recency_days) / (f.frequency - 1),
                                            np.nan).round(0)
    f["rto_rate"] = (f.rto_count / f.frequency).round(2)

    # categories bought (only from orders before as_of)
    cats = db.query_df(f"""
        SELECT o.customer_id, p.category, SUM(oi.quantity) AS units
        FROM order_items oi JOIN orders o ON o.id = oi.order_id AND o.{LIVE} AND o.created_at < ?
        JOIN products p ON p.id = oi.product_id GROUP BY o.customer_id, p.category""", (cut,))
    if not cats.empty:
        f["categories_bought"] = cats.groupby("customer_id").category.nunique()
        top = cats.sort_values("units", ascending=False).drop_duplicates("customer_id").set_index("customer_id")
        f["top_category"] = top.category

    t = db.query_df("""SELECT customer_id, COUNT(*) AS tickets,
                              SUM(category IN ('damaged_product', 'allergic_reaction', 'refund')) AS complaints
                       FROM support_tickets WHERE created_at < ? GROUP BY customer_id""", (cut,))
    f = f.join(t.set_index("customer_id"), how="left")

    c = db.query_df("""SELECT c.id AS customer_id, c.name, c.city, p.tier, c.skin_type, c.preferred_language AS language,
                              c.acquisition_channel AS channel FROM customers c JOIN pincodes p ON p.pincode = c.pincode""")
    f = c.set_index("customer_id").join(f, how="inner")
    for col in ("tickets", "complaints", "categories_bought"):
        f[col] = f.get(col, 0).fillna(0).astype(int)
    f["top_category"] = f.get("top_category", pd.Series(dtype=str)).fillna("none")
    f.index.name = "customer_id"
    return f.drop(columns=["first_order_at", "last_order_at"]).reset_index()


NUMERIC = ["recency_days", "frequency", "monetary", "aov", "tenure_days", "orders_30d", "orders_90d", "spend_90d",
           "cod_share", "rto_count", "rto_rate", "returns_count", "coupon_share", "categories_bought", "tickets",
           "complaints", "tier"]
CATEGORICAL = ["skin_type", "language", "channel", "top_category"]
