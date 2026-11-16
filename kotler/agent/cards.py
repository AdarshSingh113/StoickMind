"""Product cards: the products an agent actually recommended in a reply, with picture and price.

Which products? Only those that (1) came back from a tool in this turn, so they're real catalogue rows, and
(2) are named in the reply text, so the cards match what the customer reads. Prices on the card come from the
database, never from the model.

Cards are shown as image cards in the website chat, as photos on Telegram and WhatsApp, in the dashboard inbox
and in the Agent Studio playground. A card's "Buy" link opens the demo checkout tagged with the chat it came
from, which is how AI-assisted orders are attributed (see kotler.store).
"""

from __future__ import annotations

import os
import re

from kotler.db import query_df

MAX_CARDS = 4


def public_base_url() -> str:
    """Absolute address of this deployment (needed where a message carries a link, e.g. Telegram buttons)."""
    return (os.environ.get("PUBLIC_BASE_URL") or "").rstrip("/")


def _ids(obj, out: list[int]) -> None:
    if isinstance(obj, dict):
        pid = obj.get("product_id")
        if isinstance(pid, int) and pid not in out:
            out.append(pid)
        for v in obj.values():
            _ids(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _ids(v, out)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9%+]+", " ", s.lower()).strip()


def mentioned(name: str, reply: str) -> int | None:
    """Position of the product in the reply (full name, or its first three words), else None."""
    text, full = _norm(reply), _norm(name)
    for needle in (full, " ".join(full.split()[:3])):
        if len(needle) >= 8 and needle in text:
            return text.index(needle)
    return None


def product_cards(reply: str, tool_results: list[dict], limit: int = MAX_CARDS) -> list[dict]:
    ids: list[int] = []
    for r in tool_results:
        _ids(r, ids)
    if not ids or not reply:
        return []
    rows = query_df(f"SELECT id, name, category, price, mrp, size, rating, stock, image_url FROM products "
                    f"WHERE id IN ({','.join('?' * len(ids))})", tuple(ids)).to_dict("records")
    found = sorted(((pos, r) for r in rows if (pos := mentioned(r["name"], reply)) is not None), key=lambda x: x[0])
    return [{"product_id": int(r["id"]), "name": r["name"], "category": r["category"], "price": float(r["price"]),
             "mrp": float(r["mrp"]), "size": r["size"], "rating": float(r["rating"]), "in_stock": int(r["stock"]) > 0,
             "image_url": r["image_url"]} for _, r in found[:limit]]


def image_path(image_url: str | None):
    """Local file for an image URL like /media/products/x.jpg (Telegram uploads the file itself)."""
    from pathlib import Path
    if not image_url or not image_url.startswith("/media/"):
        return None
    p = Path(__file__).resolve().parent.parent / "web" / image_url.lstrip("/")
    return p if p.is_file() else None
