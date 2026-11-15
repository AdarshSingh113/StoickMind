import json
import re

import streamlit as st

from kotler import config, db
from kotler.agent import studio as S
from kotler.agent.runtime import Agent
from kotler.llm import get_llm
from views.ui import PAGES, badge, card, esc, page_header

SUGGESTIONS = {
    "kavya": ["Moisturizer for dry skin under ₹500",
              "oily skin hai aur pimples bhi aate hai, 600 ke andar kya lu?",
              "Build me a morning routine for combination skin under ₹1500",
              "Niacinamide serum vs Vitamin C serum for dark spots?"],
    "skin-quiz": ["Start my skin quiz", "Mujhe apni skin ke liye routine chahiye",
                  "I don't know my skin type, can you help?", "Quiz skip karo, bas routine batao"],
}
DEFAULT_SUGGESTIONS = ["Hi! What can you help me with?", "Suggest something for oily skin"]


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
    page_header("Shop Assistant", "What customers see: the live agents from the Agent Studio, "
                "answering from the real catalogue in English and Hinglish.", "AI agents")

    live = [a for a in S.list_agents() if a.status == "live"]
    if not live:
        st.warning("No live agents. Publish one in the Agent Studio.")
        return
    llm = get_llm()
    online = llm is not None
    by_slug = {a.slug: a for a in live}
    chosen = st.session_state.get("shop_agent_slug")
    if chosen not in by_slug:
        chosen = "kavya" if "kavya" in by_slug else live[0].slug

    with card("agent"):
        a, b = st.columns([3, 2], vertical_alignment="center", gap="medium")
        cfg = by_slug[chosen]
        status = '<span class="k-online"></span>Online' if online else \
            '<span class="k-online" style="background:#F43F5E"></span>Offline: no API key'
        a.markdown(f"""<div class="k-agent"><div class="k-agent-avatar">{esc(cfg.name[:1])}</div><div>
            <div class="k-section">{esc(cfg.name)} · {esc(cfg.role)}</div>
            <div class="k-section-sub" style="font-size:.84rem">{status} &nbsp;·&nbsp;
            {badge(f"v{cfg.version}", "indigo")} {badge(f"{len(cfg.tools)} tools", "indigo")}
            {badge("English + Hinglish", "teal")} {badge(config.LLM_MODEL, "neutral")}</div></div></div>""",
                   unsafe_allow_html=True)
        if online:
            c0, c1, c2 = b.columns([2, 3, 1.4], vertical_alignment="bottom")
            new = c0.selectbox("Agent", list(by_slug), index=list(by_slug).index(chosen),
                               format_func=lambda s_: by_slug[s_].name, on_change=_reset)
            if new != chosen:
                st.session_state["shop_agent_slug"] = new
                _reset()
                st.rerun()
            customers = _customers()
            labels = {None: "Guest (not logged in)"} | {
                int(r.id): f"{r.name} · {r.city} · {r.skin_type} skin" for r in customers.itertuples()}
            customer_id = c1.selectbox("Chat as", list(labels), format_func=labels.get, on_change=_reset,
                                       help="Logged-in customers get personalised answers from their profile.")
            c2.button("New", on_click=_reset, use_container_width=True, icon=":material/edit_square:",
                      help="Start a new conversation")
    if "studio" in PAGES:
        st.page_link(PAGES["studio"], label=f"Edit {cfg.name}'s instructions in the Agent Studio →",
                     icon=":material/tune:")

    if not online:
        st.write("")
        with card("setup", "Connect a free Gemini key to switch the assistant on"):
            st.markdown("1. Get a key at **aistudio.google.com** → *Get API key*.\n"
                        "2. Create `.streamlit/secrets.toml` in the project folder (or, on Streamlit Cloud, "
                        "*Settings → Secrets*) containing:")
            st.code('GEMINI_API_KEY = "your-key-here"', language="toml")
            st.markdown("3. Restart the app. The secrets file is git-ignored, so the key never reaches GitHub.")
        return

    agent: Agent | None = st.session_state.get("shop_agent")
    if agent is None or agent.config.slug != cfg.slug or agent.config.version != cfg.version:
        agent = st.session_state["shop_agent"] = Agent(cfg, llm, customer_id=customer_id)
        st.session_state["shop_turns"] = []
    turns: list = st.session_state["shop_turns"]

    for t in turns:
        show_turn(t)

    prompt = st.chat_input(f"Message {cfg.name}… (English or Hinglish)")
    if not turns and not prompt:
        st.write("")
        st.markdown('<div class="k-section-sub" style="margin-bottom:6px">Try asking</div>', unsafe_allow_html=True)
        cols = st.columns(2)
        for i, s_ in enumerate(SUGGESTIONS.get(cfg.slug, DEFAULT_SUGGESTIONS)):
            if cols[i % 2].button(s_, key=f"sugg{i}", use_container_width=True, icon=":material/chat_bubble:"):
                prompt = s_
    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)
        with st.chat_message("assistant", avatar=":material/auto_awesome:"):
            with st.spinner(f"{cfg.name} is thinking..."):
                turn = agent.reply(prompt)
        turns.append({"user": prompt, "turn": turn})
        st.rerun()

    st.caption(f"Conversation #{agent.conversation_id} · replies use only products returned by tools")


def show_turn(t: dict):
    turn = t["turn"]
    with st.chat_message("user"):
        st.markdown(t["user"])
    with st.chat_message("assistant", avatar=":material/auto_awesome:"):
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
