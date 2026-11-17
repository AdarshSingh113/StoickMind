"""Campaigns + Helpdesk API (R5). Every guardrail stays in the Python modules (discount cap, holdout, template
validation, refund limits, approvals): the API only exposes them, so the React app can't bypass any of them."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from kotler import crm, db
from kotler.api.auth import require_user
from kotler.api.common import ensure_ml, need_llm, records

router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_user)])


# ------------------------------------------------------------------ campaigns
@router.get("/journeys")
def journeys() -> dict:
    from kotler.marketing import journeys as J
    ensure_ml()
    return {"journeys": records(J.journey_overview())}


@router.get("/journeys/{journey}/audience")
def journey_audience(journey: str, limit: int = Query(12, le=100)) -> dict:
    from kotler.marketing import journeys as J
    if journey not in J.JOURNEYS:
        raise HTTPException(404, "Unknown journey.")
    ensure_ml()
    a = J.audience(journey)
    cols = [c for c in ("customer_id", "first_name", "segment", "churn_risk", "product_id", "product_name", "price",
                        "reason", "language") if c in a.columns]
    images = dict(db.query_df("SELECT id, image_url FROM products").itertuples(index=False))
    rows = records(a[cols], limit)
    for r in rows:
        r["image_url"] = images.get(r.get("product_id"))
    return {"total": len(a), "sample": rows}


class TemplatesIn(BaseModel):
    journey: str
    offer_pct: int = Field(0, ge=0, le=15)


@router.post("/campaigns/templates")
def templates(body: TemplatesIn) -> dict:
    from kotler.llm import get_llm
    from kotler.marketing import campaigns as C, journeys as J
    if body.journey not in J.JOURNEYS:
        raise HTTPException(404, "Unknown journey.")
    t, source = C.generate_templates(get_llm(), body.journey, body.offer_pct)
    return {"templates": t, "source": source, "placeholders": sorted(C.PLACEHOLDERS)}


class CampaignIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=80)
    journey: str
    templates: dict
    template_source: str = "manual"
    offer_pct: int = Field(0, ge=0, le=50)        # the 15% cap is enforced (and explained) by create_campaign
    holdout_pct: float = 0.2
    channel: str = "whatsapp"


@router.post("/campaigns")
def create(body: CampaignIn) -> dict:
    from kotler.marketing import campaigns as C, journeys as J
    if body.journey not in J.JOURNEYS:
        raise HTTPException(404, "Unknown journey.")
    ensure_ml()
    try:
        cid = C.create_campaign(body.name, body.journey, body.templates, body.template_source, body.offer_pct,
                                body.holdout_pct, body.channel)
    except (ValueError, KeyError) as e:          # InvalidTemplate is a ValueError
        raise HTTPException(422, str(e)) from e
    return {"id": cid}


@router.get("/campaigns")
def list_campaigns() -> dict:
    from kotler.marketing import campaigns as C
    df = C.list_campaigns()
    return {"campaigns": records(df.drop(columns=["templates"], errors="ignore"))}


@router.get("/campaigns/{cid}")
def campaign(cid: int) -> dict:
    from kotler.marketing import campaigns as C, stats
    C.ensure_tables()
    camp = db.query_one("SELECT * FROM campaigns WHERE id = ?", (cid,))
    if not camp:
        raise HTTPException(404, "Campaign not found.")
    camp["templates"] = json.loads(camp["templates"])
    groups = db.query_df("SELECT grp, COUNT(*) AS customers FROM campaign_members WHERE campaign_id = ? GROUP BY grp",
                         (cid,))
    reasons = db.query_df("SELECT exclusion_reason AS reason, COUNT(*) AS customers FROM campaign_members "
                          "WHERE campaign_id = ? AND grp = 'excluded' GROUP BY 1 ORDER BY 2 DESC", (cid,))
    examples = db.query_df("""SELECT m.grp, m.language, m.message, cu.name FROM campaign_members m
                              JOIN customers cu ON cu.id = m.customer_id WHERE m.campaign_id = ? AND m.grp IN ('A','B')
                              ORDER BY m.grp, m.customer_id LIMIT 6""", (cid,))
    results = None
    if camp["status"] == "measured" and db.query_one(
            "SELECT COUNT(*) AS n FROM campaign_members WHERE campaign_id = ? AND converted IS NOT NULL", (cid,))["n"]:
        r = stats.analyze(cid)
        results = {**{k: v for k, v in r.items() if k not in ("groups", "ab")}, "groups": records(r["groups"]),
                   "ab": r["ab"], "verdict": stats.verdict(r)}
    return {"campaign": camp, "groups": records(groups), "exclusions": records(reasons),
            "examples": records(examples), "results": results}


@router.post("/campaigns/{cid}/send")
def send(cid: int) -> dict:
    from kotler.marketing import campaigns as C
    camp = db.query_one("SELECT status FROM campaigns WHERE id = ?", (cid,))
    if not camp:
        raise HTTPException(404, "Campaign not found.")
    if camp["status"] != "draft":
        raise HTTPException(409, "Already sent.")
    if not db.query_one("SELECT COUNT(*) AS n FROM campaign_members WHERE campaign_id = ? AND grp IN ('A', 'B')",
                        (cid,))["n"]:
        raise HTTPException(409, "Nobody to send to: every customer in this audience was excluded (see the reasons "
                                 "below, e.g. the 7-day frequency cap).")
    return {"sent": C.send_campaign(cid)}


@router.post("/campaigns/{cid}/simulate")
def simulate(cid: int) -> dict:
    from kotler.marketing import simulator
    try:
        return {"ok": True, **{k: v for k, v in simulator.simulate(cid).items() if isinstance(v, (int, float, str))}}
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


# ------------------------------------------------------------------ helpdesk
@router.get("/helpdesk")
def helpdesk(status: str | None = Query(None, pattern="^(open|resolved|escalated)$"),
             q: str | None = Query(None, max_length=80)) -> dict:
    from kotler.agent.copilot import ai_stats
    t = crm.tickets(status)
    if q:
        t = t[t.message.str.contains(q, case=False, regex=False) | t.customer.str.contains(q, case=False, regex=False)]
    counts = db.query_one("""SELECT COUNT(*) AS all_, COUNT(*) FILTER (WHERE status = 'open') AS open,
                                    COUNT(*) FILTER (WHERE status = 'escalated') AS escalated,
                                    COUNT(*) FILTER (WHERE status = 'resolved') AS resolved FROM support_tickets""")
    try:
        approvals = db.query_one("SELECT COUNT(*) AS n FROM order_actions WHERE status = 'pending_approval'")["n"]
    except Exception:
        approvals = 0
    return {"tickets": records(t, 300), "counts": {"all": counts["all_"], "open": counts["open"],
            "escalated": counts["escalated"], "resolved": counts["resolved"]},
            "summary": crm.support_summary(), "ai": ai_stats(), "pending_approvals": approvals,
            "categories": records(crm.ticket_categories())}


def _transcript(conversation_id: int) -> list[dict]:
    return records(db.query_df("SELECT role, content, tool_name, tool_args, created_at FROM messages "
                               "WHERE conversation_id = ? ORDER BY id", (conversation_id,)))


@router.get("/helpdesk/tickets/{tid}")
def ticket(tid: int) -> dict:
    t = db.query_one("""SELECT t.*, c.name AS customer, o.order_number, o.status AS order_status, o.total AS order_total,
                               o.payment_method FROM support_tickets t JOIN customers c ON c.id = t.customer_id
                        LEFT JOIN orders o ON o.id = t.order_id WHERE t.id = ?""", (tid,))
    if not t:
        raise HTTPException(404, "Ticket not found.")
    runs = db.query_df("SELECT * FROM ai_ticket_runs WHERE ticket_id = ? ORDER BY id DESC", (tid,))
    last = runs.iloc[0].to_dict() if len(runs) else None
    return {"ticket": t, "runs": records(runs),
            "transcript": _transcript(int(last["conversation_id"])) if last and last.get("conversation_id") else []}


@router.post("/helpdesk/tickets/{tid}/ai")
def run_ai(tid: int) -> dict:
    from kotler.agent.copilot import run_ticket
    llm = need_llm()
    if not db.query_one("SELECT id FROM support_tickets WHERE id = ?", (tid,)):
        raise HTTPException(404, "Ticket not found.")
    turn, outcome, agent = run_ticket(llm, tid)
    return {"outcome": outcome, "reply": turn.reply, "error": turn.error, "guard": turn.guard,
            "tools": [{"name": x.name, "arguments": x.arguments, "result": x.result} for x in turn.tools],
            "latency_ms": turn.latency_ms, "transcript": _transcript(agent.conversation_id)}


@router.get("/helpdesk/approvals")
def approvals() -> dict:
    from kotler.agent.support_tools import pending_actions
    df = pending_actions()
    rows = records(df)
    for r in rows:
        r["details"] = json.loads(r["details"] or "{}") if isinstance(r.get("details"), str) else r.get("details")
    return {"approvals": rows}


class DecisionIn(BaseModel):
    approve: bool


@router.post("/helpdesk/approvals/{action_id}")
def decide(action_id: int, body: DecisionIn) -> dict:
    from kotler.agent.support_tools import decide_action
    res = decide_action(action_id, body.approve, reviewer="admin")
    if not res.get("ok"):
        raise HTTPException(409, res.get("error", "Couldn't decide."))
    return res
