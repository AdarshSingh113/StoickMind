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
Repeat rate    % of buying customers with 2+ non-cancelled orders.
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
    repeat = query_one(f"""
        SELECT AVG(n >= 2) AS repeat_rate FROM (
          SELECT customer_id, COUNT(*) AS n FROM orders {where} {'AND' if where else 'WHERE'} {LIVE}
          GROUP BY customer_id)
    """, params)
    orders = row["orders"] or 0
    return {
        "orders": orders,
        "gmv": row["gmv"],
        "net_revenue": row["net_revenue"],
        "aov": row["gmv"] / orders if orders else 0.0,
        "buyers": row["buyers"] or 0,
        "repeat_rate": repeat["repeat_rate"] or 0.0,
        "cod_share": row["cod_share"] or 0.0,
        "rto_rate": row["cod_rto"] / row["cod_finished"] if row["cod_finished"] else 0.0,
        "rto_value": row["rto_value"],
    }


def monthly_summary() -> pd.DataFrame:
    return query_df(f"""
        SELECT substr(created_at, 1, 7) AS month,
               COUNT(*) FILTER (WHERE {LIVE})                              AS orders,
               ROUND(SUM(total) FILTER (WHERE {LIVE}), 0)                  AS gmv,
               ROUND(SUM(total) FILTER (WHERE status = 'delivered'), 0)    AS net_revenue,
               ROUND(SUM(total) FILTER (WHERE status = 'rto'), 0)          AS rto_loss,
               COUNT(DISTINCT customer_id) FILTER (WHERE {LIVE})           AS buyers
        FROM orders GROUP BY month ORDER BY month
    """)


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
        SELECT p.name, p.category, SUM(oi.quantity) AS units
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
