"""Conversation analytics: what do customers ask about, and how much of it does the AI handle without a person?

Built from the real message log (Telegram, WhatsApp, website chat), not from evals, so these numbers grow
with actual use. Demo conversations are counted and reported separately, so nobody mistakes them for traffic.

AUTOMATION RATE = conversations the AI handled end to end / all conversations, where "end to end" means the
AI replied, no person replied, nothing is waiting for a person, and it was never escalated (an escalation
counts even if the chat was later handed back to the AI). It measures "no person was needed", NOT
"the customer was happy": read it next to the judge's success rate (Agents tab). A high automation rate on
"Skin reaction" would be a red flag, not a win: those chats SHOULD reach a person.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from kotler import db
from kotler.agent.intent import LABELS, classify, conversation_intent

COLUMNS = ["channel", "external_id", "messages", "customer_messages", "ai_replies", "human_replies", "intent",
           "status", "demo", "last_at", "example"]


def conversation_table(days: int | None = 30) -> pd.DataFrame:
    """One row per conversation active in the period."""
    from kotler.channels import core
    core.ensure_tables()
    since = (datetime.now() - timedelta(days=days)).strftime(core.FMT) if days else "0000"
    ev = db.query_df("SELECT channel, external_id, direction, text, agent_slug, created_at FROM channel_events "
                     "WHERE created_at >= ? ORDER BY id", (since,))
    if ev.empty:
        return pd.DataFrame(columns=COLUMNS)
    users = db.query_df("SELECT channel, external_id, handler, needs_human, escalated_at FROM channel_users").set_index(
        ["channel", "external_id"])
    rows = []
    for (ch, ext), g in ev.groupby(["channel", "external_id"], sort=False):
        inbound = g[g.direction == "in"].text.fillna("").tolist()
        out = g[g.direction == "out"]
        human = int((out.agent_slug == "human").sum())
        ai = len(out) - human
        u = users.loc[(ch, ext)] if (ch, ext) in users.index else None
        waiting = u is not None and (bool(u.needs_human) or u.handler == "human" or isinstance(u.escalated_at, str))
        status = "handed_over" if human or waiting else ("automated" if ai else "unanswered")
        intent = conversation_intent(inbound)
        said = [t for t in inbound if not t.startswith("/")] or inbound     # "/quiz" is a poor example
        example = next((t for t in said if classify(t) == intent), said[0] if said else "")
        rows.append({"channel": ch, "external_id": ext, "messages": len(g), "customer_messages": len(inbound),
                     "ai_replies": ai, "human_replies": human, "intent": intent, "status": status,
                     "demo": ext.startswith("demo-"), "last_at": g.created_at.iloc[-1], "example": example[:120]})
    return pd.DataFrame(rows, columns=COLUMNS)


def conversation_stats(days: int | None = 30) -> dict:
    t = conversation_table(days)
    n = len(t)
    automated = int((t.status == "automated").sum())
    summary = {"conversations": n, "automated": automated, "automation_rate": automated / n if n else None,
               "handed_over": int((t.status == "handed_over").sum()), "unanswered": int((t.status == "unanswered").sum()),
               "avg_messages": float(t.messages.mean()) if n else 0.0, "demo": int(t.demo.sum())}
    intents = []
    for key, g in t.groupby("intent"):
        latest = g.sort_values("last_at").iloc[-1]
        intents.append({"intent": key, "label": LABELS[key], "conversations": len(g), "share": len(g) / n,
                        "automated_pct": 100 * (g.status == "automated").mean(),
                        "handed_over_pct": 100 * (g.status == "handed_over").mean(),
                        "avg_messages": float(g.messages.mean()), "example": latest.example})
    channels = [{"channel": ch, "conversations": len(g), "automated_pct": 100 * (g.status == "automated").mean()}
                for ch, g in t.groupby("channel")]
    return {"summary": summary, "intents": sorted(intents, key=lambda r: -r["conversations"]),
            "channels": sorted(channels, key=lambda r: -r["conversations"])}
