"""WhatsApp Cloud API adapter (Meta). Free test number; real use needs business verification.

Setup (developers.facebook.com):
  1. Create an app (type "Business"), add the WhatsApp product. Meta gives you a TEST phone number.
  2. Add up to 5 of YOUR OWN numbers as allowed recipients (Meta sends them a code).
  3. Copy: Phone number ID, a temporary access token (24 h) or a system-user token, and the app secret.
  4. Configure the webhook URL https://YOUR-APP/webhooks/whatsapp with a verify token you choose,
     and subscribe to "messages".
Environment: WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN, WHATSAPP_APP_SECRET, WHATSAPP_VERIFY_TOKEN,
             WHATSAPP_ALLOWED_NUMBERS (comma-separated, e.g. 919876543210), WHATSAPP_API_VERSION (default v21.0)

Rules we enforce in code:
- SIGNATURE: every webhook POST carries X-Hub-Signature-256 = HMAC-SHA256(app secret, raw body). Requests
  that don't match are rejected: otherwise anyone could POST fake "customer messages" to our server.
- ALLOWLIST: in test mode we only ever send to numbers in WHATSAPP_ALLOWED_NUMBERS, never to the
  (realistic-looking but random) phone numbers in the demo database.
- 24-HOUR WINDOW: WhatsApp allows free-form messages only within 24 h of the customer's last message.
  Outside it, only pre-approved TEMPLATES may be sent (marketing ones are paid per message in India).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timedelta

import requests

from kotler import db
from kotler.channels.core import Incoming, handle_incoming

GRAPH = "https://graph.facebook.com/{version}/{phone_id}/messages"


def env(name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, default)


def allowed_numbers() -> set[str]:
    return {"".join(ch for ch in n if ch.isdigit()) for n in (env("WHATSAPP_ALLOWED_NUMBERS") or "").split(",") if n.strip()}


def verify_challenge(params: dict) -> str | None:
    """Meta's one-time handshake when you register the webhook URL."""
    if params.get("hub.mode") == "subscribe" and env("WHATSAPP_VERIFY_TOKEN") and \
            hmac.compare_digest(params.get("hub.verify_token", ""), env("WHATSAPP_VERIFY_TOKEN")):
        return params.get("hub.challenge")
    return None


def valid_signature(raw_body: bytes, header: str | None) -> bool:
    secret = env("WHATSAPP_APP_SECRET")
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.split("=", 1)[1])


def parse_payload(payload: dict) -> list[Incoming]:
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name") for c in value.get("contacts", [])}
            for m in value.get("messages", []):  # 'statuses' (delivered/read receipts) are ignored
                text = m.get("text", {}).get("body", "") if m.get("type") == "text" else ""
                out.append(Incoming("whatsapp", m["from"], text, update_id=m.get("id"), display_name=names.get(m["from"])))
    return out


def within_24h(phone: str) -> bool:
    row = db.query_one("SELECT last_inbound_at FROM channel_users WHERE channel = 'whatsapp' AND external_id = ?", (phone,))
    if not row or not row["last_inbound_at"]:
        return False
    return datetime.now() - datetime.strptime(row["last_inbound_at"], "%Y-%m-%d %H:%M:%S") < timedelta(hours=24)


class NotAllowed(Exception):
    pass


def _post(body: dict) -> dict:
    url = GRAPH.format(version=env("WHATSAPP_API_VERSION", "v21.0"), phone_id=env("WHATSAPP_PHONE_NUMBER_ID"))
    r = requests.post(url, json=body, headers={"Authorization": f"Bearer {env('WHATSAPP_ACCESS_TOKEN')}"}, timeout=30)
    data = r.json()
    if r.status_code >= 400:
        raise RuntimeError(f"WhatsApp send failed: {data.get('error', {}).get('message', r.text[:200])}")
    return data


def send_text(to: str, text: str) -> dict:
    to = "".join(ch for ch in to if ch.isdigit())
    if to not in allowed_numbers():
        raise NotAllowed(f"{to} is not in WHATSAPP_ALLOWED_NUMBERS (test mode sends only to your own numbers).")
    if not within_24h(to):
        raise NotAllowed("Outside the 24-hour window: WhatsApp only allows approved templates now.")
    return _post({"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": text[:4096]}})


def send_template(to: str, template: str = "hello_world", language: str = "en_US") -> dict:
    """Pre-approved template: the only kind of message allowed outside the 24-hour window."""
    to = "".join(ch for ch in to if ch.isdigit())
    if to not in allowed_numbers():
        raise NotAllowed(f"{to} is not in WHATSAPP_ALLOWED_NUMBERS.")
    return _post({"messaging_product": "whatsapp", "to": to, "type": "template",
                  "template": {"name": template, "language": {"code": language}}})


def process_payload(payload: dict, llm=None) -> int:
    sent = 0
    for msg in parse_payload(payload):
        out = handle_incoming(msg, llm)
        for t in out.texts:
            try:
                send_text(msg.external_id, t)
                sent += 1
            except NotAllowed as e:
                print("WhatsApp reply not sent:", e)
    return sent
