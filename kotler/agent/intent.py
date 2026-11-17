"""What is the customer asking about? A small rule-based intent classifier (English + Hinglish).

Used for analytics ("what do customers ask, and how much of it does the AI handle alone?") and as a tag in
the inbox. Why rules and not an LLM: it runs on every message for free, in microseconds, gives the same
answer every time, and anyone can read why a message got its label. If the rules miss something, the
message lands in "Other", which the analytics show, so gaps are visible rather than hidden.

A conversation gets the MOST SERIOUS intent among its customer messages: "the cream gave me a rash ... I
want a refund" is a skin-reaction case first, because that is what decides how it must be handled.
"""

from __future__ import annotations

import re

# Most serious first. (key, label, pattern)
INTENTS: list[tuple[str, str, re.Pattern]] = [(k, label, re.compile(p, re.I)) for k, label, p in [
    ("skin_reaction", "Skin reaction", r"\b(allerg\w*|rash\w*|reaction|itch\w*|irritat\w*|burn(ing|s)?|swell\w*|"
                                        r"red(ness)? (patch|spots?)|breaking out|breakouts?|jalan|khujli|daane)\b"),
    ("damaged_wrong", "Damaged or wrong item", r"\b(damaged?|broken|leak\w*|spill\w*|wrong (item|product|order)|"
                                                r"missing|expired|toota|tuta|galat)\b"),
    ("refund_return", "Refund or return", r"\b(refund\w*|return\w*|money back|exchange|replace\w*|paisa wapas|"
                                           r"paise wapas|wapas (karna|chahiye))\b"),
    ("cancel", "Cancel order", r"\b(cancel\w*)\b"),
    ("order_status", "Order status", r"\b(where is my|track\w*|status|deliver\w*|shipped|shipping|courier|dispatch\w*|"
                                      r"kab (aayega|aaega|milega|tak)|nahi aaya|late|delay\w*|parcel)\b|ktl-?\d"),
    ("payment", "Payment", r"\b(cod|cash on delivery|upi|payment|paid|pay|prepaid|card)\b"),
    ("discount", "Offers and discounts", r"\b(discount\w*|coupon\w*|offer\w*|promo|code|sale|cashback|deal\w*)\b"),
    ("product_advice", "Product advice", r"\b(recommend\w*|suggest\w*|which|best|batao|bataiye|skin|oily|dry|acne|"
                                          r"pimple\w*|serum|moisturi[sz]er|sunscreen|face ?wash|cleanser|toner|"
                                          r"cream|lotion|price|kitna|kitne|cost|ingredient\w*|vitamin|niacinamide|"
                                          r"retinol|hyaluronic|spf|sunburn|tan|glow\w*|routine|hair|shampoo|lip|"
                                          r"cheap\w*|budget|use karu|buy again|order it again|reorder|in stock|"
                                          r"available)\b|^/(quiz|shop)\b"),
    ("asked_for_person", "Asked for a person", r"\b(human|real person|agent|call me|talk to (someone|a person)|"
                                                r"manager|insaan)\b"),
]]
# "sunscreen that won't irritate" is a product question, not a reaction: drop negated symptoms first.
NEGATED = re.compile(r"\b(won'?t|wont|doesn'?t|does not|will not|not|no|non-?|without|free of)\s*(\w+\s+)?"
                     r"(irritat\w*|burn\w*|itch\w*|rash\w*|reaction\w*|breakouts?|break (me )?out)\b", re.I)
OTHER = ("other", "Other")
LABELS = {k: label for k, label, _ in INTENTS} | {OTHER[0]: OTHER[1]}
RANK = {k: i for i, (k, _, _) in enumerate(INTENTS)} | {OTHER[0]: len(INTENTS)}


def classify(text: str | None) -> str:
    """The intent key of one message."""
    text = NEGATED.sub(" ", text or "")
    for key, _, pattern in INTENTS:
        if pattern.search(text):
            return key
    return OTHER[0]


def conversation_intent(texts: list[str]) -> str:
    """The most serious intent among a conversation's customer messages."""
    return min((classify(t) for t in texts), key=RANK.__getitem__, default=OTHER[0])
