"""Kotler AI — Streamlit entry point.

Run:  streamlit run app.py
"""

import os

import streamlit as st

from kotler import config, db
from kotler.seed.generate import generate

st.set_page_config(page_title="Kotler AI", page_icon="static/favicon.svg", layout="wide")

# The .db file is not committed to git. On first run (locally or on Streamlit
# Cloud) we generate the demo dataset so the app always works out of the box.
if not config.DB_PATH.exists():
    with st.spinner("First run: generating demo store data (takes a few seconds)..."):
        generate()
db.ensure_schema()  # adds tables introduced in later phases to an existing database

# Local secrets (.streamlit/secrets.toml, never committed) -> environment variables.
try:
    for key in ("GEMINI_API_KEY", "KOTLER_LLM_MODEL", "KOTLER_LLM_PROVIDER", "KOTLER_LLM_BASE_URL", "TELEGRAM_BOT_TOKEN",
                "WHATSAPP_PHONE_NUMBER_ID", "WHATSAPP_ACCESS_TOKEN", "WHATSAPP_ALLOWED_NUMBERS"):
        if key in st.secrets:
            os.environ.setdefault(key, str(st.secrets[key]))
except Exception:  # no secrets file: fine, the key may come from the environment instead
    pass

from views import (agent_studio, ai_performance, ask_data, campaigns, channels, customers, intelligence, overview, products,  # noqa: E402
                   retention, shop_assistant, support, ui)

ui.inject_css()
ui.PAGES.update({
    "overview": st.Page(overview.render, title="Overview", icon=":material/space_dashboard:", default=True),
    "customers": st.Page(customers.render, title="Customer 360", icon=":material/group:", url_path="customers"),
    "retention": st.Page(retention.render, title="Retention", icon=":material/autorenew:", url_path="retention"),
    "intelligence": st.Page(intelligence.render, title="Customer Intelligence", icon=":material/insights:",
                            url_path="intelligence"),
    "products": st.Page(products.render, title="Products", icon=":material/inventory_2:", url_path="products"),
    "campaigns": st.Page(campaigns.render, title="Campaigns", icon=":material/campaign:", url_path="campaigns"),
    "shop": st.Page(shop_assistant.render, title="Shop Assistant", icon=":material/auto_awesome:", url_path="shop"),
    "channels": st.Page(channels.render, title="Channels", icon=":material/forum:", url_path="channels"),
    "studio": st.Page(agent_studio.render, title="Agent Studio", icon=":material/tune:", url_path="studio"),
    "support": st.Page(support.render, title="Helpdesk", icon=":material/support_agent:", url_path="support"),
    "ask": st.Page(ask_data.render, title="Ask your data", icon=":material/query_stats:", url_path="ask"),
    "performance": st.Page(ai_performance.render, title="AI performance", icon=":material/monitoring:",
                           url_path="performance"),
})
P = ui.PAGES
nav = st.navigation({
    "Business": [P["overview"], P["ask"], P["customers"], P["retention"], P["intelligence"], P["products"]],
    "Marketing": [P["campaigns"]],
    "AI agents": [P["shop"], P["studio"], P["channels"], P["performance"]],
    "Support": [P["support"]],
})

ui.sidebar_brand()
ui.sidebar_footer(f"Store: {config.BRAND_NAME}", "Phase 8 · Evaluation, observability & Ask your data. All 8 phases built.")
nav.run()
