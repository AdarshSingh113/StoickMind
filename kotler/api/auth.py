"""Login for the dashboard API: one admin password, a signed session cookie.

Why not JWT in localStorage? Anything in localStorage can be read by JavaScript, so one XSS bug leaks the token.
An HttpOnly cookie can't be read by JavaScript at all; the browser attaches it automatically.

The cookie value is `<expiry>.<signature>`, where signature = HMAC-SHA256(secret, expiry). The server stores
nothing: it recomputes the signature to check the cookie wasn't forged or extended. SameSite=Strict means other
websites can't make the browser send it (protection against CSRF).

Password: KOTLER_ADMIN_PASSWORD. Unset = development default "kotler" with a warning in the UI, but NEVER in
production (Render sets RENDER=true; or set KOTLER_PRODUCTION=1): there, login is disabled until you set one.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, Response

COOKIE = "kotler_session"
SESSION_DAYS = 7
DEV_PASSWORD = "kotler"
_attempts: dict[str, deque] = defaultdict(deque)
MAX_ATTEMPTS_PER_MINUTE = 5
MAX_ATTEMPTS_GLOBAL = 30


def production() -> bool:
    return bool(os.environ.get("RENDER") or os.environ.get("KOTLER_PRODUCTION"))


def password() -> str | None:
    pw = os.environ.get("KOTLER_ADMIN_PASSWORD")
    if pw:
        return pw
    return None if production() else DEV_PASSWORD


def using_default_password() -> bool:
    return not os.environ.get("KOTLER_ADMIN_PASSWORD") and not production()


def _secret() -> bytes:
    explicit = os.environ.get("KOTLER_SECRET_KEY")
    # Derived from the password when not set: changing the password logs everyone out.
    return (explicit or f"kotler-session:{password()}").encode()


def make_token(now: float | None = None) -> str:
    exp = int((time.time() if now is None else now) + SESSION_DAYS * 86400)
    sig = hmac.new(_secret(), str(exp).encode(), hashlib.sha256).hexdigest()
    return f"{exp}.{sig}"


def valid_token(token: str | None, now: float | None = None) -> bool:
    if not token or "." not in token or password() is None:
        return False
    exp, sig = token.split(".", 1)
    if not exp.isdigit() or int(exp) < (time.time() if now is None else now):
        return False
    good = hmac.new(_secret(), exp.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, good)


def _client(request: Request) -> str:
    """Who is trying to log in? X-Forwarded-For can be typed by anyone, so it's only trusted behind a known proxy
    (Render, or KOTLER_TRUST_PROXY=1), and then only its LAST entry: the one our own proxy added."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd and (os.environ.get("RENDER") or os.environ.get("KOTLER_TRUST_PROXY")):
        return fwd.split(",")[-1].strip()
    return request.client.host if request.client else "?"


def _too_many(key: str, limit: int, now: float) -> bool:
    q = _attempts[key]
    while q and q[0] < now - 60:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def login(request: Request, response: Response, given: str) -> None:
    pw = password()
    if pw is None:
        raise HTTPException(503, "Login is disabled: set KOTLER_ADMIN_PASSWORD on the server.")
    ip, now = _client(request), time.time()
    # Per address, plus a global cap so many addresses together can't brute-force either.
    if _too_many(ip, MAX_ATTEMPTS_PER_MINUTE, now) or _too_many("*", MAX_ATTEMPTS_GLOBAL, now):
        raise HTTPException(429, "Too many attempts. Wait a minute and try again.")
    if not hmac.compare_digest(given.encode(), pw.encode()):  # constant time: no timing hints
        raise HTTPException(401, "Wrong password.")
    _attempts[ip].clear()
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(COOKIE, make_token(), max_age=SESSION_DAYS * 86400, httponly=True, samesite="strict",
                        secure=https, path="/")


def logout(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")


def require_user(request: Request) -> str:
    """FastAPI dependency: every dashboard endpoint needs a valid session."""
    if not valid_token(request.cookies.get(COOKIE)):
        raise HTTPException(401, "Please log in.")
    return "admin"
