"""Inbox AI copilot (suggest / rephrase / summarize for the person replying) and private notes."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from kotler import db
from kotler.agent.assist import unchecked_facts
from kotler.api import auth
from kotler.channels import core
from kotler.llm import FakeLLM, text_response
from kotler.seed.generate import generate

END = datetime(2026, 11, 14, 20, 0, 0)
CH, ID = "telegram", "777"


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    path = tmp_path / "c.db"
    monkeypatch.setattr("kotler.config.DB_PATH", path)
    for k in ("KOTLER_ADMIN_PASSWORD", "KOTLER_SECRET_KEY", "RENDER", "KOTLER_PRODUCTION"):
        monkeypatch.delenv(k, raising=False)
    generate(n_customers=60, months=3, seed=8, end_date=END, db_path=path)
    db.ensure_schema(path)
    core.ensure_tables()
    auth._attempts.clear()
    return path


@pytest.fixture
def admin():
    from kotler import server
    c = TestClient(server.app)
    assert c.post("/api/v1/auth/login", json={"password": "kotler"}).status_code == 200
    return c


def customer_chat() -> dict:
    """A verified customer asking about their latest order."""
    order = db.query_one("SELECT o.*, c.id AS cid FROM orders o JOIN customers c ON c.id = o.customer_id "
                         "ORDER BY o.created_at DESC LIMIT 1")
    core.get_session(CH, ID, "Riya")
    core._update_session(CH, ID, customer_id=order["cid"], handler="human")
    core._log(CH, ID, "in", f"Where is my order {order['order_number']}? It's late and I'm upset.")
    return order


def use(monkeypatch, *replies):
    llm = FakeLLM([text_response(r) for r in replies])
    monkeypatch.setattr("kotler.llm.get_llm", lambda: llm)
    return llm


def test_suggestion_is_grounded_in_real_orders(admin, monkeypatch):
    order = customer_chat()
    llm = use(monkeypatch, f"Sorry for the wait! {order['order_number']} is {order['status']}.")
    r = admin.post(f"/api/v1/inbox/{CH}/{ID}/assist", json={"action": "suggest"}).json()
    assert r["warnings"] == [] and order["order_number"] in r["text"]
    prompt = llm.calls[0][0]["content"]
    assert order["order_number"] in prompt and "policies" in prompt.lower()       # facts the model was given


def test_invented_facts_are_flagged(admin, monkeypatch):
    customer_chat()
    use(monkeypatch, "Done! Refund of ₹99,999 for KTL-999999 is processed.")
    r = admin.post(f"/api/v1/inbox/{CH}/{ID}/assist", json={"action": "suggest"}).json()
    assert r["warnings"] == ["KTL-999999", "₹99,999"]
    t = db.query_one("SELECT kind, status FROM ai_traces ORDER BY id DESC LIMIT 1")
    assert t == {"kind": "inbox_assist", "status": "corrected"}                  # visible in Monitor


def test_guest_chats_share_no_order_details(admin, monkeypatch):
    core.get_session(CH, ID)
    core._log(CH, ID, "in", "where is my order")
    llm = use(monkeypatch, "Could you share your order number and phone?")
    admin.post(f"/api/v1/inbox/{CH}/{ID}/assist", json={"action": "suggest"})
    assert "guest (not verified)" in llm.calls[0][0]["content"] and "KTL-" not in llm.calls[0][0]["content"]


def test_rephrase_needs_a_draft_and_keeps_facts(admin, monkeypatch):
    customer_chat()
    use(monkeypatch, "Arre sorry! Aapka refund ₹499 ho gaya hai.")
    assert admin.post(f"/api/v1/inbox/{CH}/{ID}/assist", json={"action": "hinglish", "draft": " "}).status_code == 422
    r = admin.post(f"/api/v1/inbox/{CH}/{ID}/assist", json={"action": "hinglish", "draft": "Sorry! Your ₹499 refund is done."})
    assert r.status_code == 200 and r.json()["warnings"] == []                   # ₹499 was in the draft
    assert admin.post(f"/api/v1/inbox/{CH}/{ID}/assist", json={"action": "delete_all"}).status_code == 422


def test_summary(admin, monkeypatch):
    customer_chat()
    use(monkeypatch, "- Late order, upset\n- Nothing yet\n- Check courier")
    r = admin.post(f"/api/v1/inbox/{CH}/{ID}/assist", json={"action": "summarize"}).json()
    assert r["text"].count("- ") == 3 and r["warnings"] == []


def test_no_llm_and_unknown_chat(admin, monkeypatch):
    customer_chat()
    monkeypatch.setattr("kotler.llm.get_llm", lambda: None)
    assert admin.post(f"/api/v1/inbox/{CH}/{ID}/assist", json={"action": "suggest"}).status_code == 503
    assert admin.post(f"/api/v1/inbox/{CH}/nobody/assist", json={"action": "suggest"}).status_code == 404


def test_notes_are_private(admin, monkeypatch):
    customer_chat()
    sent = []
    monkeypatch.setattr("kotler.channels.outbound.send", lambda *a, **k: sent.append(a))
    assert admin.post(f"/api/v1/inbox/{CH}/{ID}/notes", json={"text": "Refund approved by Priya"}).json() == {"ok": True}
    conv = admin.get(f"/api/v1/inbox/{CH}/{ID}").json()
    assert [n["text"] for n in conv["notes"]] == ["Refund approved by Priya"]
    assert all("Refund approved" not in m["text"] for m in conv["messages"]) and not sent
    assert admin.post(f"/api/v1/inbox/{CH}/{ID}/notes", json={"text": ""}).status_code == 422


def test_copilot_needs_login():
    from kotler import server
    c = TestClient(server.app)
    assert c.post(f"/api/v1/inbox/{CH}/{ID}/assist", json={"action": "suggest"}).status_code == 401
    assert c.post(f"/api/v1/inbox/{CH}/{ID}/notes", json={"text": "x"}).status_code == 401


def test_unchecked_facts():
    ctx = "KTL-000123 on 2026-11-01: shipped, COD, ₹1,299"
    assert unchecked_facts("Your KTL-000123 (₹1299) is shipped", ctx) == []
    assert unchecked_facts("Rs. 250 off on ktl-000124", ctx) == ["KTL-000124", "₹250"]


def test_reloading_demo_chats_clears_their_notes(admin):
    admin.post("/api/v1/inbox/demo")
    ch, ext = next((c["channel"], c["external_id"]) for c in admin.get("/api/v1/inbox").json()["conversations"])
    admin.post(f"/api/v1/inbox/{ch}/{ext}/notes", json={"text": "old note"})
    admin.post("/api/v1/inbox/demo")
    assert admin.get(f"/api/v1/inbox/{ch}/{ext}").json()["notes"] == []
