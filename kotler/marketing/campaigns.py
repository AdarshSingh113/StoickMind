"""Campaign engine: audience -> guardrails -> A/B/holdout split -> AI-written templates -> personalised messages.

Ideas worth knowing
-------------------
HOLDOUT (control group): some customers deliberately get NO message. Only by comparing them with the
  messaged group can we tell whether the campaign CAUSED purchases or people would have bought anyway.
A/B VARIANTS: two message styles, randomly split, so we learn which works better.
TEMPLATES, NOT FREE TEXT: the LLM writes wording with placeholders ({first_name}, {product}, {price}...);
  our code fills in the facts from the database. A template containing a raw price ("₹299") or discount
  ("20% off") is rejected, so the AI can never promise a price or offer that doesn't exist.
GUARDRAILS (marketing):
  - frequency cap: max one marketing message per customer per 7 days (across all campaigns)
  - no promotions to customers with an open/escalated support ticket (don't sell to someone who's upset)
  - campaign discounts capped at 15%
DETERMINISTIC ASSIGNMENT: a customer's group comes from a hash of (campaign, customer), so the split is
  random but reproducible and auditable.
"""

from __future__ import annotations

import hashlib
import json
import re
import string
from datetime import datetime, timedelta

import pandas as pd

from kotler import db
from kotler.llm import LLMError
from kotler.marketing import journeys

MAX_CAMPAIGN_DISCOUNT = 15
FREQUENCY_CAP_DAYS = 7
MESSAGE_COST_INR = 0.80        # approx. cost of one WhatsApp marketing message (assumption, editable)
PLACEHOLDERS = {"first_name", "product", "price", "discount", "code", "days"}
MAX_TEMPLATE_CHARS = 600
FMT = "%Y-%m-%d %H:%M:%S"

SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, journey TEXT NOT NULL, audience_desc TEXT, channel TEXT NOT NULL,
    offer_pct INTEGER NOT NULL DEFAULT 0, code TEXT, holdout_pct REAL NOT NULL, templates TEXT NOT NULL,
    template_source TEXT, status TEXT NOT NULL CHECK (status IN ('draft', 'sent', 'measured')),
    created_at TEXT NOT NULL, sent_at TEXT, measured_at TEXT
);
CREATE TABLE IF NOT EXISTS campaign_members (
    campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE, customer_id INTEGER NOT NULL,
    grp TEXT NOT NULL CHECK (grp IN ('A', 'B', 'control', 'excluded')), exclusion_reason TEXT,
    product_id INTEGER, price REAL, aov REAL, churn_risk REAL, language TEXT, message TEXT, sent_at TEXT,
    converted INTEGER, revenue REAL, PRIMARY KEY (campaign_id, customer_id)
);
"""


def ensure_tables() -> None:
    with db.get_conn() as conn:
        conn.executescript(SCHEMA)


# ------------------------------------------------------------- templates
FALLBACK = {  # hand-written templates: used when no LLM is available or the AI's output fails validation
    "replenishment": {
        "A": {"angle": "friendly reminder", "en": "Hi {first_name}! It's been {days} days since you got your *{product}*. "
              "Running low? Restock now for {price} so your routine doesn't break.",
              "hinglish": "Hi {first_name}! Aapka *{product}* liye {days} din ho gaye. Khatam hone wala hai? "
                          "Abhi {price} mein restock kar lijiye."},
        "B": {"angle": "routine results", "en": "{first_name}, consistency is what gives results. Your *{product}* "
              "should be running out about now. Reorder in one tap for {price}.",
              "hinglish": "{first_name}, results ke liye routine regular rakhna zaroori hai. Aapka *{product}* "
                          "ab khatam hone wala hoga. {price} mein reorder kijiye."}},
    "win_back": {
        "A": {"angle": "we miss you", "en": "Hi {first_name}, we miss you at Glow & Co! Your favourite *{product}* "
              "is waiting for you at {price}.",
              "hinglish": "Hi {first_name}, hum aapko miss kar rahe hain! Aapka favourite *{product}* sirf {price} mein "
                          "available hai."},
        "B": {"angle": "what's new", "en": "{first_name}, a lot has happened since your last visit. Pick up your "
              "*{product}* again for {price}, and see what's new for your skin.",
              "hinglish": "{first_name}, aapke last order ke baad bahut kuch naya aaya hai. Apna *{product}* phir se "
                          "{price} mein lijiye."}},
    "cross_sell": {
        "A": {"angle": "complete your routine", "en": "Hi {first_name}! Complete your routine with *{product}* ({price}). "
              "It pairs perfectly with what you already use.",
              "hinglish": "Hi {first_name}! Apna routine complete kijiye *{product}* ke saath ({price}). Aapke current "
                          "products ke saath perfect hai."},
        "B": {"angle": "expert tip", "en": "Skin tip for you, {first_name}: the step most people skip makes the biggest "
              "difference. Try *{product}* for {price}.",
              "hinglish": "{first_name}, ek skin tip: jo step log skip karte hain wahi sabse zyada farak laata hai. "
                          "Try kijiye *{product}* sirf {price} mein."}},
    "second_order": {
        "A": {"angle": "next step", "en": "Hi {first_name}, hope you're loving your first order! The perfect next step "
              "is *{product}* ({price}).",
              "hinglish": "Hi {first_name}, umeed hai aapko pehla order pasand aaya! Agla perfect step hai *{product}* "
                          "({price})."},
        "B": {"angle": "social proof", "en": "{first_name}, customers who bought what you did love *{product}* next. "
              "Get it for {price}.",
              "hinglish": "{first_name}, aapke jaise customers ko agla *{product}* bahut pasand aata hai. {price} mein "
                          "lijiye."}},
}
FALLBACK["segment"] = FALLBACK["win_back"]
OFFER_LINE = {"en": " Use code {code} for {discount} off (valid 7 days).",
              "hinglish": " Code {code} lagaiye aur paaiye {discount} off (7 din ke liye)."}

PROMPT = """You write WhatsApp marketing messages for Glow & Co., an Indian skincare brand.
Campaign goal: {goal}
Offer: {offer}

Write TWO variants with clearly different angles (A and B), each in English and in Hinglish
(Hindi written in English letters). Max 45 words each. Warm, personal, no spammy capitals, at most one emoji.
Use ONLY these placeholders, exactly as written: {{first_name}}, {{product}}, {{price}}, {{days}}{offer_ph}.
NEVER write a price, number of rupees, percentage or discount yourself: use the placeholders.
Put the product in *bold* like *{{product}}*.

Reply with ONLY this JSON:
{{"A": {{"angle": "...", "en": "...", "hinglish": "..."}}, "B": {{"angle": "...", "en": "...", "hinglish": "..."}}}}"""


class InvalidTemplate(ValueError):
    pass


def validate_template(text: str, has_offer: bool) -> str:
    t = (text or "").strip()
    if not t:
        raise InvalidTemplate("Empty template.")
    if len(t) > MAX_TEMPLATE_CHARS:
        raise InvalidTemplate("Template is too long.")
    try:
        fields = {f for _, f, _, _ in string.Formatter().parse(t) if f is not None}
    except ValueError as e:
        raise InvalidTemplate(f"Broken placeholder: {e}") from e
    unknown = fields - PLACEHOLDERS
    if unknown:
        raise InvalidTemplate(f"Unknown placeholders: {', '.join(sorted(unknown))}.")
    if "product" not in fields:
        raise InvalidTemplate("Template must mention {product}.")
    if not has_offer and fields & {"discount", "code"}:
        raise InvalidTemplate("This campaign has no offer, so {discount}/{code} can't be used.")
    if re.search(r"(₹|rs\.?|inr)\s?\d|\d\s?%|\d+\s?(rupees|percent)", t, re.I):
        raise InvalidTemplate("Prices and discounts must come from placeholders, not be written in the text.")
    return t


def generate_templates(llm, journey: str, offer_pct: int) -> tuple[dict, str]:
    """AI-written A/B templates, validated. Falls back to hand-written templates if needed."""
    if llm is not None:
        offer = f"{offer_pct}% off with a coupon code" if offer_pct else "no discount"
        prompt = PROMPT.format(goal=journeys.JOURNEYS.get(journey, "Bring customers back to buy again."), offer=offer,
                               offer_ph=", {discount}, {code}" if offer_pct else "")
        try:
            resp = llm.chat([{"role": "user", "content": prompt}], tools=None, temperature=0.7)
            data = json.loads(re.search(r"\{.*\}", resp.content or "", re.S).group(0))
            out = {}
            for v in ("A", "B"):
                out[v] = {"angle": str(data[v].get("angle", ""))[:60],
                          "en": validate_template(data[v]["en"], bool(offer_pct)),
                          "hinglish": validate_template(data[v]["hinglish"], bool(offer_pct))}
            return _with_offer(out, offer_pct), "ai"
        except (LLMError, InvalidTemplate, AttributeError, KeyError, TypeError, json.JSONDecodeError):
            pass  # fall through to the hand-written templates
    return _with_offer(json.loads(json.dumps(FALLBACK[journey])), offer_pct), "fallback"


def _with_offer(templates: dict, offer_pct: int) -> dict:
    """Make sure every template mentions the offer when there is one (appended by code, not the AI)."""
    if offer_pct:
        for v in templates.values():
            for lang in ("en", "hinglish"):
                if "{code}" not in v[lang]:
                    v[lang] += OFFER_LINE[lang]
    return templates


def render(template: str, row: dict, offer_pct: int, code: str | None) -> str:
    return template.format(first_name=row["first_name"], product=row["product_name"], price=f"₹{row['price']:,.0f}",
                           days=int(row.get("days_since") or 0), discount=f"{offer_pct}%", code=code or "")


# ------------------------------------------------------------ assignment
def assign_group(campaign_id: int, customer_id: int, holdout_pct: float) -> str:
    h = int(hashlib.sha256(f"{campaign_id}:{customer_id}".encode()).hexdigest(), 16)
    if (h % 10_000) / 10_000 < holdout_pct:
        return "control"
    return "A" if (h // 10_000) % 2 == 0 else "B"


def exclusions(customer_ids: list[int]) -> dict[int, str]:
    """Customers who must NOT receive this campaign, with the reason."""
    out: dict[int, str] = {}
    since = (datetime.now() - timedelta(days=FREQUENCY_CAP_DAYS)).strftime(FMT)
    recent = db.query_df("SELECT DISTINCT customer_id FROM campaign_members WHERE sent_at >= ? AND grp IN ('A', 'B')",
                         (since,))
    for cid in set(recent.customer_id) & set(customer_ids):
        out[int(cid)] = f"already messaged in the last {FREQUENCY_CAP_DAYS} days"
    upset = db.query_df("SELECT DISTINCT customer_id FROM support_tickets WHERE status IN ('open', 'escalated')")
    for cid in set(upset.customer_id) & set(customer_ids):
        out.setdefault(int(cid), "has an open support ticket")
    return out


# ---------------------------------------------------------------- create
def create_campaign(name: str, journey: str, templates: dict, template_source: str, offer_pct: int = 0,
                    holdout_pct: float = 0.2, channel: str = "whatsapp", audience_df: pd.DataFrame | None = None,
                    audience_desc: str = "") -> int:
    ensure_tables()
    if not 0 <= offer_pct <= MAX_CAMPAIGN_DISCOUNT:
        raise ValueError(f"Campaign discounts are capped at {MAX_CAMPAIGN_DISCOUNT}%.")
    if not 0.05 <= holdout_pct <= 0.5:
        raise ValueError("Holdout must be between 5% and 50%: without a control group the campaign can't be measured.")
    for v in templates.values():
        for lang in ("en", "hinglish"):
            validate_template(v[lang], bool(offer_pct))
    aud = audience_df if audience_df is not None else journeys.audience(journey)
    if aud.empty:
        raise ValueError("The audience is empty.")
    now = datetime.now().strftime(FMT)
    with db.get_conn() as conn:
        cid = conn.execute(
            "INSERT INTO campaigns (name, journey, audience_desc, channel, offer_pct, holdout_pct, templates, "
            "template_source, status, created_at) VALUES (?,?,?,?,?,?,?,?, 'draft', ?)",
            (name.strip(), journey, audience_desc or journeys.JOURNEYS.get(journey, ""), channel, offer_pct,
             holdout_pct, json.dumps(templates, ensure_ascii=False), template_source, now)).lastrowid
        code = f"KTL{cid}{offer_pct}" if offer_pct else None
        conn.execute("UPDATE campaigns SET code = ? WHERE id = ?", (code, cid))
    excluded = exclusions(aud.customer_id.astype(int).tolist())
    rows = []
    for r in aud.to_dict("records"):
        cust = int(r["customer_id"])
        grp = "excluded" if cust in excluded else assign_group(cid, cust, holdout_pct)
        lang = "en" if r["language"] == "en" else "hinglish"
        msg = render(templates[grp][lang], r, offer_pct, code) if grp in ("A", "B") else None
        rows.append((cid, cust, grp, excluded.get(cust), int(r["product_id"]), float(r["price"]), float(r["aov"]),
                     float(r["churn_risk"]), r["language"], msg))
    with db.get_conn() as conn:
        conn.executemany("INSERT INTO campaign_members (campaign_id, customer_id, grp, exclusion_reason, product_id, "
                         "price, aov, churn_risk, language, message) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    return cid


def send_campaign(campaign_id: int) -> int:
    """Simulated send: messages move to 'sent' in the outbox. (Phase 7 sends to real test numbers.)"""
    now = datetime.now().strftime(FMT)
    with db.get_conn() as conn:
        n = conn.execute("UPDATE campaign_members SET sent_at = ? WHERE campaign_id = ? AND grp IN ('A', 'B')",
                         (now, campaign_id)).rowcount
        conn.execute("UPDATE campaigns SET status = 'sent', sent_at = ? WHERE id = ?", (now, campaign_id))
    return n


def list_campaigns() -> pd.DataFrame:
    ensure_tables()
    return db.query_df("""SELECT c.*, COUNT(m.customer_id) AS audience,
                                 SUM(m.grp IN ('A', 'B')) AS messaged, SUM(m.grp = 'control') AS control,
                                 SUM(m.grp = 'excluded') AS excluded
                          FROM campaigns c LEFT JOIN campaign_members m ON m.campaign_id = c.id
                          GROUP BY c.id ORDER BY c.id DESC""")


def members(campaign_id: int) -> pd.DataFrame:
    return db.query_df("""SELECT m.*, cu.name FROM campaign_members m JOIN customers cu ON cu.id = m.customer_id
                          WHERE m.campaign_id = ?""", (campaign_id,))
