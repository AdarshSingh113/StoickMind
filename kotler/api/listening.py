"""Social listening API (all need login):

  GET    /api/v1/listening                 overview: numbers, themes, ingredients, alerts, sources, last scan
  GET    /api/v1/listening/mentions        the feed, with filters
  POST   /api/v1/listening/scan            start a scan now (runs in the background)
  GET    /api/v1/listening/terms           watch terms        POST add · POST /{id} on/off · DELETE remove
  PUT    /api/v1/listening/settings        schedule (every N hours, 0 = off) and which sources to use
  GET    /api/v1/listening/brief           the latest brief   POST write a new one (needs the AI key)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from kotler.api.auth import require_user
from kotler.listening import insights, runner, sources, store

router = APIRouter(prefix="/api/v1/listening", dependencies=[Depends(require_user)])


@router.get("")
def overview(days: int = Query(30, ge=1, le=90)) -> dict:
    return {**insights.overview(days), "sources": sources.status(), "brief": insights.latest_brief(),
            "terms": store.terms()}


@router.get("/mentions")
def mentions(days: int = Query(30, ge=1, le=90), source: str | None = Query(None, pattern="^(youtube|bluesky|news)$"),
             sentiment: str | None = Query(None, pattern="^(positive|neutral|negative|mixed)$"),
             term: str | None = Query(None, max_length=60), aspect: str | None = Query(None, max_length=30),
             alerts: bool = False, q: str | None = Query(None, max_length=100), noise: bool = False,
             limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)) -> dict:
    return insights.feed(days, source, sentiment, term, aspect, alerts, q, limit, offset, include_noise=noise)


@router.post("/scan")
def scan() -> dict:
    try:
        runner.scan_in_background("manual")
    except runner.ScanBusy as e:
        raise HTTPException(409, str(e)) from e
    return {"started": True}


class TermIn(BaseModel):
    term: str = Field(..., min_length=2, max_length=60)
    kind: str = Field("category", pattern="^(brand|product|category|competitor)$")


@router.get("/terms")
def terms() -> dict:
    return {"terms": store.terms()}


@router.post("/terms")
def add_term(body: TermIn) -> dict:
    try:
        return {"term": store.add_term(body.term, body.kind)}
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class ActiveIn(BaseModel):
    active: bool


@router.post("/terms/{term_id}")
def toggle_term(term_id: int, body: ActiveIn) -> dict:
    store.set_term_active(term_id, body.active)
    return {"ok": True}


@router.delete("/terms/{term_id}")
def delete_term(term_id: int) -> dict:
    store.delete_term(term_id)
    return {"ok": True}


class SettingsIn(BaseModel):
    every_hours: int = Field(0, ge=0, le=168)
    sources: list[str] = Field(default_factory=lambda: ["youtube", "bluesky", "news"])


@router.put("/settings")
def settings(body: SettingsIn) -> dict:
    import json
    bad = [s for s in body.sources if s not in sources.SOURCES]
    if bad:
        raise HTTPException(422, f"Unknown sources: {', '.join(bad)}")
    if body.every_hours and body.every_hours < 2:
        raise HTTPException(422, "Scan at most every 2 hours: each scan uses API quota.")
    store.set_setting("every_hours", str(body.every_hours))
    store.set_setting("sources", json.dumps(list(dict.fromkeys(body.sources))))
    return {"every_hours": body.every_hours, "sources": store.enabled_sources()}


@router.get("/brief")
def brief() -> dict:
    return {"brief": insights.latest_brief()}


class BriefIn(BaseModel):
    days: int = Field(30, ge=1, le=90)
    method: str = Field("auto", pattern="^(auto|google_search|collected)$")


@router.post("/brief")
def write_brief(body: BriefIn) -> dict:
    from kotler.api.common import need_llm
    from kotler.llm import LLMError
    llm = need_llm()
    try:
        if body.method == "collected":
            return {"brief": insights.brief_from_mentions(llm, body.days)}
        return {"brief": insights.write_brief(llm, body.days, body.method)}
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except LLMError as e:
        raise HTTPException(502, e.user_message) from e
