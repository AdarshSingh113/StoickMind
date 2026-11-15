# ✨ Kotler AI

![tests](https://github.com/AdarshSingh113/kotler-ai/actions/workflows/tests.yml/badge.svg)

**AI commerce, CRM and automation platform for Indian D2C brands, built from scratch for ₹0.**

Kotler AI simulates a D2C skincare brand (*Glow & Co.*) and layers AI on top of it:
agents that sell and support customers in English and Hinglish, ML that predicts
which COD orders will come back undelivered, and dashboards that measure everything in rupees.

> A learning and portfolio project inspired by AI commerce platforms such as BIK.ai.
> Not affiliated with any company.

## Roadmap

| Phase | Module | What it does for the business | Status |
|---|---|---|---|
| 1 | **Database & CRM** | Customers, orders, products, tickets; Customer 360; KPI dashboard; cohort retention | ✅ Done |
| 2 | **AI Shopping Agent** | Product recommendations from natural language, English and Hinglish, grounded in the real catalogue | ✅ Done |
| 3 | **Agent Studio** + Skin Quiz agent | Agents as configuration (instructions, goal, success criteria, tools), versions, playground, LLM-as-judge. 26-case real-model eval | ✅ Done |
| 4 | **AI Helpdesk + Order Management** | Asha: order tracking, cancel-and-save, damaged items, refunds within limits, policy RAG, human approvals and handoff, AI copilot on real tickets | ✅ Done |
| 5 | **Agentic CDP + ML** | RFM, churn, lifetime value, **COD RTO predictor**, plain-English segment builder | ⏳ Next |
| 6 | **Retention + AI Campaigns** | Replenishment, win-back and cross-sell journeys; AI-written messages; A/B tests and uplift in ₹ | |
| 7 | **Real channels** | Telegram bot, WhatsApp test number, embeddable website chat widget | |
| 8 | **Evaluation, observability, "Ask your data"** | Success rates per agent, cost, latency, ₹ saved; chat with your data | |

Optional later: React visual flow builder, Shopify sync, gamification.

## Tech stack (all free)

| Tool | Used for |
|---|---|
| Python 3.11+ | Everything |
| SQLite | Store data (one file, zero setup) |
| Streamlit | Dashboard UI |
| pandas, Altair | Analysis and charts |
| Faker | Street addresses (names come from our own region-aware lists) |
| GitHub Actions | Runs the tests on every push (CI) |
| Gemini API (free tier), native REST API | LLM for the agents (gemini-3.5-flash, with a fallback model) |
| openai (Python SDK) | Optional: any OpenAI-compatible provider (Groq, Ollama, ...) |
| scikit-learn | ML, from Phase 5 |
| ChromaDB | Vector search for RAG, from Phase 3 |

## Quick start

```bash
git clone https://github.com/AdarshSingh113/kotler-ai.git
cd kotler-ai
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python -m kotler.seed.generate     # creates data/kotler.db (1,500 customers, ~3,700 orders)
streamlit run app.py               # opens http://localhost:8501
pytest                             # 136 tests (also run automatically on GitHub)
```

The app generates the database by itself on first run, so `streamlit run app.py` alone also works.

### AI features (free Gemini key)

Get a key at [aistudio.google.com](https://aistudio.google.com), then create `.streamlit/secrets.toml`:

```toml
GEMINI_API_KEY = "your-key"
```

It's git-ignored, so the key never reaches GitHub. Run the agent evaluation with
`GEMINI_API_KEY=your-key python -m kotler.evals.shopping`.

## Project structure

```
kotler/
  schema.sql          tables: pincodes, products, customers, orders, order_items, support_tickets
  db.py               connection helpers (plain SQL, no ORM)
  crm.py              business metrics and lookups
  policy.py           store policies: limits enforced in code + the text the AI retrieves
  llm.py              LLM interface: Gemini / any OpenAI-compatible API, plus a fake for tests
  agent/              Agent Studio, generic runtime, tools (shopping + support), policy retrieval, judge, copilot
  evals/              real-model evaluations: shopping/quiz agents and the helpdesk agent (checks DB outcomes)
  config.py           settings from environment variables
  seed/
    catalog.py        36 products, 28 cities, regional Indian names, ticket templates (English + Hinglish)
    generate.py       realistic data generator with planted patterns
views/                Streamlit pages: overview, customers, retention, products, shop assistant, agent studio, helpdesk
app.py                Streamlit entry point
tests/                data-integrity and pattern tests
.github/workflows/    CI: runs pytest on Python 3.11 and 3.13
docs/                 learning notes for each phase
```

## Learning notes

Each phase has a write-up explaining *what*, *why* and *how*:

- [Phase 1: Database & CRM](docs/phase-1-database-and-crm.md)
- [Phase 2: AI Shopping Agent](docs/phase-2-shopping-agent.md)
- [Phase 3: Agent Studio](docs/phase-3-agent-studio.md)
- [Phase 4: AI Helpdesk & Order Management](docs/phase-4-helpdesk.md)

## Design

The app uses a custom design system on top of Streamlit: theme in `.streamlit/config.toml`
(indigo palette, self-hosted Inter font in `static/fonts`), and shared components in `views/ui.py`
(KPI strips, cards, badges, insight cards, status colours, one chart style). Every page uses them,
so the whole product looks consistent.
