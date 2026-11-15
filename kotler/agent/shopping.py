"""The shopping agent ("Kavya").

Since Phase 3 this is no longer special code: it's the built-in "kavya" agent from the
Agent Studio, run by the generic runtime. Edit its instructions in the Studio and
the Shop Assistant page uses the new version immediately.

This module keeps the Phase 2 names (ShoppingAgent, AgentTurn, MAX_STEPS) so older
code and tests keep working.
"""

from __future__ import annotations

from kotler.agent.runtime import Agent, AgentTurn, ToolTrace  # noqa: F401  (re-exported)
from kotler.agent.studio import KAVYA, get_agent

MAX_STEPS = KAVYA.max_steps


class ShoppingAgent(Agent):
    def __init__(self, llm, customer_id: int | None = None, conversation_id: int | None = None,
                 channel: str = "web"):
        super().__init__(get_agent("kavya") or KAVYA, llm, customer_id, conversation_id, channel)
