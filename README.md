# ✨ Kotler AI

**AI commerce, CRM and automation platform for Indian D2C brands, built from scratch for ₹0.**

Kotler AI simulates a D2C skincare brand (*Glow & Co.*) and layers AI on top of it:
agents that sell and support customers in English and Hinglish, ML that predicts
which COD orders will come back undelivered, and dashboards that measure everything in rupees.

> A learning and portfolio project inspired by AI commerce platforms such as BIK.ai.
> Not affiliated with any company.

## Roadmap

| Phase | Module | What it does for the business | Status |
|---|---|---|---|
| 1 | **Database & CRM** | Customers, orders, products, tickets; Customer 360; KPI dashboard | ✅ Done |
| 2 | **AI Shopping Agent** | Recommends products from natural language ("moisturizer for dry skin under ₹500"), English and Hinglish | ⏳ Next |
| 3 | **Support Agent + guardrails** | Tracks orders, handles complaints, RAG over policies, discount and refund limits, hands off to a human when unsure | |
| 4 | **COD RTO risk predictor** | Scores every COD order before shipping and triggers confirmation or a prepaid nudge for risky ones | |
| 5 | **WhatsApp / Telegram channel** | Customers talk to the agents on the apps they actually use | |
| 6 | **AI evaluation & observability** | Test sets, LLM-as-judge, latency, tokens, % tickets resolved by AI, ₹ saved | |

Later: RFM segmentation, marketing automation, Agent Studio, demand forecasting, review insights, Shopify sync.

## Tech stack (all free)

| Tool | Used for |
|---|---|
| Python 3.11+ | Everything |
| SQLite | Store data (one file, zero setup) |
| Streamlit | Dashboard UI |
| pandas, Altair | Analysis and charts |
| Faker | Realistic Indian names and addresses |
| Gemini API (free tier) / Ollama (local) | LLMs, from Phase 2 |
| scikit-learn | ML, from Phase 4 |
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
pytest                             # 7 tests
```

The app generates the database by itself on first run, so `streamlit run app.py` alone also works.

## Project structure

```
kotler/
  schema.sql          tables: pincodes, products, customers, orders, order_items, support_tickets
  db.py               connection helpers (plain SQL, no ORM)
  crm.py              business metrics and lookups (later reused as AI-agent tools)
  config.py           settings from environment variables
  seed/
    catalog.py        36 hand-written products, 28 cities, ticket templates (English + Hinglish)
    generate.py       realistic data generator with planted patterns
views/                Streamlit pages: overview, customers, products, support
app.py                Streamlit entry point
tests/                data-integrity and pattern tests
docs/                 learning notes for each phase
```

## Learning notes

Each phase has a write-up explaining *what*, *why* and *how*:

- [Phase 1: Database & CRM](docs/phase-1-database-and-crm.md)
