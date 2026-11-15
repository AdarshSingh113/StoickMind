"""Kotler AI API server: the part of the product that the outside world talks to.

Run locally:   uvicorn kotler.server:app --reload --port 8000     (then open http://localhost:8000)
Free hosting:  see docs/deploy.md (Render / Codespaces)

Endpoints
  GET  /                      demo storefront with the chat widget
  GET  /widget.js             embeddable chat widget: <script src="https://YOUR-APP/widget.js" defer></script>
  POST /api/chat              website chat (the widget calls this)
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
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from kotler import config, db
from kotler.channels import core, telegram, whatsapp

WEB_DIR = Path(__file__).with_name("web")
SESSION_ID = re.compile(r"^[A-Za-z0-9-]{8,64}$")



@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup()
    yield


def startup() -> None:
    """Make sure a database with the schema and built-in agents exists before the first request."""
    if not config.DB_PATH.exists():
        from kotler.seed.generate import generate
        generate()
    db.ensure_schema()
    core.ensure_tables()
    from kotler.agent.studio import ensure_builtin_agents
    ensure_builtin_agents()


app = FastAPI(title="Kotler AI", description="Channels and chat API for Kotler AI agents.", version="0.7.0",
              lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in os.environ.get("KOTLER_ALLOWED_ORIGINS", "*").split(",")],
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"])


@app.get("/health")
def health() -> dict:
    from kotler.llm import get_llm
    return {"ok": True, "llm_configured": get_llm() is not None, "telegram": bool(telegram.token()),
            "whatsapp": bool(os.environ.get("WHATSAPP_ACCESS_TOKEN"))}


# ------------------------------------------------------------------ web chat
class ChatIn(BaseModel):
    session_id: str = Field(..., description="Random id the widget keeps in localStorage")
    message: str = Field(..., max_length=1000)


@app.post("/api/chat")
def chat(body: ChatIn) -> dict:
    if not SESSION_ID.match(body.session_id):
        raise HTTPException(400, "Invalid session id.")
    out = core.handle_incoming(core.Incoming("web", body.session_id, body.message))
    return {"replies": out.texts, "agent": out.agent_slug, "rate_limited": out.rate_limited}


@app.get("/widget.js")
def widget() -> Response:
    return Response((WEB_DIR / "widget.js").read_text(), media_type="application/javascript",
                    headers={"Cache-Control": "public, max-age=300"})


@app.get("/", response_class=HTMLResponse)
def store() -> str:
    products = db.query_df("SELECT name, category, price, mrp, rating, stock FROM products WHERE is_active = 1 "
                           "ORDER BY rating DESC LIMIT 12").to_dict("records")
    cards = "".join(
        f"""<div class="p"><div class="cat">{html.escape(p['category'].replace('_', ' '))}</div>
        <div class="n">{html.escape(p['name'])}</div>
        <div class="pr">₹{p['price']:,.0f} <s>₹{p['mrp']:,.0f}</s> · ★ {p['rating']}</div>
        <button data-q="Tell me about {html.escape(p['name'])}. Is it right for my skin?">Ask our assistant</button></div>"""
        for p in products)
    page = (WEB_DIR / "store.html").read_text()
    return page.replace("{{BRAND}}", html.escape(config.BRAND_NAME)).replace("{{PRODUCTS}}", cards)


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
