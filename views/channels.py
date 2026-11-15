import os
import re

import pandas as pd
import streamlit as st

from kotler import db
from kotler.channels import core, outbound
from kotler.llm import get_llm
from kotler.marketing import campaigns as C
from views.ui import badge, card, esc, kpi_strip, page_header

CH_LABEL = {"telegram": "Telegram", "whatsapp": "WhatsApp", "web": "Website chat"}


def _v(x, default: str = "") -> str:
    """pandas missing values are NaN, and NaN is truthy: `x or default` would print "nan"."""
    return default if x is None or (isinstance(x, float) and pd.isna(x)) else str(x)


def _status(ok: bool, yes: str = "Configured", no: str = "Not set up") -> str:
    return badge(yes if ok else no, "good" if ok else "neutral")


def render():
    page_header("Channels", "Where customers reach the agents: Telegram, WhatsApp and your website.", "Channels")
    core.ensure_tables()
    chats = outbound.connected_chats()
    today = db.query_one("SELECT COUNT(*) AS n FROM channel_events WHERE date(created_at) = date('now', 'localtime')")["n"]
    kpi_strip([
        {"label": "Connected chats", "value": f"{len(chats)}", "sub": " · ".join(
            f"{CH_LABEL[c]} {n}" for c, n in chats.channel.value_counts().items()) or "none yet"},
        {"label": "Linked to customers", "value": f"{int(chats.customer_id.notna().sum())}", "sub": "verified or by phone"},
        {"label": "Messages today", "value": f"{today}"},
        {"label": "Opted out of marketing", "value": f"{int((chats.marketing_opt_in == 0).sum())}", "sub": "sent STOP"},
    ])
    st.write("")
    t1, t2, t3 = st.tabs(["Setup", "Conversations", "Send"])
    with t1:
        _setup()
    with t2:
        _conversations(chats)
    with t3:
        _send(chats)


def _setup():
    tg, wa = bool(os.environ.get("TELEGRAM_BOT_TOKEN")), bool(os.environ.get("WHATSAPP_ACCESS_TOKEN"))
    a, b, c = st.columns(3, gap="medium")
    with a, card("ch-tg", "Telegram", "Free, 2-minute setup"):
        st.markdown(_status(tg) + " " + _status(bool(get_llm()), "AI key set", "No AI key"), unsafe_allow_html=True)
        st.markdown("1. In Telegram, message **@BotFather** → `/newbot` → copy the token.\n"
                    "2. Add `TELEGRAM_BOT_TOKEN` to your secrets (never to git).\n"
                    "3. Easiest: run `python -m kotler.channels.telegram poll` on any machine (no public URL needed).\n"
                    "4. Or deploy the API server and run `… set-webhook https://YOUR-APP/webhooks/telegram`.")
    with b, card("ch-wa", "WhatsApp", "Meta Cloud API, free test number"):
        st.markdown(_status(wa), unsafe_allow_html=True)
        st.markdown("1. developers.facebook.com → create a Business app → add **WhatsApp**.\n"
                    "2. Add up to 5 of your own numbers as recipients.\n"
                    "3. Set `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_APP_SECRET`, "
                    "`WHATSAPP_VERIFY_TOKEN`, `WHATSAPP_ALLOWED_NUMBERS`.\n"
                    "4. Webhook URL: `https://YOUR-APP/webhooks/whatsapp`, subscribe to *messages*.")
    with c, card("ch-web", "Website chat", "Any website, one line"):
        st.markdown(_status(True, "Ready", ""), unsafe_allow_html=True)
        st.markdown("Run or deploy the API server, then add to any page:")
        st.code('<script src="https://YOUR-APP/widget.js" defer></script>', language="html")
        st.markdown("A demo store with the widget is served at `https://YOUR-APP/`.")
    st.caption("The dashboard (Streamlit) and the API server must share one database to see the same conversations. "
               "See docs/deploy.md for setups that do.")


def _conversations(chats):
    if chats.empty:
        st.info("No conversations yet. Message your Telegram bot, or open the demo store's chat widget.")
        return
    left, right = st.columns([2, 3], gap="medium")
    with left, card("ch-list", "Chats"):
        labels = {i: f"{CH_LABEL[r.channel]} · {_v(r.display_name, r.external_id[:10])} · "
                     f"{_v(r.customer, 'guest')} · {r.messages} msgs" for i, r in chats.iterrows()}
        idx = st.radio("Chat", list(labels), format_func=labels.get, label_visibility="collapsed")
    row = chats.loc[idx]
    with right, card("ch-thread", f"{CH_LABEL[row.channel]} · {_v(row.display_name, row.external_id)}",
                     f"Customer: {_v(row.customer, 'guest (not verified)')} · agent: {_v(row.agent_slug, '–')} · "
                     f"marketing: {'on' if row.marketing_opt_in else 'opted out'}"):
        for m in outbound.thread(row.channel, row.external_id).itertuples():
            mine = m.direction == "in"
            st.markdown(f"""<div style="display:flex;justify-content:{'flex-end' if mine else 'flex-start'}">
                <div style="max-width:80%;margin:4px 0;padding:8px 12px;border-radius:12px;white-space:pre-wrap;font-size:.9rem;
                background:{'#EEF2FF' if mine else '#fff'};border:1px solid #E6E8F0">{re.sub(r"\*([^*\n]+)\*", r"<b>\1</b>", esc(m.text))}
                <div style="color:#94A3B8;font-size:.72rem;margin-top:4px">{esc(m.created_at)}
                {'' if mine else ' · ' + esc(_v(m.agent_slug))}</div></div></div>""", unsafe_allow_html=True)


def _send(chats):
    real = chats[chats.channel.isin(["telegram", "whatsapp"])]
    if real.empty:
        st.info("Connect Telegram or WhatsApp first: send your bot a message, then come back.")
        return
    labels = {i: f"{CH_LABEL[r.channel]} · {_v(r.display_name, r.external_id)}" for i, r in real.iterrows()}
    a, b = st.columns(2, gap="medium")
    with a, card("ch-link", "Demo: link your chat to a customer", "So campaign messages for that customer reach you"):
        i = st.selectbox("Your chat", list(labels), format_func=labels.get, key="link-chat")
        cust = st.number_input("Customer ID", min_value=1, step=1, value=1)
        if st.button("Link", icon=":material/link:"):
            outbound.link_chat_to_customer(real.loc[i].channel, real.loc[i].external_id, int(cust))
            st.success(f"Linked to customer #{int(cust)}. Chats now treat you as them (orders, profile).")
    with b, card("ch-camp", "Deliver a campaign on a real channel", "Only to linked, opted-in chats"):
        camps = C.list_campaigns()
        camps = camps[camps.status != "draft"]
        if camps.empty:
            st.caption("No campaigns yet (Campaigns page).")
            return
        cl = {int(r.id): f"#{r.id} · {r.name}" for r in camps.itertuples()}
        cid = st.selectbox("Campaign", list(cl), format_func=cl.get)
        ch = st.selectbox("Channel", ["telegram", "whatsapp"], format_func=CH_LABEL.get)
        if st.button("Deliver", type="primary", icon=":material/send:"):
            res = outbound.deliver_campaign(cid, ch)
            st.write(res)
