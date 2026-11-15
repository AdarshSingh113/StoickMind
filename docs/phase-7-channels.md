# Phase 7: Real channels (Telegram, WhatsApp, website chat)

Up to Phase 6 the agents only lived inside the dashboard. A business needs them **where customers already are**:
a chat app and its own website. In this phase the same agents (Kavya, Ira, Asha) answer on three real channels.

## What we built

| File | Role |
|---|---|
| `kotler/channels/core.py` | Channel-independent brain: sessions, routing, commands, STOP/START, rate limit, de-duplication, message splitting |
| `kotler/channels/telegram.py` | Telegram Bot API adapter: polling (no server needed) or webhook mode, HTML formatting |
| `kotler/channels/whatsapp.py` | WhatsApp Cloud API adapter: verify handshake, HMAC signature check, allowlist, 24-hour window |
| `kotler/channels/outbound.py` | Messages *we* start: campaign delivery to linked, opted-in chats |
| `kotler/server.py` | FastAPI server: webhooks, `/api/chat`, the widget script and a demo store |
| `kotler/web/widget.js`, `store.html` | One-line embeddable chat bubble and a demo storefront |
| `views/channels.py` | Channels page: setup status, live conversations, campaign delivery |
| `tests/test_phase7_channels.py` | 21 tests, with fake Telegram/Meta APIs (no network) |

## 1. Architecture: adapters around one core

```
Telegram ──┐                       ┌── Kavya (shopping)
WhatsApp ──┼─► adapter ─► core ─► route ─┼── Ira (skin quiz)
Website  ──┘   (parse/send)  (session,  └── Asha (helpdesk)
                              rules)
```

Each adapter does only two things: turn the platform's JSON into an `Incoming` message, and send `Outgoing` text
back in the platform's format. **Every business rule lives once, in `core.py`.** Adding Instagram later means
writing one small adapter, not copying the rules.

## 2. Sessions: remembering who you are between messages

A chat app sends one message at a time. `channel_users` stores per chat: the current conversation, the agent,
the linked customer and marketing consent.

- **WhatsApp** gives us the phone number, so a chat is linked to a customer automatically.
- **Telegram / website** are anonymous. When Asha verifies a guest (order number + last 4 digits of the phone),
  the link is saved, so the *next* message doesn't ask again. A test checks this.

## 3. Routing and commands

| Message | Goes to |
|---|---|
| `/shop`, `/quiz`, `/help` (or `/support`) | Kavya, Ira, Asha |
| words like order, track, refund, cancel, courier | Asha |
| anything else | Kavya |
| `/new` | starts a fresh conversation |
| `STOP` / `START` | opts out of / back into marketing |

Once a conversation has an agent it **sticks**: "also, which sunscreen?" in the middle of an order chat stays
with Asha instead of jumping between agents.

## 4. Webhooks: acknowledge fast, work in the background

Telegram and WhatsApp *push* messages to a URL. If we don't reply `200` quickly they **retry**, and an LLM answer
takes 10–30 seconds. So the endpoint checks the request, returns 200 at once and a `BackgroundTask` writes and
sends the reply.

Retries still happen (network blips), so every update id goes into `processed_updates`. A retried update is
recognised and ignored: **idempotency**. Without it a customer could get the same answer, or worse the same
refund action, twice.

## 5. Security: who is allowed to call our webhook?

A webhook URL is public. Anyone could POST a fake "customer message" to it. So:

- **Telegram**: when we register the webhook we give Telegram a secret; it sends it back in the
  `X-Telegram-Bot-Api-Secret-Token` header. Wrong or missing → `403`.
- **WhatsApp**: Meta signs the raw body with our app secret (HMAC-SHA256, header `X-Hub-Signature-256`). We
  recompute it with `hmac.compare_digest` (constant time). A single changed byte → `403`. A test tampers with the
  body to prove it.
- **Website**: the session id must match `^[A-Za-z0-9-]{8,64}$`, messages are capped at 1,000 characters, and the
  widget renders replies with `textContent`, never `innerHTML`. A reply containing `<script>` shows as text.
- **Rate limit**: 12 messages per user per minute. Protects the free LLM quota from one noisy user.
- **Secrets**: tokens come only from environment variables / `secrets.toml`, never from git.

## 6. WhatsApp's rules (and why they exist)

| Rule | What we do |
|---|---|
| 24-hour customer-service window | Free-form replies only within 24 h of the customer's last message; outside it only pre-approved templates |
| Test numbers | `WHATSAPP_ALLOWED_NUMBERS`: code refuses to send to anyone else, so demo data can never message a real stranger |
| Consent | `STOP` sets `marketing_opt_in = 0`; campaign delivery skips them; every campaign message says "Reply STOP" |

## 7. Formatting per channel

The agents write `*bold*` (WhatsApp style). Telegram uses HTML, so `to_html` **escapes first** (`<`, `>`, `&`)
and only then turns `*x*` into `<b>x</b>`. Escaping after would let a product name or user text inject tags.
Long answers are split at line breaks under the 4,000-character limit.

## 8. Closing the loop with Phase 6

On the Channels page you can link your own Telegram chat to a demo customer and deliver a real campaign:
only chats that are linked **and** opted in receive it. Everyone else in the campaign stays simulated.

## Bugs the tests caught

- The fake reply in a test quoted "₹299", a price not in the catalogue. Phase 2's price-grounding guard replaced
  the whole answer with a safe fallback. The guard works on every channel, not only in the dashboard.
- `NaN` names from pandas printed as "nan" in the chat list (`NaN` is truthy, so `x or default` fails).

## Try it

```bash
python -m kotler.channels.telegram poll        # Telegram, no public URL needed
uvicorn kotler.server:app --port 8000          # website chat: open http://localhost:8000
```

Hosting for free: see [deploy.md](deploy.md).

## What you learned

Adapters and a shared core, webhooks vs polling, fast acknowledgement + background work, idempotency, request
authentication (shared secret, HMAC), output escaping, rate limiting, consent, and platform rules like
WhatsApp's 24-hour window.
