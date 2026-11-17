"""Ask your data + AI performance API (R4). Thin wrappers: the logic lives in kotler.analytics and kotler.obs."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from kotler.api.auth import require_user
from kotler.api.common import need_llm, records

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_user)])


class AskIn(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)
    history: list[dict] = Field(default_factory=list, max_length=6)


@router.post("/ask")
def ask(body: AskIn) -> dict:
    from kotler.analytics import ask as A
    llm = need_llm()
    hist = [{"question": str(h.get("question", ""))[:500], "sql": str(h.get("sql", ""))[:3000]} for h in body.history]
    res = A.ask(llm, body.question.strip(), hist)
    return {"question": res.question, "sql": res.sql, "title": res.title, "explanation": res.explanation,
            "chart": res.chart, "columns": list(res.rows.columns), "rows": records(res.rows, 500),
            "row_count": len(res.rows), "answer": res.answer, "answer_status": res.answer_status,
            "ungrounded": res.ungrounded, "attempts": res.attempts, "error": res.error, "data_end": A.data_end()}


@router.get("/performance")
def performance(days: int = Query(30, ge=0, le=365), include_eval: bool = False) -> dict:
    from kotler.obs import metrics
    d = days or None
    agents = metrics.per_agent(d, include_eval)
    return {"summary": metrics.summary(d, include_eval), "agents": records(agents),
            "daily": records(metrics.daily(d or 90, include_eval)),
            "cost_by_feature": records(metrics.cost_by_feature(d, include_eval)),
            "tools": records(metrics.tool_stats(d)), "guards": records(metrics.guard_stats(d))}


@router.get("/performance/conversations")
def conversations(days: int = Query(30, ge=0, le=365)) -> dict:
    from kotler import store
    from kotler.obs.conversations import conversation_stats
    return {**conversation_stats(days or None), "ai_sales": store.ai_sales(days or None)}


@router.get("/performance/traces")
def traces(days: int = Query(30, ge=0, le=365), include_eval: bool = False, kind: str | None = None,
           status: str | None = None, q: str | None = Query(None, max_length=100), limit: int = Query(100, le=500)) -> dict:
    from kotler.obs import metrics
    tr = metrics.traces(days or None, include_eval, kind=kind)
    kinds = sorted(tr.kind.dropna().unique().tolist())
    if status:
        tr = tr[tr.status == status]
    if q:
        tr = tr[tr.input.fillna("").str.contains(q, case=False, regex=False)]
    cols = ["id", "kind", "name", "channel", "conversation_id", "started_at", "latency_ms", "status", "escalated", "input"]
    return {"traces": records(tr[cols], limit), "total": len(tr), "kinds": kinds}


@router.get("/performance/traces/{trace_id}")
def trace(trace_id: int) -> dict:
    from kotler.obs import metrics
    d = metrics.trace_detail(trace_id)
    if not d:
        raise HTTPException(404, "Trace not found.")
    return {"trace": d["trace"], "meta": d["meta"], "llm_calls": records(d["llm_calls"]), "spans": records(d["spans"]),
            "children": records(d["children"])}


@router.get("/performance/evals")
def eval_runs() -> dict:
    from kotler.obs import evals
    evals.import_result_files()
    runs = evals.runs()
    suites = sorted(runs.suite.unique().tolist()) if len(runs) else []
    return {"runs": records(runs), "compare": {s: evals.compare(s) for s in suites}}


@router.get("/performance/evals/{run_id}")
def eval_results(run_id: int) -> dict:
    from kotler.obs import evals
    return {"results": records(evals.results(run_id))}


@router.get("/performance/impact")
def impact(days: int = Query(30, ge=1, le=365)) -> dict:
    from kotler.obs import impact as I
    df = I.impact(days)
    return {"levers": records(df), "measured_total": float(df[df.evidence == "measured"].inr.sum()) if len(df) else 0.0,
            "assumptions": {"human_cost_per_conversation": I.HUMAN_COST_PER_CONVERSATION}}
