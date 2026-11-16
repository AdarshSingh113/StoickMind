"""Tracing: a record of everything the AI did, so we can measure it, debug it and pay for it.

Vocabulary (the same as in production tools like Langfuse, LangSmith or OpenTelemetry):

  trace  = one unit of work the user cares about, e.g. "Kavya answered one message",
           "the judge scored a conversation", "Ask-your-data answered a question".
  span   = a step inside a trace: one LLM call, one tool call, one safety check that fired.

Two design choices worth learning:

1. INSTRUMENT AT THE CHOKE POINT. Every LLM call in Kotler goes through a provider's `chat()` method.
   `kotler.llm` wraps that ONE method, so every call is logged automatically, including calls from code
   written later. Nobody has to remember to add logging, so nothing is missed.

2. CONTEXT, NOT PARAMETERS. The currently open trace lives in a `ContextVar`. An LLM call deep inside the
   judge doesn't need a `trace_id` argument: it looks up "which trace am I in?". ContextVars are per thread
   and per async task, so two customers chatting at the same time never mix their traces.

Observability must never break the product: every write here swallows its own errors.
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime

from kotler import config, db

SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_traces (
    id              INTEGER PRIMARY KEY,
    parent_id       INTEGER,                 -- a trace started inside another (copilot -> agent turn)
    kind            TEXT NOT NULL,           -- agent_turn, judge, campaign_templates, segment_builder, ask_data, eval
    name            TEXT,                    -- agent slug or feature name
    conversation_id INTEGER,
    channel         TEXT,
    started_at      TEXT NOT NULL,
    latency_ms      INTEGER,
    status          TEXT NOT NULL DEFAULT 'running',  -- ok, corrected, fail_safe, error
    escalated       INTEGER NOT NULL DEFAULT 0,
    input           TEXT,                    -- what was asked (truncated)
    output          TEXT,                    -- what was answered (truncated)
    error           TEXT,
    meta            TEXT                     -- JSON: guards fired, tools used, SQL...
);
CREATE INDEX IF NOT EXISTS idx_traces_started ON ai_traces(started_at);
CREATE INDEX IF NOT EXISTS idx_traces_name    ON ai_traces(name);

CREATE TABLE IF NOT EXISTS llm_calls (
    id                INTEGER PRIMARY KEY,
    trace_id          INTEGER,               -- NULL = a call outside any trace (still counted)
    created_at        TEXT NOT NULL,
    provider          TEXT NOT NULL,
    model             TEXT,
    requested_model   TEXT,                  -- differs from model when a fallback answered
    latency_ms        INTEGER,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    tool_calls        INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL,         -- ok, fallback, error
    error             TEXT
);
CREATE INDEX IF NOT EXISTS idx_llm_calls_trace ON llm_calls(trace_id);
CREATE INDEX IF NOT EXISTS idx_llm_calls_time  ON llm_calls(created_at);

CREATE TABLE IF NOT EXISTS trace_spans (
    id          INTEGER PRIMARY KEY,
    trace_id    INTEGER NOT NULL,
    type        TEXT NOT NULL,               -- tool, guard
    name        TEXT NOT NULL,
    latency_ms  INTEGER,
    ok          INTEGER NOT NULL DEFAULT 1,
    detail      TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spans_trace ON trace_spans(trace_id);
"""

_current: ContextVar[int | None] = ContextVar("kotler_trace", default=None)
_ready: set[str] = set()


def _now() -> str:
    # Milliseconds, so steps inside one second (LLM call -> tool -> LLM call) keep their real order.
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def ensure_tables() -> None:
    key = str(config.DB_PATH)
    if key in _ready and config.DB_PATH.exists():
        return
    with db.get_conn() as conn:
        conn.executescript(SCHEMA)
    _ready.add(key)


def current_trace_id() -> int | None:
    return _current.get()


def _safe(fn):
    """Logging is a side job: if it fails, the customer still gets their answer."""
    def wrapper(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception:
            return None
    return wrapper


class Trace:
    def __init__(self, trace_id: int | None):
        self.id = trace_id
        self.status = "ok"
        self.escalated = False
        self.output: str | None = None
        self.error: str | None = None
        self.meta: dict = {}

    @_safe
    def span(self, type_: str, name: str, latency_ms: int | None = None, ok: bool = True, detail: str = "") -> None:
        if self.id is None:
            return
        with db.get_conn() as conn:
            conn.execute("INSERT INTO trace_spans (trace_id, type, name, latency_ms, ok, detail, created_at) "
                         "VALUES (?,?,?,?,?,?,?)", (self.id, type_, name, latency_ms, int(ok), detail[:1000], _now()))


@contextmanager
def trace(kind: str, name: str | None = None, conversation_id: int | None = None, channel: str | None = None,
          input: str | None = None):
    """Open a trace for the duration of the `with` block. Nested traces record their parent."""
    trace_id = _start(kind, name, conversation_id, channel, input)
    t = Trace(trace_id)
    token = _current.set(trace_id)
    started = time.perf_counter()
    try:
        yield t
    except Exception as e:
        t.status, t.error = "error", f"{type(e).__name__}: {e}"
        raise
    finally:
        _current.reset(token)
        _finish(t, int((time.perf_counter() - started) * 1000))


@_safe
def _start(kind, name, conversation_id, channel, input) -> int:
    ensure_tables()
    with db.get_conn() as conn:
        return conn.execute(
            "INSERT INTO ai_traces (parent_id, kind, name, conversation_id, channel, started_at, input) "
            "VALUES (?,?,?,?,?,?,?)",
            (_current.get(), kind, name, conversation_id, channel, _now(), (input or "")[:2000])).lastrowid


@_safe
def _finish(t: Trace, latency_ms: int) -> None:
    if t.id is None:
        return
    with db.get_conn() as conn:
        conn.execute("UPDATE ai_traces SET latency_ms = ?, status = ?, escalated = ?, output = ?, error = ?, meta = ? "
                     "WHERE id = ?", (latency_ms, t.status, int(t.escalated), (t.output or "")[:2000],
                                      (t.error or None) and t.error[:1000], json.dumps(t.meta, default=str), t.id))


@_safe
def log_llm_call(provider: str, model: str | None, requested_model: str | None, latency_ms: int,
                 prompt_tokens: int = 0, completion_tokens: int = 0, tool_calls: int = 0,
                 error: str | None = None) -> None:
    ensure_tables()
    status = "error" if error else ("fallback" if requested_model and model and model != requested_model else "ok")
    with db.get_conn() as conn:
        conn.execute("INSERT INTO llm_calls (trace_id, created_at, provider, model, requested_model, latency_ms, "
                     "prompt_tokens, completion_tokens, tool_calls, status, error) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (_current.get(), _now(), provider, model, requested_model, latency_ms, prompt_tokens,
                      completion_tokens, tool_calls, status, (error or None) and error[:500]))
