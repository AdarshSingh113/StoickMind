"""Kotler AI — Streamlit entry point.

Run:  streamlit run app.py
"""

import os

import streamlit as st

from kotler import config, db
from kotler.seed.generate import generate

st.set_page_config(page_title="Kotler AI", page_icon="✨", layout="wide")

# The .db file is not committed to git. On first run (locally or on Streamlit
# Cloud) we generate the demo dataset so the app always works out of the box.
if not config.DB_PATH.exists():
    with st.spinner("First run: generating demo store data (takes a few seconds)..."):
        generate()
db.ensure_schema()  # adds tables introduced in later phases to an existing database

# Local secrets (.streamlit/secrets.toml, never committed) -> environment variables.
try:
    for key in ("GEMINI_API_KEY", "KOTLER_LLM_MODEL", "KOTLER_LLM_BASE_URL"):
        if key in st.secrets:
            os.environ.setdefault(key, str(st.secrets[key]))
except Exception:  # no secrets file: fine, the key may come from the environment instead
    pass

from views import customers, overview, products, retention, shop_assistant, support  # noqa: E402  (needs DB first)

pages = {
    "Business": [
        st.Page(overview.render, title="Overview", icon=":material/monitoring:", default=True),
        st.Page(customers.render, title="Customer 360", icon=":material/group:", url_path="customers"),
        st.Page(retention.render, title="Retention", icon=":material/autorenew:", url_path="retention"),
        st.Page(products.render, title="Products", icon=":material/inventory_2:", url_path="products"),
    ],
    "AI agents": [
        st.Page(shop_assistant.render, title="Shop Assistant", icon=":material/spa:", url_path="shop"),
    ],
    "Support": [
        st.Page(support.render, title="Support tickets", icon=":material/support_agent:", url_path="support"),
    ],
}

with st.sidebar:
    st.markdown(f"### ✨ Kotler AI\nAI commerce platform for **{config.BRAND_NAME}**")
    st.caption("Phase 2 · AI Shopping Agent")

st.navigation(pages).run()
