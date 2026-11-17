"""Handoff rules: a person joins when a rule matches, enforced in code even if the model forgets."""

import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from kotler import db
from kotler.agent import studio as S
from kotler.agent.handoff import RULES, triggered
from kotler.agent.runtime import Agent
from kotler.api import auth
from kotler.channels import core
from kotler.llm import FakeLLM, text_response, tool_call_response
from kotler.seed.generate import generate

END = datetime(2026, 11, 14, 20, 0, 0)
ALL = list(RULES)


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    path = tmp_path / "h.db"
    monkeypatch.setattr("kotler.config.DB_PATH", path)
    for k in ("KOTLER_ADMIN_PASSWORD", "KOTLER_SECRET_KEY", "RENDER", "KOTLER_PRODUCTION"):
        monkeypatch.delenv(k, raising=False)
    generate(n_customers=40, months=2, seed=5, end_date=END, db_path=path)
    db.ensure_schema(path)
    core.ensure_tables()
    auth._attempts.clear()
    return path


@pytest.mark.parametrize("text,fired", [
    ("The cream gave me a rash", ["skin_reaction"]),
    ("cream lagane ke baad jalan ho rahi hai", ["skin_reaction"]),
    ("where is my order, I want to talk to a manager", ["asks_for_person"]),
    ("mujhe kisi insaan se baat karni hai", ["asks_for_person"]),
    ("I will go to consumer court", ["legal_threat"]),
    ("This is the WORST service ever", ["angry"]),
    ("WHERE IS MY ORDER IT HAS BEEN TWO WEEKS", ["angry"]),
    ("Thank you so much!!!", []),
    ("Sunscreen for sensitive skin that won't irritate", []),
    ("your agent was helpful, thanks", []),
])
def test_rules(text, fired):
    assert triggered(ALL, text) == fired


def test_model_forgets_to_escalate_code_does_it():
    llm = FakeLLM([text_response("I'm sorry about the delay. Let me check that for you.")])
    turn = Agent(S.get_agent("asha"), llm, customer_id=1).reply("I'm filing a police complaint, this is fraud")
    esc = [t for t in turn.tools if t.name == "escalate_to_human"]
    assert len(esc) == 1 and esc[0].arguments["priority"] == "high" and "legal_threat" in esc[0].arguments["summary"]
    assert turn.handoff == ["legal_threat"] and turn.escalated
    assert turn.reply.endswith("A person from our team will also reply here within 1 hour.")
    t = db.query_one("SELECT id, escalated, meta FROM ai_traces WHERE kind = 'agent_turn' ORDER BY id DESC LIMIT 1")
    assert t["escalated"] == 1 and json.loads(t["meta"])["handoff"] == ["legal_threat"]
    span = db.query_one("SELECT name, ok FROM trace_spans WHERE trace_id = ? AND name = 'handoff_rule'", (t["id"],))
    assert span == {"name": "handoff_rule", "ok": 0}


def test_no_double_escalation_when_the_agent_escalates():
    llm = FakeLLM([tool_call_response("escalate_to_human", {"summary": "rash", "priority": "high"}),
                   text_response("Please stop using it and rinse with cool water. Our care team will reply within 1 hour.")])
    turn = Agent(S.get_agent("asha"), llm, customer_id=1).reply("The serum gave me a rash")
    assert sum(t.name == "escalate_to_human" for t in turn.tools) == 1
    assert "A person from our team" not in turn.reply and turn.handoff == ["skin_reaction"]


def test_agent_without_the_tool_flags_the_chat(monkeypatch):
    llm = FakeLLM(lambda m, t: text_response("Sorry to hear that! Please stop using it."))
    monkeypatch.setattr("kotler.llm.get_llm", lambda: llm)
    out = core.handle_incoming(core.Incoming("telegram", "55", "face cream ke baad khujli ho rahi hai"))
    assert out.agent_slug == "kavya" and "Hamari team ka ek member bhi yahin reply karega." in out.texts[-1]
    assert db.query_one("SELECT needs_human FROM channel_users WHERE external_id = '55'")["needs_human"] == 1
    assert not db.query_one("SELECT COUNT(*) AS n FROM order_actions")["n"]                     # no ticket: no tool


def test_rules_can_be_switched_off():
    cfg = S.save_agent(S.replace(S.get_agent("asha"), handoff_rules=[]))
    turn = Agent(cfg, FakeLLM([text_response("Let me check.")]), customer_id=1).reply("I'll go to consumer court")
    assert not turn.handoff and not turn.escalated and turn.tools == []


def test_old_rows_get_defaults_and_old_snapshots_restore_cleanly():
    with db.get_conn() as conn:
        conn.execute("UPDATE agents SET handoff_rules = NULL")
    assert S.get_agent("asha").handoff_rules == S.ASHA.handoff_rules
    assert S.get_agent("kavya").handoff_rules == ["skin_reaction", "asks_for_person", "legal_threat"]
    v1 = S.versions("asha")[-1]
    with db.get_conn() as conn:                     # a snapshot saved before handoff rules existed
        snap = {k: v for k, v in v1["snapshot"].items() if k != "handoff_rules"}
        conn.execute("UPDATE agent_versions SET snapshot = ? WHERE slug = 'asha' AND version = ?",
                     (json.dumps(snap), v1["version"]))
    S.save_agent(S.replace(S.get_agent("asha"), handoff_rules=["angry"]))
    assert S.restore("asha", v1["version"]).handoff_rules == ["angry"]       # kept, not wiped


def test_studio_api():
    from kotler import server
    c = TestClient(server.app)
    c.post("/api/v1/auth/login", json={"password": "kotler"})
    meta = c.get("/api/v1/agents/meta").json()
    assert {r["key"] for r in meta["handoff_rules"]} == set(RULES)
    assert {t["name"] for t in meta["tools"]} == set(meta["data_access"])            # every tool is described
    a = c.get("/api/v1/agents/kavya").json()["agent"]
    body = {k: a[k] for k in ("name", "role", "description", "instructions", "goal", "success_criteria", "tools",
                              "temperature", "max_steps")}
    assert c.put("/api/v1/agents/kavya", json=body).json()["agent"]["handoff_rules"] == a["handoff_rules"]   # omitted: kept
    r = c.put("/api/v1/agents/kavya", json={**body, "handoff_rules": ["angry"], "note": "rules"}).json()["agent"]
    assert r["handoff_rules"] == ["angry"]
    assert "handoff_rules" in c.get("/api/v1/agents/kavya").json()["versions"][0]["changes"]
    assert c.put("/api/v1/agents/kavya", json={**body, "handoff_rules": ["moon"]}).status_code == 422
