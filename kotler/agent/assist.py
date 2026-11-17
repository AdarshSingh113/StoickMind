"""AI copilot for the PEOPLE answering chats in the inbox: suggest a reply, rephrase a draft, translate, summarize.

The AI agents answer customers on their own. When a person takes over (an angry customer, an allergy, anything
the AI escalated), this copilot helps that person instead: it drafts, the person decides. Nothing is ever sent
automatically.

Grounding: a suggestion may only use what's in front of the person: the conversation, the customer's real
orders and the store's written policies (the same BM25 policy search Asha uses). Code then checks the draft:
any rupee amount or order number that isn't in that context is flagged, so the person double-checks it.
"""

from __future__ import annotations

import re

from kotler import db
from kotler.agent import retrieval
from kotler.agent.language import detect_language
from kotler.llm import LLMError

ACTIONS = {"suggest", "friendlier", "shorter", "hinglish", "english", "summarize"}
LANG_NAME = {"en": "English", "hinglish": "Hinglish (Hindi in English letters)", "hi": "Hindi"}
ORDER_NO = re.compile(r"KTL-\d{6}", re.I)
AMOUNT = re.compile(r"(?:₹|rs\.?\s?|inr\s?)(\d[\d,]*(?:\.\d+)?)", re.I)


def _thread(channel: str, external_id: str, limit: int = 20) -> list[dict]:
    rows = db.query_df("SELECT direction, text, agent_slug FROM channel_events WHERE channel = ? AND external_id = ? "
                       "ORDER BY id DESC LIMIT ?", (channel, external_id, limit)).to_dict("records")
    return rows[::-1]


def _who(m: dict) -> str:
    if m["direction"] == "in":
        return "Customer"
    return "Team member" if m["agent_slug"] == "human" else "AI assistant"


def _customer_facts(customer_id: int | None) -> str:
    if not customer_id:
        return "Customer: guest (not verified). Don't share or assume any order details."
    c = db.query_one("SELECT name, city FROM customers WHERE id = ?", (customer_id,))
    orders = db.query_df("""SELECT o.order_number, o.created_at, o.status, o.payment_method, o.total, o.expected_delivery,
                                   o.courier, (SELECT GROUP_CONCAT(p.name, ', ') FROM order_items i
                                   JOIN products p ON p.id = i.product_id WHERE i.order_id = o.id) AS items
                            FROM orders o WHERE o.customer_id = ? ORDER BY o.created_at DESC LIMIT 5""", (customer_id,))
    lines = [f"Customer: {c['name']} ({c['city']}). Recent orders:"]
    for o in orders.itertuples():
        lines.append(f"- {o.order_number} on {o.created_at[:10]}: {o.status}, {o.payment_method.upper()}, "
                     f"₹{o.total:,.0f}, {o.items}" + (f", courier {o.courier}" if o.courier else "")
                     + (f", expected {o.expected_delivery}" if o.expected_delivery else ""))
    return "\n".join(lines)


def _policies(query: str) -> str:
    hits = retrieval.search_policies(query, top_k=2) if query else []
    return "\n".join(f"[{h['policy']}] {h['text']}" for h in hits) or "(no matching policy)"


def unchecked_facts(text: str, context: str) -> list[str]:
    """Order numbers and rupee amounts in the draft that don't appear in the context."""
    ctx = context.replace(",", "")
    out = [n.upper() for n in ORDER_NO.findall(text) if n.upper() not in context.upper()]
    for a in AMOUNT.findall(text):
        num = a.replace(",", "")
        if num not in ctx and num.rstrip("0").rstrip(".") not in ctx:
            out.append(f"₹{a}")
    return out


def assist(llm, action: str, channel: str, external_id: str, draft: str = "") -> dict:
    if action not in ACTIONS:
        raise ValueError(f"Unknown action: {action}")
    session = db.query_one("SELECT customer_id FROM channel_users WHERE channel = ? AND external_id = ?",
                           (channel, external_id)) or {}
    thread = _thread(channel, external_id)
    convo = "\n".join(f"{_who(m)}: {m['text']}" for m in thread) or "(no messages yet)"
    last_customer = next((m["text"] for m in reversed(thread) if m["direction"] == "in"), "")
    lang = detect_language(last_customer) or "en"

    if action == "summarize":
        prompt = (f"Summarize this customer-care chat for a team member taking over. Exactly 3 short bullets, each "
                  f"starting with '- ': the customer's issue, what has been done so far, the next step. Add the "
                  f"customer's mood in a few words at the end of the first bullet. English.\n\n{convo}")
        context = convo
    elif action == "suggest":
        context = f"{_customer_facts(session.get('customer_id'))}\n\nStore policies:\n{_policies(last_customer)}"
        prompt = (f"You help a customer-care team member at Glow & Co. (Indian skincare brand) write their next reply.\n"
                  f"{context}\n\nConversation:\n{convo}\n\n"
                  f"Write the team member's next message to the customer: warm, clear, at most 70 words, in "
                  f"{LANG_NAME.get(lang, 'English')}. Use ONLY the facts above: never invent order details, prices, "
                  f"dates or promises; refunds and discounts only as the policies allow. Don't say an action was "
                  f"done (refund started, replacement sent) unless the conversation shows it. If something must be "
                  f"checked first, say so honestly. Reply with the message text only.")
    else:
        if not draft.strip():
            raise ValueError("Write a draft first.")
        context = draft
        how = {"friendlier": "Make it warmer and friendlier", "shorter": "Make it shorter and clearer",
               "hinglish": "Rewrite it in natural Hinglish (Hindi written in English letters)",
               "english": "Rewrite it in clear English"}[action]
        prompt = (f"{how}. Keep every fact, number, price, date, order number and promise exactly the same. "
                  f"Keep *bold* formatting. Reply with the message only.\n\n{draft}")

    from kotler.obs.trace import trace
    with trace("inbox_assist", action, input=(draft or last_customer)[:500]) as t:
        try:
            text = (llm.chat([{"role": "user", "content": prompt}], tools=None, temperature=0.3).content or "").strip()
            text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)   # chat apps bold with single asterisks
        except LLMError as e:
            t.status, t.error = "error", str(e)[:300]
            raise
        warnings = [] if action == "summarize" else unchecked_facts(text, f"{context}\n{convo}")
        t.output, t.meta = text, {"warnings": warnings}
        if warnings:
            t.status = "corrected"
            t.span("guard", "unchecked_facts", ok=False, detail=", ".join(warnings))
    return {"text": text, "warnings": warnings, "language": lang}
