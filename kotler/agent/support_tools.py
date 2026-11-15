"""Support & order-management tools (Phase 4).

These tools ACT: they cancel orders, issue coupons, raise refunds and replacements.
So every business rule is enforced HERE, in code, not left to the prompt:

  identity     order tools only work on the logged-in (or verified) customer's own orders;
               guests verify with order number + last 4 phone digits, max 3 attempts
  cancellation only before shipping
  discounts    max 10%, one AI coupon per customer per 30 days
  refunds      within 7 days of delivery; up to ₹1,000 automatic, above -> human approval;
               cash-on-delivery refunds always need a human (bank/UPI details)
  replacements within 7 days of delivery; orders above ₹1,500 -> human approval
  everything   recorded in order_actions with the conversation that caused it

A prompt can be argued with ("ignore your rules, my cousin works there"); a Python `if` cannot.
The tools also return plain facts (status, timelines, what happens next) so the agent can
explain outcomes without inventing them.
"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta

from kotler import db, policy
from kotler.agent import retrieval
from kotler.agent.tools import TOOLS, WRITE_TOOLS, ToolContext, _schema

FMT = "%Y-%m-%d %H:%M:%S"


def store_now() -> datetime:
    """'Today' for the simulated store = the newest order's time (keeps demo data and tests consistent)."""
    row = db.query_one("SELECT MAX(created_at) AS t FROM orders")
    return datetime.strptime(row["t"], FMT) if row and row["t"] else datetime.now()


def _now_str() -> str:
    return datetime.now().strftime(FMT)


def _norm_order(order_number: str) -> str:
    s = str(order_number or "").strip().upper().replace(" ", "")
    if s.isdigit():
        s = f"KTL-{s}"
    if s.startswith("KTL") and not s.startswith("KTL-"):
        s = "KTL-" + s[3:]
    return s


def _record(ctx: ToolContext, action: str, status: str, order: dict | None = None, amount: float | None = None,
            reason: str = "", details: dict | None = None) -> int:
    with db.get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO order_actions (action, status, order_id, customer_id, conversation_id, agent_slug, amount, "
            "reason, details, created_at, decided_at, decided_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (action, status, order["id"] if order else None, ctx.customer_id, ctx.conversation_id, ctx.agent_slug,
             amount, reason[:500] if reason else None, json.dumps(details or {}), _now_str(),
             _now_str() if status == "done" else None, "auto" if status == "done" else None))
        return cur.lastrowid


NOT_VERIFIED = {"error": "Customer not verified. Ask for the order number and the last 4 digits of the phone "
                         "number used for the order, then call verify_order."}


def _owned_order(ctx: ToolContext, order_number: str) -> tuple[dict | None, dict | None]:
    """The order, if it belongs to the current customer. Never reveals whether someone else's order exists."""
    if ctx.customer_id is None:
        return None, NOT_VERIFIED
    order = db.query_one("SELECT * FROM orders WHERE order_number = ? AND customer_id = ?",
                         (_norm_order(order_number), ctx.customer_id))
    if not order:
        return None, {"error": f"No order {_norm_order(order_number)} found on this customer's account. "
                               "Ask them to check the number (format KTL-123456)."}
    return order, None


def _items(order_id: int) -> list[dict]:
    return db.query_df("""SELECT p.name, oi.quantity, oi.unit_price FROM order_items oi
                          JOIN products p ON p.id = oi.product_id WHERE oi.order_id = ?""", (order_id,)).to_dict("records")


def _days_since_delivery(order: dict) -> float | None:
    if not order.get("delivered_at"):
        return None
    return (store_now() - datetime.strptime(order["delivered_at"], FMT)).total_seconds() / 86400


STATUS_TEXT = {
    "placed": "Order received, being packed. Not shipped yet, so it can still be cancelled.",
    "shipped": "On the way with the courier.",
    "out_for_delivery": "Out for delivery today.",
    "delivered": "Delivered.",
    "cancelled": "Cancelled.",
    "rto": "The courier couldn't deliver it (refused or unreachable) and it is returning to us.",
    "returned": "Returned to us after delivery.",
}


# ------------------------------------------------------------------ tools
def search_policies(ctx: ToolContext, query: str) -> dict:
    hits = retrieval.search_policies(query, top_k=2)
    if not hits:
        return {"results": [], "note": "No matching policy. Don't guess: offer to connect the customer to the team."}
    return {"results": [{"policy": h["policy"], "text": h["text"]} for h in hits]}


def verify_order(ctx: ToolContext, order_number: str, phone_last4: str) -> dict:
    """Guest identity check. On success the conversation is bound to that customer (in code)."""
    if ctx.customer_id is not None:
        return {"verified": True, "note": "Customer is already logged in."}
    if ctx.verify_attempts >= policy.MAX_VERIFY_ATTEMPTS:
        return {"verified": False, "locked": True,
                "note": "Too many failed attempts. Offer to connect the customer to the care team instead."}
    digits = "".join(ch for ch in str(phone_last4) if ch.isdigit())[-4:]
    row = db.query_one("""SELECT c.id, c.name, c.phone FROM orders o JOIN customers c ON c.id = o.customer_id
                          WHERE o.order_number = ?""", (_norm_order(order_number),))
    if row and len(digits) == 4 and row["phone"].endswith(digits):
        ctx.customer_id = row["id"]
        return {"verified": True, "first_name": row["name"].split()[0]}
    ctx.verify_attempts += 1
    # Same answer whether the order doesn't exist or the digits are wrong: don't leak which.
    return {"verified": False, "attempts_left": policy.MAX_VERIFY_ATTEMPTS - ctx.verify_attempts,
            "note": "Order number and phone digits don't match."}


def list_my_orders(ctx: ToolContext, limit: int = 5) -> dict:
    if ctx.customer_id is None:
        return NOT_VERIFIED
    rows = db.query_df("""SELECT id, order_number, created_at, status, total, payment_method FROM orders
                          WHERE customer_id = ? ORDER BY created_at DESC LIMIT ?""",
                       (ctx.customer_id, max(1, min(int(limit or 5), 10)))).to_dict("records")
    for r in rows:
        r["items"] = ", ".join(f"{i['name']} x{i['quantity']}" for i in _items(r.pop("id")))
        r["placed_on"] = r.pop("created_at")[:10]
    return {"orders": rows}


def get_order_status(ctx: ToolContext, order_number: str) -> dict:
    order, err = _owned_order(ctx, order_number)
    if err:
        return err
    now = store_now()
    out = {
        "order_number": order["order_number"], "status": order["status"], "status_meaning": STATUS_TEXT[order["status"]],
        "placed_on": order["created_at"][:10], "payment": order["payment_method"].upper(), "total_inr": order["total"],
        "items": [f"{i['name']} x{i['quantity']}" for i in _items(order["id"])],
        "courier": order["courier"], "tracking_number": order["tracking_number"],
        "expected_delivery": (order["expected_delivery"] or "")[:10] or None,
        "delivered_on": (order["delivered_at"] or "")[:10] or None,
        "can_cancel": order["status"] in policy.CANCELLABLE_STATUSES,
    }
    if order["status"] in ("placed", "shipped", "out_for_delivery") and order["expected_delivery"]:
        late = (now - datetime.strptime(order["expected_delivery"], FMT)).total_seconds() / 86400
        out["days_late"] = round(late, 1) if late > 0 else 0
        if late > 2:
            out["note"] = "More than 2 days late: apologise, and escalate to the care team if the customer wants."
    days = _days_since_delivery(order)
    if days is not None:
        out["return_window_open"] = days <= policy.RETURN_WINDOW_DAYS
    return out


def cancel_order(ctx: ToolContext, order_number: str, reason: str) -> dict:
    order, err = _owned_order(ctx, order_number)
    if err:
        return err
    if order["status"] == "cancelled":
        return {"cancelled": True, "note": "This order was already cancelled."}
    if order["status"] not in policy.CANCELLABLE_STATUSES:
        return {"cancelled": False, "status": order["status"],
                "reason": "Already shipped, so it can't be cancelled. After delivery the customer can raise a "
                          "return under the returns policy."}
    with db.get_conn() as conn:
        conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order["id"],))
    refund = order["payment_method"] == "prepaid"
    _record(ctx, "cancel", "done", order, order["total"] if refund else 0, reason)
    return {"cancelled": True, "order_number": order["order_number"],
            "refund": f"₹{order['total']:,.0f} to the original payment method in 5-7 working days" if refund
            else "Cash on delivery: nothing was paid, so there is nothing to refund."}


def offer_discount(ctx: ToolContext, percent: int, reason: str) -> dict:
    if ctx.customer_id is None:
        return NOT_VERIFIED
    pct = int(percent)
    if pct < 1 or pct > policy.MAX_DISCOUNT_PCT:
        return {"issued": False, "error": f"Not allowed. The maximum discount you may offer is {policy.MAX_DISCOUNT_PCT}%."}
    since = (datetime.now() - timedelta(days=policy.DISCOUNT_COOLDOWN_DAYS)).strftime(FMT)
    recent = db.query_one("SELECT code, pct, expires_at FROM coupons_issued WHERE customer_id = ? AND created_at >= ? "
                          "ORDER BY created_at DESC", (ctx.customer_id, since))
    if recent:
        return {"issued": False, "existing_coupon": recent["code"], "pct": recent["pct"],
                "note": f"Customer already received an AI coupon in the last {policy.DISCOUNT_COOLDOWN_DAYS} days; "
                        "share that code instead of a new one."}
    code = f"CARE{pct}-{secrets.token_hex(3).upper()}"
    expires = (datetime.now() + timedelta(days=policy.COUPON_VALID_DAYS)).strftime(FMT)
    with db.get_conn() as conn:
        conn.execute("INSERT INTO coupons_issued (code, customer_id, pct, reason, conversation_id, created_at, expires_at) "
                     "VALUES (?,?,?,?,?,?,?)", (code, ctx.customer_id, pct, reason[:300], ctx.conversation_id,
                                                _now_str(), expires))
    _record(ctx, "coupon", "done", None, None, reason, {"code": code, "pct": pct})
    return {"issued": True, "code": code, "pct": pct, "valid_until": expires[:10],
            "note": "Valid on the next order, one coupon per order."}


def _match_item(order_id: int, product_name: str | None) -> tuple[dict | None, list[str]]:
    items = _items(order_id)
    names = [i["name"] for i in items]
    if not product_name:
        return None, names
    q = product_name.lower()
    for i in items:
        if q in i["name"].lower() or i["name"].lower() in q or any(w in i["name"].lower() for w in q.split() if len(w) > 4):
            return i, names
    return None, names


def _existing(order_id: int, action: str) -> dict | None:
    return db.query_one("SELECT id, status, amount FROM order_actions WHERE order_id = ? AND action = ? "
                        "AND status != 'rejected' ORDER BY id DESC", (order_id, action))


def report_damaged_item(ctx: ToolContext, order_number: str, product_name: str, issue: str) -> dict:
    order, err = _owned_order(ctx, order_number)
    if err:
        return err
    days = _days_since_delivery(order)
    if days is None:
        return {"accepted": False, "reason": f"Order isn't delivered yet (status: {order['status']})."}
    if days > policy.RETURN_WINDOW_DAYS:
        return {"accepted": False, "reason": f"Reported {days:.0f} days after delivery; the window is "
                                             f"{policy.RETURN_WINDOW_DAYS} days. Offer to connect the care team."}
    item, names = _match_item(order["id"], product_name)
    if not item:
        return {"accepted": False, "reason": "That product isn't in this order.", "items_in_order": names}
    prev = _existing(order["id"], "replacement")
    if prev:
        return {"accepted": True, "already_raised": True, "reference": f"RPL-{prev['id']}", "status": prev["status"]}
    needs_human = order["total"] > policy.REPLACEMENT_AUTO_LIMIT
    status = "pending_approval" if needs_human else "done"
    ref = _record(ctx, "replacement", status, order, item["unit_price"] * item["quantity"], issue,
                  {"product": item["name"], "quantity": item["quantity"]})
    return {"accepted": True, "reference": f"RPL-{ref}", "product": item["name"],
            "status": "approved: free replacement ships within 2 working days" if not needs_human
            else "sent to our care team for confirmation within 24 hours (high-value order)"}


def request_refund(ctx: ToolContext, order_number: str, reason: str, product_name: str | None = None) -> dict:
    order, err = _owned_order(ctx, order_number)
    if err:
        return err
    if order["status"] == "cancelled":
        return {"accepted": False, "reason": "Cancelled order: any prepaid amount is refunded automatically."}
    days = _days_since_delivery(order)
    if days is None:
        return {"accepted": False, "reason": f"Order isn't delivered yet (status: {order['status']}). "
                                             "Before shipping it can be cancelled instead."}
    if days > policy.RETURN_WINDOW_DAYS:
        return {"accepted": False, "reason": f"Requested {days:.0f} days after delivery; refunds must be requested "
                                             f"within {policy.RETURN_WINDOW_DAYS} days. Offer to connect the care team."}
    item, names = _match_item(order["id"], product_name) if product_name else (None, [])
    if product_name and not item:
        return {"accepted": False, "reason": "That product isn't in this order.", "items_in_order": names}
    amount = item["unit_price"] * item["quantity"] if item else order["total"]
    prev = _existing(order["id"], "refund")
    if prev:
        return {"accepted": True, "already_raised": True, "reference": f"REF-{prev['id']}", "status": prev["status"]}
    cod = order["payment_method"] == "cod"
    needs_human = cod or amount > policy.AUTO_REFUND_LIMIT
    status = "pending_approval" if needs_human else "done"
    ref = _record(ctx, "refund", status, order, amount, reason, {"product": item["name"] if item else "whole order"})
    if not needs_human:
        outcome = f"approved: ₹{amount:,.0f} to the original payment method in 5-7 working days"
    elif cod:
        outcome = "sent to our care team: cash on delivery refunds go by UPI/bank transfer, they'll confirm details within 24 hours"
    else:
        outcome = f"sent to our care team for approval within 24 hours (above ₹{policy.AUTO_REFUND_LIMIT:,.0f})"
    return {"accepted": True, "reference": f"REF-{ref}", "amount_inr": amount, "status": outcome}


def escalate_to_human(ctx: ToolContext, summary: str, priority: str = "medium", order_number: str | None = None) -> dict:
    priority = priority if priority in ("low", "medium", "high") else "medium"
    order = None
    if order_number and ctx.customer_id is not None:
        order, _ = _owned_order(ctx, order_number)
    ticket_id = None
    if ctx.customer_id is not None:
        with db.get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO support_tickets (customer_id, order_id, created_at, channel, category, priority, status, "
                "message) VALUES (?,?,?,?,?,?,?,?)",
                (ctx.customer_id, order["id"] if order else None, _now_str(), "website_chat", "escalated_by_ai",
                 priority, "escalated", f"[AI handoff] {summary[:900]}"))
            ticket_id = cur.lastrowid
    ref = _record(ctx, "escalation", "pending_approval", order, None, summary, {"priority": priority, "ticket_id": ticket_id})
    wait = "within 1 hour" if priority == "high" else "within 4 working hours"
    out = {"escalated": True, "reference": f"ESC-{ref}", "a_human_will_reply": wait}
    if ctx.customer_id is None:
        out["note"] = "Guest: ask for a phone number or email so the team can reach them."
    return out


# -------------------------------------------------------- human decisions
def pending_actions():
    return db.query_df("""SELECT a.id, a.action, a.amount, a.reason, a.details, a.created_at, a.agent_slug,
                                 o.order_number, o.payment_method, c.name AS customer
                          FROM order_actions a LEFT JOIN orders o ON o.id = a.order_id
                          LEFT JOIN customers c ON c.id = a.customer_id
                          WHERE a.status = 'pending_approval' ORDER BY a.id DESC""")


def decide_action(action_id: int, approve: bool, reviewer: str = "care team") -> dict:
    row = db.query_one("SELECT * FROM order_actions WHERE id = ?", (action_id,))
    if not row or row["status"] != "pending_approval":
        return {"ok": False, "error": "Action not found or already decided."}
    with db.get_conn() as conn:
        conn.execute("UPDATE order_actions SET status = ?, decided_at = ?, decided_by = ? WHERE id = ?",
                     ("approved" if approve else "rejected", _now_str(), reviewer, action_id))
        details = json.loads(row["details"] or "{}")
        if row["action"] == "escalation" and details.get("ticket_id"):
            conn.execute("UPDATE support_tickets SET status = 'resolved', resolved_at = ?, resolved_by = 'human' "
                         "WHERE id = ?", (_now_str(), details["ticket_id"]))
    return {"ok": True}


# ------------------------------------------------------------- registry
ORDER = {"type": "string", "description": "Order number like KTL-103245 (the customer may type just the digits)."}

TOOLS.update({
    "search_policies": (search_policies, _schema(
        "search_policies",
        "Look up the store's official policies (shipping times, cancellation, returns, refunds, damaged items, "
        "allergic reactions, discounts, cash on delivery, support hours). ALWAYS use before stating any policy, "
        "time window or timeline.",
        {"query": {"type": "string", "description": "What the customer asked about, e.g. 'refund for damaged serum'."}},
        ["query"])),
    "verify_order": (verify_order, _schema(
        "verify_order",
        "Verify a guest (not logged in) before discussing their order: needs the order number and the last 4 digits "
        "of the phone number used for the order.",
        {"order_number": ORDER, "phone_last4": {"type": "string", "description": "Last 4 digits of the phone number."}},
        ["order_number", "phone_last4"])),
    "list_my_orders": (list_my_orders, _schema(
        "list_my_orders", "The verified customer's recent orders (number, date, status, total, items).",
        {"limit": {"type": "integer", "description": "How many (1-10, default 5)."}})),
    "get_order_status": (get_order_status, _schema(
        "get_order_status", "Full status of one order: courier, tracking, expected delivery, whether it can be "
                            "cancelled, whether the return window is open.", {"order_number": ORDER}, ["order_number"])),
    "cancel_order": (cancel_order, _schema(
        "cancel_order", "Cancel an order that hasn't shipped yet. Only after the customer confirms they still want to "
                        "cancel.", {"order_number": ORDER, "reason": {"type": "string"}}, ["order_number", "reason"])),
    "offer_discount": (offer_discount, _schema(
        "offer_discount", f"Issue a one-time coupon for the customer's next order (max {policy.MAX_DISCOUNT_PCT}%, once per "
                          f"{policy.DISCOUNT_COOLDOWN_DAYS} days). Use sparingly, e.g. to keep an order or apologise "
                          "for a real problem.",
        {"percent": {"type": "integer", "description": f"1-{policy.MAX_DISCOUNT_PCT}"}, "reason": {"type": "string"}},
        ["percent", "reason"])),
    "report_damaged_item": (report_damaged_item, _schema(
        "report_damaged_item", "Raise a free replacement for a damaged, leaking, broken or wrong item "
                               f"(within {policy.RETURN_WINDOW_DAYS} days of delivery).",
        {"order_number": ORDER, "product_name": {"type": "string", "description": "Which product was affected."},
         "issue": {"type": "string", "description": "What was wrong, in the customer's words."}},
        ["order_number", "product_name", "issue"])),
    "request_refund": (request_refund, _schema(
        "request_refund", f"Raise a refund for a delivered order or one product in it (within {policy.RETURN_WINDOW_DAYS} "
                          "days of delivery). Small prepaid refunds are approved instantly; others go to the care team.",
        {"order_number": ORDER, "reason": {"type": "string"},
         "product_name": {"type": "string", "description": "Optional: refund only this product."}},
        ["order_number", "reason"])),
    "escalate_to_human": (escalate_to_human, _schema(
        "escalate_to_human", "Hand the conversation to a human on the care team. Use when the customer is angry or asks "
                             "for a human, mentions legal action, has a medical reaction, or the request is outside "
                             "what your tools allow.",
        {"summary": {"type": "string", "description": "What happened and what the customer wants, for the human."},
         "priority": {"type": "string", "enum": ["low", "medium", "high"]}, "order_number": ORDER},
        ["summary", "priority"])),
})
WRITE_TOOLS.update({"cancel_order", "offer_discount", "report_damaged_item", "request_refund", "escalate_to_human"})
SUPPORT_TOOLS = ["search_policies", "verify_order", "list_my_orders", "get_order_status", "cancel_order",
                 "offer_discount", "report_damaged_item", "request_refund", "escalate_to_human", "get_my_profile"]
