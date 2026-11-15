"""Phase 7 tests: channel core, Telegram & WhatsApp adapters (against fake APIs), the API server, delivery."""

import hashlib
import hmac
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from kotler import db
from kotler.channels import core, outbound, telegram, whatsapp
from kotler.llm import FakeLLM, text_response, tool_call_response
from kotler.seed.generate import generate

END = datetime(2026, 11, 14, 20, 0, 0)


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    path = tmp_path / "p7.db"
    monkeypatch.setattr("kotler.config.DB_PATH", path)
    generate(n_customers=120, months=4, seed=11, end_date=END, db_path=path)
    db.ensure_schema(path)
    core.ensure_tables()
    return path


class FakeHTTP:
    """Stands in for requests.post to Telegram / Meta and records every call."""

    def __init__(self, responses=None):
        self.calls, self.responses = [], responses or {}

    def __call__(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers or {}})
        method = url.rsplit("/", 1)[-1]
        body = self.responses.get(method, {"ok": True, "result": True})
        if callable(body):
            body = body()

        class R:
            status_code = 200

            def json(self_inner):
                return body

            text = ""
        return R()

    def sent(self, method="sendMessage"):
        return [c["json"] for c in self.calls if c["url"].endswith(method)]


@pytest.fixture
def fake_llm(monkeypatch):
    llm = FakeLLM(lambda messages, tools: text_response("Try *Neem Face Wash* for oily skin."))
    monkeypatch.setattr("kotler.llm.get_llm", lambda: llm)
    return llm


def msg(text, uid=None, ext="777", channel="telegram", name="Test User"):
    return core.Incoming(channel, ext, text, update_id=uid, display_name=name)


# ------------------------------------------------------------------- core
def test_welcome_and_routing(fake_llm):
    assert "Glow & Co. assistant" in core.handle_incoming(msg("/start", "1")).texts[0]
    assert core.handle_incoming(msg("where is my order KTL-100005?", "2")).agent_slug == "asha"
    core.handle_incoming(msg("/new", "3"))
    assert core.handle_incoming(msg("moisturizer for dry skin", "4")).agent_slug == "kavya"
    out = core.handle_incoming(msg("/quiz", "5"))
    assert out.agent_slug == "skin-quiz" and "Ira" in out.texts[0]
    assert core.handle_incoming(msg("/help where is my order", "6")).agent_slug == "asha"  # command + question


def test_agent_sticks_for_the_conversation(fake_llm):
    core.handle_incoming(msg("my order is late", "1"))
    assert core.handle_incoming(msg("also, which sunscreen do you have?", "2")).agent_slug == "asha"


def test_webhook_retries_are_processed_once(fake_llm):
    core.handle_incoming(msg("hello there friend", "42"))
    calls = len(fake_llm.calls)
    again = core.handle_incoming(msg("hello there friend", "42"))
    assert again.duplicate and not again.texts and len(fake_llm.calls) == calls


def test_rate_limit(fake_llm):
    outs = [core.handle_incoming(msg(f"question {i} about serums", str(i))) for i in range(core.RATE_LIMIT + 1)]
    assert outs[-1].rate_limited and not any(o.rate_limited for o in outs[:-1])


def test_stop_and_start():
    core.handle_incoming(msg("STOP", "1"))
    assert db.query_one("SELECT marketing_opt_in FROM channel_users")["marketing_opt_in"] == 0
    core.handle_incoming(msg("START", "2"))
    assert db.query_one("SELECT marketing_opt_in FROM channel_users")["marketing_opt_in"] == 1


def test_guest_verification_persists_across_messages():
    o = db.query_one("SELECT o.order_number, o.customer_id, c.phone FROM orders o JOIN customers c ON c.id = o.customer_id "
                     "LIMIT 1")
    llm = FakeLLM([tool_call_response("verify_order", {"order_number": o["order_number"], "phone_last4": o["phone"][-4:]}),
                   text_response("Verified."),
                   tool_call_response("get_order_status", {"order_number": o["order_number"]}),
                   text_response("Here's your status.")])
    core.handle_incoming(msg(f"track {o['order_number']}, last digits {o['phone'][-4:]}", "1"), llm)
    out = core.handle_incoming(msg("and the courier?", "2"), llm)
    assert out.texts == ["Here's your status."]
    assert db.query_one("SELECT customer_id FROM channel_users")["customer_id"] == o["customer_id"]
    assert "error" not in llm.calls[-1][-1]["content"]  # the 2nd message's tool call ran as the verified customer


def test_whatsapp_number_links_customer_automatically():
    phone = db.query_one("SELECT id, phone FROM customers LIMIT 1")
    core.get_session("whatsapp", "91" + phone["phone"])
    assert db.query_one("SELECT customer_id FROM channel_users")["customer_id"] == phone["id"]


def test_non_text_message_gets_a_polite_reply(fake_llm):
    assert "text messages" in core.handle_incoming(msg("", "1")).texts[0]


def test_split_message():
    parts = core.split_message("line\n" * 2000, 4000)
    assert len(parts) > 1 and all(len(p) <= 4000 for p in parts)


# --------------------------------------------------------------- telegram
def test_telegram_formatting_escapes_html():
    assert telegram.to_html("Try *Neem* <script>x</script> & more") == \
        "Try <b>Neem</b> &lt;script&gt;x&lt;/script&gt; &amp; more"


def test_telegram_parse_update():
    u = {"update_id": 9, "message": {"chat": {"id": 55}, "from": {"first_name": "Ria"}, "text": "hi"}}
    m = telegram.parse_update(u)
    assert (m.external_id, m.text, m.update_id, m.display_name) == ("55", "hi", "9", "Ria")
    assert telegram.parse_update({"update_id": 1, "my_chat_member": {}}) is None


def test_telegram_process_update_sends_html_reply(monkeypatch, fake_llm):
    http = FakeHTTP()
    monkeypatch.setattr(telegram.requests, "post", http)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    telegram.process_update({"update_id": 1, "message": {"chat": {"id": 55}, "from": {"first_name": "Ria"},
                                                         "text": "serum for oily skin"}})
    sent = http.sent()
    assert sent[0]["chat_id"] == "55" and sent[0]["parse_mode"] == "HTML" and "<b>Neem Face Wash</b>" in sent[0]["text"]
    assert all("bot123:abc" in c["url"] for c in http.calls)


def test_telegram_polling_advances_offset(monkeypatch, fake_llm):
    batches = [[{"update_id": 10, "message": {"chat": {"id": 1}, "text": "hi there friend"}}], []]
    http = FakeHTTP({"getUpdates": lambda: {"ok": True, "result": batches.pop(0) if batches else []},
                     "getMe": {"ok": True, "result": {"username": "kotler_bot"}}})
    monkeypatch.setattr(telegram.requests, "post", http)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    telegram.poll(max_loops=2)
    offsets = [c["json"].get("offset") for c in http.calls if c["url"].endswith("getUpdates")]
    assert offsets == [None, 11] and len(http.sent()) == 1


# --------------------------------------------------------------- whatsapp
def _sign(body: bytes, secret="s3cret"):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_whatsapp_verify_and_signature(monkeypatch):
    monkeypatch.setenv("WHATSAPP_VERIFY_TOKEN", "vt")
    monkeypatch.setenv("WHATSAPP_APP_SECRET", "s3cret")
    assert whatsapp.verify_challenge({"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "42"}) == "42"
    assert whatsapp.verify_challenge({"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"}) is None
    body = b'{"entry": []}'
    assert whatsapp.valid_signature(body, _sign(body))
    assert not whatsapp.valid_signature(body, _sign(body, "other"))
    assert not whatsapp.valid_signature(body + b" ", _sign(body))  # tampered body


def _wa_payload(frm="919999999999", text="hi", mid="wamid.1"):
    return {"entry": [{"changes": [{"value": {
        "contacts": [{"wa_id": frm, "profile": {"name": "Neha"}}],
        "messages": [{"from": frm, "id": mid, "type": "text", "text": {"body": text}}],
        "statuses": [{"id": "x", "status": "read"}]}}]}]}


def test_whatsapp_parse_ignores_statuses():
    ms = whatsapp.parse_payload(_wa_payload())
    assert len(ms) == 1 and ms[0].external_id == "919999999999" and ms[0].display_name == "Neha"


def test_whatsapp_send_rules(monkeypatch):
    http = FakeHTTP()
    monkeypatch.setattr(whatsapp.requests, "post", http)
    monkeypatch.setenv("WHATSAPP_ALLOWED_NUMBERS", "919999999999")
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
    with pytest.raises(whatsapp.NotAllowed, match="not in WHATSAPP_ALLOWED"):
        whatsapp.send_text("918888888888", "hello")
    with pytest.raises(whatsapp.NotAllowed, match="24-hour"):
        whatsapp.send_text("919999999999", "hello")      # never wrote to us
    core.get_session("whatsapp", "919999999999")
    with db.get_conn() as conn:
        conn.execute("UPDATE channel_users SET last_inbound_at = ?", ((datetime.now() - timedelta(hours=2)).strftime(core.FMT),))
    whatsapp.send_text("+91 99999 99999", "hello")
    assert http.calls[-1]["headers"]["Authorization"] == "Bearer tok" and "/123/messages" in http.calls[-1]["url"]
    whatsapp.send_template("919999999999")
    assert http.calls[-1]["json"]["type"] == "template"
    assert len(http.calls) == 2  # nothing sent to the non-allowlisted number


# ----------------------------------------------------------------- server
@pytest.fixture
def client(monkeypatch, fake_llm):
    from kotler import server
    return TestClient(server.app)


def test_health_store_widget(client):
    assert client.get("/health").json()["ok"]
    page = client.get("/store").text
    assert "Ask our assistant" in page and '<script src="/widget.js"' in page
    assert "textContent" in client.get("/widget.js").text


def test_web_chat_api(client):
    r = client.post("/api/chat", json={"session_id": "abcd-1234-efgh", "message": "serum for oily skin"})
    assert r.status_code == 200 and r.json()["replies"] and r.json()["agent"] == "kavya"
    assert client.post("/api/chat", json={"session_id": "../etc", "message": "x"}).status_code == 400
    assert client.post("/api/chat", json={"session_id": "abcd-1234-efgh", "message": "x" * 1001}).status_code == 422


def test_telegram_webhook_requires_secret_and_replies(client, monkeypatch):
    http = FakeHTTP()
    monkeypatch.setattr(telegram.requests, "post", http)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "sec")
    update = {"update_id": 5, "message": {"chat": {"id": 9}, "text": "serum please"}}
    assert client.post("/webhooks/telegram", json=update).status_code == 403
    assert client.post("/webhooks/telegram", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "bad"}).status_code == 403
    r = client.post("/webhooks/telegram", json=update, headers={"X-Telegram-Bot-Api-Secret-Token": "sec"})
    assert r.status_code == 200 and http.sent()[0]["chat_id"] == "9"  # background task ran


def test_whatsapp_webhook(client, monkeypatch):
    http = FakeHTTP()
    monkeypatch.setattr(whatsapp.requests, "post", http)
    for k, v in {"WHATSAPP_VERIFY_TOKEN": "vt", "WHATSAPP_APP_SECRET": "s3cret", "WHATSAPP_ACCESS_TOKEN": "tok",
                 "WHATSAPP_PHONE_NUMBER_ID": "1", "WHATSAPP_ALLOWED_NUMBERS": "919999999999"}.items():
        monkeypatch.setenv(k, v)
    ok = client.get("/webhooks/whatsapp", params={"hub.mode": "subscribe", "hub.verify_token": "vt", "hub.challenge": "c1"})
    assert ok.text == "c1"
    body = json.dumps(_wa_payload(text="which sunscreen for oily skin")).encode()
    assert client.post("/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": _sign(body, "x")}).status_code == 403
    r = client.post("/webhooks/whatsapp", content=body, headers={"X-Hub-Signature-256": _sign(body),
                                                                  "Content-Type": "application/json"})
    assert r.status_code == 200 and http.calls[-1]["json"]["to"] == "919999999999"


# --------------------------------------------------------------- delivery
def test_campaign_delivery_only_to_linked_opted_in(monkeypatch):
    from kotler.marketing import campaigns as C
    C.ensure_tables()
    with db.get_conn() as conn:
        cid = conn.execute("INSERT INTO campaigns (name, journey, channel, holdout_pct, templates, status, created_at) "
                           "VALUES ('t', 'win_back', 'whatsapp', 0.2, '{}', 'sent', 'now')").lastrowid
        for cust in (1, 2, 3):
            conn.execute("INSERT INTO campaign_members (campaign_id, customer_id, grp, message) VALUES (?,?,?,?)",
                         (cid, cust, "A", f"Hi customer {cust}"))
    for ext, cust in (("t1", 1), ("t2", 2)):
        core.get_session("telegram", ext)
        outbound.link_chat_to_customer("telegram", ext, cust)
    core.handle_incoming(msg("STOP", "x", ext="t2"))     # customer 2 opted out
    http = FakeHTTP()
    monkeypatch.setattr(telegram.requests, "post", http)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    res = outbound.deliver_campaign(cid, "telegram")
    assert res["sent"] == 1 and [s["chat_id"] for s in http.sent()] == ["t1"]
    assert "Reply STOP" in http.sent()[0]["text"]
