# R1 + R2: the React app, login, Overview and the live Inbox

Streamlit got us far, but it re-runs the whole page on every click and can't push live updates. Customers and
clients judge a product by its screens, so the product's screens are now a real web app: **React + TypeScript**.
All Python logic (agents, ML, campaigns, tracing) is unchanged; the new app talks to it through a JSON API.

```
Browser ── React app (frontend/, built to frontend/dist)
   │  fetch /api/v1/...   (session cookie sent automatically)
   │  EventSource /api/v1/inbox/stream   (live messages)
   ▼
FastAPI (kotler/server.py) ── also serves the built app, the widget, the webhooks
   ▼
SQLite + kotler/* (unchanged)
```

One server serves everything, so the dashboard and the Telegram/WhatsApp webhooks share one database. That fixes
the Phase 7 limitation where the Streamlit dashboard couldn't see chats arriving on the deployed server.

## Run it

```bash
uvicorn kotler.server:app --reload --port 8000     # terminal 1: the API
cd frontend && npm install && npm run dev          # terminal 2: the app with hot reload, http://localhost:5173
```

Password in development: `kotler`. In production set `KOTLER_ADMIN_PASSWORD` (login is disabled until you do).
For a production-like run: `cd frontend && npm run build`, then open http://localhost:8000.

## What we built

| Where | What |
|---|---|
| `kotler/api/auth.py` | Login: one password, signed HttpOnly cookie, rate limits |
| `kotler/api/overview.py` | `GET /api/v1/overview`: everything the Overview screen needs in one call |
| `kotler/api/inbox.py` | Inbox API: list, thread, take over, hand back, reply, live stream, demo data |
| `kotler/channels/core.py` | Human handoff: while a person handles a chat, the AI stays silent |
| `kotler/web/widget.js` | The website widget now receives a person's replies (polls every 4 s while open) |
| `frontend/src/lib/` | API client with types, Indian number formatting, theme, live updates |
| `frontend/src/components/` | Design system: buttons, cards, badges, skeletons, app shell, Ctrl+K palette |
| `frontend/src/pages/` | Login, Overview, Inbox |
| `tests/test_r1_r2_api.py` | 20 API tests · `frontend/src/lib/format.test.ts` 6 unit tests · `frontend/e2e/smoke.mjs` 22 browser checks |
| `Dockerfile` | One image: builds the React app, serves it from Python |

## React in 10 ideas (as used in this code)

1. **Components are functions that return UI.** `KpiCard({ k })` returns the card for one KPI. Data in (props),
   UI out. Reuse = call the function again.
2. **State** (`useState`) is data that, when changed, re-draws the component: the selected period, the reply text.
3. **Effects** (`useEffect`) run code *after* drawing: open the live connection, scroll to the newest message,
   listen for Ctrl+K. They return a cleanup function (close the connection), which React calls when the component
   disappears.
4. **Server state is not UI state.** Data from the API is cached by **TanStack Query** under a key, e.g.
   `["conversation", "telegram", "555"]`. Any component asking for that key shares one request and one copy.
   `invalidateQueries(["inbox"])` says "this is stale" and every screen showing the inbox refetches.
5. **Mutations** (`useMutation`) are actions that change data on the server (take over, send). On success they
   invalidate the right queries, so the screen updates itself.
6. **Routing** (React Router): the URL is the state of navigation. `/inbox/telegram/555` opens that thread, the
   back button works, links can be shared.
7. **TypeScript types** (`lib/api.ts`) describe what the API returns. A typo like `c.custmer_name` fails at build
   time, not in front of a user.
8. **Tailwind** puts styling next to the markup (`rounded-xl border bg-card`). Colours are **design tokens**
   (`bg-card`, `text-muted-foreground`) defined once in `index.css` for light and dark mode.
9. **Code splitting**: `lazy(() => import("@/pages/Overview"))`. Each page is downloaded the first time it opens,
   so the login screen doesn't wait for the chart library (840 KB became ~130 KB + 120 KB on demand).
10. **Never `innerHTML` with user text.** `*bold*` in messages is turned into `<strong>` by building React nodes,
    so a customer can't inject HTML into the operator's screen.

## Security decisions

- **HttpOnly cookie, not a token in localStorage.** JavaScript can't read it, so an XSS bug can't steal it.
- **Signed, not stored:** the cookie is `expiry.HMAC(secret, expiry)`. Changing the password changes the secret
  and logs everyone out. A forged or extended cookie fails the signature check (tested).
- **SameSite=Strict** blocks other sites from making the browser send the cookie (CSRF).
- **Rate limiting:** 5 attempts a minute per address plus 30 globally. `X-Forwarded-For` is only trusted behind
  a known proxy: anyone can type that header, and a test proves spoofing it doesn't bypass the limit.
- **No default password in production** (`RENDER` or `KOTLER_PRODUCTION` set): login is disabled until
  `KOTLER_ADMIN_PASSWORD` exists. A yellow banner shows while the development password is in use.
- **The server is the gatekeeper.** The React app hiding pages is convenience; every API call checks the cookie.
- **Static files:** paths are resolved and must stay inside `frontend/dist` (no `../` escapes, tested).

## The live Inbox: how a message travels

1. A customer writes on Telegram → webhook → `core.handle_incoming` logs it in `channel_events`.
2. If a person has **taken over**, the AI is skipped and the chat is flagged *needs human*.
3. `/api/v1/inbox/stream` (Server-Sent Events) checks for new events every second and pushes them.
4. The browser's `EventSource` receives it → `invalidateQueries` → the list and the open thread refetch → it appears.
   If the operator is elsewhere, a toast offers to open it.
5. The operator replies → `POST /reply` → sent on the customer's channel (Telegram API, WhatsApp API, or stored for
   the website widget, which picks it up on its next poll).

**Why SSE and not WebSockets?** We only push server → browser; sending is a normal POST. SSE is plain HTTP, works
through proxies, and the browser reconnects by itself, resending `Last-Event-ID` so nothing is missed.

**Why does "take over" exist at all?** Without it the AI and the person would both answer the same customer.
The handoff is enforced in `core.py` (server-side), not by hiding a button.

## Bugs the tests and screenshots caught

- A token made with `now=0` was valid: `now or time.time()` treats 0 as "not given". Now `is None`.
- Login rate limit could be bypassed by sending a new `X-Forwarded-For` each try.
- The revenue chart's first day dipped to ₹0: a 30-day window started at 22:05, so day one was 2 hours long.
  Windows are whole days now.
- Its last days also dipped: they showed *delivered* revenue, and recent orders haven't arrived. The chart now shows
  ordered vs delivered, and says why they differ.
- Demo chats said "Hi Priya" while the profile showed a different (real) customer. Names now come from the data.
- Toasts covered the "Hand back to AI" button; old demo messages triggered toasts; "Rto" instead of "RTO";
  the same customer had different avatar colours in two places; "₹4.4 L" wrapped on phones.

## What you learned

Single-page apps vs server-rendered dashboards, components/state/effects, server-state caching and invalidation,
typed API clients, routing, design tokens and dark mode, code splitting, cookie sessions and CSRF, rate limiting
behind proxies, Server-Sent Events, human-in-the-loop handoff, end-to-end testing with a real browser, and
multi-stage Docker builds.
