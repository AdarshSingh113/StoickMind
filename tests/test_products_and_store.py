"""Product images, product cards (chat, Telegram, WhatsApp, inbox), the demo checkout and AI attribution."""

import json
import re
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kotler import db, store
from kotler.agent.cards import mentioned, product_cards
from kotler.channels import core, telegram, whatsapp
from kotler.llm import FakeLLM, text_response, tool_call_response
from kotler.seed.generate import generate
from kotler.seed.images import catalog_for_renderer

END = datetime(2026, 11, 14, 20, 0, 0)
MEDIA = Path(__file__).resolve().parent.parent / "kotler" / "web" / "media" / "products"


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    path = tmp_path / "shop.db"
    monkeypatch.setattr("kotler.config.DB_PATH", path)
    for k in ("PUBLIC_BASE_URL", "KOTLER_ADMIN_PASSWORD", "RENDER", "KOTLER_PRODUCTION"):
        monkeypatch.delenv(k, raising=False)
    generate(n_customers=80, months=3, seed=4, end_date=END, db_path=path)
    db.ensure_schema(path)
    core.ensure_tables()
    return path


@pytest.fixture
def client():
    from kotler import server
    server._checkout_hits.clear()
    return TestClient(server.app)


def neem():
    return db.query_one("SELECT * FROM products WHERE name LIKE 'Neem%'")


# ------------------------------------------------------------------ images
def test_every_product_has_an_image_file():
    rows = db.query_df("SELECT name, image_url FROM products")
    assert rows.image_url.notna().all()
    for url in rows.image_url:
        assert (MEDIA / url.rsplit("/", 1)[1]).is_file(), url
    assert {p["slug"] for p in catalog_for_renderer()} == {f.stem for f in MEDIA.glob("*.jpg")}   # no stray files


def test_old_databases_get_the_image_column():
    with db.get_conn() as conn:
        conn.execute("ALTER TABLE products DROP COLUMN image_url")
    db.ensure_schema()
    assert db.query_one("SELECT COUNT(*) AS n FROM products WHERE image_url IS NULL")["n"] == 0


def test_media_is_served_and_safe(client):
    url = neem()["image_url"]
    r = client.get(url)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert client.get("/media/products/nope.jpg").status_code == 404
    assert "DB_PATH" not in client.get("/media/../config.py").text


# ------------------------------------------------------------------ cards
def test_cards_only_for_real_recommended_products():
    p = neem()
    tool_results = [{"products": [{"product_id": p["id"], "name": p["name"]}, {"product_id": 99999, "name": "Ghost"}]}]
    reply = f"Try *{p['name']}* for oily skin. The *Retinol 0.3% Night Serum* is great too."
    cards = product_cards(reply, tool_results)
    assert [c["product_id"] for c in cards] == [p["id"]]          # retinol named but no tool returned it
    assert cards[0]["price"] == p["price"] and cards[0]["image_url"] == p["image_url"]   # price from the DB
    assert product_cards("No products here.", tool_results) == []
    assert mentioned("Salicylic Acid 2% Acne Serum", "the salicylic acid 2% serum") is not None


def test_agent_turn_and_web_chat_return_cards(client, monkeypatch):
    p = neem()
    llm = FakeLLM([tool_call_response("get_product_details", {"product_id": p["id"]}),
                   text_response(f"For oily skin try *{p['name']}*.")])
    monkeypatch.setattr("kotler.llm.get_llm", lambda: llm)
    r = client.post("/api/chat", json={"session_id": "visitor-abc-12345", "message": "face wash for oily skin"}).json()
    card = r["cards"][0]
    assert card["name"] == p["name"] and card["buy_url"].startswith(f"/store/checkout?product={p['id']}&ref=web%3A")
    meta = db.query_one("SELECT meta FROM channel_events WHERE direction = 'out' ORDER BY id DESC LIMIT 1")["meta"]
    assert json.loads(meta)["cards"][0]["product_id"] == p["id"]   # the inbox can show them


def test_inbox_shows_cards(client):
    client.post("/api/v1/auth/login", json={"password": "kotler"})
    client.post("/api/v1/inbox/demo")
    kavya = next(c for c in client.get("/api/v1/inbox").json()["conversations"] if c["agent_slug"] == "kavya")
    msgs = client.get(f"/api/v1/inbox/{kavya['channel']}/{kavya['external_id']}").json()["messages"]
    assert any(m["cards"] for m in msgs) and all("meta" not in m for m in msgs)


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, url, json=None, data=None, files=None, headers=None, timeout=None):
        self.calls.append({"method": url.rsplit("/", 1)[-1], "json": json, "data": data, "files": sorted(files or {})})

        class R:
            status_code = 200

            def json(self_inner):
                return {"ok": True, "result": {"message_id": 1}}
        return R()


def test_telegram_uploads_product_photos(monkeypatch):
    p = neem()
    rec = Recorder()
    monkeypatch.setattr(telegram.requests, "post", rec)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    llm = FakeLLM([tool_call_response("get_product_details", {"product_id": p["id"]}), text_response(f"Try *{p['name']}*.")])
    telegram.process_update({"update_id": 1, "message": {"chat": {"id": 42}, "text": "face wash for oily skin"}}, llm)
    photo = next(c for c in rec.calls if c["method"] == "sendPhoto")
    assert photo["files"] == ["p0"] and "reply_markup" not in photo["data"]          # no public URL: no Buy button
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://kotler.example.com")
    telegram.send_cards("42", [product_cards(f"Try *{p['name']}*", [{"product_id": p["id"]}])[0]])
    buttons = json.loads(rec.calls[-1]["data"]["reply_markup"])["inline_keyboard"][0][0]["url"]
    assert buttons.startswith("https://kotler.example.com/store/checkout?product=") and "ref=telegram%3A42" in buttons


def test_whatsapp_images_need_a_public_url(monkeypatch):
    rec = Recorder()
    monkeypatch.setattr(whatsapp.requests, "post", rec)
    monkeypatch.setenv("WHATSAPP_ALLOWED_NUMBERS", "919999999999")
    core.get_session("whatsapp", "919999999999")
    with db.get_conn() as conn:
        conn.execute("UPDATE channel_users SET last_inbound_at = ?", (datetime.now().strftime(core.FMT),))
    card = product_cards(f"Try *{neem()['name']}*", [{"product_id": neem()["id"]}])
    assert whatsapp.send_cards("919999999999", card) == 0 and not rec.calls
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://kotler.example.com")
    assert whatsapp.send_cards("919999999999", card) == 1
    img = rec.calls[-1]["json"]["image"]
    assert img["link"].startswith("https://kotler.example.com/media/products/") and "ref=whatsapp%3A919999999999" in img["caption"]


# ------------------------------------------------------------------ checkout + attribution
def _form(link: str, client, **over):
    page = client.get(link).text
    hidden = dict(re.findall(r'name="(product|ref|sig)" value="([^"]*)"', page))
    pincode = db.query_one("SELECT pincode FROM pincodes ORDER BY pincode LIMIT 1")["pincode"]
    return {**hidden, "quantity": "1", "name": "Riya Sen", "phone": "98765 01234", "pincode": pincode,
            "address": "12 Lajpat Nagar, Block C", "payment": "cod", **over}


def test_attributed_checkout(client):
    p = neem()
    link = store.buy_link(p["id"], "telegram:42")
    assert "Recommended by our AI assistant" in client.get(link).text
    r = client.post("/store/checkout", data=_form(link, client, quantity="2"))
    assert "placed" in r.text and "Attributed to the AI conversation" in r.text
    o = db.query_one("SELECT * FROM orders ORDER BY id DESC LIMIT 1")
    assert (o["source"], o["ai_ref"], o["status"], o["total"]) == ("ai_chat", "telegram:42", "placed", p["price"] * 2)
    assert db.query_one("SELECT stock FROM products WHERE id = ?", (p["id"],))["stock"] == p["stock"] - 2
    sales = store.ai_sales()
    assert sales["orders"] == 1 and sales["revenue"] == o["total"]


def test_forged_ref_is_a_normal_order_and_chat_is_not_linked(client):
    core.get_session("telegram", "42")
    data = _form(store.buy_link(neem()["id"]), client, ref="telegram:42", sig="0" * 20)
    client.post("/store/checkout", data=data)
    assert db.query_one("SELECT source, ai_ref FROM orders ORDER BY id DESC LIMIT 1") == {"source": "store", "ai_ref": None}
    assert db.query_one("SELECT customer_id FROM channel_users WHERE external_id = '42'")["customer_id"] is None


def test_checkout_validation_and_existing_customer(client):
    link = store.buy_link(neem()["id"])
    for bad in ({"phone": "12345"}, {"address": "x"}, {"pincode": "000000"}, {"payment": "upi"}, {"quantity": "9"}):
        r = client.post("/store/checkout", data=_form(link, client, **bad))
        assert 'class="error"' in r.text, bad
    existing = db.query_one("SELECT id, phone FROM customers LIMIT 1")
    n = db.query_one("SELECT COUNT(*) AS n FROM customers")["n"]
    client.post("/store/checkout", data=_form(link, client, phone=existing["phone"]))
    assert db.query_one("SELECT customer_id FROM orders ORDER BY id DESC LIMIT 1")["customer_id"] == existing["id"]
    assert db.query_one("SELECT COUNT(*) AS n FROM customers")["n"] == n
    page = client.post("/store/checkout", data=_form(link, client, phone=existing["phone"])).text
    assert existing["phone"] not in page.replace("98765 01234", "")       # nothing about the customer is revealed


def test_checkout_rate_limit(client):
    link = store.buy_link(neem()["id"])
    for _ in range(10):
        assert "placed" in client.post("/store/checkout", data=_form(link, client)).text
    assert "Too many orders" in client.post("/store/checkout", data=_form(link, client)).text


def test_store_page_has_images_and_buy_links(client):
    page = client.get("/store").text
    assert page.count("/media/products/") >= 30 and "/store/checkout?product=" in page and "Demo" in page
