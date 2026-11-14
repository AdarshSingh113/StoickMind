import json
import re

import streamlit as st

from kotler import config, db
from kotler.agent.shopping import ShoppingAgent
from kotler.llm import get_llm

SUGGESTIONS = [
    "Moisturizer for dry skin under ₹500",
    "oily skin hai aur pimples bhi aate hai, 600 ke andar kya lu?",
    "Build me a morning routine for combination skin under ₹1500",
    "Niacinamide serum vs Vitamin C serum for dark spots?",
]


@st.cache_data(ttl=600)
def _customers():
    return db.query_df("""
        SELECT c.id, c.name, c.city, c.skin_type, c.preferred_language, COUNT(o.id) AS orders
        FROM customers c JOIN orders o ON o.customer_id = c.id
        GROUP BY c.id ORDER BY orders DESC, c.id LIMIT 60""")


def whatsapp_to_markdown(text: str) -> str:
    """The agent writes WhatsApp formatting (*bold*, plain line breaks) because the same
    reply will go to WhatsApp in Phase 5. Convert it for the web: one message, rendered per channel."""
    text = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])", r"**\1**", text)
    # A blank line after a list ends it (otherwise Markdown glues the next sentence onto the last item).
    text = re.sub(r"(^\s*\d+\.[^\n]*)\n(?!\s*\d+\.)(?=\S)", r"\1\n\n", text, flags=re.M)
    return text.replace("\n", "  \n")


def _reset():
    st.session_state.pop("shop_agent", None)
    st.session_state["shop_turns"] = []


def render():
    st.title("AI Shop Assistant")
    st.caption("Chat as a customer would. The agent searches the real catalogue through tools. "
               "Open **Tools used** under a reply to see exactly what it did.")

    llm = get_llm()
    if llm is None:
        st.warning("No AI key configured, so the assistant is offline.", icon=":material/key_off:")
        st.markdown("Get a free key at **aistudio.google.com**, then create `.streamlit/secrets.toml` "
                    "in the project folder containing:")
        st.code('GEMINI_API_KEY = "your-key-here"', language="toml")
        st.markdown("Restart the app. This file is in `.gitignore`, so the key never goes to GitHub.")
        return

    customers = _customers()
    labels = {None: "Guest (not logged in)"} | {
        int(r.id): f"{r.name} · {r.city} · {r.skin_type} skin · {r.preferred_language}" for r in customers.itertuples()}
    left, right = st.columns([3, 1])
    customer_id = left.selectbox("Chat as", list(labels), format_func=labels.get, on_change=_reset,
                                 help="Logged-in customers get personalised answers from their profile and history.")
    right.button("New chat", on_click=_reset, use_container_width=True, icon=":material/refresh:")

    if "shop_agent" not in st.session_state:
        st.session_state["shop_agent"] = ShoppingAgent(llm, customer_id=customer_id)
        st.session_state["shop_turns"] = []
    agent: ShoppingAgent = st.session_state["shop_agent"]
    turns: list = st.session_state["shop_turns"]

    for t in turns:
        _show_turn(t)

    prompt = st.chat_input("Ask about products, routines, ingredients... (English or Hinglish)")
    if not turns and not prompt:
        st.markdown("**Try one of these:**")
        cols = st.columns(2)
        for i, s in enumerate(SUGGESTIONS):
            if cols[i % 2].button(s, key=f"sugg{i}", use_container_width=True):
                prompt = s
    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant", avatar=":material/spa:"):
            with st.spinner("Kavya is looking through the catalogue..."):
                turn = agent.reply(prompt)
        turns.append({"user": prompt, "turn": turn})
        st.rerun()

    st.caption(f"Model: `{config.LLM_MODEL}` · conversation #{agent.conversation_id}")


def _show_turn(t: dict):
    turn = t["turn"]
    with st.chat_message("user"):
        st.markdown(t["user"])
    with st.chat_message("assistant", avatar=":material/spa:"):
        if turn.error:
            st.error(turn.reply)
        else:
            st.markdown(whatsapp_to_markdown(turn.reply))
        meta = f"{turn.latency_ms / 1000:.1f}s · {turn.llm_calls} LLM call(s) · " \
               f"{turn.prompt_tokens + turn.completion_tokens:,} tokens"
        with st.expander(f"Tools used: {len(turn.tools)} · {meta}"):
            if turn.error:
                st.code(turn.error)
            if not turn.tools:
                st.write("No tools called.")
            for tool in turn.tools:
                st.markdown(f"**{tool.name}**(`{json.dumps(tool.arguments, ensure_ascii=False)}`)")
                st.json(tool.result, expanded=False)
