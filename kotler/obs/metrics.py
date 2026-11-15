"""Turning traces into answers: Is the AI fast? Reliable? Good? What does it cost?

Metrics worth learning:
- p50 / p95 latency: the median customer's wait, and the wait of the unluckiest 1 in 20. Averages hide the slow
  tail, and the slow tail is what customers complain about.
- error rate, fallback rate: how often the model failed, or the backup model had to answer.
- guard rate: how often a safety check (claim check, price grounding, fail-safe) had to step in. A rising guard
  rate after a prompt change is an early warning, before customers notice anything.
- escalation rate: how much work still reaches humans.
- success rate: the LLM judge's verdict on whole conversations (quality, not just "no error").
- cost per conversation: tokens × price. Estimated from list prices: the free tier itself costs ₹0.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd

from kotler import config, db
from kotler.obs.trace import ensure_tables

EMPTY_TRACES = ["id", "parent_id", "kind", "name", "conversation_id", "channel", "started_at", "latency_ms", "status",
                "escalated", "input", "output", "error", "meta"]


def cost_inr(model: str | None, prompt_tokens: float, completion_tokens: float) -> float:
    pin, pout = config.LLM_PRICES_USD_PER_M.get(model or "", config.DEFAULT_PRICE_USD_PER_M)
    return (prompt_tokens * pin + completion_tokens * pout) / 1e6 * config.USD_INR


def _since(days: int | None) -> str:
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S") if days else "0000"


def _channel_filter(include_eval: bool) -> str:
    return "" if include_eval else " AND COALESCE(t.channel, '') != 'eval'"


def llm_calls(days: int | None = 30, include_eval: bool = False) -> pd.DataFrame:
    ensure_tables()
    df = db.query_df(f"""SELECT c.*, t.kind, t.name, t.channel FROM llm_calls c LEFT JOIN ai_traces t ON t.id = c.trace_id
                         WHERE c.created_at >= ?{_channel_filter(include_eval)}""", (_since(days),))
    df["cost_inr"] = [cost_inr(m, p, o) for m, p, o in zip(df.model, df.prompt_tokens, df.completion_tokens)]
    return df


def traces(days: int | None = 30, include_eval: bool = False, kind: str | None = None) -> pd.DataFrame:
    ensure_tables()
    q = f"SELECT t.* FROM ai_traces t WHERE t.started_at >= ?{_channel_filter(include_eval)}"
    params: list = [_since(days)]
    if kind:
        q += " AND t.kind = ?"
        params.append(kind)
    return db.query_df(q + " ORDER BY t.id DESC", tuple(params))


def _pct(s: pd.Series, q: float) -> float | None:
    s = s.dropna()
    return float(s.quantile(q)) if len(s) else None


def summary(days: int | None = 30, include_eval: bool = False) -> dict:
    calls, tr = llm_calls(days, include_eval), traces(days, include_eval)
    turns = tr[tr.kind == "agent_turn"]
    n_turns = len(turns)
    return {
        "llm_calls": len(calls),
        "tokens": int(calls.prompt_tokens.sum() + calls.completion_tokens.sum()),
        "cost_inr": float(calls.cost_inr.sum()),
        "llm_error_rate": float((calls.status == "error").mean()) if len(calls) else 0.0,
        "fallback_rate": float((calls.status == "fallback").mean()) if len(calls) else 0.0,
        "agent_turns": n_turns,
        "conversations": int(turns.conversation_id.nunique()),
        "p50_s": (_pct(turns.latency_ms, .5) or 0) / 1000, "p95_s": (_pct(turns.latency_ms, .95) or 0) / 1000,
        "guard_rate": float(turns.status.isin(["corrected", "fail_safe"]).mean()) if n_turns else 0.0,
        "error_rate": float((turns.status == "error").mean()) if n_turns else 0.0,
        "escalation_rate": float(turns.escalated.mean()) if n_turns else 0.0,
        "cost_per_conversation_inr": float(calls[calls.kind == "agent_turn"].cost_inr.sum()
                                           / max(turns.conversation_id.nunique(), 1)),
    }


def per_agent(days: int | None = 30, include_eval: bool = False) -> pd.DataFrame:
    tr = traces(days, include_eval, kind="agent_turn")
    if tr.empty:
        return pd.DataFrame()
    calls = llm_calls(days, include_eval)
    cost = calls.groupby("trace_id").agg(cost_inr=("cost_inr", "sum"),
                                         tokens=("prompt_tokens", "sum"), out=("completion_tokens", "sum"))
    tr = tr.join(cost, on="id")
    scores = db.query_df("SELECT agent_slug AS name, COUNT(*) AS judged, AVG(achieved) AS success, AVG(score) AS score "
                         "FROM conversation_scores GROUP BY agent_slug").set_index("name")
    rows = []
    for name, g in tr.groupby("name"):
        rows.append({
            "agent": name, "turns": len(g), "conversations": g.conversation_id.nunique(),
            "p50_s": (_pct(g.latency_ms, .5) or 0) / 1000, "p95_s": (_pct(g.latency_ms, .95) or 0) / 1000,
            "error_pct": 100 * (g.status == "error").mean(),
            "guard_pct": 100 * g.status.isin(["corrected", "fail_safe"]).mean(),
            "fail_safe_pct": 100 * (g.status == "fail_safe").mean(),
            "escalation_pct": 100 * g.escalated.mean(),
            "tokens_per_turn": (g.tokens.fillna(0) + g.out.fillna(0)).mean(),
            "cost_per_conv_inr": g.cost_inr.fillna(0).sum() / max(g.conversation_id.nunique(), 1),
            "judged": int(scores.judged.get(name, 0)),
            "success_pct": 100 * scores.success[name] if name in scores.index else None,
            "avg_score": scores.score[name] if name in scores.index else None,
        })
    return pd.DataFrame(rows).sort_values("turns", ascending=False)


def cost_by_feature(days: int | None = 30, include_eval: bool = False) -> pd.DataFrame:
    calls = llm_calls(days, include_eval)
    if calls.empty:
        return pd.DataFrame(columns=["feature", "calls", "tokens", "cost_inr"])
    calls["feature"] = calls.kind.fillna("untraced")
    calls["tokens"] = calls.prompt_tokens + calls.completion_tokens
    return (calls.groupby("feature").agg(calls=("id", "count"), tokens=("tokens", "sum"), cost_inr=("cost_inr", "sum"))
            .reset_index().sort_values("cost_inr", ascending=False))


def daily(days: int = 30, include_eval: bool = False) -> pd.DataFrame:
    calls = llm_calls(days, include_eval)
    tr = traces(days, include_eval, kind="agent_turn")
    if calls.empty and tr.empty:
        return pd.DataFrame(columns=["day", "llm_calls", "cost_inr", "errors", "turns", "p95_s"])
    calls["day"] = calls.created_at.str[:10]
    tr["day"] = tr.started_at.str[:10]
    a = calls.groupby("day").agg(llm_calls=("id", "count"), cost_inr=("cost_inr", "sum"),
                                 errors=("status", lambda s: int((s == "error").sum())))
    b = tr.groupby("day").agg(turns=("id", "count"), p95_s=("latency_ms", lambda s: s.quantile(.95) / 1000))
    return a.join(b, how="outer").fillna(0).reset_index()


def tool_stats(days: int | None = 30) -> pd.DataFrame:
    ensure_tables()
    return db.query_df("""SELECT name AS tool, COUNT(*) AS calls, ROUND(100.0 * AVG(1 - ok), 1) AS error_pct,
                                 ROUND(AVG(latency_ms), 0) AS avg_ms
                          FROM trace_spans WHERE type = 'tool' AND created_at >= ? GROUP BY name ORDER BY calls DESC""",
                       (_since(days),))


def guard_stats(days: int | None = 30) -> pd.DataFrame:
    ensure_tables()
    return db.query_df("""SELECT name AS guard, COUNT(*) AS fired, MAX(created_at) AS last_fired
                          FROM trace_spans WHERE type = 'guard' AND created_at >= ? GROUP BY name ORDER BY fired DESC""",
                       (_since(days),))


def trace_detail(trace_id: int) -> dict:
    ensure_tables()
    t = db.query_one("SELECT * FROM ai_traces WHERE id = ?", (trace_id,))
    if not t:
        return {}
    calls = db.query_df("SELECT * FROM llm_calls WHERE trace_id = ? ORDER BY id", (trace_id,))
    calls["cost_inr"] = [cost_inr(m, p, o) for m, p, o in zip(calls.model, calls.prompt_tokens, calls.completion_tokens)]
    return {
        "trace": dict(t), "meta": json.loads(t["meta"] or "{}"), "llm_calls": calls,
        "spans": db.query_df("SELECT type, name, latency_ms, ok, detail, created_at FROM trace_spans WHERE trace_id = ? "
                             "ORDER BY id", (trace_id,)),
        "children": db.query_df("SELECT id, kind, name, status, latency_ms FROM ai_traces WHERE parent_id = ?", (trace_id,)),
    }
