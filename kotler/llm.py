"""LLM layer: one small interface, swappable backends.

Why an abstraction?
- Vendor independence: Gemini today; Groq, Ollama or OpenAI tomorrow, just by
  changing a URL and a model name, because they all speak the
  "OpenAI-compatible" chat-completions format.
- Testability: FakeLLM lets us test the agent loop without network or API cost.

The OpenAI-compatible format in one minute
------------------------------------------
We send a list of messages:
    {"role": "system",    "content": "You are..."}
    {"role": "user",      "content": "moisturizer for dry skin"}
plus a list of tools (JSON-schema descriptions of our Python functions).
The model answers EITHER with text, OR with tool_calls:
    {"role": "assistant", "tool_calls": [{"id": "c1", "function":
        {"name": "search_products", "arguments": "{\"skin_type\": \"dry\"}"}}]}
We run the function and send the result back as:
    {"role": "tool", "tool_call_id": "c1", "content": "{...json...}"}
...and call the model again. That loop is an "agent".
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable

from kotler import config


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict = field(default_factory=dict)   # assistant message to append to the history as-is
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


class LLMError(Exception):
    """Raised when the model can't be reached. `user_message` is safe to show."""

    def __init__(self, message: str, user_message: str = "Sorry, I'm having trouble right now. Please try again."):
        super().__init__(message)
        self.user_message = user_message


class OpenAICompatLLM:
    """Any provider with an OpenAI-compatible /chat/completions endpoint (Gemini by default)."""

    def __init__(self, model: str | None = None, base_url: str | None = None,
                 api_key: str | None = None, timeout: float = 60, max_retries: int = 2):
        import openai  # imported lazily so tests without the package still run

        self._openai = openai
        self.model = model or config.LLM_MODEL
        self.client = openai.OpenAI(
            api_key=api_key or config.llm_api_key() or "missing",
            base_url=base_url or config.LLM_BASE_URL,
            timeout=timeout,
            max_retries=0,  # we retry ourselves, with backoff, so we can log it
        )
        self.max_retries = max_retries

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             temperature: float = 0.3) -> LLMResponse:
        oa = self._openai
        kwargs = dict(model=self.model, messages=messages, temperature=temperature)
        if tools:
            kwargs["tools"] = tools
        for attempt in range(self.max_retries + 1):
            start = time.perf_counter()
            try:
                resp = self.client.chat.completions.create(**kwargs)
                break
            except (oa.RateLimitError, oa.InternalServerError, oa.APIConnectionError, oa.APITimeoutError) as e:
                if attempt == self.max_retries:
                    busy = isinstance(e, oa.RateLimitError)
                    raise LLMError(str(e), "I'm getting a lot of questions right now. Please try again in a minute."
                                   if busy else "Sorry, I couldn't reach the AI service. Please try again.") from e
                time.sleep(2 * 2 ** attempt)  # 2s, 4s: exponential backoff
            except (oa.AuthenticationError, oa.PermissionDeniedError, oa.BadRequestError, oa.NotFoundError) as e:
                raise LLMError(str(e), "The AI service isn't configured correctly (check the API key and model).") from e
        latency = int((time.perf_counter() - start) * 1000)

        msg = resp.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_invalid_json": tc.function.arguments}
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args if isinstance(args, dict) else {}))
        # Keep the message exactly as returned (Gemini attaches hidden "thought signatures"
        # to tool calls that must be sent back unchanged in the same turn).
        raw = msg.model_dump(exclude_none=True)
        usage = resp.usage
        return LLMResponse(
            content=msg.content, tool_calls=calls, raw=raw, latency_ms=latency,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )


class FakeLLM:
    """Scripted LLM for tests. Give it a list of responses, or a function
    (messages, tools) -> LLMResponse for dynamic behaviour."""

    def __init__(self, script: list[LLMResponse] | Callable[[list[dict], list[dict] | None], LLMResponse]):
        self.script = script
        self.calls: list[list[dict]] = []
        self.model = "fake"

    def chat(self, messages, tools=None, temperature=0.3) -> LLMResponse:
        self.calls.append([dict(m) for m in messages])
        if callable(self.script):
            return self.script(messages, tools)
        if not self.script:
            raise LLMError("FakeLLM script exhausted")
        return self.script.pop(0)


def tool_call_response(name: str, arguments: dict, call_id: str = "call_1") -> LLMResponse:
    """Helper to build a response that asks for one tool call (used by tests)."""
    raw = {"role": "assistant", "content": None, "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}]}
    return LLMResponse(content=None, tool_calls=[ToolCall(call_id, name, arguments)], raw=raw)


def text_response(text: str) -> LLMResponse:
    return LLMResponse(content=text, raw={"role": "assistant", "content": text})


def get_llm() -> OpenAICompatLLM | None:
    """The configured LLM, or None if no API key is set (the UI then explains how to add one)."""
    return OpenAICompatLLM() if config.llm_api_key() else None
