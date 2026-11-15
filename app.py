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
    for key in ("GEMINI_API_KEY", "KOTLER_LLM_MODEL", "KOTLER_LLM_PROVIDER", "KOTLER_LLM_BASE_URL"):
        if key in st.secrets:
            os.environ.setdefault(key, str(st.secrets[key]))
except Exception:  # no secrets file: fine, the key may come from the environment instead
    pass

from views import agent_studio, customers, overview, products, retention, shop_assistant, support, ui  # noqa: E402

ui.inject_css()
ui.PAGES.update({
    "overview": st.Page(overview.render, title="Overview", icon=":material/space_dashboard:", default=True),
    "customers": st.Page(customers.render, title="Customer 360", icon=":material/group:", url_path="customers"),
    "retention": st.Page(retention.render, title="Retention", icon=":material/autorenew:", url_path="retention"),
    "products": st.Page(products.render, title="Products", icon=":material/inventory_2:", url_path="products"),
    "shop": st.Page(shop_assistant.render, title="Shop Assistant", icon=":material/auto_awesome:", url_path="shop"),
    "studio": st.Page(agent_studio.render, title="Agent Studio", icon=":material/tune:", url_path="studio"),
    "support": st.Page(support.render, title="Helpdesk", icon=":material/support_agent:", url_path="support"),
})
P = ui.PAGES
nav = st.navigation({
    "Business": [P["overview"], P["customers"], P["retention"], P["products"]],
    "AI agents": [P["shop"], P["studio"]],
    "Support": [P["support"]],
})

ui.sidebar_brand()
ui.sidebar_footer(f"Store: {config.BRAND_NAME}", "Phase 4 · AI Helpdesk & Order Management. Next: customer data platform & ML.")
nav.run()
