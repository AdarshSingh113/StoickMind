"""The generic agent runtime: runs ANY agent configured in the Studio.

    messages = [system prompt (from config), ...history, user message]
    repeat up to config.max_steps:
        response = llm(messages, tools allowed for THIS agent)
        if response asks for tools: run them (if allowed), append results, continue
        else: return the text

Compared with Phase 2's ShoppingAgent, two things changed:
1. Prompt, tools, temperature and step limit come from the agent's configuration.
2. Tool permissions are enforced HERE, in code. The model only sees the schemas of its
   allowed tools, and if it still asks for another tool (it can hallucinate names),
   the call is refused. Never rely on the prompt alone for permissions.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime

from kotler import db
from kotler.agent.prompts import compose_system_prompt
from kotler.agent.studio import AgentConfig
from kotler.agent.tools import TOOLS, ToolContext, execute_tool, get_my_profile, to_json
from kotler.llm import LLMError

HISTORY_TURNS = 10     # previous user/assistant messages included as memory


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


class Agent:
    def __init__(self, config: AgentConfig, llm, customer_id: int | None = None,
                 conversation_id: int | None = None, channel: str = "web"):
        self.config = config
        self.llm = llm
        self.ctx = ToolContext(customer_id=customer_id)
        self.allowed = [t for t in config.tools if t in TOOLS]
        self.schemas = [TOOLS[t][1] for t in self.allowed]
        db.ensure_schema()
        self.conversation_id = conversation_id or self._start_conversation(channel)

    # ------------------------------------------------------------ public
    def reply(self, user_text: str) -> AgentTurn:
        started = time.perf_counter()
        history = self._history()          # load BEFORE saving the new message
        self._save("user", user_text)

        system = compose_system_prompt(self.config, get_my_profile(self.ctx, _include_language=True))
        messages = [{"role": "system", "content": system}, *history, {"role": "user", "content": user_text}]
        turn = AgentTurn(reply="")
        max_steps = max(1, int(self.config.max_steps))
        try:
            for step in range(max_steps):
                last_step = step == max_steps - 1
                # On the last step we withhold the tools, which forces a text answer.
                tools = None if last_step or not self.schemas else self.schemas
                resp = self.llm.chat(messages, tools=tools, temperature=self.config.temperature)
                turn.llm_calls += 1
                turn.prompt_tokens += resp.prompt_tokens
                turn.completion_tokens += resp.completion_tokens

                if not resp.tool_calls:
                    turn.reply = (resp.content or "").strip()
                    break

                messages.append(resp.raw)  # the assistant's tool request, unchanged
                for call in resp.tool_calls:
                    if call.name not in self.allowed:
                        result = {"error": f"Tool '{call.name}' is not available to this agent."}
                    else:
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

    def transcript(self) -> list[dict]:
        """The whole conversation, tool calls included (used by the judge)."""
        return db.query_df("SELECT role, content, tool_name, tool_args FROM messages WHERE conversation_id = ? "
                           "ORDER BY id", (self.conversation_id,)).to_dict("records")

    # ----------------------------------------------------------- storage
    def _start_conversation(self, channel: str) -> int:
        with db.get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO conversations (customer_id, agent, channel, model, created_at) VALUES (?,?,?,?,?)",
                (self.ctx.customer_id, self.config.slug, channel, getattr(self.llm, "model", None), _now()))
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
