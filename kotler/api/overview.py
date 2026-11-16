"""GET /api/v1/overview: everything the Overview screen needs, in ONE request.

API design choice: one endpoint per SCREEN ("backend for frontend"), not one per table. The page loads with a
single round trip and the browser never assembles business logic from raw rows. The numbers come from the same
functions the Streamlit dashboard uses (kotler.crm), so both always agree.

"Today" is the newest order in the data, not the real date: the demo data ends on a fixed day.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query

from kotler import crm, db
from kotler.api.auth import require_user

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_user)])


def _day(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%d")


def _delta(cur: float, prev: float) -> float | None:
    return None if not prev else (cur - prev) / prev


def _records(df) -> list[dict]:
    return df.astype(object).where(df.notna(), None).to_dict("records")


@router.get("/overview")
def overview(days: int = Query(30, ge=7, le=365)) -> dict:
    # Whole days only: a window starting at 22:05 would make its first day look like a crash.
    end = datetime.fromisoformat(crm.data_end()[:10]) + timedelta(days=1)
    start, prev_start = end - timedelta(days=days), end - timedelta(days=2 * days)
    cur = crm.kpis(start.isoformat(" "), end.isoformat(" "))
    prev = crm.kpis(prev_start.isoformat(" "), start.isoformat(" "))
    p = {"s": start.isoformat(" "), "e": end.isoformat(" ")}

    kpis = []
    for key, label, fmt, good_up in (("net_revenue", "Net revenue", "inr", True), ("orders", "Orders", "int", True),
                                     ("aov", "Avg order value", "inr", True), ("new_buyers", "New customers", "int", True),
                                     ("rto_rate", "COD return-to-origin", "pct", False)):
        kpis.append({"key": key, "label": label, "value": cur[key], "previous": prev[key],
                     "delta": _delta(cur[key], prev[key]), "format": fmt, "good_when_up": good_up})

    daily = db.query_df(f"""
        SELECT substr(created_at, 1, 10) AS day,
               ROUND(COALESCE(SUM(total) FILTER (WHERE status = 'delivered'), 0)) AS net_revenue,
               ROUND(COALESCE(SUM(total) FILTER (WHERE {crm.LIVE}), 0)) AS gmv,
               COUNT(*) FILTER (WHERE {crm.LIVE}) AS orders
        FROM orders WHERE created_at >= :s AND created_at < :e GROUP BY day ORDER BY day""", p)
    # Days without orders still belong on the chart (a gap is information).
    all_days = [_day(start + timedelta(days=i)) for i in range(days)]
    by_day = {r["day"]: r for r in daily.to_dict("records")}
    daily_rows = [{"day": d, **{k: by_day.get(d, {}).get(k, 0) for k in ("gmv", "net_revenue", "orders")}}
                  for d in all_days]

    monthly = crm.monthly_summary().tail(12)
    top = db.query_df(f"""
        SELECT p.name, p.category, p.image_url, SUM(oi.quantity) AS units, ROUND(SUM(oi.quantity * oi.unit_price)) AS revenue
        FROM order_items oi JOIN orders o ON o.id = oi.order_id AND o.{crm.LIVE}
        JOIN products p ON p.id = oi.product_id
        WHERE o.created_at >= :s AND o.created_at < :e
        GROUP BY p.id ORDER BY revenue DESC LIMIT 6""", p)
    cats = db.query_df(f"""
        SELECT p.category, ROUND(SUM(oi.quantity * oi.unit_price)) AS revenue
        FROM order_items oi JOIN orders o ON o.id = oi.order_id AND o.{crm.LIVE}
        JOIN products p ON p.id = oi.product_id
        WHERE o.created_at >= :s AND o.created_at < :e GROUP BY p.category ORDER BY revenue DESC""", p)

    support = crm.support_summary()
    try:
        approvals = db.query_one("SELECT COUNT(*) AS n FROM order_actions WHERE status = 'pending_approval'")["n"]
    except Exception:
        approvals = 0
    from kotler.channels import core
    from kotler.obs import metrics
    core.ensure_tables()
    inbox = db.query_one("""SELECT COUNT(*) AS chats, COALESCE(SUM(needs_human), 0) AS needs_human,
                                   COALESCE(SUM(handler = 'human'), 0) AS human FROM channel_users""")
    ai = metrics.summary(days)

    return {
        "period": {"days": days, "start": _day(start), "end": _day(end - timedelta(seconds=1))},
        "kpis": kpis,
        "repeat_rate_90d": crm.repeat_rate_90d()["rate"],
        "daily": daily_rows,
        "monthly": _records(monthly[["month", "net_revenue", "orders", "new_buyers", "returning_buyers"]]),
        "top_products": _records(top),
        "categories": _records(cats),
        "support": {"open": support["open"], "escalated": support["escalated"],
                    "ai_resolved_share": support["ai_share"], "avg_resolution_hours": support["avg_hours"],
                    "pending_approvals": approvals},
        "inbox": inbox,
        "ai": {k: ai[k] for k in ("agent_turns", "conversations", "p95_s", "guard_rate", "escalation_rate", "cost_inr")},
        "insights": insights(cur, prev, days),
    }


def inr(x: float) -> str:
    """Indian digit grouping: 4,39,774 (lakh, crore), not 439,774."""
    n = f"{abs(x):.0f}"
    head, tail = n[:-3], n[-3:]
    while len(head) > 2:
        tail, head = head[-2:] + "," + tail, head[:-2]
    return ("-" if x < 0 else "") + "₹" + (f"{head},{tail}" if head else tail)


def insights(cur: dict, prev: dict, days: int) -> list[dict]:
    """Three plain-English observations, computed (not written by an LLM: these must always be right)."""
    out = []
    d = _delta(cur["net_revenue"], prev["net_revenue"])
    if d is not None:
        trend = "flat" if abs(d) < 0.01 else f"{'up' if d > 0 else 'down'} {abs(d):.0%}"
        out.append({"tone": "neutral" if abs(d) < 0.01 else "good" if d > 0 else "bad", "title": f"Revenue {trend}",
                    "body": f"{inr(cur['net_revenue'])} delivered in the last {days} days vs {inr(prev['net_revenue'])} "
                            "in the period before. Recent orders still in transit aren't counted yet."})
    tiers = crm.rto_by_tier()
    cod = tiers[tiers.payment_method == "cod"].sort_values("rto_pct", ascending=False)
    if not cod.empty:
        w = cod.iloc[0]
        out.append({"tone": "warn", "title": f"{w.city_tier} COD refusals: {w.rto_pct:.0f}%",
                    "body": f"The highest return-to-origin rate across city tiers ({int(w.shipments)} COD shipments). "
                            "Confirming these orders on WhatsApp before shipping is the cheapest fix."})
    rep = crm.repeat_rate_90d()
    out.append({"tone": "neutral", "title": f"{rep['rate']:.0%} buy again within 90 days",
                "body": f"Of {rep['customers']} customers whose first order is at least 90 days old. Retention "
                        "journeys target the rest."})
    return out
