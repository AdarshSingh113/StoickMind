"""Deliver campaign messages on real channels, and send test messages.

Who can receive a campaign message on a real channel?
  - their chat is LINKED to the customer (WhatsApp: automatically by phone number; Telegram/web: after the
    customer verified with an order number, or an operator linked a demo chat in the dashboard),
  - they have NOT opted out (STOP),
  - WhatsApp only: their number is on the test allowlist AND they wrote to us in the last 24 hours
    (outside the window WhatsApp only allows paid, pre-approved templates).
Everyone else in the campaign stays "simulated". Nothing is ever sent to the random demo phone numbers.
"""

from __future__ import annotations

from datetime import datetime

from kotler import db
from kotler.channels import core, telegram, whatsapp


def link_chat_to_customer(channel: str, external_id: str, customer_id: int) -> None:
    """DEMO/OPERATOR action from the dashboard (never from chat): treat this chat as that customer."""
    core.ensure_tables()
    with db.get_conn() as conn:
        conn.execute("UPDATE channel_users SET customer_id = ?, conversation_id = NULL WHERE channel = ? AND external_id = ?",
                     (customer_id, channel, external_id))


def send(channel: str, external_id: str, text: str, author: str = "campaign") -> None:
    """Send a message WE start (campaign, or a person replying from the inbox) and log it.
    Website chats have no open connection: the message is stored and the widget picks it up (it polls).
    Demo chats (external id 'demo-...') are only logged, never sent anywhere."""
    if channel == "web" or external_id.startswith("demo-"):
        pass
    elif channel == "telegram":
        telegram.send_text(external_id, text)
    elif channel == "whatsapp":
        whatsapp.send_text(external_id, text)
    else:
        raise ValueError(f"Unknown channel {channel!r}.")
    with db.get_conn() as conn:
        conn.execute("INSERT INTO channel_events (channel, external_id, direction, text, agent_slug, created_at) "
                     "VALUES (?,?,?,?,?,?)", (channel, external_id, "out", text[:4000], author,
                                              datetime.now().strftime("%Y-%m-%d %H:%M:%S")))


def deliver_campaign(campaign_id: int, channel: str) -> dict:
    msgs = db.query_df("SELECT customer_id, message FROM campaign_members WHERE campaign_id = ? AND grp IN ('A', 'B') "
                       "AND message IS NOT NULL", (campaign_id,))
    recipients = core.opted_in_recipients(channel, msgs.customer_id.astype(int).tolist())
    result = {"campaign_messages": len(msgs), "linked_and_opted_in": len(recipients), "sent": 0, "failed": []}
    for cid, text in zip(msgs.customer_id.astype(int), msgs.message):
        ext = recipients.get(cid)
        if not ext:
            continue
        try:
            send(channel, ext, text + "\n\n(Reply STOP to stop offers.)")
            result["sent"] += 1
        except Exception as e:  # not allowed / outside 24h / API error: report, don't crash the batch
            result["failed"].append({"customer_id": cid, "reason": str(e)[:200]})
    return result


def connected_chats():
    core.ensure_tables()
    return db.query_df("""SELECT u.channel, u.external_id, u.display_name, u.customer_id, c.name AS customer,
                                 u.agent_slug, u.marketing_opt_in, u.last_inbound_at, u.created_at,
                                 (SELECT COUNT(*) FROM channel_events e WHERE e.channel = u.channel
                                  AND e.external_id = u.external_id) AS messages
                          FROM channel_users u LEFT JOIN customers c ON c.id = u.customer_id
                          ORDER BY u.last_inbound_at DESC""")


def thread(channel: str, external_id: str):
    return db.query_df("SELECT direction, text, agent_slug, created_at FROM channel_events WHERE channel = ? AND "
                       "external_id = ? ORDER BY id", (channel, external_id))
