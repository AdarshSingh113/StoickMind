"""Kotler AI API server: the part of the product that the outside world talks to.

Run locally:   uvicorn kotler.server:app --reload --port 8000     (then open http://localhost:8000)
Free hosting:  see docs/deploy.md (Render / Codespaces)

Endpoints
  GET  /                      the dashboard (React app, built into frontend/dist), needs login
  /api/v1/...                 dashboard API (kotler/api): auth, overview, inbox
  GET  /store                 demo storefront with the chat widget
  GET  /widget.js             embeddable chat widget: <script src="https://YOUR-APP/widget.js" defer></script>
  POST /api/chat              website chat (the widget calls this)
  GET  /api/chat/updates      messages a PERSON sent to this web chat from the inbox (the widget polls)
  POST /webhooks/telegram     Telegram updates (checked with the secret token)
  GET  /webhooks/whatsapp     Meta's verification handshake
  POST /webhooks/whatsapp     WhatsApp messages (checked with the HMAC signature)
  GET  /health                for uptime checks

Webhook pattern: ACKNOWLEDGE FAST, WORK IN THE BACKGROUND. Telegram and WhatsApp retry if we don't answer
quickly, and an LLM reply can take 10-30 s. So the endpoint validates the request, returns 200 at once, and a
background task generates and sends the reply. Retries are harmless anyway: the core processes each update once.
Why a separate server and not Streamlit? Streamlit serves a dashboard to a browser; it can't receive webhooks.
"""

from __future__ import annotations

import html
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from kotler import config, db, store as shop
from kotler.api import analytics, auth, customers, inbox, operations, overview, studio
from kotler.channels import core, telegram, whatsapp

WEB_DIR = Path(__file__).with_name("web")
DIST_DIR = Path(__file__).resolve().parent.parent / "frontend" / "dist"   # the built React app
SESSION_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")



@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup()
    yield


def startup() -> None:
    """Make sure a database with the schema and built-in agents exists before the first request."""
    from kotler.bootstrap import prepare
    prepare()


app = FastAPI(title="Kotler AI", description="Channels and chat API for Kotler AI agents.", version="0.7.0",
              lifespan=lifespan)
# Product images (and other public media). Mounted before the React app's catch-all route below.
app.mount("/media", StaticFiles(directory=WEB_DIR / "media"), name="media")
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in os.environ.get("KOTLER_ALLOWED_ORIGINS", "*").split(",")],
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


for module in (overview, inbox, customers, analytics, operations, studio):
    app.include_router(module.router)


@app.get("/health")
def health() -> dict:
    from kotler.llm import get_llm
    return {"ok": True, "llm_configured": get_llm() is not None, "telegram": bool(telegram.token()),
            "whatsapp": bool(os.environ.get("WHATSAPP_ACCESS_TOKEN")), "frontend_built": DIST_DIR.exists()}


# ------------------------------------------------------------------ dashboard login
class LoginIn(BaseModel):
    password: str = Field(..., max_length=200)


@app.post("/api/v1/auth/login")
def login(body: LoginIn, request: Request, response: Response) -> dict:
    auth.login(request, response, body.password)
    return {"ok": True}


@app.post("/api/v1/auth/logout")
def logout(response: Response) -> dict:
    auth.logout(response)
    return {"ok": True}


@app.get("/api/v1/auth/me")
def me(request: Request) -> dict:
    return {"user": auth.require_user(request), "brand": config.BRAND_NAME,
            "default_password": auth.using_default_password()}


# ------------------------------------------------------------------ web chat
class ChatIn(BaseModel):
    session_id: str = Field(..., description="Random id the widget keeps in localStorage")
    message: str = Field(..., max_length=1000)


@app.post("/api/chat")
def chat(body: ChatIn) -> dict:
    if not SESSION_ID.match(body.session_id):
        raise HTTPException(400, "Invalid session id.")
    out = core.handle_incoming(core.Incoming("web", body.session_id, body.message))
    cards = [{**c, "buy_url": shop.buy_link(c["product_id"], f"web:{body.session_id}")} for c in out.cards]
    return {"replies": out.texts, "agent": out.agent_slug, "rate_limited": out.rate_limited,
            "human": out.human, "last_id": _last_web_event(body.session_id), "cards": cards}


def _last_web_event(session_id: str) -> int:
    return db.query_one("SELECT COALESCE(MAX(id), 0) AS m FROM channel_events WHERE channel = 'web' AND "
                        "external_id = ?", (session_id,))["m"]


@app.get("/api/chat/updates")
def chat_updates(session_id: str, after: int = 0) -> dict:
    """Messages a person sent to this web chat from the inbox (the widget asks every few seconds)."""
    if not SESSION_ID.match(session_id):
        raise HTTPException(400, "Invalid session id.")
    core.ensure_tables()
    rows = db.query_df("SELECT id, text FROM channel_events WHERE channel = 'web' AND external_id = ? AND id > ? "
                       "AND direction = 'out' AND agent_slug = 'human' ORDER BY id", (session_id, after))
    return {"messages": rows.to_dict("records"), "last_id": max([after, *rows.id.tolist()])}


@app.get("/widget.js")
def widget() -> Response:
    return Response((WEB_DIR / "widget.js").read_text(), media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=300"})


@app.get("/store", response_class=HTMLResponse)
def store_page() -> str:
    products = db.query_df("SELECT id, name, category, price, mrp, rating, image_url FROM products "
                           "WHERE is_active = 1 AND stock > 0 ORDER BY rating DESC").to_dict("records")
    e = html.escape
    cards = "".join(
        f"""<div class="p"><img src="{e(p['image_url'] or '')}" alt="{e(p['name'])}" loading="lazy">
        <div class="body"><div class="cat">{e(p['category'].replace('_', ' '))}</div><div class="n">{e(p['name'])}</div>
        <div class="pr"><b>₹{p['price']:,.0f}</b> <s>₹{p['mrp']:,.0f}</s> · ★ {p['rating']}</div>
        <div class="row"><a class="buy" href="{e(shop.buy_link(p['id']))}">Buy</a>
        <button class="ask" data-q="Tell me about {e(p['name'])}. Is it right for my skin?">Ask</button></div></div></div>"""
        for p in products)
    page = (WEB_DIR / "store.html").read_text()
    return page.replace("{{BRAND}}", e(config.BRAND_NAME)).replace("{{PRODUCTS}}", cards)


def _checkout_page(content: str) -> HTMLResponse:
    page = (WEB_DIR / "checkout.html").read_text()
    return HTMLResponse(page.replace("{{BRAND}}", html.escape(config.BRAND_NAME)).replace("{{CONTENT}}", content))


def _checkout_form(p: dict, ref: str, sig: str, error: str = "", form: dict | None = None) -> HTMLResponse:
    e, f = html.escape, form or {}
    options = "".join(f'<option value="{c["pincode"]}"{" selected" if f.get("pincode") == c["pincode"] else ""}>'
                      f'{e(c["city"])}, {e(c["state"])} ({c["pincode"]})</option>' for c in shop.cities())
    qty = "".join(f'<option{" selected" if str(q) == f.get("quantity", "1") else ""}>{q}</option>'
                  for q in range(1, shop.MAX_QTY + 1))
    cod = f.get("payment", "cod") == "cod"
    return _checkout_page(f"""
      <section class="card product"><img src="{e(p['image_url'] or '')}" alt="{e(p['name'])}">
        <h1>{e(p['name'])}</h1><div class="muted">{e(p['size'])} · ★ {p['rating']}</div>
        <div class="price">₹{p['price']:,.0f} <s>₹{p['mrp']:,.0f}</s></div>
        {'<p><span class="badge">Recommended by our AI assistant</span></p>' if shop.valid_ref(ref, sig) else ''}</section>
      <form class="card" method="post">
        {f'<div class="error">{e(error)}</div>' if error else ''}
        <input type="hidden" name="product" value="{p['id']}"><input type="hidden" name="ref" value="{e(ref)}">
        <input type="hidden" name="sig" value="{e(sig)}">
        <label>Quantity</label><select name="quantity">{qty}</select>
        <label>Full name</label><input name="name" required maxlength="60" value="{e(f.get('name', ''))}">
        <label>Mobile number</label><input name="phone" required inputmode="numeric" maxlength="14" placeholder="98765 43210" value="{e(f.get('phone', ''))}">
        <label>City</label><select name="pincode">{options}</select>
        <label>Address</label><textarea name="address" rows="2" required maxlength="200" placeholder="House no., street, area">{e(f.get('address', ''))}</textarea>
        <label>Payment</label><div class="pay"><label><input type="radio" name="payment" value="cod"{' checked' if cod else ''}> Cash on delivery</label>
        <label><input type="radio" name="payment" value="prepaid"{'' if cod else ' checked'}> Prepaid (demo)</label></div>
        <button>Place demo order</button>
        <p class="muted" style="text-align:center;margin:10px 0 0">Demo store: no payment is taken and nothing ships.</p>
      </form>""")


@app.get("/store/checkout", response_class=HTMLResponse, include_in_schema=False)
def checkout(product: int, ref: str = "", sig: str = "") -> Response:
    p = shop.product(product)
    if not p:
        return RedirectResponse("/store")
    return _checkout_form(p, ref[:120], sig[:64])


_checkout_hits: dict[str, list[float]] = {}


@app.post("/store/checkout", response_class=HTMLResponse, include_in_schema=False)
async def checkout_submit(request: Request) -> Response:
    import time
    from urllib.parse import parse_qs
    raw = (await request.body())[:4000].decode("utf-8", "replace")
    form = {k: v[0] for k, v in parse_qs(raw).items()}
    p = shop.product(int(form.get("product", "0") or 0)) if (form.get("product") or "").isdigit() else None
    if not p:
        return RedirectResponse("/store", status_code=303)
    ip, now = auth._client(request), time.time()           # public form: at most 10 orders per hour per address
    hits = [t for t in _checkout_hits.get(ip, []) if t > now - 3600]
    if len(hits) >= 10:
        return _checkout_form(p, form.get("ref", ""), form.get("sig", ""), "Too many orders from here. Try later.", form)
    try:
        res = shop.place_order(p["id"], int(form.get("quantity", "1") or 1), form.get("name", ""), form.get("phone", ""),
                               form.get("pincode", ""), form.get("address", ""), form.get("payment", ""),
                               form.get("ref") or None, form.get("sig") or None)
    except (shop.CheckoutError, ValueError) as err:
        return _checkout_form(p, form.get("ref", ""), form.get("sig", ""), str(err), form)
    _checkout_hits[ip] = [*hits, now]
    e = html.escape
    return _checkout_page(f"""<section class="card ok"><div class="tick">✓</div>
      <h1>Order {e(res['order_number'])} placed</h1>
      <p class="muted">{e(p['name'])} · ₹{res['total']:,.0f} · expected by {e(res['expected_delivery'])}</p>
      {'<p><span class="badge">Attributed to the AI conversation</span></p>' if res['attributed'] else ''}
      <p class="muted">This is a demo store: nothing will be charged or shipped.</p>
      <a class="back" href="/store">← Back to the store</a></section>""")


# ------------------------------------------------------------------- Telegram
@app.post("/webhooks/telegram")
async def telegram_webhook(request: Request, background: BackgroundTasks,
                           x_telegram_bot_api_secret_token: str | None = Header(default=None)) -> dict:
    secret = telegram.webhook_secret()
    if not secret or x_telegram_bot_api_secret_token != secret:
        raise HTTPException(403, "Bad secret token.")
    update = await request.json()
    background.add_task(telegram.process_update, update)
    return {"ok": True}


# ------------------------------------------------------------------- WhatsApp
@app.get("/webhooks/whatsapp")
def whatsapp_verify(request: Request) -> PlainTextResponse:
    challenge = whatsapp.verify_challenge(dict(request.query_params))
    if challenge is None:
        raise HTTPException(403, "Verification failed.")
    return PlainTextResponse(challenge)


@app.post("/webhooks/whatsapp")
async def whatsapp_webhook(request: Request, background: BackgroundTasks,
                           x_hub_signature_256: str | None = Header(default=None)) -> dict:
    raw = await request.body()
    if not whatsapp.valid_signature(raw, x_hub_signature_256):
        raise HTTPException(403, "Bad signature.")
    background.add_task(whatsapp.process_payload, await request.json())
    return {"ok": True}


# ------------------------------------------------------------------ the React app (must be LAST)
@app.get("/{path:path}", include_in_schema=False)
def spa(path: str) -> Response:
    """Serve the built React app. Real files (JS, CSS, fonts) as they are; every other path gets index.html,
    because the app does its own routing in the browser (/inbox, /overview...)."""
    if path.startswith(("api/", "webhooks/", "media/", "store/")):
        raise HTTPException(404, "Not found.")
    if not DIST_DIR.exists():
        return HTMLResponse("<h3>Kotler AI API is running.</h3><p>The dashboard isn't built yet: "
                            "<code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>. "
                            "Demo store: <a href='/store'>/store</a></p>")
    file = (DIST_DIR / path).resolve()
    if path and file.is_file() and DIST_DIR.resolve() in file.parents:   # no ../ escapes
        cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
        return FileResponse(file, headers={"Cache-Control": cache})
    return FileResponse(DIST_DIR / "index.html", headers={"Cache-Control": "no-cache"})
