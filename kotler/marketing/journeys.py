"""Retention journeys: WHO should get a message today, and about WHICH product.

Four classic D2C journeys, each a rule over real purchase data + Phase 5 scores:

  replenishment  the product they bought is probably running out (category refill cycle)
  win_back       valuable customers drifting away (At risk / Can't lose them / Need attention)
  cross_sell     "complete your routine": bought a serum but never a sunscreen, etc.
  second_order   new customers, 10-30 days after their first order (the hardest order to win)

Every audience row carries the PERSONALISATION FIELDS a message needs (first name, product,
price, days since...). Those come from the database, never from the AI, so a message can't
promise a product or price that doesn't exist. Out-of-stock products are never promoted.
"""

from __future__ import annotations

import pandas as pd

from kotler import db

# Days until a typical customer runs out (for one unit).
REFILL_DAYS = {"face_wash": 45, "moisturizer": 50, "serum": 40, "sunscreen": 45, "toner": 60, "lip_care": 60,
               "eye_care": 60, "body_care": 50, "kit": 45}
# "Complete your routine": if they bought the key, suggest the value category.
COMPLEMENTS = {"serum": "sunscreen", "face_wash": "moisturizer", "moisturizer": "sunscreen", "toner": "serum",
               "sunscreen": "serum", "eye_care": "serum", "body_care": "face_wash", "lip_care": "moisturizer"}
WIN_BACK_SEGMENTS = ("At risk", "Can't lose them", "Need attention")

JOURNEYS = {
    "replenishment": "Their product is probably running out: remind them to restock.",
    "win_back": "Valuable customers drifting away: bring them back.",
    "cross_sell": "Complete their routine with a product they've never bought.",
    "second_order": "New customers: win the all-important second order.",
}


def _base() -> pd.DataFrame:
    """Customers with today's features and scores (Phase 5)."""
    return db.query_df("""
        SELECT f.customer_id, c.name, c.preferred_language AS language, f.skin_type, f.recency_days, f.frequency,
               f.aov, f.segment, f.churn_risk, f.clv_12m, f.top_category, f.complaints
        FROM customer_features f JOIN customers c ON c.id = f.customer_id""").assign(
        first_name=lambda d: d.name.str.split().str[0]).drop(columns="name")


def _purchases() -> pd.DataFrame:
    df = db.query_df("""
        SELECT o.customer_id, oi.product_id, p.name AS product_name, p.category, p.price, p.stock, p.skin_types,
               MAX(o.created_at) AS last_bought, SUM(oi.quantity) AS units
        FROM order_items oi JOIN orders o ON o.id = oi.order_id AND o.status IN ('delivered', 'shipped',
             'out_for_delivery', 'placed')
        JOIN products p ON p.id = oi.product_id
        GROUP BY o.customer_id, oi.product_id""")
    now = pd.to_datetime(db.query_one("SELECT MAX(created_at) AS t FROM orders")["t"])
    df["days_since"] = (now - pd.to_datetime(df.last_bought)).dt.days
    return df


def _best_in_category(category: str, skin_type: str | None) -> dict | None:
    rows = db.query_df("SELECT id, name, price, rating, skin_types FROM products WHERE category = ? AND stock > 0 "
                       "AND is_active = 1 ORDER BY rating DESC", (category,)).to_dict("records")
    suits = [r for r in rows if not skin_type or skin_type in r["skin_types"] or "all" in r["skin_types"]]
    return (suits or rows or [None])[0]


def replenishment(base: pd.DataFrame, purchases: pd.DataFrame) -> pd.DataFrame:
    p = purchases[purchases.stock > 0].copy()
    p["cycle"] = p.category.map(REFILL_DAYS).fillna(50) * p.units.clip(upper=2)
    due = p[(p.days_since >= p.cycle - 7) & (p.days_since <= p.cycle + 21)]
    due = due.assign(overdue=due.days_since - due.cycle).sort_values("overdue", ascending=False)
    due = due.drop_duplicates("customer_id")
    out = base.merge(due[["customer_id", "product_id", "product_name", "price", "days_since"]], on="customer_id")
    out["reason"] = "bought " + out.product_name + " " + out.days_since.astype(str) + " days ago"
    return out


def win_back(base: pd.DataFrame, purchases: pd.DataFrame) -> pd.DataFrame:
    cand = base[base.segment.isin(WIN_BACK_SEGMENTS) & (base.recency_days.between(45, 240))]
    fav = purchases[purchases.stock > 0].sort_values("units", ascending=False).drop_duplicates("customer_id")
    out = cand.merge(fav[["customer_id", "product_id", "product_name", "price"]], on="customer_id")
    out["days_since"] = out.recency_days
    out["reason"] = out.segment + ", last order " + out.recency_days.astype(str) + " days ago"
    return out


def cross_sell(base: pd.DataFrame, purchases: pd.DataFrame) -> pd.DataFrame:
    recent = purchases[purchases.days_since <= 120]
    # "Already has it" counts EVERY non-cancelled order: a sunscreen they returned or refused at the door
    # is not something to cross-sell them again.
    bought = db.query_df("""SELECT DISTINCT o.customer_id, p.category FROM order_items oi
                            JOIN orders o ON o.id = oi.order_id AND o.status != 'cancelled'
                            JOIN products p ON p.id = oi.product_id""").groupby("customer_id").category.apply(set)
    rows = []
    for cid, g in recent.sort_values("units", ascending=False).groupby("customer_id"):
        for cat in g.category:
            target = COMPLEMENTS.get(cat)
            if target and target not in bought.get(cid, set()):
                rows.append({"customer_id": cid, "from_category": cat, "target_category": target})
                break
    if not rows:
        return base.iloc[0:0]
    df = pd.DataFrame(rows).merge(base, on="customer_id")
    picks = [_best_in_category(t, s) for t, s in zip(df.target_category, df.skin_type)]
    df["product_id"] = [p["id"] if p else None for p in picks]
    df["product_name"] = [p["name"] if p else None for p in picks]
    df["price"] = [p["price"] if p else None for p in picks]
    df = df.dropna(subset=["product_id"])
    df["days_since"] = df.recency_days
    df["reason"] = "buys " + df.from_category.str.replace("_", " ") + ", never bought " + \
        df.target_category.str.replace("_", " ")
    return df.drop(columns=["from_category", "target_category"])


def second_order(base: pd.DataFrame, purchases: pd.DataFrame) -> pd.DataFrame:
    cand = base[(base.frequency == 1) & base.recency_days.between(10, 30)]
    first = purchases.sort_values("units", ascending=False).drop_duplicates("customer_id")
    df = cand.merge(first[["customer_id", "category"]], on="customer_id")
    picks = [_best_in_category(COMPLEMENTS.get(c, "serum"), s) for c, s in zip(df.category, df.skin_type)]
    df["product_id"] = [p["id"] if p else None for p in picks]
    df["product_name"] = [p["name"] if p else None for p in picks]
    df["price"] = [p["price"] if p else None for p in picks]
    df = df.dropna(subset=["product_id"]).drop(columns="category")
    df["days_since"] = df.recency_days
    df["reason"] = "first order " + df.recency_days.astype(str) + " days ago"
    return df


BUILDERS = {"replenishment": replenishment, "win_back": win_back, "cross_sell": cross_sell, "second_order": second_order}
COLUMNS = ["customer_id", "first_name", "language", "skin_type", "segment", "churn_risk", "clv_12m", "aov", "complaints",
           "product_id", "product_name", "price", "days_since", "reason"]


def audience(journey: str) -> pd.DataFrame:
    base, purchases = _base(), _purchases()
    df = BUILDERS[journey](base, purchases)
    df = df.assign(journey=journey)
    df["product_id"] = df.product_id.astype(int)
    return df[COLUMNS + ["journey"]].reset_index(drop=True)


def audience_from_segment(sql: str) -> pd.DataFrame:
    """A saved Phase 5 segment as an audience; each customer gets their favourite in-stock product."""
    from kotler.ml.segment_builder import run_query

    ids = set(run_query(sql).customer_id)
    base, purchases = _base(), _purchases()
    base = base[base.customer_id.isin(ids)]
    fav = purchases[purchases.stock > 0].sort_values("units", ascending=False).drop_duplicates("customer_id")
    df = base.merge(fav[["customer_id", "product_id", "product_name", "price"]], on="customer_id")
    df["days_since"] = df.recency_days
    df["reason"] = "in saved segment"
    return df[COLUMNS].assign(journey="segment").reset_index(drop=True)


def journey_overview() -> pd.DataFrame:
    rows = []
    for j, desc in JOURNEYS.items():
        a = audience(j)
        rows.append({"journey": j, "description": desc, "customers": len(a),
                     "avg_churn_risk": round(float(a.churn_risk.mean()), 2) if len(a) else None,
                     "value_12m": round(float(a.clv_12m.sum()), 0) if len(a) else 0})
    return pd.DataFrame(rows)
