"""Customers API (R3): searchable customer list and the Customer 360 view."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from kotler import crm, db
from kotler.api.auth import require_user
from kotler.api.common import ensure_ml, records, table_exists

router = APIRouter(prefix="/api/v1/customers", dependencies=[Depends(require_user)])

SORTS = {"value": "lifetime_value DESC", "recent": "last_order_at DESC", "orders": "orders DESC",
         "churn": "churn_risk DESC", "name": "name ASC", "clv": "clv_12m DESC"}

BASE = f"""
WITH stats AS (
  SELECT customer_id,
         COUNT(*) FILTER (WHERE {crm.LIVE}) AS orders,
         COUNT(*) FILTER (WHERE source = 'ai_chat' AND {crm.LIVE}) AS ai_orders,
         COALESCE(SUM(total) FILTER (WHERE status = 'delivered'), 0) AS lifetime_value,
         MAX(created_at) AS last_order_at
  FROM orders GROUP BY customer_id)
SELECT c.id, c.name, c.city, c.state, p.tier, c.skin_type, c.preferred_language AS language,
       c.acquisition_channel AS channel, c.created_at,
       COALESCE(s.orders, 0) AS orders, COALESCE(s.ai_orders, 0) AS ai_orders,
       COALESCE(s.lifetime_value, 0) AS lifetime_value, s.last_order_at,
       sc.segment, sc.churn_risk, sc.clv_12m, sc.value_at_risk
FROM customers c
JOIN pincodes p ON p.pincode = c.pincode
LEFT JOIN stats s ON s.customer_id = c.id
LEFT JOIN customer_scores sc ON sc.customer_id = c.id
"""


@router.get("")
def list_customers(q: str | None = Query(None, max_length=80), segment: str | None = None,
                   tier: int | None = Query(None, ge=1, le=3), sort: str = "value", via_ai: bool = False,
                   page: int = Query(1, ge=1), page_size: int = Query(25, ge=5, le=100)) -> dict:
    ensure_ml()
    where, params = [], {}
    if q:
        where.append("(c.name LIKE :q OR c.city LIKE :q OR c.phone LIKE :q OR c.email LIKE :q)")
        params["q"] = f"%{q.strip()}%"
    if segment:
        where.append("sc.segment = :segment")
        params["segment"] = segment
    if via_ai:   # bought from a product card in an AI conversation (signed link, see kotler/store.py)
        where.append("s.ai_orders > 0")
    if tier:
        where.append("p.tier = :tier")
        params["tier"] = tier
    sql = BASE + (" WHERE " + " AND ".join(where) if where else "")
    total = db.query_one(f"SELECT COUNT(*) AS n FROM ({sql})", params)["n"]
    order = SORTS.get(sort, SORTS["value"])
    rows = db.query_df(f"SELECT * FROM ({sql}) ORDER BY {order} NULLS LAST, id LIMIT :lim OFFSET :off",
                       {**params, "lim": page_size, "off": (page - 1) * page_size})
    segs = db.query_df("SELECT segment, COUNT(*) AS customers, ROUND(AVG(churn_risk), 3) AS churn_risk, "
                       "ROUND(SUM(value_at_risk)) AS value_at_risk FROM customer_scores GROUP BY segment "
                       "ORDER BY customers DESC")
    return {"total": total, "page": page, "page_size": page_size, "customers": records(rows),
            "segments": records(segs)}


@router.get("/{customer_id}")
def customer_360(customer_id: int) -> dict:
    ensure_ml()
    c = db.query_one(BASE + " WHERE c.id = :id", {"id": customer_id})
    if not c:
        raise HTTPException(404, "Customer not found.")
    contact = db.query_one("SELECT phone, email, pincode FROM customers WHERE id = ?", (customer_id,))
    scores = db.query_one("SELECT * FROM customer_scores WHERE customer_id = ?", (customer_id,)) or {}
    features = (db.query_one("SELECT frequency, aov, recency_days, tenure_days, cod_share, rto_count, returns_count, "
                             "coupon_share, avg_days_between_orders, categories_bought, top_category, tickets, complaints "
                             "FROM customer_features WHERE customer_id = ?", (customer_id,))
                if table_exists("customer_features") else None) or {}
    orders = db.query_df("""SELECT o.id, o.order_number, o.created_at, o.status, o.payment_method, o.total, o.discount,
                                   o.coupon_code, o.courier, o.delivered_at, o.source,
                                   (SELECT GROUP_CONCAT(p.name || ' ×' || i.quantity, ', ') FROM order_items i
                                    JOIN products p ON p.id = i.product_id WHERE i.order_id = o.id) AS items
                            FROM orders o WHERE o.customer_id = ? ORDER BY o.created_at DESC LIMIT 50""", (customer_id,))
    monthly = db.query_df(f"""SELECT substr(created_at, 1, 7) AS month, ROUND(SUM(total)) AS spend, COUNT(*) AS orders
                              FROM orders WHERE customer_id = ? AND {crm.LIVE} GROUP BY month ORDER BY month""",
                          (customer_id,))
    tickets = db.query_df("""SELECT id, created_at, channel, category, priority, status, message, resolved_by
                             FROM support_tickets WHERE customer_id = ? ORDER BY created_at DESC""", (customer_id,))
    from kotler.channels import core
    core.ensure_tables()
    chats = db.query_df("""SELECT channel, external_id, display_name, handler, needs_human, last_inbound_at
                           FROM channel_users WHERE customer_id = ? ORDER BY last_inbound_at DESC""", (customer_id,))
    convs = db.query_df("""SELECT v.id, v.agent, v.channel, v.created_at,
                                  (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = v.id AND m.role = 'user') AS turns
                           FROM conversations v WHERE v.customer_id = ? ORDER BY v.id DESC LIMIT 10""", (customer_id,))
    campaigns = (db.query_df("""SELECT c.id, c.name, c.journey, m.grp, m.converted, m.revenue, c.status
                                FROM campaign_members m JOIN campaigns c ON c.id = m.campaign_id
                                WHERE m.customer_id = ? ORDER BY c.id DESC""", (customer_id,))
                 if table_exists("campaign_members") else None)
    top = crm.customer_top_products(customer_id)
    from kotler.ml.segments import SEGMENTS
    seg = scores.get("segment")
    return {"customer": {**c, **contact}, "scores": scores, "features": features,
            "segment_info": {"description": SEGMENTS[seg][0], "action": SEGMENTS[seg][1]} if seg in SEGMENTS else None,
            "orders": records(orders), "monthly": records(monthly), "tickets": records(tickets),
            "chats": records(chats), "conversations": records(convs),
            "campaigns": records(campaigns) if campaigns is not None else [], "top_products": records(top)}
