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
from kotler.agent import handoff
from kotler.agent.cards import product_cards
from kotler.agent.claims import find_unbacked_claims, find_ungrounded_prices
from kotler.agent.language import INSTRUCTION, detect_language
from kotler.agent.prompts import compose_system_prompt
from kotler.agent.studio import AgentConfig
from kotler.agent.tools import TOOLS, WRITE_TOOLS, ToolContext, execute_tool, get_my_profile, to_json
from kotler.llm import LLMError
from kotler.obs import trace as obs

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
    guard: list[str] = field(default_factory=list)   # safety checks that fired (shown in the UI)
    products: list[dict] = field(default_factory=list)   # product cards for products the reply recommends
    handoff: list[str] = field(default_factory=list)     # handoff rules that matched: a person must join

    @property
    def escalated(self) -> bool:
        """A person needs to join: the agent escalated, or a handoff rule matched."""
        return bool(self.handoff) or any(t.name == "escalate_to_human" and t.result.get("escalated") for t in self.tools)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Agent:
    def __init__(self, config: AgentConfig, llm, customer_id: int | None = None,
                 conversation_id: int | None = None, channel: str = "web"):
        self.config = config
        self.llm = llm
        self.channel = channel
        self.ctx = ToolContext(customer_id=customer_id, agent_slug=config.slug)
        self.allowed = [t for t in config.tools if t in TOOLS]
        self.schemas = [TOOLS[t][1] for t in self.allowed]
        db.ensure_schema()
        self.conversation_id = conversation_id or self._start_conversation(channel)
        self.ctx.conversation_id = self.conversation_id

    # ------------------------------------------------------------ public
    def reply(self, user_text: str) -> AgentTurn:
        """One customer message -> one answer, recorded as one trace (LLM calls, tools, guards inside it)."""
        with obs.trace("agent_turn", self.config.slug, self.conversation_id, self.channel, user_text) as t:
            self._trace = t
            turn = self._reply(user_text)
            t.output, t.error = turn.reply, turn.error
            t.escalated = turn.escalated
            t.status = ("error" if turn.error else "fail_safe" if any(g.startswith("fail-safe") for g in turn.guard)
                        else "corrected" if turn.guard else "ok")
            t.meta = {"tools": [x.name for x in turn.tools], "guards": turn.guard, "llm_calls": turn.llm_calls,
                      "version": self.config.version, "handoff": turn.handoff}
        return turn

    def _reply(self, user_text: str) -> AgentTurn:
        started = time.perf_counter()
        history = self._history()          # load BEFORE saving the new message
        self._save("user", user_text)

        system = compose_system_prompt(self.config, get_my_profile(self.ctx, _include_language=True))
        # Language is detected in code and stated explicitly, right NEXT TO the customer's message
        # (closest to where the answer is written). Only the model sees this note; history stores the raw text.
        lang = detect_language(user_text)
        sent_text = f"{user_text}\n\n[{INSTRUCTION[lang]}]" if lang else user_text
        messages = [{"role": "system", "content": system}, *history, {"role": "user", "content": sent_text}]
        turn = AgentTurn(reply="")
        budget = max(1, int(self.config.max_steps))
        can_act = bool(set(self.allowed) & WRITE_TOOLS)
        corrected = False
        try:
            step = 0
            while step < budget:
                last_step = step == budget - 1
                step += 1
                # On the last step we withhold the tools, which forces a text answer.
                tools = None if last_step or not self.schemas else self.schemas
                resp = self.llm.chat(messages, tools=tools, temperature=self.config.temperature)
                turn.llm_calls += 1
                turn.prompt_tokens += resp.prompt_tokens
                turn.completion_tokens += resp.completion_tokens

                if not resp.tool_calls:
                    turn.reply = (resp.content or "").strip()
                    issues = find_unbacked_claims(turn.reply, turn.tools, set(self.allowed)) if can_act else []
                    # Evidence: this turn's tool results, the customer's messages (budgets), earlier replies
                    # (already checked when sent) and the agent's own instructions (e.g. quiz budget options).
                    issues += find_ungrounded_prices(turn.reply, turn.tools, [h["content"] for h in history]
                                                     + [user_text, self.config.instructions])
                    if issues and not corrected:
                        # One chance to make the claim true (call the tool) or take it back.
                        corrected = True
                        turn.guard.append("claim check: " + "; ".join(issues))
                        self._trace.span("guard", "claim_check", ok=False, detail="; ".join(issues))
                        messages.append({"role": "assistant", "content": turn.reply})
                        messages.append({"role": "user", "content": (
                            f"[Automatic check failed: {'; '.join(issues)}. Call the right tool now (for products and "
                            "prices: search_products / build_routine / get_product_details; for actions: the action "
                            "tool) and use ONLY what it returns. Never invent products, prices or reference numbers. "
                            "If no tool can do it, rewrite your reply without the claim.]")})
                        budget = step + 2
                        continue
                    if issues:
                        turn.reply = self._fail_safe(user_text, issues, turn)
                    break

                messages.append(resp.raw)  # the assistant's tool request, unchanged
                for call in resp.tool_calls:
                    self._run_tool(call.name, call.arguments, turn, messages, call.id)
                if lang and lang != "en":
                    # Tool results are English; repeat the language note AFTER them, where the answer starts.
                    messages.append({"role": "user", "content": f"[{INSTRUCTION[lang]}]"})
            if not turn.reply:
                turn.reply = "Sorry, I couldn't put an answer together. Could you rephrase that?"
            elif lang in ("hinglish", "hi") and detect_language(turn.reply) == "en":
                turn.reply = self._rewrite_language(turn, lang)
                self._trace.span("guard", "language_rewrite", ok=detect_language(turn.reply) == lang, detail=lang)
        except LLMError as e:
            turn.reply, turn.error = e.user_message, str(e)[:500]
        self._apply_handoff_rules(user_text, lang, turn)

        turn.products = product_cards(turn.reply, [t.result for t in turn.tools])
        turn.latency_ms = int((time.perf_counter() - started) * 1000)
        self._save("assistant", turn.reply, latency_ms=turn.latency_ms, prompt_tokens=turn.prompt_tokens,
                   completion_tokens=turn.completion_tokens, error=turn.error)
        return turn

    def _run_tool(self, name: str, arguments: dict, turn: AgentTurn, messages: list | None = None,
                  call_id: str | None = None) -> dict:
        started = time.perf_counter()
        if name not in self.allowed:
            result = {"error": f"Tool '{name}' is not available to this agent."}
        else:
            result = execute_tool(name, arguments, self.ctx)
        if getattr(self, "_trace", None):
            err = result.get("error") if isinstance(result, dict) else None
            self._trace.span("tool", name, int((time.perf_counter() - started) * 1000), ok=not err,
                             detail=str(err or "")[:300])
        turn.tools.append(ToolTrace(name, arguments, result))
        self._save("tool", to_json(result), tool_name=name, tool_args=to_json(arguments))
        if messages is not None:
            messages.append({"role": "tool", "tool_call_id": call_id, "content": to_json(result)})
        return result

    def _apply_handoff_rules(self, user_text: str, lang: str | None, turn: AgentTurn) -> None:
        """Handoff rules (kotler/agent/handoff.py) are guarantees, not requests: if one matches and the agent
        didn't escalate, escalate now (or flag the chat for a person) and tell the customer."""
        fired = handoff.triggered(self.config.handoff_rules, user_text)
        if not fired:
            return
        turn.handoff = fired
        trace = getattr(self, "_trace", None)
        if any(t.name == "escalate_to_human" and t.result.get("escalated") for t in turn.tools):
            if trace:
                trace.span("guard", "handoff_rule", ok=True, detail=f"{', '.join(fired)}: the agent escalated itself")
            return
        when = ""
        if "escalate_to_human" in self.allowed:
            res = self._run_tool("escalate_to_human", {
                "summary": f"Handoff rule ({', '.join(fired)}). Customer said: {user_text[:400]}",
                "priority": handoff.priority(fired)}, turn)
            when = res.get("a_human_will_reply", "") if lang in (None, "en") else ""
        if trace:
            trace.span("guard", "handoff_rule", ok=False, detail=", ".join(fired))
        turn.reply = f"{turn.reply}\n\n{handoff.notice(lang, when)}".strip()

    def _fail_safe(self, user_text: str, issues: list[str], turn: AgentTurn) -> str:
        """The model still claims an action it didn't take. Never send that. Fail towards a human:
        escalate for real (if this agent may), and tell the customer honestly what happens next."""
        turn.guard.append("fail-safe: " + "; ".join(issues))
        if getattr(self, "_trace", None):
            self._trace.span("guard", "fail_safe", ok=False, detail="; ".join(issues))
        if all("price" in i for i in issues):  # shopping agents: never send invented prices
            return ("Sorry, I want to give you exact prices, and I couldn't look them up just now. "
                    "Could you send your message again?")
        if "escalate_to_human" in self.allowed:
            res = self._run_tool("escalate_to_human", {
                "summary": f"Auto-escalated: the AI could not complete the request reliably. Customer said: {user_text[:400]}",
                "priority": "high"}, turn)
            if res.get("escalated"):
                return (f"I've passed this to our care team so a person can sort it out properly "
                        f"(reference {res['reference']}). Someone will reply {res['a_human_will_reply']}.")
        return ("Sorry, I couldn't complete that just now. Please message our care team on WhatsApp and "
                "they'll help you right away.")

    def _rewrite_language(self, turn: AgentTurn, lang: str) -> str:
        """Safety net: the reply came back in English for a Hinglish/Hindi customer. Ask for a faithful
        rewrite (facts, numbers, names and references unchanged). Costs one extra call, only on a miss."""
        target = {"hinglish": "Hinglish (Hindi written in English letters)", "hi": "Hindi (Devanagari)"}[lang]
        prompt = (f"Rewrite this customer-care message in {target}. Keep every fact, number, price, date, product "
                  f"name and reference code exactly the same. Keep *bold* formatting. Reply with the message only.\n\n"
                  f"{turn.reply}")
        try:
            resp = self.llm.chat([{"role": "user", "content": prompt}], tools=None, temperature=0)
        except LLMError:
            return turn.reply  # an English answer beats no answer
        turn.llm_calls += 1
        turn.prompt_tokens += resp.prompt_tokens
        turn.completion_tokens += resp.completion_tokens
        rewritten = (resp.content or "").strip()
        return rewritten if rewritten and detect_language(rewritten) == lang else turn.reply

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
