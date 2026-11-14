"""Tools the shopping agent can call.

Each tool = a plain Python function + a JSON schema that tells the LLM what it
does and which arguments it takes. The LLM never touches the database: it only
*asks* us to run a tool; our code decides what actually happens.

Security rule: identity comes from the server, never from the model.
`get_my_profile` has no customer_id argument; it reads ToolContext, which our
code fills in from the logged-in session. Otherwise a prompt like
"show me the profile of customer 42" could leak someone else's data.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from kotler.db import query_df, query_one

# Customers write "pimples", "daag", "chipchipa skin"... the catalogue says
# "acne", "dark spots", "oiliness". This map bridges the two (English + Hinglish).
SYNONYMS = {
    "pimple": "acne", "pimples": "acne", "breakout": "acne", "breakouts": "acne", "daane": "acne",
    "dane": "acne", "muhase": "acne", "muhaase": "acne", "zits": "acne",
    "daag": "dark spots", "dhabbe": "dark spots", "marks": "dark spots", "spots": "dark spots",
    "pigmentation": "pigmentation", "tanning": "tan", "tanned": "tan",
    "chipchipa": "oiliness", "oily": "oiliness", "greasy": "oiliness",
    "rukhi": "dryness", "dry": "dryness", "flaky": "flakiness",
    "dull": "dullness", "glow": "dullness", "glowing": "dullness", "nikhar": "dullness",
    "wrinkles": "fine lines", "aging": "fine lines", "ageing": "fine lines",
    "pores": "large pores", "blackhead": "blackheads",
    "sunburn": "sunburn", "irritation": "irritation", "itching": "irritation", "jalan": "irritation",
    "circles": "dark circles", "puffy": "puffiness",
}
STOPWORDS = {"for", "the", "a", "an", "and", "with", "my", "skin", "ke", "liye", "ki", "ka", "hai", "best",
             "good", "acha", "accha", "product", "products", "under", "below", "me", "mujhe", "kuch", "koi",
             # category words: the category filter handles these; as keywords they'd wrongly
             # exclude e.g. "Ceramide Barrier Repair Cream" from a "moisturizer" search
             "moisturizer", "moisturiser", "cream", "face", "wash", "facewash", "cleanser", "serum",
             "sunscreen", "spf", "toner", "lotion", "gel"}
FACE_CATEGORIES = {"face_wash", "moisturizer", "serum", "sunscreen", "toner", "kit"}

SKIN_TYPES = ["oily", "dry", "combination", "sensitive", "normal"]
# What each skin type typically needs; used to rank products when no concern is given.
SKIN_NEEDS = {"dry": "dryness dehydration barrier", "oily": "oiliness acne pores", "combination": "oiliness dehydration",
              "sensitive": "irritation redness", "normal": "dullness dehydration"}
CATEGORIES = ["face_wash", "moisturizer", "serum", "sunscreen", "toner", "lip_care", "eye_care", "body_care", "kit"]


@dataclass
class ToolContext:
    customer_id: int | None = None   # set by OUR code from the session, never by the LLM


# ------------------------------------------------------------------ helpers
def _terms(text: str | None) -> list[str]:
    if not text:
        return []
    words = re.findall(r"[a-z0-9%]+", text.lower())
    out = []
    for w in words:
        if w in STOPWORDS or len(w) < 2:
            continue
        out.extend(SYNONYMS.get(w, w).split())
    return out


def _score(row: dict, terms: list[str]) -> float:
    """Simple keyword relevance: concern matches count most, then name, then text."""
    concerns, name = row["concerns"].lower(), row["name"].lower()
    text = f"{row['description']} {row['key_ingredients']}".lower()
    s = 0.0
    for t in terms:
        s += 3 * (t in concerns) + 2 * (t in name) + 1 * (t in text)
    if row["category"] == "body_care" and "body" not in terms:
        s *= 0.3  # "pimples" means face unless the customer says body
    return s


def _public(row: dict, full: bool = False) -> dict:
    """What the LLM gets to see about a product. Short by default to save tokens."""
    out = {
        "product_id": row["id"], "name": row["name"], "category": row["category"],
        "price_inr": row["price"], "mrp_inr": row["mrp"], "size": row["size"],
        "suits_skin_types": row["skin_types"], "concerns": row["concerns"],
        "key_ingredients": row["key_ingredients"], "rating": row["rating"],
        "in_stock": row["stock"] > 0,
    }
    if full:
        out["description"] = row["description"]
        out["low_stock"] = 0 < row["stock"] <= 10
    else:
        out["summary"] = row["description"].split(". ")[0]
    return out


def _products(where: str = "", params: dict | None = None) -> list[dict]:
    return query_df(f"SELECT * FROM products WHERE is_active = 1 {where}", params or {}).to_dict("records")


def _suits(row: dict, skin_type: str | None) -> bool:
    if not skin_type:
        return True
    types = row["skin_types"].split(",")
    return skin_type in types or "all" in types


# -------------------------------------------------------------------- tools
def search_products(ctx: ToolContext, query: str | None = None, skin_type: str | None = None,
                    concern: str | None = None, category: str | None = None,
                    max_price: float | None = None, min_price: float | None = None, limit: int = 5) -> dict:
    where, params = [], {}
    if category:
        where.append("category = :category")
        params["category"] = category
    if max_price is not None:
        where.append("price <= :max_price")
        params["max_price"] = float(max_price)
    if min_price is not None:
        where.append("price >= :min_price")
        params["min_price"] = float(min_price)
    rows = _products(("AND " + " AND ".join(where)) if where else "", params)
    rows = [r for r in rows if _suits(r, skin_type)]

    out_of_stock = [r["name"] for r in rows if r["stock"] <= 0]
    rows = [r for r in rows if r["stock"] > 0]

    # The concern FILTERS (must match); free-text keywords only RANK.
    concern_terms, query_terms = _terms(concern), _terms(query)
    note = None
    if concern_terms or query_terms:
        if concern_terms:
            matched = [r for r in rows if _score(r, concern_terms) > 0]
            if matched:
                rows = matched
            else:
                note = f"No product targets '{concern}' within these filters; showing the closest options."
        rows.sort(key=lambda r: (-_score(r, concern_terms + query_terms), -r["rating"]))
    else:
        rows.sort(key=lambda r: -r["rating"])

    limit = max(1, min(int(limit or 5), 8))
    result = {"count": len(rows), "products": [_public(r) for r in rows[:limit]]}
    if out_of_stock:
        result["out_of_stock_not_shown"] = out_of_stock
    if note:
        result["note"] = note
    if not rows:
        result["note"] = "No products match these filters. Suggest relaxing the budget or category."
    return result


def get_product_details(ctx: ToolContext, product_id: int) -> dict:
    row = query_one("SELECT * FROM products WHERE id = ? AND is_active = 1", (int(product_id),))
    if not row:
        return {"error": f"No product with id {product_id}."}
    return _public(row, full=True)


def compare_products(ctx: ToolContext, product_ids: list[int]) -> dict:
    ids = [int(i) for i in (product_ids or [])][:4]
    if len(ids) < 2:
        return {"error": "Give at least two product ids to compare."}
    found = [get_product_details(ctx, i) for i in ids]
    return {"products": [p for p in found if "error" not in p],
            "missing_ids": [i for i, p in zip(ids, found) if "error" in p]}


ROUTINE_STEPS = [("cleanse", "face_wash"), ("treat", "serum"), ("moisturize", "moisturizer"), ("protect", "sunscreen")]


def build_routine(ctx: ToolContext, skin_type: str, concern: str | None = None,
                  budget: float | None = None, time_of_day: str = "morning") -> dict:
    """Pick one product per step for the skin type (and concern), within budget.

    With <=6 candidates per step there are at most ~1,300 combinations, so we
    simply try them all and keep the best one that fits the budget. When the
    search space is this small, brute force is the simplest correct algorithm.
    """
    from itertools import product as combos

    terms = _terms(concern)
    # Ranking also considers what the skin type needs, and prefers products made
    # specifically for this skin type over "all skin types" ones.
    rank_terms = terms + SKIN_NEEDS.get(skin_type, "").split()

    def fit(r: dict) -> float:
        return _score(r, rank_terms) + (1.5 if skin_type in r["skin_types"].split(",") else 0)

    steps = [s for s in ROUTINE_STEPS if not (time_of_day == "night" and s[1] == "sunscreen")]
    candidates: list[list[dict | None]] = []
    for step, cat in steps:
        rows = [r for r in _products("AND category = :c AND stock > 0", {"c": cat}) if _suits(r, skin_type)]
        rows.sort(key=lambda r: (-fit(r), -r["rating"]))
        rows = rows[:6]
        # The serum step is optional (skipped if the budget is tight), the rest are essential.
        candidates.append(rows + [None] if step == "treat" else (rows or [None]))

    def value(combo) -> tuple:
        picked = [r for r in combo if r]
        has_treat = combo[[s for s, _ in steps].index("treat")] is not None
        quality = sum(fit(r) for r in picked) + sum(r["rating"] for r in picked) / 10
        # With a concern, the treatment step matters most; then completeness; then fit; then price.
        return (has_treat if terms else 0, len(picked), quality, -sum(r["price"] for r in picked))

    best = None
    for combo in combos(*candidates):
        total = sum(r["price"] for r in combo if r)
        if budget is not None and total > budget:
            continue
        if best is None or value(combo) > value(best):
            best = combo
    within = best is not None
    if best is None:  # nothing fits: return the cheapest possible routine and say so
        best = min(combos(*candidates), key=lambda c: sum(r["price"] for r in c if r))

    chosen = [(step, r) for (step, _), r in zip(steps, best) if r]
    total = sum(r["price"] for _, r in chosen)
    result = {
        "skin_type": skin_type, "time_of_day": time_of_day,
        "steps": [{"step": step, **_public(r)} for step, r in chosen],
        "total_inr": total, "within_budget": within,
    }
    if not within:
        result["note"] = f"No complete routine fits ₹{budget:.0f}; this is the cheapest one (₹{total:.0f})."
    kits = [r for r in _products("AND category = 'kit' AND stock > 0") if _suits(r, skin_type)
            and (budget is None or r["price"] <= budget) and r["price"] < total]
    if kits:
        result["cheaper_kit_alternative"] = _public(max(kits, key=lambda r: _score(r, terms)))
    return result


def get_my_profile(ctx: ToolContext) -> dict:
    """The logged-in customer's preferences and history. Deliberately leaves out
    phone, email and address: the shopping agent doesn't need them (data minimisation)."""
    if ctx.customer_id is None:
        return {"logged_in": False}
    c = query_one("SELECT name, city, skin_type, preferred_language, created_at FROM customers WHERE id = ?",
                  (ctx.customer_id,))
    if not c:
        return {"logged_in": False}
    stats = query_one("""SELECT COUNT(*) AS orders, MAX(created_at) AS last_order_at FROM orders
                         WHERE customer_id = ? AND status != 'cancelled'""", (ctx.customer_id,))
    favs = query_df("""
        SELECT p.id AS product_id, p.name, SUM(oi.quantity) AS times_bought
        FROM order_items oi JOIN orders o ON o.id = oi.order_id AND o.status != 'cancelled'
        JOIN products p ON p.id = oi.product_id
        WHERE o.customer_id = ? GROUP BY p.id ORDER BY times_bought DESC LIMIT 3""", (ctx.customer_id,))
    return {
        "logged_in": True, "first_name": c["name"].split()[0], "city": c["city"],
        "skin_type": c["skin_type"], "preferred_language": c["preferred_language"],
        "customer_since": c["created_at"][:10], "orders": stats["orders"],
        "last_order_date": (stats["last_order_at"] or "")[:10] or None,
        "favourite_products": favs.to_dict("records"),
    }


# ------------------------------------------------------------- registry
def _schema(name: str, description: str, properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required or []}}}


SKIN = {"type": "string", "enum": SKIN_TYPES, "description": "Customer's skin type."}

TOOLS: dict[str, tuple[Callable[..., dict], dict]] = {
    "search_products": (search_products, _schema(
        "search_products",
        "Search the catalogue. Use for any product recommendation or 'do you have X' question. "
        "Translate the customer's words into filters, e.g. 'pimples' -> concern 'acne', "
        "'600 ke andar' -> max_price 600. Only in-stock products are returned.",
        {
            "query": {"type": "string", "description": "Free-text keywords, e.g. 'niacinamide' or 'vitamin c'."},
            "skin_type": SKIN,
            "concern": {"type": "string", "description": "Skin concern in English, e.g. acne, dark spots, "
                                                         "dryness, oiliness, dullness, tan, fine lines, dark circles."},
            "category": {"type": "string", "enum": CATEGORIES},
            "max_price": {"type": "number", "description": "Maximum price per product in INR."},
            "min_price": {"type": "number", "description": "Minimum price per product in INR."},
            "limit": {"type": "integer", "description": "How many products to return (1-8, default 5)."},
        })),
    "get_product_details": (get_product_details, _schema(
        "get_product_details",
        "Full details of one product: description, how to use, warnings, stock. Use before answering "
        "detailed questions about a specific product.",
        {"product_id": {"type": "integer"}}, ["product_id"])),
    "compare_products": (compare_products, _schema(
        "compare_products", "Side-by-side details of 2-4 products, for 'X vs Y' questions.",
        {"product_ids": {"type": "array", "items": {"type": "integer"}}}, ["product_ids"])),
    "build_routine": (build_routine, _schema(
        "build_routine",
        "Build a complete skincare routine (cleanser, serum, moisturizer, sunscreen) for a skin type, "
        "optionally for a concern and within a total budget.",
        {
            "skin_type": SKIN,
            "concern": {"type": "string", "description": "Main concern in English, e.g. acne, dark spots."},
            "budget": {"type": "number", "description": "Maximum TOTAL for the whole routine in INR."},
            "time_of_day": {"type": "string", "enum": ["morning", "night"]},
        }, ["skin_type"])),
    "get_my_profile": (get_my_profile, _schema(
        "get_my_profile",
        "The logged-in customer's skin type, preferred language, order count and favourite products. "
        "Use to personalise, e.g. to know their skin type or what they bought before.",
        {})),
}

TOOL_SCHEMAS = [schema for _, schema in TOOLS.values()]


def execute_tool(name: str, arguments: dict, ctx: ToolContext) -> dict:
    """Run a tool safely. Errors are returned to the model as data, so it can
    recover (e.g. fix an argument) instead of the whole chat crashing."""
    if name not in TOOLS:
        return {"error": f"Unknown tool '{name}'. Available: {', '.join(TOOLS)}."}
    fn, _ = TOOLS[name]
    try:
        return fn(ctx, **{k: v for k, v in arguments.items() if not k.startswith("_")})
    except (TypeError, ValueError) as e:
        return {"error": f"Invalid arguments for {name}: {e}"}


def to_json(result: Any) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)
