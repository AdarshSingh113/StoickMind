"""Channel core: handle one incoming message from ANY channel (Telegram, WhatsApp, website widget).

Channel adapters only translate (their JSON in, their API out). Everything else lives here, once:

- IDENTITY     each (channel, external id) has a session. On WhatsApp the phone number identifies a known
               customer automatically; elsewhere people start as guests and can verify with an order number
               + phone digits (verify_order). The verified customer is SAVED on the session, because every
               message arrives as a separate web request and a new Agent object.
- ROUTING      /shop -> Kavya, /help -> Asha, /quiz -> Ira; otherwise order/refund/delivery words go to Asha,
               everything else to Kavya. The chosen agent sticks for the conversation until /new.
- IDEMPOTENCY  Telegram and WhatsApp RETRY webhooks when we're slow. A retried "cancel my order" must not
               run twice, so each update id is processed exactly once.
- RATE LIMIT   max 12 messages per user per minute: protects the free LLM quota from one chatty user.
- CONSENT      "STOP" opts out of marketing (campaigns skip them); "START" opts back in.
- HANDOFF      a person can TAKE OVER a chat from the dashboard inbox (handler = 'human'): the AI stays silent
               until it's handed back. Chats where the AI escalated are flagged needs_human.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from kotler import db

FMT = "%Y-%m-%d %H:%M:%S"
RATE_LIMIT = 12            # messages per user per minute
MAX_CHARS = {"telegram": 4000, "whatsapp": 4000, "web": 4000}

SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_users (
    channel TEXT NOT NULL, external_id TEXT NOT NULL, display_name TEXT, customer_id INTEGER REFERENCES customers(id),
    agent_slug TEXT, conversation_id INTEGER, marketing_opt_in INTEGER NOT NULL DEFAULT 1, opted_out_at TEXT,
    verify_attempts INTEGER NOT NULL DEFAULT 0, last_inbound_at TEXT, created_at TEXT NOT NULL,
    PRIMARY KEY (channel, external_id)
);
CREATE TABLE IF NOT EXISTS processed_updates (
    channel TEXT NOT NULL, update_id TEXT NOT NULL, received_at TEXT NOT NULL, PRIMARY KEY (channel, update_id)
);
CREATE TABLE IF NOT EXISTS channel_events (
    id INTEGER PRIMARY KEY, channel TEXT NOT NULL, external_id TEXT NOT NULL, direction TEXT NOT NULL
        CHECK (direction IN ('in', 'out')), text TEXT, agent_slug TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_channel_events_user ON channel_events(channel, external_id, created_at);
"""

ORDER_WORDS = re.compile(r"\b(order|orders|track|tracking|deliver|delivery|courier|cancel|refund|return|replace|"
                         r"damaged|broken|leak|leaking|parcel|shipped|kab aayega|nahi aaya|paisa wapas)\b|ktl-?\d", re.I)
COMMANDS = {"/shop": "kavya", "/help": "asha", "/support": "asha", "/quiz": "skin-quiz"}
WELCOME = ("Hi{name}! I'm the Glow & Co. assistant.\n\n"
           "Ask me anything, in English or Hinglish:\n"
           "• product advice: \"moisturizer for dry skin under ₹500\"\n"
           "• your orders: \"where is my order KTL-103245?\"\n\n"
           "Commands: /shop (shopping help), /help (orders & support), /quiz (skin quiz), /new (start over), "
           "STOP (no marketing messages).")


# Columns added after Phase 7. Existing databases get them with ALTER TABLE: a tiny "migration".
MIGRATIONS = {
    "channel_users": {"handler": "TEXT NOT NULL DEFAULT 'ai'", "needs_human": "INTEGER NOT NULL DEFAULT 0",
                      "handoff_at": "TEXT", "last_read_id": "INTEGER NOT NULL DEFAULT 0"},
    "channel_events": {"meta": "TEXT"},   # JSON, e.g. the product cards shown with an AI reply
}


def ensure_tables() -> None:
    with db.get_conn() as conn:
        conn.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, ddl in cols.items():
                if col not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def _now() -> str:
    return datetime.now().strftime(FMT)


@dataclass
class Incoming:
    channel: str            # 'telegram' | 'whatsapp' | 'web'
    external_id: str        # Telegram chat id, WhatsApp phone number, or web session id
    text: str
    update_id: str | None = None
    display_name: str | None = None


@dataclass
class Outgoing:
    texts: list[str] = field(default_factory=list)
    agent_slug: str | None = None
    duplicate: bool = False
    rate_limited: bool = False
    human: bool = False        # a person is handling this chat: the AI stayed silent
    cards: list[dict] = field(default_factory=list)   # product cards for the products the reply recommends


def _customer_for_phone(phone: str) -> int | None:
    digits = "".join(ch for ch in phone if ch.isdigit())[-10:]
    row = db.query_one("SELECT id FROM customers WHERE phone = ?", (digits,)) if len(digits) == 10 else None
    return row["id"] if row else None


def get_session(channel: str, external_id: str, display_name: str | None = None) -> dict:
    ensure_tables()
    row = db.query_one("SELECT * FROM channel_users WHERE channel = ? AND external_id = ?", (channel, external_id))
    if row:
        return row
    customer_id = _customer_for_phone(external_id) if channel == "whatsapp" else None
    with db.get_conn() as conn:
        conn.execute("INSERT INTO channel_users (channel, external_id, display_name, customer_id, created_at) "
                     "VALUES (?,?,?,?,?)", (channel, external_id, display_name, customer_id, _now()))
    return db.query_one("SELECT * FROM channel_users WHERE channel = ? AND external_id = ?", (channel, external_id))


def _update_session(channel: str, external_id: str, **fields) -> None:
    sets = ", ".join(f"{k} = ?" for k in fields)
    with db.get_conn() as conn:
        conn.execute(f"UPDATE channel_users SET {sets} WHERE channel = ? AND external_id = ?",
                     (*fields.values(), channel, external_id))


def _log(channel: str, external_id: str, direction: str, text: str, agent: str | None = None,
         meta: dict | None = None) -> None:
    import json
    with db.get_conn() as conn:
        conn.execute("INSERT INTO channel_events (channel, external_id, direction, text, agent_slug, created_at, meta) "
                     "VALUES (?,?,?,?,?,?,?)", (channel, external_id, direction, text[:4000], agent, _now(),
                                                json.dumps(meta) if meta else None))


def already_processed(channel: str, update_id: str | None) -> bool:
    """Record the update id; True if we've seen it before (a webhook retry)."""
    if not update_id:
        return False
    ensure_tables()
    try:
        with db.get_conn() as conn:
            conn.execute("INSERT INTO processed_updates (channel, update_id, received_at) VALUES (?,?,?)",
                         (channel, str(update_id), _now()))
        return False
    except sqlite3.IntegrityError:
        return True


def rate_limited(channel: str, external_id: str) -> bool:
    since = (datetime.now() - timedelta(minutes=1)).strftime(FMT)
    n = db.query_one("SELECT COUNT(*) AS n FROM channel_events WHERE channel = ? AND external_id = ? AND direction = 'in' "
                     "AND created_at >= ?", (channel, external_id, since))["n"]
    return n >= RATE_LIMIT


def route(text: str, current: str | None) -> str:
    if current:
        return current
    return "asha" if ORDER_WORDS.search(text or "") else "kavya"


def split_message(text: str, limit: int) -> list[str]:
    """Split long replies at paragraph/line boundaries (channels cap message length)."""
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            parts.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) + 1 > limit:
            parts.append(current.rstrip())
            current = ""
        current += line + "\n"
    if current.strip():
        parts.append(current.rstrip())
    return parts


def handle_incoming(msg: Incoming, llm=None) -> Outgoing:
    """Process one message and return the reply text(s). Pure logic: sending is the adapter's job."""
    from kotler.agent.runtime import Agent
    from kotler.agent.studio import get_agent
    from kotler.llm import get_llm

    ensure_tables()
    if already_processed(msg.channel, msg.update_id):
        return Outgoing(duplicate=True)
    session = get_session(msg.channel, msg.external_id, msg.display_name)
    text = (msg.text or "").strip()
    if rate_limited(msg.channel, msg.external_id):
        return Outgoing(texts=["You're sending messages very fast. Please wait a minute and try again."],
                        rate_limited=True)
    _log(msg.channel, msg.external_id, "in", text)
    _update_session(msg.channel, msg.external_id, last_inbound_at=_now())

    def reply(texts: list[str], agent: str | None = None, cards: list[dict] | None = None) -> Outgoing:
        for i, t in enumerate(texts):
            last = i == len(texts) - 1
            _log(msg.channel, msg.external_id, "out", t, agent, {"cards": cards} if cards and last else None)
        return Outgoing(texts=texts, agent_slug=agent, cards=cards or [])

    cmd = text.split()[0].lower() if text else ""
    first = f" {msg.display_name.split()[0]}" if msg.display_name else ""
    if cmd in ("/start", "hi", "hello", "hey") and not session["conversation_id"]:
        return reply([WELCOME.format(name=first)])
    if cmd in ("/start", "/new"):
        _update_session(msg.channel, msg.external_id, agent_slug=None, conversation_id=None)
        return reply([WELCOME.format(name=first)] if cmd == "/start" else ["Starting fresh. How can I help?"])
    if text.upper() in ("STOP", "/STOP", "UNSUBSCRIBE"):
        _update_session(msg.channel, msg.external_id, marketing_opt_in=0, opted_out_at=_now())
        return reply(["Done: you won't get marketing messages from us. You can still chat with us anytime. "
                      "Send START to opt back in."])
    if text.upper() in ("START", "/OPTIN"):
        _update_session(msg.channel, msg.external_id, marketing_opt_in=1, opted_out_at=None)
        return reply(["You're subscribed to offers and reminders again. Send STOP anytime to opt out."])
    if cmd in COMMANDS:
        slug = COMMANDS[cmd]
        _update_session(msg.channel, msg.external_id, agent_slug=slug, conversation_id=None)
        rest = text[len(cmd):].strip()
        if not rest:
            name = (get_agent(slug).name if get_agent(slug) else slug)
            return reply([f"You're now chatting with {name}. What would you like to know?"], slug)
        text, session = rest, get_session(msg.channel, msg.external_id)
    if session.get("handler") == "human":
        # A person took over in the inbox. Log the message (done above), stay silent, flag it for them.
        _update_session(msg.channel, msg.external_id, needs_human=1)
        return Outgoing(human=True)
    if not text:
        return reply(["I can only read text messages for now. Please type your question."])

    slug = route(text, session["agent_slug"])
    config = get_agent(slug)
    if config is None or config.status != "live":
        slug, config = "kavya", get_agent("kavya")
    llm = llm or get_llm()
    if llm is None:
        return reply(["Our assistant is offline right now. Please try again later."], slug)

    same_agent = session["agent_slug"] == slug and session["conversation_id"]
    agent = Agent(config, llm, customer_id=session["customer_id"],
                  conversation_id=session["conversation_id"] if same_agent else None, channel=msg.channel)
    agent.ctx.verify_attempts = session["verify_attempts"]
    turn = agent.reply(text)
    # Persist what the agent learned (verification!) and which conversation/agent we're in.
    escalated = any(t.name == "escalate_to_human" and t.result.get("escalated") for t in turn.tools)
    _update_session(msg.channel, msg.external_id, agent_slug=slug, conversation_id=agent.conversation_id,
                    customer_id=agent.ctx.customer_id, verify_attempts=agent.ctx.verify_attempts,
                    **({"needs_human": 1} if escalated else {}))
    return reply(split_message(turn.reply, MAX_CHARS.get(msg.channel, 4000)), slug, turn.products)


def opted_in_recipients(channel: str, customer_ids: list[int]) -> dict[int, str]:
    """customer_id -> external id, for customers linked on this channel who haven't opted out."""
    ensure_tables()
    rows = db.query_df("SELECT customer_id, external_id FROM channel_users WHERE channel = ? AND marketing_opt_in = 1 "
                       "AND customer_id IS NOT NULL", (channel,))
    rows = rows[rows.customer_id.isin(customer_ids)]
    return dict(zip(rows.customer_id.astype(int), rows.external_id))
