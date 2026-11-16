"""CRM & business-metric queries.

Two consumers use this module:
1. The Streamlit dashboard (humans).
2. The AI agents from Phase 2 onwards (as tools: get_order_status, find_customer, ...).

Metric definitions (write these down — interviewers love asking them)
---------------------------------------------------------------------
GMV            Gross Merchandise Value: value of all orders placed, excluding
               cancellations. "How much did people try to buy?"
Net revenue    Value of orders actually delivered and kept (excludes RTO,
               returns, in-transit). "How much money did we really make?"
AOV            Average order value = GMV / number of non-cancelled orders.
New buyers     Buyers in the period whose first-ever order is in the period.
90-day repeat  Of customers who first bought 90+ days ago, % who bought again
               within 90 days of their first order. Fair to every customer:
               each one gets the same 90-day window. (A naive "2+ orders" rate
               punishes customers who joined yesterday.)
RTO rate       % of finished COD shipments that came back undelivered
               (rto / (delivered + returned + rto)).
"""

from __future__ import annotations

import pandas as pd

from kotler.db import query_df, query_one

LIVE = "status != 'cancelled'"
FINISHED = "status IN ('delivered', 'returned', 'rto')"


# --------------------------------------------------------------- business KPIs
def kpis(start: str | None = None, end: str | None = None) -> dict:
    """Headline numbers for orders created in [start, end) (ISO dates, optional)."""
    where, params = _date_filter(start, end)
    row = query_one(f"""
        SELECT
          COUNT(*) FILTER (WHERE {LIVE})                                AS orders,
          COALESCE(SUM(total) FILTER (WHERE {LIVE}), 0)                 AS gmv,
          COALESCE(SUM(total) FILTER (WHERE status = 'delivered'), 0)   AS net_revenue,
          COUNT(DISTINCT customer_id) FILTER (WHERE {LIVE})             AS buyers,
          AVG(payment_method = 'cod') FILTER (WHERE {LIVE})             AS cod_share,
          COUNT(*) FILTER (WHERE payment_method = 'cod' AND status = 'rto')     AS cod_rto,
          COUNT(*) FILTER (WHERE payment_method = 'cod' AND {FINISHED})         AS cod_finished,
          COALESCE(SUM(total) FILTER (WHERE status = 'rto'), 0)         AS rto_value
        FROM orders {where}
    """, params)
    new = query_one(f"""
        WITH firsts AS (SELECT customer_id, MIN(created_at) AS first_at FROM orders
                        WHERE {LIVE} GROUP BY customer_id)
        SELECT COUNT(*) AS new_buyers FROM firsts
        WHERE first_at >= COALESCE(:start, '0000') AND first_at < COALESCE(:end, '9999')
    """, {"start": start, "end": end})
    orders = row["orders"] or 0
    return {
        "orders": orders,
        "gmv": row["gmv"],
        "net_revenue": row["net_revenue"],
        "aov": row["gmv"] / orders if orders else 0.0,
        "buyers": row["buyers"] or 0,
        "new_buyers": new["new_buyers"] or 0,
        "cod_share": row["cod_share"] or 0.0,
        "rto_rate": row["cod_rto"] / row["cod_finished"] if row["cod_finished"] else 0.0,
        "rto_value": row["rto_value"],
    }


def data_end() -> str:
    """Timestamp of the newest order: our 'today' for period filters."""
    return query_one("SELECT MAX(created_at) AS t FROM orders")["t"]


def repeat_rate_90d(window_days: int = 90) -> dict:
    """% of customers who bought again within `window_days` of their first order.
    Only customers whose first order is at least `window_days` old are counted."""
    row = query_one(f"""
        WITH live AS (SELECT customer_id, created_at FROM orders WHERE {LIVE}),
        firsts AS (SELECT customer_id, MIN(created_at) AS first_at FROM live GROUP BY customer_id),
        eligible AS (SELECT * FROM firsts
                     WHERE julianday((SELECT MAX(created_at) FROM orders)) - julianday(first_at) >= :w)
        SELECT COUNT(*) AS customers,
               AVG(EXISTS (SELECT 1 FROM live l WHERE l.customer_id = e.customer_id
                           AND l.created_at > e.first_at
                           AND julianday(l.created_at) - julianday(e.first_at) <= :w)) AS rate
        FROM eligible e
    """, {"w": window_days})
    return {"customers": row["customers"] or 0, "rate": row["rate"] or 0.0}


def cohort_retention(max_months: int = 6) -> pd.DataFrame:
    """Cohort table: rows = month of first purchase, columns = months later,
    values = % of the cohort that ordered in that month (month 0 is always 100%)."""
    df = query_df(f"""
        WITH live AS (SELECT customer_id, created_at FROM orders WHERE {LIVE}),
        firsts AS (SELECT customer_id, MIN(created_at) AS first_at FROM live GROUP BY customer_id)
        SELECT substr(f.first_at, 1, 7) AS cohort,
               (CAST(substr(l.created_at, 1, 4) AS INT) - CAST(substr(f.first_at, 1, 4) AS INT)) * 12
             + (CAST(substr(l.created_at, 6, 2) AS INT) - CAST(substr(f.first_at, 6, 2) AS INT)) AS month_n,
               COUNT(DISTINCT l.customer_id) AS active
        FROM live l JOIN firsts f USING (customer_id)
        GROUP BY cohort, month_n
    """)
    if df.empty:
        return df
    table = df.pivot(index="cohort", columns="month_n", values="active").fillna(0)
    sizes = table[0]
    pct = table.div(sizes, axis=0).mul(100).round(1)
    pct = pct[[c for c in pct.columns if c <= max_months]].astype(float)
    # Hide cells in the future (cohort too young to have reached that month).
    last = pd.Period(df.cohort.max(), "M")
    for cohort in pct.index:
        age = (last - pd.Period(cohort, "M")).n
        pct.loc[cohort, [c for c in pct.columns if c > age]] = float("nan")
    pct.columns = [f"M{c}" for c in pct.columns]
    pct.insert(0, "customers", sizes.astype(int))
    return pct.reset_index()


def monthly_summary() -> pd.DataFrame:
    df = query_df(f"""
        WITH firsts AS (SELECT customer_id, substr(MIN(created_at), 1, 7) AS first_month
                        FROM orders WHERE {LIVE} GROUP BY customer_id)
        SELECT substr(o.created_at, 1, 7) AS month,
               COUNT(*) FILTER (WHERE o.{LIVE})                              AS orders,
               ROUND(SUM(o.total) FILTER (WHERE o.{LIVE}), 0)                AS gmv,
               ROUND(SUM(o.total) FILTER (WHERE o.status = 'delivered'), 0)  AS net_revenue,
               ROUND(COALESCE(SUM(o.total) FILTER (WHERE o.status = 'rto'), 0), 0) AS rto_loss,
               COUNT(DISTINCT o.customer_id) FILTER (WHERE o.{LIVE})         AS buyers,
               (SELECT COUNT(*) FROM firsts f WHERE f.first_month = substr(o.created_at, 1, 7)) AS new_buyers,
               ROUND(100.0 * AVG(o.status = 'rto') FILTER (WHERE o.payment_method = 'cod' AND o.{FINISHED}), 1)
                                                                             AS cod_rto_pct
        FROM orders o GROUP BY month ORDER BY month
    """)
    df["aov"] = (df.gmv / df.orders).round(0)
    df["returning_buyers"] = df.buyers - df.new_buyers
    df["growth_pct"] = (df.net_revenue.pct_change() * 100).round(1)
    return df


def category_by_month(months: int = 6) -> pd.DataFrame:
    """GMV per product category per month (last `months` months), for a heatmap table."""
    df = query_df(f"""
        SELECT p.category, substr(o.created_at, 1, 7) AS month, ROUND(SUM(oi.quantity * oi.unit_price), 0) AS gmv
        FROM order_items oi JOIN orders o ON o.id = oi.order_id AND o.{LIVE}
        JOIN products p ON p.id = oi.product_id
        GROUP BY p.category, month
    """)
    if df.empty:
        return df
    table = df.pivot(index="category", columns="month", values="gmv").fillna(0)
    table = table[sorted(table.columns)[-months:]]
    return table.loc[table.sum(axis=1).sort_values(ascending=False).index]


def ticket_categories() -> pd.DataFrame:
    return query_df("""SELECT category, COUNT(*) AS tickets,
                              COUNT(*) FILTER (WHERE status != 'resolved') AS unresolved
                       FROM support_tickets GROUP BY category ORDER BY tickets DESC""")


def channel_summary() -> pd.DataFrame:
    """Which acquisition channel brings the most valuable customers?"""
    return query_df(f"""
        SELECT c.acquisition_channel AS channel,
               COUNT(DISTINCT c.id) AS customers,
               ROUND(SUM(o.total) FILTER (WHERE o.status = 'delivered'), 0) AS net_revenue,
               ROUND(1.0 * SUM(o.total) FILTER (WHERE o.status = 'delivered') / COUNT(DISTINCT c.id), 0)
                   AS revenue_per_customer
        FROM customers c LEFT JOIN orders o ON o.customer_id = c.id
        GROUP BY channel ORDER BY net_revenue DESC
    """)


def rto_by_tier() -> pd.DataFrame:
    return query_df(f"""
        SELECT 'Tier ' || p.tier AS city_tier, o.payment_method,
               COUNT(*) AS shipments,
               ROUND(100.0 * AVG(o.status = 'rto'), 1) AS rto_pct
        FROM orders o JOIN pincodes p ON p.pincode = o.shipping_pincode
        WHERE o.{FINISHED}
        GROUP BY p.tier, o.payment_method ORDER BY p.tier, o.payment_method
    """)


# ------------------------------------------------------------------ customers
def customer_summary(search: str | None = None) -> pd.DataFrame:
    """One row per customer with order stats. Basis for RFM in Phase 4."""
    where, params = "", {}
    if search:
        where = "WHERE c.name LIKE :q OR c.phone LIKE :q OR c.email LIKE :q OR c.city LIKE :q"
        params = {"q": f"%{search.strip()}%"}
    return query_df(f"""
        SELECT c.id, c.name, c.phone, c.city, p.tier, c.skin_type, c.preferred_language AS language,
               c.acquisition_channel AS channel, c.created_at,
               COUNT(o.id) FILTER (WHERE o.{LIVE})                              AS orders,
               ROUND(COALESCE(SUM(o.total) FILTER (WHERE o.status = 'delivered'), 0), 0) AS lifetime_value,
               MAX(o.created_at)                                                AS last_order_at,
               CAST(julianday((SELECT MAX(created_at) FROM orders)) - julianday(MAX(o.created_at)) AS INT)
                                                                                AS days_since_last_order
        FROM customers c
        JOIN pincodes p ON p.pincode = c.pincode
        LEFT JOIN orders o ON o.customer_id = c.id
        {where}
        GROUP BY c.id ORDER BY lifetime_value DESC
    """, params)


def get_customer(customer_id: int | None = None, phone: str | None = None) -> dict | None:
    if customer_id is not None:
        return query_one("SELECT * FROM customers WHERE id = ?", (customer_id,))
    if phone:
        digits = "".join(ch for ch in phone if ch.isdigit())[-10:]
        return query_one("SELECT * FROM customers WHERE phone = ?", (digits,))
    return None


def customer_orders(customer_id: int) -> pd.DataFrame:
    return query_df("""
        SELECT o.order_number, o.created_at, o.status, o.payment_method, o.total, o.coupon_code,
               o.courier, o.tracking_number, o.expected_delivery, o.delivered_at,
               GROUP_CONCAT(p.name || ' x' || oi.quantity, ', ') AS items
        FROM orders o
        JOIN order_items oi ON oi.order_id = o.id
        JOIN products p ON p.id = oi.product_id
        WHERE o.customer_id = ?
        GROUP BY o.id ORDER BY o.created_at DESC
    """, (customer_id,))


def customer_tickets(customer_id: int) -> pd.DataFrame:
    return query_df("""
        SELECT t.created_at, t.category, t.priority, t.status, t.channel, t.message, o.order_number
        FROM support_tickets t LEFT JOIN orders o ON o.id = t.order_id
        WHERE t.customer_id = ? ORDER BY t.created_at DESC
    """, (customer_id,))


def customer_top_products(customer_id: int, limit: int = 5) -> pd.DataFrame:
    return query_df("""
        SELECT p.name, p.category, p.image_url, SUM(oi.quantity) AS units
        FROM order_items oi
        JOIN orders o ON o.id = oi.order_id AND o.status != 'cancelled'
        JOIN products p ON p.id = oi.product_id
        WHERE o.customer_id = ?
        GROUP BY p.id ORDER BY units DESC LIMIT ?
    """, (customer_id, limit))


# ------------------------------------------------------------ orders/products
def get_order(order_number: str) -> dict | None:
    """Look up one order. Phase 3's support agent will call this as a tool."""
    return query_one("""
        SELECT o.*, c.name AS customer_name, c.phone AS customer_phone
        FROM orders o JOIN customers c ON c.id = o.customer_id
        WHERE o.order_number = ?
    """, (order_number.strip().upper(),))


def product_performance() -> pd.DataFrame:
    return query_df(f"""
        SELECT p.id, p.sku, p.name, p.category, p.skin_types, p.price, p.stock, p.rating,
               COALESCE(SUM(oi.quantity) FILTER (WHERE o.{LIVE}), 0)                    AS units_sold,
               ROUND(COALESCE(SUM(oi.quantity * oi.unit_price) FILTER (WHERE o.{LIVE}), 0), 0) AS gmv,
               COUNT(DISTINCT o.customer_id) FILTER (WHERE o.{LIVE})                     AS buyers
        FROM products p
        LEFT JOIN order_items oi ON oi.product_id = p.id
        LEFT JOIN orders o ON o.id = oi.order_id
        GROUP BY p.id ORDER BY gmv DESC
    """)


def tickets(status: str | None = None) -> pd.DataFrame:
    where, params = ("WHERE t.status = ?", (status,)) if status else ("", ())
    return query_df(f"""
        SELECT t.id, t.created_at, c.name AS customer, t.channel, t.category, t.priority,
               t.status, t.message, o.order_number, t.resolved_by,
               ROUND((julianday(t.resolved_at) - julianday(t.created_at)) * 24, 1) AS hours_to_resolve
        FROM support_tickets t
        JOIN customers c ON c.id = t.customer_id
        LEFT JOIN orders o ON o.id = t.order_id
        {where} ORDER BY t.created_at DESC
    """, params)


def support_summary() -> dict:
    row = query_one("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status = 'open')      AS open,
               COUNT(*) FILTER (WHERE status = 'escalated') AS escalated,
               AVG((julianday(resolved_at) - julianday(created_at)) * 24) AS avg_hours,
               AVG(resolved_by = 'ai') FILTER (WHERE status = 'resolved') AS ai_share
        FROM support_tickets
    """)
    return {k: (v or 0) for k, v in row.items()}


# --------------------------------------------------------------------- helpers
def _date_filter(start: str | None, end: str | None) -> tuple[str, dict]:
    clauses, params = [], {}
    if start:
        clauses.append("created_at >= :start")
        params["start"] = start
    if end:
        clauses.append("created_at < :end")
        params["end"] = end
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params
