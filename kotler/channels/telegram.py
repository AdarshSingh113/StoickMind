"""Telegram adapter (free, no business verification needed).

Setup (2 minutes): open Telegram, message @BotFather, send /newbot, pick a name. It gives you a TOKEN.
Never commit it: put it in an environment variable / secrets file as TELEGRAM_BOT_TOKEN.

Two ways to receive messages:
  1. POLLING (easiest, no public URL): this process asks Telegram "anything new?" in a loop.
         python -m kotler.channels.telegram poll
     Works on your laptop, a GitHub Codespace, or any always-on machine.
  2. WEBHOOK (for hosting): Telegram POSTs each message to our server (kotler/server.py).
         python -m kotler.channels.telegram set-webhook https://YOUR-APP.onrender.com/webhooks/telegram
     A secret token (TELEGRAM_WEBHOOK_SECRET) proves the request really comes from Telegram.

Formatting: agents write WhatsApp-style *bold*; Telegram gets it converted to HTML (with escaping, so a
customer typing "<script>" can't break or inject anything).
"""

from __future__ import annotations

import html
import os
import re
import sys
import time

import requests

from kotler.channels.core import Incoming, handle_incoming

API = "https://api.telegram.org/bot{token}/{method}"


def token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN")


def webhook_secret() -> str | None:
    return os.environ.get("TELEGRAM_WEBHOOK_SECRET")


def call(method: str, **params) -> dict:
    tok = token()
    if not tok:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set.")
    r = requests.post(API.format(token=tok, method=method), json=params, timeout=60)
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram {method} failed: {data.get('description')}")
    return data["result"]


def to_html(text: str) -> str:
    """WhatsApp-style formatting -> Telegram HTML, escaping everything else."""
    safe = html.escape(text)
    safe = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", safe)
    return re.sub(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])", r"<b>\1</b>", safe)


def parse_update(update: dict) -> Incoming | None:
    msg = update.get("message") or update.get("edited_message")
    if not msg or "chat" not in msg:
        return None
    sender = msg.get("from", {})
    name = " ".join(x for x in (sender.get("first_name"), sender.get("last_name")) if x) or None
    text = msg.get("text") or ""
    if not text and (msg.get("photo") or msg.get("voice") or msg.get("sticker") or msg.get("document")):
        text = ""  # core replies "I can only read text messages for now"
    return Incoming("telegram", str(msg["chat"]["id"]), text, update_id=str(update.get("update_id")), display_name=name)


def send_text(chat_id: str, text: str) -> None:
    call("sendMessage", chat_id=chat_id, text=to_html(text), parse_mode="HTML", disable_web_page_preview=True)


def process_update(update: dict, llm=None) -> int:
    """Handle one Telegram update end to end. Returns the number of messages sent."""
    msg = parse_update(update)
    if msg is None:
        return 0
    try:
        call("sendChatAction", chat_id=msg.external_id, action="typing")
    except Exception:
        pass  # cosmetic only
    out = handle_incoming(msg, llm)
    for t in out.texts:
        send_text(msg.external_id, t)
    return len(out.texts)


def poll(llm=None, max_loops: int | None = None) -> None:
    """Long polling: no public URL needed. Ctrl+C to stop."""
    try:
        call("deleteWebhook")  # polling and webhooks can't both be active
    except RuntimeError:
        pass
    me = call("getMe")
    print(f"Polling as @{me['username']}. Message your bot on Telegram. Ctrl+C to stop.")
    offset, loops = None, 0
    while max_loops is None or loops < max_loops:
        loops += 1
        try:
            updates = call("getUpdates", offset=offset, timeout=50, allowed_updates=["message", "edited_message"])
        except Exception as e:  # network blips: wait and retry
            print("getUpdates failed:", e)
            time.sleep(5)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            try:
                process_update(u, llm)
            except Exception as e:  # one bad message must not stop the bot
                print("Failed to process update", u.get("update_id"), e)


def set_webhook(url: str) -> dict:
    params = {"url": url, "allowed_updates": ["message", "edited_message"], "drop_pending_updates": True}
    if webhook_secret():
        params["secret_token"] = webhook_secret()
    call("setWebhook", **params)
    return call("getWebhookInfo")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "poll"
    if cmd == "poll":
        poll()
    elif cmd == "set-webhook":
        print(set_webhook(sys.argv[2]))
    elif cmd == "delete-webhook":
        print(call("deleteWebhook"))
    else:
        print(__doc__)
