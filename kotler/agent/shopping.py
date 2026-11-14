"""The shopping agent: an LLM in a loop with tools.

    messages = [system prompt, ...history, user message]
    repeat up to MAX_STEPS:
        response = llm(messages, tools)
        if response asks for tools:
            run each tool, append results to messages, continue
        else:
            return response text            # final answer

That's the whole idea behind "AI agents". Frameworks like LangChain wrap this
loop; writing it yourself means you can explain and debug every step.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

from kotler import db
from kotler.agent.prompts import shopping_system_prompt
from kotler.agent.tools import TOOL_SCHEMAS, ToolContext, execute_tool, get_my_profile, to_json
from kotler.llm import LLMError

MAX_STEPS = 5          # max LLM calls per customer message (stops infinite tool loops)
HISTORY_TURNS = 10     # how many previous user/assistant messages to include as memory


@dataclass
class ToolTrace:
    name: str
    arguments: dict
    result: dict


@dataclass
class AgentTurn:
    reply: str
    tools: list[ToolTrace] = field(default_factory=list)
    llm_calls: int = 0
    latency_ms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    error: str | None = None


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class ShoppingAgent:
    def __init__(self, llm, customer_id: int | None = None, conversation_id: int | None = None,
                 channel: str = "web"):
        self.llm = llm
        self.ctx = ToolContext(customer_id=customer_id)
        db.ensure_schema()
        self.conversation_id = conversation_id or self._start_conversation(channel)

    # ------------------------------------------------------------ public
    def reply(self, user_text: str) -> AgentTurn:
        started = time.perf_counter()
        history = self._history()          # load BEFORE saving the new message
        self._save("user", user_text)

        messages = [{"role": "system", "content": shopping_system_prompt(get_my_profile(self.ctx))},
                    *history, {"role": "user", "content": user_text}]
        turn = AgentTurn(reply="")
        try:
            for step in range(MAX_STEPS):
                last_step = step == MAX_STEPS - 1
                # On the last step we withhold the tools, which forces a text answer.
                resp = self.llm.chat(messages, tools=None if last_step else TOOL_SCHEMAS)
                turn.llm_calls += 1
                turn.prompt_tokens += resp.prompt_tokens
                turn.completion_tokens += resp.completion_tokens

                if not resp.tool_calls:
                    turn.reply = (resp.content or "").strip()
                    break

                messages.append(resp.raw)  # the assistant's tool request, unchanged
                for call in resp.tool_calls:
                    result = execute_tool(call.name, call.arguments, self.ctx)
                    turn.tools.append(ToolTrace(call.name, call.arguments, result))
                    self._save("tool", to_json(result), tool_name=call.name, tool_args=to_json(call.arguments))
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": to_json(result)})
            if not turn.reply:
                turn.reply = "Sorry, I couldn't put an answer together. Could you rephrase that?"
        except LLMError as e:
            turn.reply, turn.error = e.user_message, str(e)[:500]

        turn.latency_ms = int((time.perf_counter() - started) * 1000)
        self._save("assistant", turn.reply, latency_ms=turn.latency_ms, prompt_tokens=turn.prompt_tokens,
                   completion_tokens=turn.completion_tokens, error=turn.error)
        return turn

    # ----------------------------------------------------------- storage
    def _start_conversation(self, channel: str) -> int:
        with db.get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO conversations (customer_id, agent, channel, model, created_at) VALUES (?,?,?,?,?)",
                (self.ctx.customer_id, "shopping", channel, getattr(self.llm, "model", None), _now()))
            return cur.lastrowid

    def _save(self, role: str, content: str, **extra) -> None:
        cols = ["conversation_id", "role", "content", "created_at", *extra]
        vals = [self.conversation_id, role, content, _now(), *extra.values()]
        with db.get_conn() as conn:
            conn.execute(f"INSERT INTO messages ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)

    def _history(self) -> list[dict]:
        """Previous user and assistant texts only. Old tool results are left out:
        they're bulky, and the final answers already contain what matters."""
        rows = db.query_df("""
            SELECT role, content FROM messages
            WHERE conversation_id = ? AND role IN ('user', 'assistant') AND error IS NULL
            ORDER BY id DESC LIMIT ?""", (self.conversation_id, HISTORY_TURNS))
        return [{"role": r.role, "content": r.content} for r in rows.iloc[::-1].itertuples()]
