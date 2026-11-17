"""Intent tagging (English + Hinglish) and conversation analytics: automation rate, topics, channels."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from kotler import db
from kotler.agent.intent import classify, conversation_intent
from kotler.api import auth
from kotler.channels import core
from kotler.obs.conversations import conversation_stats
from kotler.seed.generate import generate

END = datetime(2026, 11, 14, 20, 0, 0)


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    path = tmp_path / "i.db"
    monkeypatch.setattr("kotler.config.DB_PATH", path)
    for k in ("KOTLER_ADMIN_PASSWORD", "KOTLER_SECRET_KEY", "RENDER", "KOTLER_PRODUCTION"):
        monkeypatch.delenv(k, raising=False)
    generate(n_customers=40, months=2, seed=3, end_date=END, db_path=path)
    db.ensure_schema(path)
    core.ensure_tables()
    auth._attempts.clear()
    return path


@pytest.mark.parametrize("text,intent", [
    ("Hi, where is my order? It's been 5 days", "order_status"),
    ("mera parcel kab aayega", "order_status"),
    ("Order KTL-101562 please", "order_status"),
    ("The moisturizer gave me a rash on my cheeks", "skin_reaction"),
    ("cream lagane ke baad jalan ho rahi hai", "skin_reaction"),
    ("Sunscreen for sensitive skin that won't irritate", "product_advice"),     # negated: a product question
    ("bottle toota hua aaya", "damaged_wrong"),
    ("paisa wapas chahiye", "refund_return"),
    ("I want to cancel my order", "cancel"),
    ("can I pay by UPI?", "payment"),
    ("koi discount code hai?", "discount"),
    ("oily skin ke liye face wash batao", "product_advice"),
    ("/quiz", "product_advice"),
    ("I need to speak to a human", "asked_for_person"),
    ("Great, thanks!", "other"),
])
def test_classify(text, intent):
    assert classify(text) == intent


def test_conversation_takes_the_most_serious_topic():
    assert conversation_intent(["The cream gave me a rash", "Ok. I want a refund."]) == "skin_reaction"
    assert conversation_intent(["hello", "thanks"]) == "other" and conversation_intent([]) == "other"


def chat(ext, msgs, handler="ai", needs=0, channel="telegram"):
    core.get_session(channel, ext)
    core._update_session(channel, ext, handler=handler, needs_human=needs)
    for direction, text, who in msgs:
        core._log(channel, ext, direction, text, who)


def test_automation_rate_and_topics():
    chat("1", [("in", "where is my order", None), ("out", "It's shipped", "asha"), ("in", "thanks", None)])
    chat("2", [("in", "face wash for oily skin?", None), ("out", "Try Neem", "kavya")])
    chat("3", [("in", "the serum gave me a rash", None), ("out", "Sorry, passing to the team", "asha"),
               ("out", "Hi, I'm Neha", "human")], handler="human")
    chat("4", [("in", "refund please", None), ("out", "A person will reply", "asha")], needs=1)   # escalated, waiting
    chat("demo-5", [("in", "price of serum?", None)], channel="web")                           # nobody replied
    s = conversation_stats(30)
    assert s["summary"] == {"conversations": 5, "automated": 2, "automation_rate": 0.4, "handed_over": 2,
                            "unanswered": 1, "avg_messages": pytest.approx(11 / 5), "demo": 1}
    by = {r["intent"]: r for r in s["intents"]}
    assert by["product_advice"]["conversations"] == 2 and by["product_advice"]["automated_pct"] == 50
    assert by["skin_reaction"]["handed_over_pct"] == 100 and by["skin_reaction"]["example"] == "the serum gave me a rash"
    assert {c["channel"]: c["conversations"] for c in s["channels"]} == {"telegram": 4, "web": 1}


def test_period_filter_and_empty():
    assert conversation_stats(30)["summary"]["conversations"] == 0
    chat("1", [("in", "hi", None)])
    with db.get_conn() as conn:
        conn.execute("UPDATE channel_events SET created_at = '2020-01-01 10:00:00'")
    assert conversation_stats(30)["summary"]["conversations"] == 0 and conversation_stats(None)["summary"]["conversations"] == 1


def test_api_and_inbox_tags():
    from kotler import server
    c = TestClient(server.app)
    assert c.get("/api/v1/performance/conversations").status_code == 401
    c.post("/api/v1/auth/login", json={"password": "kotler"})
    c.post("/api/v1/inbox/demo")
    r = c.get("/api/v1/performance/conversations?days=30").json()
    assert r["summary"]["conversations"] == 5 and r["summary"]["demo"] == 5 and "ai_sales" in r
    tags = {x["display_name"]: x["intent_label"] for x in c.get("/api/v1/inbox").json()["conversations"]}
    assert "Skin reaction" in tags.values() and "Order status" in tags.values()


def test_an_escalation_counts_even_after_handing_back(monkeypatch):
    from kotler import server
    from kotler.llm import FakeLLM, text_response
    monkeypatch.setattr("kotler.llm.get_llm", lambda: FakeLLM(lambda m, t: text_response("Please stop using it.")))
    core.handle_incoming(core.Incoming("web", "visitor-1", "The serum is burning my skin"))        # handoff rule
    assert db.query_one("SELECT escalated_at FROM channel_users WHERE external_id = 'visitor-1'")["escalated_at"]
    c = TestClient(server.app)
    c.post("/api/v1/auth/login", json={"password": "kotler"})
    c.post("/api/v1/inbox/web/visitor-1/takeover")
    c.post("/api/v1/inbox/web/visitor-1/release")                     # handed back, no person replied
    s = conversation_stats(30)
    assert s["summary"]["automated"] == 0 and s["summary"]["handed_over"] == 1


def test_older_databases_backfill_escalations():
    chat("9", [("in", "refund please", None), ("out", "A person will reply", "asha")], needs=1)
    with db.get_conn() as conn:
        conn.execute("ALTER TABLE channel_users DROP COLUMN escalated_at")
    core.ensure_tables()
    assert db.query_one("SELECT escalated_at FROM channel_users WHERE external_id = '9'")["escalated_at"]
