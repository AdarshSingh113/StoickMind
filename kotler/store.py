"""The demo storefront's checkout, and AI attribution: which orders came from an AI agent's recommendation?

Flow: an agent recommends products → the chat shows product cards with a "Buy" link → the link opens
/store/checkout carrying `ref` (the chat it came from, e.g. "telegram:12345") and `sig`, an HMAC signature of
that ref → the order is saved with source = 'ai_chat' and ai_ref = the chat.

Why sign the ref? Anyone can edit a URL. Without a signature, typing ?ref=... would mark any order as
"AI-assisted" and inflate the numbers. A forged or missing signature simply makes it a normal store order.

What checkout deliberately does NOT do: link the chat to the customer. Otherwise someone could open a link from
their own chat, type another person's phone number, and then ask the agent about that person's orders.

This is a DEMO store: no payment is taken and nothing ships. Every page says so.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from datetime import datetime, timedelta
from urllib.parse import quote

from kotler import config, db

MAX_QTY = 3
FMT = "%Y-%m-%d %H:%M:%S"


def _secret() -> bytes:
    from kotler.api.auth import _secret as session_secret
    return b"kotler-attribution:" + session_secret()


def sign(ref: str) -> str:
    return hmac.new(_secret(), ref.encode(), hashlib.sha256).hexdigest()[:20]


def valid_ref(ref: str | None, sig: str | None) -> bool:
    return bool(ref and sig) and hmac.compare_digest(sign(ref), sig)


def buy_link(product_id: int, ref: str | None = None) -> str:
    """Relative checkout link. With a ref (the chat), the order will be attributed to the AI conversation."""
    link = f"/store/checkout?product={int(product_id)}"
    if ref:
        link += f"&ref={quote(ref, safe='')}&sig={sign(ref)}"
    return link


class CheckoutError(ValueError):
    pass


def cities() -> list[dict]:
    return db.query_df("SELECT city, state, MIN(pincode) AS pincode, tier FROM pincodes GROUP BY city "
                       "ORDER BY city").to_dict("records")


def product(product_id: int) -> dict | None:
    return db.query_one("SELECT * FROM products WHERE id = ? AND is_active = 1", (product_id,))


def place_order(product_id: int, quantity: int, name: str, phone: str, pincode: str, address: str,
                payment: str, ref: str | None = None, sig: str | None = None) -> dict:
    p = product(product_id)
    if not p:
        raise CheckoutError("That product isn't available.")
    if p["stock"] < quantity:
        raise CheckoutError("Sorry, not enough stock.")
    if not 1 <= quantity <= MAX_QTY:
        raise CheckoutError(f"You can order 1 to {MAX_QTY}.")
    name = re.sub(r"\s+", " ", name or "").strip()[:60]
    digits = "".join(ch for ch in phone or "" if ch.isdigit())[-10:]
    address = re.sub(r"\s+", " ", address or "").strip()[:200]
    if len(name) < 2:
        raise CheckoutError("Please enter your name.")
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        raise CheckoutError("Please enter a valid 10-digit Indian mobile number.")
    if len(address) < 8:
        raise CheckoutError("Please enter your full address.")
    if payment not in ("cod", "prepaid"):
        raise CheckoutError("Choose cash on delivery or prepaid.")
    pin = db.query_one("SELECT pincode, city, state FROM pincodes WHERE pincode = ?", (pincode,))
    if not pin:
        raise CheckoutError("We don't deliver to that pincode yet.")

    attributed = valid_ref(ref, sig)
    now = datetime.now()
    subtotal = p["price"] * quantity
    shipping = 0.0 if subtotal >= config.FREE_SHIPPING_THRESHOLD else config.SHIPPING_FEE
    full_address = f"{address}, {pin['city']}, {pin['state']} {pin['pincode']}"
    from kotler.ml.rto import address_features
    quality = 0.5 if address_features(full_address)["vague_address"] else 0.9
    with db.get_conn() as conn:
        row = conn.execute("SELECT id FROM customers WHERE phone = ?", (digits,)).fetchone()
        if row:
            customer_id = row[0]
        else:
            customer_id = conn.execute(
                "INSERT INTO customers (name, phone, email, city, state, pincode, preferred_language, "
                "acquisition_channel, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (name, digits, None, pin["city"], pin["state"], pin["pincode"], "en",
                 "ai_chat" if attributed else "website", now.strftime(FMT))).lastrowid
        last = conn.execute("SELECT MAX(CAST(SUBSTR(order_number, 5) AS INTEGER)) FROM orders").fetchone()[0] or 100000
        number = f"KTL-{last + 1}"
        order_id = conn.execute(
            "INSERT INTO orders (order_number, customer_id, created_at, status, payment_method, subtotal, discount, "
            "shipping_fee, total, shipping_address, shipping_pincode, address_quality, expected_delivery, source, ai_ref) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (number, customer_id, now.strftime(FMT), "placed", payment, subtotal, 0, shipping, subtotal + shipping,
             full_address, pin["pincode"], quality, (now + timedelta(days=5)).strftime(FMT),
             "ai_chat" if attributed else "store", ref if attributed else None)).lastrowid
        conn.execute("INSERT INTO order_items (order_id, product_id, quantity, unit_price) VALUES (?,?,?,?)",
                     (order_id, product_id, quantity, p["price"]))
        conn.execute("UPDATE products SET stock = stock - ? WHERE id = ?", (quantity, product_id))
    return {"order_number": number, "total": subtotal + shipping, "attributed": attributed,
            "expected_delivery": (now + timedelta(days=5)).strftime("%d %b")}


def ai_sales(days: int | None = None) -> dict:
    """AI-assisted orders: placed from a product card in an AI conversation (demo-store checkout)."""
    since = (datetime.now() - timedelta(days=days)).strftime(FMT) if days else "0000"
    row = db.query_one("""SELECT COUNT(*) AS orders, COALESCE(SUM(total), 0) AS revenue,
                                 COUNT(DISTINCT ai_ref) AS chats
                          FROM orders WHERE source = 'ai_chat' AND status != 'cancelled' AND created_at >= ?""", (since,))
    try:
        shown = db.query_one("""SELECT COUNT(DISTINCT channel || ':' || external_id) AS n FROM channel_events
                                WHERE meta LIKE '%"cards"%' AND created_at >= ?""", (since,))["n"]
    except Exception:
        shown = 0
    return {"orders": row["orders"], "revenue": float(row["revenue"]), "chats_converted": row["chats"],
            "chats_shown_products": shown,
            "conversion_rate": (row["chats"] / shown) if shown else None}
