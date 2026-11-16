# R3 – R6: the complete web app (and a new look)

Every screen from the Streamlit dashboard now exists in the React app, in a warm, bold commerce style, plus a
public landing page. The Python logic is unchanged: each screen calls a thin API that wraps the functions built in
Phases 1–8, so **every guardrail still applies** (discount cap, holdout, template validation, refund limits,
approvals, read-only analytics, tool permissions).

| Route | Screen | API |
|---|---|---|
| `/` | Landing page: hero, 10 module tabs with previews, guardrails, how it works | (static) |
| `/app` | Overview | `GET /api/v1/overview` |
| `/app/inbox` | Live inbox with human takeover | `/api/v1/inbox/*` |
| `/app/customers`, `/app/customers/:id` | Customers + Customer 360 | `/api/v1/customers*` |
| `/app/ask` | Ask your data | `POST /api/v1/ask` |
| `/app/performance` | Agents, traces, cost, evals, ₹ impact | `/api/v1/performance*` |
| `/app/campaigns`, `/new`, `/:id` | Journeys, create (AI A/B), send, measure | `/api/v1/journeys*`, `/api/v1/campaigns*` |
| `/app/helpdesk` | Ticket queue + AI copilot, approvals | `/api/v1/helpdesk*` |
| `/app/studio`, `/app/studio/:slug` | Agent list, editor, versions, playground, judge | `/api/v1/agents*` |

## The design

- **Tokens, not colours.** The whole re-theme was mostly one file (`index.css`): orange `--primary`, near-black
  `--ink`, warm cream background, matching dark mode. Components never name a colour, so they all followed.
- **Type:** Plus Jakarta Sans (free, self-hosted via npm) for headings, Inter for text. Big, extra-bold headlines
  with tight letter spacing carry the "confident commerce brand" look.
- **Shape:** pill buttons, 16-24 px card radius, soft warm shadows; the selected item (sidebar, tabs) is a dark
  pill with an orange icon.
- The landing page borrows the *style* of modern commerce SaaS sites, not their content: the copy describes what
  Kotler actually does, and the previews use our real product names and real numbers from the demo data.

## API design decisions

- **One endpoint per screen** where it helps (Customer 360 returns profile, scores, features, orders, chats,
  tickets and campaigns in one call), small endpoints for actions (send, measure, approve, restore).
- **503 means "no AI key"**, not "broken". Ask, the copilot and the playground need Gemini; without a key the UI
  says how to add one and every other screen keeps working. Campaign messages fall back to validated hand-written
  templates.
- **ML on demand:** the first Customers/Campaigns request trains the models if needed (a few seconds), guarded by
  a lock so two requests don't train twice.

## Bugs found while building

- **"22 Nov ago":** a relative-time helper returned a date after 7 days, and every "… ago" label became nonsense.
  A new `ago()` writes "on 22 Nov 2025" (unit-tested).
- **Trace timeline out of order:** timestamps had one-second resolution, so a tool call could appear after the LLM
  call it triggered. Trace times now have milliseconds.
- **Language badge "Hi"** for Hindi (title-casing the code `hi`).
- Tests found that ML training needs the full-size demo data; small fixtures are fine for everything else.

## Tests

- `tests/test_r3_r6_api.py`: 15 tests. Login on every route; filters/sort/paging; Customer 360 consistency;
  `/ask` returns 503 without a key and blocks phone numbers through the API; the campaign lifecycle and its
  guardrails over HTTP (30% discount, 0% holdout and a typed price are all refused); approvals decide once;
  agent versions and restore; built-ins can't be deleted; playground conversations stay with their agent.
- `frontend/e2e/smoke.mjs`: 38 browser checks across every screen, including creating, sending and measuring a
  campaign, editing and rolling back an agent, and the live inbox.
