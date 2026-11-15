"""R1/R2 tests: dashboard login, the Overview API, the Inbox API with human takeover, live events, SPA serving."""

import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from kotler import crm, db
from kotler.api import auth, inbox
from kotler.channels import core, telegram
from kotler.llm import FakeLLM, text_response, tool_call_response
from kotler.seed.generate import generate

END = datetime(2026, 11, 14, 20, 0, 0)


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    path = tmp_path / "r.db"
    monkeypatch.setattr("kotler.config.DB_PATH", path)
    for k in ("KOTLER_ADMIN_PASSWORD", "KOTLER_SECRET_KEY", "RENDER", "KOTLER_PRODUCTION"):
        monkeypatch.delenv(k, raising=False)
    generate(n_customers=120, months=4, seed=12, end_date=END, db_path=path)
    db.ensure_schema(path)
    core.ensure_tables()
    auth._attempts.clear()
    return path


@pytest.fixture
def client():
    from kotler import server
    return TestClient(server.app)


@pytest.fixture
def admin(client):
    assert client.post("/api/v1/auth/login", json={"password": "kotler"}).status_code == 200
    return client


# ------------------------------------------------------------------ auth
def test_api_needs_login(client):
    for path in ("/api/v1/overview", "/api/v1/inbox", "/api/v1/auth/me"):
        assert client.get(path).status_code == 401
    assert client.post("/api/v1/inbox/demo").status_code == 401


def test_login_cookie_is_httponly_and_strict(client):
    assert client.post("/api/v1/auth/login", json={"password": "nope"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"password": "kotler"})
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie
    me = client.get("/api/v1/auth/me").json()
    assert me["user"] == "admin" and me["default_password"] is True
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").status_code == 401


def test_forged_or_expired_tokens_fail():
    good = auth.make_token()
    exp, sig = good.split(".")
    assert auth.valid_token(good)
    assert not auth.valid_token(f"{int(exp) + 999999}.{sig}")          # extended expiry, old signature
    assert not auth.valid_token(f"{exp}.{'0' * 64}")
    assert not auth.valid_token(auth.make_token(now=0))                # expired long ago
    assert not auth.valid_token("garbage")


def test_password_change_logs_everyone_out(monkeypatch):
    token = auth.make_token()
    monkeypatch.setenv("KOTLER_ADMIN_PASSWORD", "new-secret")
    assert not auth.valid_token(token)


def test_login_is_rate_limited(client):
    codes = [client.post("/api/v1/auth/login", json={"password": f"x{i}"}).status_code for i in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429


def test_spoofed_forwarded_for_does_not_bypass_the_limit(client):
    codes = [client.post("/api/v1/auth/login", json={"password": "x"}, headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code
             for i in range(6)]
    assert codes[5] == 429


def test_production_refuses_default_password(client, monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    assert client.post("/api/v1/auth/login", json={"password": "kotler"}).status_code == 503
    monkeypatch.setenv("KOTLER_ADMIN_PASSWORD", "long-random-pass")
    assert client.post("/api/v1/auth/login", json={"password": "long-random-pass"}).status_code == 200
    assert client.get("/api/v1/auth/me").json()["default_password"] is False


# ------------------------------------------------------------------ overview
def test_overview_matches_crm(admin):
    o = admin.get("/api/v1/overview?days=30").json()
    assert o["period"]["end"] == "2026-11-14" and len(o["daily"]) == 30
    k = {x["key"]: x for x in o["kpis"]}
    direct = crm.kpis("2026-10-16 00:00:00", "2026-11-15 00:00:00")
    assert k["orders"]["value"] == direct["orders"] and k["net_revenue"]["value"] == pytest.approx(direct["net_revenue"])
    assert sum(d["orders"] for d in o["daily"]) == direct["orders"]
    assert {"tone", "title", "body"} <= set(o["insights"][0]) and len(o["top_products"]) <= 6
    assert admin.get("/api/v1/overview?days=3").status_code == 422      # validated input


def test_indian_number_format():
    from kotler.api.overview import inr
    assert inr(439774) == "₹4,39,774" and inr(12345678) == "₹1,23,45,678" and inr(999) == "₹999"


# ------------------------------------------------------------------ inbox
def _chat(text, uid, ext="555", llm=None, channel="telegram"):
    return core.handle_incoming(core.Incoming(channel, ext, text, update_id=uid, display_name="Ria"), llm)


def test_inbox_lists_and_marks_read(admin):
    _chat("/start", "1")
    lst = admin.get("/api/v1/inbox").json()
    row = lst["conversations"][0]
    assert lst["counts"]["all"] == 1 and row["unread"] == 1 and row["last_direction"] == "out"
    conv = admin.get("/api/v1/inbox/telegram/555").json()
    assert [m["direction"] for m in conv["messages"]] == ["in", "out"] and conv["customer"] is None
    assert admin.get("/api/v1/inbox").json()["conversations"][0]["unread"] == 0
    assert admin.get("/api/v1/inbox/telegram/nope").status_code == 404
    assert admin.get("/api/v1/inbox/sms/555").status_code == 404


def test_takeover_silences_the_ai_until_released(admin, monkeypatch):
    sent = []
    monkeypatch.setattr(telegram, "send_text", lambda chat, text: sent.append((chat, text)))
    _chat("/start", "1")
    admin.post("/api/v1/inbox/telegram/555/takeover")
    llm = FakeLLM([])                                           # would raise if the AI were called
    out = _chat("hello? anyone?", "2", llm=llm)
    assert out.human and out.texts == [] and not llm.calls
    assert admin.get("/api/v1/inbox?view=needs_human").json()["counts"]["needs_human"] == 1
    r = admin.post("/api/v1/inbox/telegram/555/reply", json={"text": "Hi Ria, Neha here!"})
    assert r.status_code == 200 and sent == [("555", "Hi Ria, Neha here!")]
    msgs = admin.get("/api/v1/inbox/telegram/555").json()["messages"]
    assert msgs[-1]["agent_slug"] == "human" and admin.get("/api/v1/inbox").json()["counts"]["needs_human"] == 0
    admin.post("/api/v1/inbox/telegram/555/release")
    out = _chat("which serum for oily skin?", "3", llm=FakeLLM([text_response("Try our niacinamide serum.")]))
    assert out.texts == ["Try our niacinamide serum."]


def test_reply_requires_takeover_and_reports_send_errors(admin, monkeypatch):
    _chat("/start", "1")
    assert admin.post("/api/v1/inbox/telegram/555/reply", json={"text": "hi"}).status_code == 409
    admin.post("/api/v1/inbox/telegram/555/takeover")
    monkeypatch.setattr(telegram, "send_text", lambda *a: (_ for _ in ()).throw(RuntimeError("chat not found")))
    r = admin.post("/api/v1/inbox/telegram/555/reply", json={"text": "hi"})
    assert r.status_code == 422 and "chat not found" in r.json()["detail"]
    assert admin.post("/api/v1/inbox/telegram/555/reply", json={"text": ""}).status_code == 422


def test_ai_escalation_flags_the_chat():
    llm = FakeLLM([tool_call_response("escalate_to_human", {"summary": "angry customer", "priority": "high"}),
                   text_response("I've passed this to our team.")])
    _chat("my order is late and I want to talk to a person", "1", llm=llm)
    assert db.query_one("SELECT needs_human FROM channel_users")["needs_human"] == 1


def test_web_chat_human_reply_reaches_the_widget(admin, client):
    sid = "visitor-1234-abcd"
    first = client.post("/api/chat", json={"session_id": sid, "message": "/start"}).json()
    admin.post(f"/api/v1/inbox/web/{sid}/takeover")
    quiet = client.post("/api/chat", json={"session_id": sid, "message": "help please"}).json()
    assert quiet["human"] and quiet["replies"] == []
    admin.post(f"/api/v1/inbox/web/{sid}/reply", json={"text": "I'm here to help!"})
    upd = client.get(f"/api/chat/updates?session_id={sid}&after={quiet['last_id']}").json()
    assert [m["text"] for m in upd["messages"]] == ["I'm here to help!"] and upd["last_id"] > first["last_id"]
    assert client.get("/api/chat/updates?session_id=../x&after=0").status_code == 400


def test_whatsapp_reply_outside_24h_is_blocked(admin, monkeypatch):
    monkeypatch.setenv("WHATSAPP_ALLOWED_NUMBERS", "919999999999")
    core.get_session("whatsapp", "919999999999")
    admin.post("/api/v1/inbox/whatsapp/919999999999/takeover")
    assert admin.get("/api/v1/inbox/whatsapp/919999999999").json()["can_reply"] is False
    r = admin.post("/api/v1/inbox/whatsapp/919999999999/reply", json={"text": "hi"})
    assert r.status_code == 422 and "24-hour" in r.json()["detail"]


def test_live_events_since():
    start = inbox.latest_event_id()
    _chat("/start", "1")
    ev = inbox.events_since(start)
    assert [e["direction"] for e in ev] == ["in", "out"] and ev[0]["display_name"] == "Ria"
    assert inbox.events_since(ev[-1]["id"]) == []


def test_stream_endpoint_sends_new_events(admin):
    _chat("/start", "1")

    async def first_chunks():
        from httpx import ASGITransport, AsyncClient
        from kotler import server
        cookies = {auth.COOKIE: auth.make_token()}
        async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://t", cookies=cookies) as c:
            async with c.stream("GET", "/api/v1/inbox/stream?max_seconds=2", headers={"Last-Event-ID": "0"}) as r:
                assert r.headers["content-type"].startswith("text/event-stream")
                return "".join([chunk async for chunk in r.aiter_text()])
    body = asyncio.run(first_chunks())
    assert "retry: 3000" in body and body.count("event: message") == 2 and '"direction": "in"' in body


def test_demo_conversations_use_real_customer_names(admin):
    assert admin.post("/api/v1/inbox/demo").json()["loaded"] == 5
    assert admin.post("/api/v1/inbox/demo").json()["loaded"] == 5          # replaces, doesn't duplicate
    lst = admin.get("/api/v1/inbox").json()
    assert lst["counts"] == {"all": 5, "needs_human": 2, "human": 1, "ai": 4}
    linked = [c for c in lst["conversations"] if c["customer_id"]]
    first = linked[0]["customer_name"].split()[0]
    texts = " ".join(m["text"] for c in linked for m in admin.get(f"/api/v1/inbox/{c['channel']}/{c['external_id']}").json()["messages"])
    assert "{first}" not in texts and first in texts


# ------------------------------------------------------------------ serving
def test_spa_and_store_routes(client):
    assert "Ask our assistant" in client.get("/store").text
    assert client.get("/api/does-not-exist").status_code == 404
    page = client.get("/inbox/telegram/123")
    assert page.status_code == 200 and "text/html" in page.headers["content-type"]   # app or "not built" page
    traversal = client.get("/..%2F..%2Fkotler/config.py")
    assert "DB_PATH" not in traversal.text
