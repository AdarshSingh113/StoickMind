"""Store policies: ONE source of truth for both the rules the code enforces and the text the AI reads.

A classic AI-support failure: the help-centre page says "returns within 15 days", the
backend allows 7, and the bot quotes the page. Here the policy TEXT is generated from the
same constants the tools ENFORCE, so they can't drift apart.
"""

from __future__ import annotations

# ---- limits enforced in code (kotler/agent/support_tools.py) -----------------
RETURN_WINDOW_DAYS = 7          # damaged / wrong item / refund requests after delivery
AUTO_REFUND_LIMIT = 1000.0      # refunds up to this are approved automatically; above -> human approval
REPLACEMENT_AUTO_LIMIT = 1500.0  # replacements for orders above this value need human approval
MAX_DISCOUNT_PCT = 10           # the most an AI agent may ever offer
DISCOUNT_COOLDOWN_DAYS = 30     # one AI-issued coupon per customer per 30 days
COUPON_VALID_DAYS = 30
CANCELLABLE_STATUSES = ("placed",)  # once shipped, an order can't be cancelled
MAX_VERIFY_ATTEMPTS = 3         # guest identity checks per conversation before locking

# ---- the policy document the agent retrieves from -------------------------------
POLICIES = {
    "shipping": f"""Shipping and delivery
We ship across India with Delhivery, Blue Dart, Ecom Express, Xpressbees and Shadowfax.
Orders are packed within 24 hours. Delivery takes 2-4 days to metro (tier 1) cities, 3-5 days to tier 2 cities
and 4-8 days to smaller towns. Shipping is free on orders above ₹499, otherwise ₹49.
Tracking details are shared on WhatsApp and email once the order ships.
If an order is more than 2 days past its expected delivery date, we raise it with the courier and keep the customer updated.""",

    "cancellation": f"""Order cancellation
Orders can be cancelled free of charge only before they ship (status "placed"). Once an order has shipped it
cannot be cancelled; the customer can return it after delivery as per the returns policy.
Prepaid orders cancelled before shipping are refunded in full to the original payment method within 5-7 working days.
Cash on delivery orders that are cancelled before shipping have nothing to refund.""",

    "returns": f"""Returns and replacements
Because skincare is personal care, opened products can't be returned for a change of mind.
We replace free of charge any item that arrives damaged, leaking, broken or wrong, if reported within
{RETURN_WINDOW_DAYS} days of delivery. A replacement ships within 2 working days.
Unopened, sealed products can be returned within {RETURN_WINDOW_DAYS} days of delivery for a refund.""",

    "refunds": f"""Refunds
Approved refunds go to the original payment method within 5-7 working days. For cash on delivery orders,
refunds are sent by UPI or bank transfer after we confirm the details.
Refunds up to ₹{AUTO_REFUND_LIMIT:,.0f} are approved immediately. Larger refunds are reviewed by our support team
within 24 hours. Refund requests must be made within {RETURN_WINDOW_DAYS} days of delivery.""",

    "damaged": f"""Damaged, leaking or wrong items
If a product arrives damaged, leaking, broken or wrong, tell us within {RETURN_WINDOW_DAYS} days of delivery with
the order number and which product was affected. We send a free replacement (or a refund if the item is out of stock).
Replacements for orders above ₹{REPLACEMENT_AUTO_LIMIT:,.0f} are confirmed by our team within 24 hours.""",

    "allergic_reaction": """Allergic reactions and skin irritation
If a product causes burning, rashes, swelling or irritation: stop using it immediately and rinse with cool water.
If symptoms are severe or don't settle within a day, see a doctor or dermatologist.
We always recommend a patch test on the inner arm 24 hours before using a new product.
Customers with a reaction are connected to our care team, who can arrange a refund for that product.""",

    "discounts": f"""Discounts and coupons
New customers get 10% off the first order with code WELCOME10. Seasonal offers are announced on WhatsApp and Instagram.
Our assistants can't create custom discounts above {MAX_DISCOUNT_PCT}%. Coupons are valid for {COUPON_VALID_DAYS} days
and one coupon can be used per order.""",

    "cod": """Cash on delivery
Cash on delivery is available on most pincodes. Please keep the exact amount ready.
Refusing a cash on delivery parcel at the door causes a return-to-origin shipment; repeated refusals may
disable cash on delivery for that account.""",

    "contact": """Contact and support hours
Our care team is available on WhatsApp and email 9am-9pm, all days. AI assistants answer instantly, 24x7,
and hand over to a human when needed. Escalated cases are answered within 4 working hours.""",
}
