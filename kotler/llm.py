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


class GeminiLLM:
    """Google's native Gemini API (generateContent).

    Why a second backend? Google's newer "auth keys" (they start with "AQ.") only work on the
    native API, not on the OpenAI-compatible endpoint. So we translate our OpenAI-style
    messages into Gemini's format and back. The agent never knows the difference:
    that's the payoff of putting providers behind one interface.

    OpenAI style                          Gemini native
    ------------------------------------  ----------------------------------------------
    {"role": "system", content}           systemInstruction: {parts: [{text}]}
    {"role": "user", content}             {role: "user",  parts: [{text}]}
    {"role": "assistant", content}        {role: "model", parts: [{text}]}
    assistant tool_calls                  {role: "model", parts: [{functionCall: {name, args}}]}
    {"role": "tool", tool_call_id, ...}   {role: "user",  parts: [{functionResponse: {name, response}}]}
    """

    BASE = "https://generativelanguage.googleapis.com/v1beta"

    def __init__(self, model: str | None = None, api_key: str | None = None, timeout: float = 60,
                 max_retries: int = 2):
        import requests

        self._requests = requests
        self.model = model or config.LLM_MODEL
        self.fallbacks = [m for m in config.LLM_FALLBACK_MODELS if m != self.model]
        self.api_key = api_key or config.llm_api_key() or ""
        self.timeout = timeout
        self.max_retries = max_retries
        self.last_model: str | None = None  # which model actually answered (for logging)

    # --------------------------------------------------------- translation
    @staticmethod
    def _schema(tool: dict) -> dict:
        fn = tool["function"]
        decl = {"name": fn["name"], "description": fn.get("description", "")}
        params = fn.get("parameters") or {}
        if params.get("properties"):  # Gemini rejects an object schema with no properties
            decl["parameters"] = params
        return decl

    @staticmethod
    def to_gemini(messages: list[dict]) -> tuple[dict | None, list[dict]]:
        system, contents, names = None, [], {}
        for m in messages:
            role = m["role"]
            if role == "system":
                system = {"parts": [{"text": m["content"]}]}
            elif role == "user":
                part = {"text": m["content"] or ""}
                if contents and contents[-1]["role"] == "user":
                    contents[-1]["parts"].append(part)  # e.g. a note right after tool results: same user turn
                else:
                    contents.append({"role": "user", "parts": [part]})
            elif role == "assistant":
                if m.get("_gemini_parts"):  # replay exactly what Gemini sent (keeps thought signatures)
                    parts = m["_gemini_parts"]
                else:
                    parts = [{"text": m["content"]}] if m.get("content") else []
                    for tc in m.get("tool_calls") or []:
                        parts.append({"functionCall": {"name": tc["function"]["name"],
                                                       "args": json.loads(tc["function"]["arguments"] or "{}")}})
                for tc in m.get("tool_calls") or []:
                    names[tc["id"]] = tc["function"]["name"]
                contents.append({"role": "model", "parts": parts or [{"text": ""}]})
            elif role == "tool":
                try:
                    response = json.loads(m["content"])
                except (json.JSONDecodeError, TypeError):
                    response = {"result": m["content"]}
                if not isinstance(response, dict):
                    response = {"result": response}
                part = {"functionResponse": {"name": names.get(m["tool_call_id"], "tool"), "response": response}}
                # All results for one model turn go in ONE user message, in the same order as the calls.
                if contents and contents[-1]["role"] == "user" and "functionResponse" in contents[-1]["parts"][0]:
                    contents[-1]["parts"].append(part)
                else:
                    contents.append({"role": "user", "parts": [part]})
        return system, contents

    # ---------------------------------------------------------------- call
    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             temperature: float = 0.3) -> LLMResponse:
        system, contents = self.to_gemini(messages)
        body: dict = {"contents": contents, "generationConfig": {"temperature": temperature}}
        if system:
            body["systemInstruction"] = system
        if tools:
            body["tools"] = [{"functionDeclarations": [self._schema(t) for t in tools]}]
        # Main model first; if it's overloaded even after retries, fall back to the next one.
        last_error: LLMError | None = None
        for model in [self.model, *self.fallbacks]:
            try:
                return self._call(model, body)
            except LLMError as e:
                last_error = e
                if not getattr(e, "retryable", False):
                    raise
        raise last_error  # every model was overloaded

    def _call(self, model: str, body: dict) -> LLMResponse:
        url = f"{self.BASE}/models/{model}:generateContent"
        for attempt in range(self.max_retries + 1):
            start = time.perf_counter()
            try:
                r = self._requests.post(url, json=body, timeout=self.timeout,
                                        headers={"x-goog-api-key": self.api_key})
            except self._requests.RequestException as e:
                if attempt == self.max_retries:
                    raise LLMError(str(e), "Sorry, I couldn't reach the AI service. Please try again.") from e
                time.sleep(2 * 2 ** attempt)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                if attempt == self.max_retries:
                    err = LLMError(f"{model} {r.status_code}: {r.text[:300]}",
                                   "I'm getting a lot of questions right now. Please try again in a minute."
                                   if r.status_code == 429 else "Sorry, the AI service is busy. Please try again.")
                    err.retryable = True
                    raise err
                time.sleep(1.5 * 2 ** attempt)
                continue
            if r.status_code != 200:
                raise LLMError(f"{r.status_code}: {r.text[:300]}",
                               "The AI service isn't configured correctly (check the API key and model).")
            break
        latency = int((time.perf_counter() - start) * 1000)
        self.last_model = model

        data = r.json()
        candidates = data.get("candidates") or []
        if not candidates:  # e.g. blocked by safety filters
            reason = (data.get("promptFeedback") or {}).get("blockReason", "no answer")
            return LLMResponse(content=f"Sorry, I can't help with that ({reason}).", latency_ms=latency,
                               raw={"role": "assistant", "content": "Sorry, I can't help with that."})
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        calls, tool_calls = [], []
        for i, p in enumerate(parts):
            if "functionCall" in p:
                fc = p["functionCall"]
                call_id = fc.get("id") or f"call_{i}"
                args = fc.get("args") or {}
                calls.append(ToolCall(call_id, fc["name"], args))
                tool_calls.append({"id": call_id, "type": "function",
                                   "function": {"name": fc["name"], "arguments": json.dumps(args)}})
        raw = {"role": "assistant", "content": text or None, "_gemini_parts": parts}
        if tool_calls:
            raw["tool_calls"] = tool_calls
        usage = data.get("usageMetadata") or {}
        return LLMResponse(content=text or None, tool_calls=calls, raw=raw, latency_ms=latency,
                           prompt_tokens=usage.get("promptTokenCount", 0),
                           completion_tokens=usage.get("candidatesTokenCount", 0)
                           + usage.get("thoughtsTokenCount", 0))


def get_llm() -> GeminiLLM | OpenAICompatLLM | None:
    """The configured LLM, or None if no API key is set (the UI then explains how to add one).
    KOTLER_LLM_PROVIDER: "gemini" (native Gemini API, default) or "openai" (any OpenAI-compatible API)."""
    if not config.llm_api_key():
        return None
    return OpenAICompatLLM() if config.LLM_PROVIDER == "openai" else GeminiLLM()
