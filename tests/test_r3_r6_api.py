"""R3-R6 API tests: customers, Ask your data + AI performance, campaigns, helpdesk, Agent Studio.

The API is a thin layer, so these tests check what the layer adds: login on every route, input validation, the
guardrails still apply through HTTP, and AI-only endpoints fail clearly (503) instead of crashing without a key.
"""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from kotler import db
from kotler.llm import FakeLLM, text_response, tool_call_response
from kotler.seed.generate import generate

END = datetime(2026, 11, 14, 20, 0, 0)


@pytest.fixture(scope="module")
def dbpath(tmp_path_factory):
    path = tmp_path_factory.mktemp("r3") / "r3.db"
    generate(n_customers=1500, months=12, seed=42, end_date=END, db_path=path)   # ML training needs real-size data
    return path


@pytest.fixture(autouse=True)
def database(dbpath, tmp_path, monkeypatch):
    work = tmp_path / "work.db"
    work.write_bytes(dbpath.read_bytes())                    # every test starts from the same data
    monkeypatch.setattr("kotler.config.DB_PATH", work)
    monkeypatch.setattr("kotler.config.DATA_DIR", dbpath.parent)   # trained models are reused across tests
    for k in ("KOTLER_ADMIN_PASSWORD", "RENDER", "KOTLER_PRODUCTION"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("kotler.llm.get_llm", lambda: None)
    db.ensure_schema(work)
    from kotler.api import auth
    auth._attempts.clear()
    return work


@pytest.fixture
def admin():
    from kotler import server
    c = TestClient(server.app)
    assert c.post("/api/v1/auth/login", json={"password": "kotler"}).status_code == 200
    return c


def test_every_new_route_needs_login():
    from kotler import server
    c = TestClient(server.app)
    for path in ("/api/v1/customers", "/api/v1/customers/1", "/api/v1/performance", "/api/v1/performance/traces",
                 "/api/v1/performance/evals", "/api/v1/performance/impact", "/api/v1/journeys", "/api/v1/campaigns",
                 "/api/v1/helpdesk", "/api/v1/helpdesk/approvals", "/api/v1/agents", "/api/v1/agents/kavya"):
        assert c.get(path).status_code == 401, path
    assert c.post("/api/v1/ask", json={"question": "orders?"}).status_code == 401
    assert c.put("/api/v1/agents/kavya", json={}).status_code == 401


# ------------------------------------------------------------------ R3 customers
def test_customer_list_search_filter_sort_page(admin):
    r = admin.get("/api/v1/customers?page_size=10").json()
    assert r["total"] == 1500 and len(r["customers"]) == 10 and r["segments"]
    values = [c["lifetime_value"] for c in r["customers"]]
    assert values == sorted(values, reverse=True)
    seg = r["segments"][0]["segment"]
    f = admin.get(f"/api/v1/customers?segment={seg}&page_size=100").json()
    assert f["total"] == r["segments"][0]["customers"] and {c["segment"] for c in f["customers"]} == {seg}
    name = r["customers"][0]["name"]
    assert any(c["name"] == name for c in admin.get(f"/api/v1/customers?q={name.split()[0]}").json()["customers"])
    churn = [c["churn_risk"] for c in admin.get("/api/v1/customers?sort=churn&page_size=20").json()["customers"]]
    assert churn == sorted(churn, reverse=True)
    p2 = admin.get("/api/v1/customers?page_size=10&page=2").json()["customers"]
    assert not {c["id"] for c in p2} & {c["id"] for c in r["customers"]}
    assert admin.get("/api/v1/customers?tier=4").status_code == 422


def test_customer_360(admin):
    cid = admin.get("/api/v1/customers?page_size=5").json()["customers"][0]["id"]
    d = admin.get(f"/api/v1/customers/{cid}").json()
    assert d["customer"]["id"] == cid and d["customer"]["phone"] and d["orders"] and d["monthly"]
    assert 0 <= d["scores"]["churn_risk"] <= 1 and d["segment_info"]["action"]
    assert sum(m["orders"] for m in d["monthly"]) == d["customer"]["orders"]
    assert admin.get("/api/v1/customers/999999").status_code == 404


# ------------------------------------------------------------------ R4 ask + performance
def test_ask_needs_ai_and_returns_checked_answers(admin, monkeypatch):
    assert admin.post("/api/v1/ask", json={"question": "how many orders?"}).status_code == 503
    n = db.query_one("SELECT COUNT(*) AS n FROM orders")["n"]
    llm = FakeLLM([text_response(json.dumps({"sql": "SELECT COUNT(*) AS orders FROM orders", "title": "Orders",
                                             "explanation": "Counts orders.", "chart": {"type": "none"}})),
                   text_response(f"There are {n:,} orders.")])
    monkeypatch.setattr("kotler.llm.get_llm", lambda: llm)
    r = admin.post("/api/v1/ask", json={"question": "how many orders?", "history": [{"question": "x", "sql": "SELECT 1"}]}).json()
    assert r["rows"] == [{"orders": n}] and r["answer_status"] == "verified" and r["columns"] == ["orders"]
    assert admin.post("/api/v1/ask", json={"question": "x" * 501}).status_code == 422


def test_ask_blocks_personal_data_through_the_api(admin, monkeypatch):
    spec = lambda sql: text_response(json.dumps({"sql": sql, "title": "t", "explanation": "e", "chart": {"type": "none"}}))
    monkeypatch.setattr("kotler.llm.get_llm", lambda: FakeLLM([spec("SELECT phone FROM customers"), spec("SELECT phone FROM customers")]))
    r = admin.post("/api/v1/ask", json={"question": "phone numbers please"}).json()
    assert r["error"] and "customers.phone" in r["error"] and r["rows"] == []


def test_performance_endpoints(admin, monkeypatch):
    from kotler.agent.runtime import Agent
    from kotler.agent.studio import ensure_builtin_agents, get_agent
    ensure_builtin_agents()
    Agent(get_agent("kavya"), FakeLLM([tool_call_response("search_products", {"skin_type": "oily"}), text_response("Here you go.")])).reply("serum?")
    p = admin.get("/api/v1/performance?days=30").json()
    assert p["summary"]["agent_turns"] == 1 and p["agents"][0]["agent"] == "kavya" and p["tools"][0]["tool"] == "search_products"
    t = admin.get("/api/v1/performance/traces").json()
    assert t["total"] == 1 and t["kinds"] == ["agent_turn"]
    d = admin.get(f"/api/v1/performance/traces/{t['traces'][0]['id']}").json()
    assert len(d["llm_calls"]) == 2 and d["spans"][0]["name"] == "search_products"
    assert admin.get("/api/v1/performance/traces/99999").status_code == 404
    assert "runs" in admin.get("/api/v1/performance/evals").json()
    imp = admin.get("/api/v1/performance/impact").json()
    assert {l["evidence"] for l in imp["levers"]} <= {"measured", "modelled", "simulated"}


def test_trace_steps_keep_their_order():
    from kotler.obs.trace import _now
    assert len(_now()) == 23   # milliseconds: steps in the same second keep their order


# ------------------------------------------------------------------ R5 campaigns
def _templates(admin, offer=10):
    r = admin.post("/api/v1/campaigns/templates", json={"journey": "win_back", "offer_pct": offer}).json()
    assert r["source"] == "fallback"                 # no AI key: hand-written templates, still validated
    return r["templates"]


def test_campaign_lifecycle(admin):
    j = admin.get("/api/v1/journeys").json()["journeys"]
    assert {x["journey"] for x in j} == {"replenishment", "win_back", "cross_sell", "second_order"}
    aud = admin.get("/api/v1/journeys/win_back/audience?limit=5").json()
    assert aud["total"] > 0 and len(aud["sample"]) <= 5
    t = _templates(admin)
    cid = admin.post("/api/v1/campaigns", json={"name": "Win-back test", "journey": "win_back", "templates": t,
                                                "template_source": "fallback", "offer_pct": 10, "holdout_pct": 0.2}).json()["id"]
    d = admin.get(f"/api/v1/campaigns/{cid}").json()
    assert d["campaign"]["status"] == "draft" and d["results"] is None and d["examples"]
    assert admin.post(f"/api/v1/campaigns/{cid}/simulate").status_code == 409        # must send first
    assert admin.post(f"/api/v1/campaigns/{cid}/send").json()["sent"] > 0
    assert admin.post(f"/api/v1/campaigns/{cid}/send").status_code == 409            # only once
    assert admin.post(f"/api/v1/campaigns/{cid}/simulate").status_code == 200
    r = admin.get(f"/api/v1/campaigns/{cid}").json()["results"]
    assert r["verdict"] and {g["group"] for g in r["groups"]} == {"A", "B", "control"} and 0 <= r["p_value"] <= 1
    assert admin.get("/api/v1/campaigns").json()["campaigns"][0]["status"] == "measured"


def test_campaign_guardrails_hold_through_the_api(admin):
    t = _templates(admin, offer=0)
    base = {"name": "Guardrail test", "journey": "win_back", "templates": t, "offer_pct": 0, "holdout_pct": 0.2}
    assert "15%" in admin.post("/api/v1/campaigns", json={**base, "offer_pct": 30}).json()["detail"]
    assert "Holdout" in admin.post("/api/v1/campaigns", json={**base, "holdout_pct": 0.0}).json()["detail"]
    bad = json.loads(json.dumps(t))
    bad["A"]["en"] = "Hi {first_name}, get {product} for just ₹99!"
    assert "placeholders" in admin.post("/api/v1/campaigns", json={**base, "templates": bad}).json()["detail"]
    assert admin.post("/api/v1/campaigns", json={**base, "journey": "nope"}).status_code == 404


# ------------------------------------------------------------------ R5 helpdesk
def test_helpdesk_lists_and_needs_ai(admin):
    h = admin.get("/api/v1/helpdesk?status=open").json()
    assert h["tickets"] and all(t["status"] == "open" for t in h["tickets"]) and h["counts"]["open"] == len(h["tickets"])
    tid = h["tickets"][0]["id"]
    assert admin.get(f"/api/v1/helpdesk/tickets/{tid}").json()["ticket"]["id"] == tid
    assert admin.post(f"/api/v1/helpdesk/tickets/{tid}/ai").status_code == 503
    assert admin.get("/api/v1/helpdesk?status=weird").status_code == 422


def test_copilot_run_through_the_api(admin, monkeypatch):
    tid = admin.get("/api/v1/helpdesk?status=open").json()["tickets"][0]["id"]
    monkeypatch.setattr("kotler.llm.get_llm", lambda: FakeLLM([text_response("I've checked: it arrives tomorrow.")]))
    r = admin.post(f"/api/v1/helpdesk/tickets/{tid}/ai").json()
    assert r["outcome"] == "resolved" and r["transcript"][-1]["content"].startswith("I've checked")
    assert admin.get(f"/api/v1/helpdesk/tickets/{tid}").json()["ticket"]["status"] == "resolved"


def test_approvals_decide_once(admin):
    o = db.query_one("SELECT id, customer_id, total FROM orders WHERE status = 'delivered' LIMIT 1")
    with db.get_conn() as conn:
        aid = conn.execute("INSERT INTO order_actions (action, status, order_id, customer_id, agent_slug, amount, reason, "
                           "created_at) VALUES ('refund', 'pending_approval', ?, ?, 'asha', ?, 'damaged', '2026-11-14 10:00:00')",
                           (o["id"], o["customer_id"], o["total"])).lastrowid
    a = admin.get("/api/v1/helpdesk/approvals").json()["approvals"]
    assert [x["id"] for x in a] == [aid]
    assert admin.post(f"/api/v1/helpdesk/approvals/{aid}", json={"approve": True}).json()["ok"]
    assert admin.post(f"/api/v1/helpdesk/approvals/{aid}", json={"approve": False}).status_code == 409
    assert db.query_one("SELECT status, decided_by FROM order_actions WHERE id = ?", (aid,)) == {"status": "approved", "decided_by": "admin"}


# ------------------------------------------------------------------ R6 Agent Studio
def test_studio_edit_version_restore(admin):
    agents = admin.get("/api/v1/agents").json()["agents"]
    assert {"kavya", "asha", "skin-quiz"} <= {a["slug"] for a in agents}
    meta = admin.get("/api/v1/agents/meta").json()
    assert any(t["writes"] for t in meta["tools"]) and "Blank agent" in meta["templates"]
    cur = admin.get("/api/v1/agents/kavya").json()["agent"]
    body = {k: cur[k] for k in ("name", "role", "description", "instructions", "goal", "success_criteria", "tools", "temperature", "max_steps")}
    v2 = admin.put("/api/v1/agents/kavya", json={**body, "goal": "A sharper goal", "note": "sharper"}).json()["agent"]
    assert v2["version"] == cur["version"] + 1 and v2["goal"] == "A sharper goal"
    vs = admin.get("/api/v1/agents/kavya").json()["versions"]
    assert vs[0]["note"] == "sharper" and "goal" in vs[0]["changes"]
    back = admin.post("/api/v1/agents/kavya/restore", json={"version": cur["version"]}).json()["agent"]
    assert back["goal"] == cur["goal"] and back["version"] == v2["version"] + 1          # history never rewritten
    bad = admin.put("/api/v1/agents/kavya", json={**body, "tools": ["drop_database"]})
    assert bad.status_code == 422 and "Unknown tools" in bad.json()["detail"]


def test_studio_create_status_delete(admin):
    r = admin.post("/api/v1/agents", json={"slug": "riya-winback", "name": "Riya", "template": "Customer care"})
    assert r.status_code == 200 and r.json()["agent"]["status"] == "draft"
    assert admin.post("/api/v1/agents", json={"slug": "riya-winback", "name": "Riya"}).status_code == 409
    assert admin.post("/api/v1/agents", json={"slug": "Bad Slug!", "name": "x"}).status_code == 422
    assert admin.post("/api/v1/agents/riya-winback/status", json={"status": "live"}).json()["agent"]["status"] == "live"
    assert admin.delete("/api/v1/agents/kavya").status_code == 409                      # built-ins can't be deleted
    assert admin.delete("/api/v1/agents/riya-winback").json()["deleted"] == "riya-winback"
    assert admin.get("/api/v1/agents/riya-winback").status_code == 404


def test_playground_and_judge(admin, monkeypatch):
    assert admin.post("/api/v1/agents/kavya/chat", json={"message": "hi"}).status_code == 503
    llm = FakeLLM([text_response("Hi! What's your skin type?"), text_response("Thanks, oily it is."),
                   text_response('{"achieved": true, "score": 5, "reason": "Asked the right question."}')])
    monkeypatch.setattr("kotler.llm.get_llm", lambda: llm)
    first = admin.post("/api/v1/agents/kavya/chat", json={"message": "hi"}).json()
    second = admin.post("/api/v1/agents/kavya/chat", json={"message": "oily", "conversation_id": first["conversation_id"]}).json()
    assert second["conversation_id"] == first["conversation_id"] and second["reply"] == "Thanks, oily it is."
    assert admin.post("/api/v1/agents/asha/chat", json={"message": "x", "conversation_id": first["conversation_id"]}).status_code == 404
    v = admin.post("/api/v1/agents/kavya/judge", json={"conversation_id": first["conversation_id"]}).json()
    assert v["achieved"] is True and v["score"] == 5
