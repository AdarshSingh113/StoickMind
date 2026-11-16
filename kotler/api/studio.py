"""Agent Studio API (R6): agents as configuration, versions, rollback, a playground and the LLM judge."""

from __future__ import annotations

from dataclasses import asdict, replace

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from kotler import db
from kotler.agent import studio as S
from kotler.api.auth import require_user
from kotler.api.common import need_llm, records

router = APIRouter(prefix="/api/v1/agents", dependencies=[Depends(require_user)])


def _get(slug: str) -> S.AgentConfig:
    S.ensure_builtin_agents()
    cfg = S.get_agent(slug)
    if not cfg:
        raise HTTPException(404, "Agent not found.")
    return cfg


def _scores() -> dict:
    df = db.query_df("SELECT agent_slug, COUNT(*) AS judged, AVG(achieved) AS success, AVG(score) AS score "
                     "FROM conversation_scores GROUP BY agent_slug")
    return {r["agent_slug"]: r for r in records(df)}


def _conversations() -> dict:
    df = db.query_df("SELECT agent, COUNT(*) AS n FROM conversations GROUP BY agent")
    return dict(zip(df.agent, df.n))


@router.get("")
def list_agents() -> dict:
    S.ensure_builtin_agents()
    sc, conv = _scores(), _conversations()
    return {"agents": [{**asdict(a), "score": sc.get(a.slug), "conversations": int(conv.get(a.slug, 0))}
                       for a in S.list_agents()]}


@router.get("/meta")
def meta() -> dict:
    from kotler.agent.tools import TOOLS, WRITE_TOOLS
    import kotler.agent.support_tools  # noqa: F401  (registers the helpdesk tools)
    return {"tools": [{"name": n, "description": spec["function"]["description"], "writes": n in WRITE_TOOLS}
                      for n, (_, spec) in TOOLS.items()],
            "templates": {k: asdict(v) for k, v in S.TEMPLATES.items()}}


@router.get("/{slug}")
def agent(slug: str) -> dict:
    cfg = _get(slug)
    vs = S.versions(slug)
    from kotler.agent.judge import agent_scorecard
    return {"agent": asdict(cfg), "versions": [{**v, "changes": S.diff(vs[i + 1]["snapshot"], v["snapshot"])
                                                if i + 1 < len(vs) else []} for i, v in enumerate(vs)],
            "scorecard": records(agent_scorecard(slug)["by_version"])}


class AgentIn(BaseModel):
    name: str
    role: str
    description: str = ""
    instructions: str
    goal: str
    success_criteria: str
    tools: list[str] = Field(default_factory=list)
    temperature: float = 0.3
    max_steps: int = 5
    note: str = Field("", max_length=200)


@router.put("/{slug}")
def update(slug: str, body: AgentIn) -> dict:
    cfg = _get(slug)
    data = body.model_dump()
    note = data.pop("note")
    try:
        saved = S.save_agent(replace(cfg, **data), note=note or "Edited in Agent Studio")
    except S.AgentValidationError as e:
        raise HTTPException(422, str(e)) from e
    return {"agent": asdict(saved)}


class CreateIn(BaseModel):
    slug: str
    name: str
    template: str = "Blank agent"


@router.post("")
def create(body: CreateIn) -> dict:
    S.ensure_builtin_agents()
    if body.template not in S.TEMPLATES:
        raise HTTPException(422, "Unknown template.")
    if S.get_agent(body.slug):
        raise HTTPException(409, f"An agent with ID '{body.slug}' already exists.")
    try:
        saved = S.save_agent(replace(S.TEMPLATES[body.template], slug=body.slug, name=body.name, status="draft",
                                     is_builtin=False), note=f"Created from template: {body.template}")
    except S.AgentValidationError as e:
        raise HTTPException(422, str(e)) from e
    return {"agent": asdict(saved)}


class StatusIn(BaseModel):
    status: str = Field(..., pattern="^(draft|live)$")


@router.post("/{slug}/status")
def status(slug: str, body: StatusIn) -> dict:
    _get(slug)
    return {"agent": asdict(S.set_status(slug, body.status))}


class RestoreIn(BaseModel):
    version: int


@router.post("/{slug}/restore")
def restore(slug: str, body: RestoreIn) -> dict:
    _get(slug)
    try:
        return {"agent": asdict(S.restore(slug, body.version))}
    except S.AgentValidationError as e:
        raise HTTPException(404, str(e)) from e


@router.delete("/{slug}")
def delete(slug: str) -> dict:
    _get(slug)
    try:
        S.delete_agent(slug)
    except S.AgentValidationError as e:
        raise HTTPException(409, str(e)) from e
    return {"deleted": slug}


class ChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    conversation_id: int | None = None
    customer_id: int | None = None


@router.post("/{slug}/chat")
def chat(slug: str, body: ChatIn) -> dict:
    """Playground: talk to the CURRENT configuration (drafts too) before customers do."""
    from kotler.agent.runtime import Agent
    cfg = _get(slug)
    llm = need_llm()
    if body.conversation_id:
        conv = db.query_one("SELECT agent FROM conversations WHERE id = ?", (body.conversation_id,))
        if not conv or conv["agent"] != slug:
            raise HTTPException(404, "Conversation not found for this agent.")
    agent = Agent(cfg, llm, customer_id=body.customer_id, conversation_id=body.conversation_id, channel="playground")
    turn = agent.reply(body.message)
    return {"conversation_id": agent.conversation_id, "reply": turn.reply, "error": turn.error, "guard": turn.guard,
            "tools": [{"name": t.name, "arguments": t.arguments, "result": t.result} for t in turn.tools],
            "latency_ms": turn.latency_ms, "tokens": turn.prompt_tokens + turn.completion_tokens}


class JudgeIn(BaseModel):
    conversation_id: int


@router.post("/{slug}/judge")
def judge(slug: str, body: JudgeIn) -> dict:
    from kotler.agent.judge import judge_conversation
    cfg = _get(slug)
    return judge_conversation(need_llm(), cfg, body.conversation_id)
