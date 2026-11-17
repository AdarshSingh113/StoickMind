"""Inbox API: every customer conversation from Telegram, WhatsApp and the website, live, with human takeover.

Endpoints (all need login):
  GET  /api/v1/inbox                                   conversation list (filters: view, channel, q)
  GET  /api/v1/inbox/{channel}/{external_id}           one conversation: messages + customer profile
  POST /api/v1/inbox/{channel}/{external_id}/takeover  a person takes over; the AI goes silent
  POST /api/v1/inbox/{channel}/{external_id}/release   hand back to the AI
  POST /api/v1/inbox/{channel}/{external_id}/reply     the person's message, sent on the customer's channel
  POST /api/v1/inbox/{channel}/{external_id}/notes     a private team note (never sent to the customer)
  POST /api/v1/inbox/{channel}/{external_id}/assist    AI copilot: suggest / rephrase / translate / summarize
  GET  /api/v1/inbox/stream                            Server-Sent Events: new messages as they happen
  POST /api/v1/inbox/demo                              load demo conversations (to try the inbox without bots)

LIVE UPDATES: Server-Sent Events (SSE) vs WebSockets. SSE is a normal HTTP response that never ends; the server
writes `data: {...}` lines whenever something happens and the browser's EventSource reconnects by itself, resending
the last id it saw (`Last-Event-ID`), so no message is missed after a network blip. We only need server -> browser
pushes (sending is a normal POST), so SSE is simpler than WebSockets and works through every proxy.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from kotler import db
from kotler.api.auth import require_user
from kotler.channels import core, outbound

router = APIRouter(prefix="/api/v1/inbox", dependencies=[Depends(require_user)])
CHANNELS = {"telegram", "whatsapp", "web"}


def _records(df) -> list[dict]:
    return df.astype(object).where(df.notna(), None).to_dict("records")


def _session(channel: str, external_id: str) -> dict:
    if channel not in CHANNELS:
        raise HTTPException(404, "Unknown channel.")
    core.ensure_tables()
    row = db.query_one("SELECT * FROM channel_users WHERE channel = ? AND external_id = ?", (channel, external_id))
    if not row:
        raise HTTPException(404, "Conversation not found.")
    return row


LIST_SQL = """
SELECT u.channel, u.external_id, u.display_name, u.customer_id, c.name AS customer_name, c.city,
       u.agent_slug, u.handler, u.needs_human, u.marketing_opt_in, u.last_inbound_at, u.handoff_at,
       e.text AS last_text, e.direction AS last_direction, e.agent_slug AS last_author, e.created_at AS last_at,
       e.id AS last_id,
       (SELECT COUNT(*) FROM channel_events x WHERE x.channel = u.channel AND x.external_id = u.external_id
          AND x.direction = 'in' AND x.id > u.last_read_id) AS unread
FROM channel_users u
LEFT JOIN customers c ON c.id = u.customer_id
LEFT JOIN channel_events e ON e.id = (SELECT MAX(id) FROM channel_events y
                                      WHERE y.channel = u.channel AND y.external_id = u.external_id)
"""


@router.get("")
def list_conversations(view: str = Query("all", pattern="^(all|needs_human|human|ai)$"),
                       channel: str | None = None, q: str | None = Query(None, max_length=100)) -> dict:
    core.ensure_tables()
    where, params = [], []
    if view == "needs_human":
        where.append("u.needs_human = 1")
    elif view in ("human", "ai"):
        where.append("u.handler = ?")
        params.append(view)
    if channel in CHANNELS:
        where.append("u.channel = ?")
        params.append(channel)
    if q:
        where.append("(u.display_name LIKE ? OR c.name LIKE ? OR EXISTS (SELECT 1 FROM channel_events s WHERE "
                     "s.channel = u.channel AND s.external_id = u.external_id AND s.text LIKE ?))")
        params += [f"%{q}%"] * 3
    sql = LIST_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY last_id DESC NULLS LAST LIMIT 200"
    counts = db.query_one("""SELECT COUNT(*) AS all_, COALESCE(SUM(needs_human), 0) AS needs_human,
                                    COALESCE(SUM(handler = 'human'), 0) AS human, COALESCE(SUM(handler = 'ai'), 0) AS ai
                             FROM channel_users""")
    return {"conversations": _with_intents(_records(db.query_df(sql, tuple(params)))),
            "counts": {"all": counts["all_"], "needs_human": counts["needs_human"], "human": counts["human"],
                       "ai": counts["ai"]}}


def _with_intents(convs: list[dict]) -> list[dict]:
    """Tag each conversation with what the customer is asking about (rule-based, see kotler.agent.intent)."""
    from kotler.agent.intent import LABELS, conversation_intent
    if not convs:
        return convs
    keys = [f"{c['channel']}:{c['external_id']}" for c in convs]
    texts = db.query_df(f"""SELECT channel || ':' || external_id AS k, text FROM channel_events WHERE direction = 'in'
                            AND channel || ':' || external_id IN ({",".join("?" * len(keys))})""", tuple(keys))
    by = texts.groupby("k").text.apply(lambda s: s.fillna("").tolist()).to_dict()
    for c, k in zip(convs, keys):
        intent = conversation_intent(by.get(k, []))
        c["intent"], c["intent_label"] = intent, LABELS[intent]
    return convs


def _profile(customer_id: int | None) -> dict | None:
    if not customer_id:
        return None
    c = db.query_one("""SELECT c.id, c.name, c.phone, c.email, c.city, c.state, p.tier, c.skin_type,
                               c.preferred_language, c.acquisition_channel, c.created_at
                        FROM customers c JOIN pincodes p ON p.pincode = c.pincode WHERE c.id = ?""", (customer_id,))
    if not c:
        return None
    stats = db.query_one("""SELECT COUNT(*) FILTER (WHERE status != 'cancelled') AS orders,
                                   COALESCE(SUM(total) FILTER (WHERE status = 'delivered'), 0) AS lifetime_value,
                                   MAX(created_at) AS last_order_at FROM orders WHERE customer_id = ?""", (customer_id,))
    try:
        score = db.query_one("SELECT segment, churn_risk, clv_12m FROM customer_scores WHERE customer_id = ?",
                             (customer_id,))
    except Exception:
        score = None
    orders = db.query_df("""SELECT order_number, created_at, status, payment_method, total FROM orders
                            WHERE customer_id = ? ORDER BY created_at DESC LIMIT 5""", (customer_id,))
    tickets = db.query_one("SELECT COUNT(*) AS n FROM support_tickets WHERE customer_id = ? AND status != 'resolved'",
                           (customer_id,))["n"]
    return {**c, **stats, **(score or {}), "open_tickets": tickets, "recent_orders": _records(orders)}


@router.get("/{channel}/{external_id}")
def conversation(channel: str, external_id: str) -> dict:
    s = _session(channel, external_id)
    msgs = db.query_df("SELECT id, direction, text, agent_slug, created_at, meta FROM channel_events WHERE channel = ? "
                       "AND external_id = ? ORDER BY id", (channel, external_id))
    if len(msgs):
        with db.get_conn() as conn:  # opening a conversation marks it read
            conn.execute("UPDATE channel_users SET last_read_id = ? WHERE channel = ? AND external_id = ?",
                         (int(msgs.id.max()), channel, external_id))
    from kotler.channels import whatsapp
    notes = db.query_df("SELECT id, author, text, created_at FROM inbox_notes WHERE channel = ? AND external_id = ? "
                        "ORDER BY id", (channel, external_id))
    return {"notes": _records(notes), "session": {k: s[k] for k in ("channel", "external_id", "display_name", "customer_id", "agent_slug",
                                          "handler", "needs_human", "marketing_opt_in", "last_inbound_at", "handoff_at")},
            "can_reply": channel != "whatsapp" or external_id.startswith("demo-") or whatsapp.within_24h(external_id),
            "messages": [_with_cards(m) for m in _records(msgs)], "customer": _profile(s["customer_id"])}


def _with_cards(m: dict) -> dict:
    meta = json.loads(m.pop("meta") or "{}")
    return {**m, "cards": meta.get("cards", [])}


@router.post("/{channel}/{external_id}/takeover")
def takeover(channel: str, external_id: str) -> dict:
    _session(channel, external_id)
    with db.get_conn() as conn:
        conn.execute("UPDATE channel_users SET handler = 'human', handoff_at = ?, escalated_at = COALESCE(escalated_at, ?) "
                     "WHERE channel = ? AND external_id = ?", (core._now(), core._now(), channel, external_id))
    return {"handler": "human"}


@router.post("/{channel}/{external_id}/release")
def release(channel: str, external_id: str) -> dict:
    _session(channel, external_id)
    with db.get_conn() as conn:
        conn.execute("UPDATE channel_users SET handler = 'ai', needs_human = 0, handoff_at = NULL "
                     "WHERE channel = ? AND external_id = ?", (channel, external_id))
    return {"handler": "ai"}


class ReplyIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


@router.post("/{channel}/{external_id}/reply")
def reply(channel: str, external_id: str, body: ReplyIn) -> dict:
    s = _session(channel, external_id)
    if s["handler"] != "human":
        raise HTTPException(409, "Take over the conversation first, so the AI and you don't both answer.")
    try:
        outbound.send(channel, external_id, body.text.strip(), author="human")
    except Exception as e:  # WhatsApp 24h window, allowlist, Telegram API error...
        raise HTTPException(422, f"Not sent: {e}") from e
    with db.get_conn() as conn:
        conn.execute("UPDATE channel_users SET needs_human = 0 WHERE channel = ? AND external_id = ?",
                     (channel, external_id))
    return {"sent": True}


class NoteIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


@router.post("/{channel}/{external_id}/notes")
def add_note(channel: str, external_id: str, body: NoteIn) -> dict:
    """A private note for the team. Stored separately from messages, so it can never be sent to the customer."""
    _session(channel, external_id)
    with db.get_conn() as conn:
        conn.execute("INSERT INTO inbox_notes (channel, external_id, author, text, created_at) VALUES (?,?,?,?,?)",
                     (channel, external_id, "admin", body.text.strip(), core._now()))
    return {"ok": True}


class AssistIn(BaseModel):
    action: str = Field(..., pattern="^(suggest|friendlier|shorter|hinglish|english|summarize)$")
    draft: str = Field("", max_length=4000)


@router.post("/{channel}/{external_id}/assist")
def assist(channel: str, external_id: str, body: AssistIn) -> dict:
    """AI copilot for the person replying: suggestions only, never sent automatically."""
    from kotler.agent.assist import assist as run
    from kotler.api.common import need_llm
    from kotler.llm import LLMError
    _session(channel, external_id)
    llm = need_llm()
    try:
        return run(llm, body.action, channel, external_id, body.draft)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except LLMError as e:
        raise HTTPException(502, e.user_message) from e


# --------------------------------------------------------------------- live stream
def events_since(last_id: int, limit: int = 100) -> list[dict]:
    core.ensure_tables()
    return _records(db.query_df(
        """SELECT e.id, e.channel, e.external_id, e.direction, e.text, e.agent_slug, e.created_at,
                  u.display_name, u.needs_human, u.handler
           FROM channel_events e LEFT JOIN channel_users u ON u.channel = e.channel AND u.external_id = e.external_id
           WHERE e.id > ? ORDER BY e.id LIMIT ?""", (last_id, limit)))


def latest_event_id() -> int:
    core.ensure_tables()
    return db.query_one("SELECT COALESCE(MAX(id), 0) AS m FROM channel_events")["m"]


@router.get("/stream")
async def stream(request: Request, last_event_id: str | None = Header(default=None),
                 max_seconds: float = Query(3600, le=3600)) -> StreamingResponse:
    start_id = int(last_event_id) if (last_event_id or "").isdigit() else latest_event_id()

    async def gen():
        last, idle, began = start_id, 0.0, asyncio.get_event_loop().time()
        yield "retry: 3000\n\n"                       # browser reconnects after 3 s if the line drops
        while asyncio.get_event_loop().time() - began < max_seconds:
            if await request.is_disconnected():
                break
            rows = await asyncio.to_thread(events_since, last)
            for r in rows:
                last = r["id"]
                yield f"id: {r['id']}\nevent: message\ndata: {json.dumps(r, default=str)}\n\n"
            idle = 0.0 if rows else idle + 1
            if idle >= 15:                            # keep-alive comment so proxies don't close the connection
                idle = 0.0
                yield ": ping\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --------------------------------------------------------------------- demo data
DEMO = [
    ("whatsapp", "demo-919812300001", None, "asha", 0, "ai", [
        ("in", "Hi, where is my order? It's been 5 days", None),
        ("out", "Hi {first}! Your order *{order}* was shipped with Delhivery and is out for delivery today. "
                "You'll get it by 7 pm.", "asha"),
        ("in", "Great, thanks!", None)]),
    ("telegram", "demo-552100002", None, "kavya", 0, "ai", [
        ("in", "oily skin ke liye koi achha face wash batao", None),
        ("out", "Oily skin ke liye *Neem & Tea Tree Oil-Control Face Wash* best rahega: oil control karta hai aur "
                "pores clean rakhta hai. Saath mein *10% Niacinamide + Zinc Serum* bhi le sakte ho.", "kavya"),
        ("in", "serum ka price kya hai?", None)]),
    ("whatsapp", "demo-919812300003", None, "asha", 1, "ai", [
        ("in", "The moisturizer gave me a rash on my cheeks. I'm really upset.", None),
        ("out", "I'm so sorry, {first}. Please stop using it and wash with cool water. I've passed this to our care "
                "team as a priority (reference ESC-2041). A person will reply within 2 hours.", "asha"),
        ("in", "Ok. I want a refund.", None)]),
    ("web", "demo-web-0004", None, "skin-quiz", 0, "ai", [
        ("in", "/quiz", None),
        ("out", "Hi! I'm Ira. Let's find your skin type. How does your skin feel by noon: oily, tight, or normal?",
         "skin-quiz"),
        ("in", "oily on the forehead, dry on the cheeks", None),
        ("out", "That sounds like *combination* skin. What's your main concern: acne, dullness or dark spots?",
         "skin-quiz")]),
    ("telegram", "demo-552100005", None, "asha", 1, "human", [
        ("in", "I want to cancel my order and talk to a real person", None),
        ("out", "I understand. I've connected you with our team.", "asha"),
        ("out", "Hi {first}, this is Neha from Glow & Co. I can help you with the cancellation.", "human"),
        ("in", "Thanks Neha. Order {order} please.", None)]),
]


@router.post("/demo")
def load_demo() -> dict:
    """Realistic sample chats (marked 'demo-'), so the inbox can be tried without connecting a bot."""
    core.ensure_tables()
    base = datetime.now() - timedelta(minutes=90)
    # Linked chats use REAL demo customers (so the profile panel has orders), with their names in the text.
    from kotler.agent.cards import product_cards
    all_products = [{"product_id": int(i)} for i in db.query_df("SELECT id FROM products").id]
    cust = db.query_df("""SELECT c.id, c.name, (SELECT order_number FROM orders o WHERE o.customer_id = c.id
                                                ORDER BY created_at DESC LIMIT 1) AS order_number
                          FROM customers c ORDER BY c.id LIMIT 5""").to_dict("records")
    with db.get_conn() as conn:
        conn.execute("DELETE FROM channel_events WHERE external_id LIKE 'demo-%'")
        conn.execute("DELETE FROM channel_users WHERE external_id LIKE 'demo-%'")
        conn.execute("DELETE FROM inbox_notes WHERE external_id LIKE 'demo-%'")
        for i, (ch, ext, name, agent, needs, handler, msgs) in enumerate(DEMO):
            t = base + timedelta(minutes=17 * i)
            c = cust[i] if ch != "web" and i < len(cust) else None
            fill = {"first": c["name"].split()[0] if c else "there", "order": (c or {}).get("order_number") or "KTL-100001"}
            conn.execute("INSERT INTO channel_users (channel, external_id, display_name, customer_id, agent_slug, "
                         "handler, needs_human, last_inbound_at, created_at, escalated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (ch, ext, c["name"] if c else name, c["id"] if c else None, agent, handler, needs,
                          t.strftime(core.FMT), t.strftime(core.FMT),
                          t.strftime(core.FMT) if needs or handler == "human" else None))
            for j, (direction, text, author) in enumerate(msgs):
                text = text.format(**fill)
                cards = product_cards(text, all_products) if author in ("kavya", "skin-quiz") else []
                conn.execute("INSERT INTO channel_events (channel, external_id, direction, text, agent_slug, created_at, "
                             "meta) VALUES (?,?,?,?,?,?,?)", (ch, ext, direction, text, author,
                                                            (t + timedelta(seconds=40 * j)).strftime(core.FMT),
                                                            json.dumps({"cards": cards}) if cards else None))
    return {"loaded": len(DEMO)}
