"""Small helpers shared by the dashboard API modules."""

from __future__ import annotations

import math
import threading

from fastapi import HTTPException

from kotler import db

_ml_lock = threading.Lock()


def records(df, limit: int | None = None) -> list[dict]:
    """DataFrame -> JSON-safe rows (NaN -> null, numpy -> Python)."""
    if limit is not None:
        df = df.head(limit)
    out = df.astype(object).where(df.notna(), None).to_dict("records")
    for r in out:
        for k, v in r.items():
            if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
                r[k] = None
            elif hasattr(v, "item"):
                r[k] = v.item()
    return out


def need_llm():
    """The LLM, or a clear 503 the UI can show ("add a key") instead of a crash."""
    from kotler.llm import get_llm
    llm = get_llm()
    if llm is None:
        raise HTTPException(503, "AI isn't configured on the server: set GEMINI_API_KEY (see README).")
    return llm


def table_exists(name: str) -> bool:
    return db.query_one("SELECT COUNT(*) AS n FROM sqlite_master WHERE type = 'table' AND name = ?", (name,))["n"] > 0


def ensure_ml() -> None:
    """Churn / value / RTO models and customer_scores. Trained once (a few seconds), then reused."""
    with _ml_lock:
        from kotler.ml import pipeline
        pipeline.ensure_trained()
