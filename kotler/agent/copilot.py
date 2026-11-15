"""AI copilot for the support inbox: let an agent handle a real ticket.

Tickets come in on WhatsApp / email / chat, where we already know who the customer is
(their WhatsApp number is on file), so the agent runs as that logged-in customer.

Outcome of each run:
  resolved   the agent handled it without needing a human
  escalated  it called escalate_to_human (a human takes over)
  error      the AI service failed (the ticket stays with humans)

Open tickets are actually updated (that's the point of automation). Already-closed historical
tickets can be REPLAYED to measure "what share would AI have resolved?" without changing history.
"""

from __future__ import annotations

from datetime import datetime

from kotler import db
from kotler.agent.runtime import Agent, AgentTurn
from kotler.agent.studio import get_agent


def run_ticket(llm, ticket_id: int, agent_slug: str = "asha") -> tuple[AgentTurn, str, Agent]:
    ticket = db.query_one("SELECT * FROM support_tickets WHERE id = ?", (ticket_id,))
    if not ticket:
        raise ValueError(f"Ticket {ticket_id} not found")
    agent = Agent(get_agent(agent_slug), llm, customer_id=ticket["customer_id"], channel=ticket["channel"])
    turn = agent.reply(ticket["message"])
    escalated = any(t.name == "escalate_to_human" and t.result.get("escalated") for t in turn.tools)
    outcome = "error" if turn.error else "escalated" if escalated else "resolved"
    actions = sum(1 for t in turn.tools if t.name in ("cancel_order", "offer_discount", "report_damaged_item",
                                                      "request_refund", "escalate_to_human") and "error" not in t.result)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with db.get_conn() as conn:
        conn.execute("INSERT INTO ai_ticket_runs (ticket_id, conversation_id, agent_slug, outcome, actions, latency_ms, "
                     "created_at) VALUES (?,?,?,?,?,?,?)",
                     (ticket_id, agent.conversation_id, agent_slug, outcome, actions, turn.latency_ms, now))
        if ticket["status"] == "open" and outcome == "resolved":
            conn.execute("UPDATE support_tickets SET status = 'resolved', resolved_at = ?, resolved_by = 'ai' "
                         "WHERE id = ?", (now, ticket_id))
        elif ticket["status"] == "open" and outcome == "escalated":
            conn.execute("UPDATE support_tickets SET status = 'escalated' WHERE id = ?", (ticket_id,))
    return turn, outcome, agent


def ai_stats() -> dict:
    row = db.query_one("""SELECT COUNT(*) AS runs,
                                 AVG(outcome = 'resolved') FILTER (WHERE outcome != 'error') AS resolved_rate,
                                 AVG(outcome = 'escalated') FILTER (WHERE outcome != 'error') AS escalated_rate,
                                 AVG(latency_ms) FILTER (WHERE outcome != 'error') AS latency_ms,
                                 SUM(actions) AS actions
                          FROM ai_ticket_runs""")
    return {k: (v or 0) for k, v in row.items()}


def recent_runs(limit: int = 20):
    return db.query_df("""SELECT r.created_at, r.ticket_id, t.category, t.message, r.outcome, r.actions, r.latency_ms
                          FROM ai_ticket_runs r JOIN support_tickets t ON t.id = r.ticket_id
                          ORDER BY r.id DESC LIMIT ?""", (limit,))
