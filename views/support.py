import json

import altair as alt
import pandas as pd
import streamlit as st

from kotler import crm, db
from kotler.agent.copilot import ai_stats, recent_runs, run_ticket
from kotler.agent.support_tools import decide_action, pending_actions
from kotler.llm import get_llm
from views.shop_assistant import show_turn
from views.ui import PALETTE, badge, card, esc, kpi_strip, page_header, show, status_styler

ACTION_LABEL = {"refund": "Refund", "replacement": "Replacement", "escalation": "Human handoff",
                "cancel": "Cancellation", "coupon": "Coupon"}


def render():
    page_header("Support", "Every customer question and complaint, handled by Asha (AI) first, "
                "with humans for approvals and hand-offs.", "Helpdesk")
    s = crm.support_summary()
    ai = ai_stats()
    pending = pending_actions()
    cats = crm.ticket_categories()
    status_share = cats.loc[cats.category == "order_status", "tickets"].sum() / max(cats.tickets.sum(), 1)

    kpi_strip([
        {"label": "Open tickets", "value": f"{s['open']}",
         "delta_html": badge(f"{s['escalated']} escalated", "bad" if s["escalated"] else "neutral")},
        {"label": "Human avg resolution", "value": f"{s['avg_hours']:.1f} h", "sub": "before AI"},
        {"label": "AI resolution rate", "value": f"{ai['resolved_rate']:.0%}" if ai["runs"] else "–",
         "delta_html": badge(f"{ai['runs']} AI runs", "indigo"), "sub": "no human needed",
         "help": "Share of tickets Asha handled without escalating to a human."},
        {"label": "AI reply time", "value": f"{ai['latency_ms'] / 1000:.0f} s" if ai["runs"] else "–",
         "sub": f"vs {s['avg_hours']:.0f} h for humans"},
        {"label": "Waiting for approval", "value": f"{len(pending)}",
         "delta_html": badge("needs a human", "amber" if len(pending) else "neutral")},
    ])
    _ = status_share
    st.write("")
    inbox, copilot, approvals = st.tabs(["Inbox", "AI copilot", f"Approvals ({len(pending)})"])
    with inbox:
        _inbox(cats)
    with copilot:
        _copilot()
    with approvals:
        _approvals(pending)


# ------------------------------------------------------------------ inbox
def _inbox(cats):
    all_tickets = crm.tickets()
    left, right = st.columns([5, 2], gap="medium")
    with left, card("tickets", "Ticket inbox"):
        f1, f2 = st.columns([3, 2])
        q = f1.text_input("Search", placeholder="Search message, customer or order…", label_visibility="collapsed")
        status = f2.segmented_control("Status", ["open", "escalated", "resolved"], label_visibility="collapsed",
                                      format_func=str.capitalize)
        df = all_tickets
        if status:
            df = df[df.status == status]
        if q:
            ql = q.lower()
            df = df[df.message.str.lower().str.contains(ql, regex=False) | df.customer.str.lower().str.contains(ql, regex=False)
                    | df.order_number.fillna("").str.lower().str.contains(ql, regex=False)]
        df = df.assign(channel=df.channel.str.replace("_", " ").str.capitalize(),
                       created=pd.to_datetime(df.created_at).dt.strftime("%d %b, %H:%M"),
                       priority=df.priority.str.capitalize(), status=df.status.str.capitalize(),
                       by=df.resolved_by.fillna("").str.upper().replace({"AI": "AI ✦", "HUMAN": "Human"}))
        st.dataframe(df.style.map(status_styler, subset=["priority", "status"]), hide_index=True,
                     use_container_width=True, height=470,
                     column_order=["created", "customer", "message", "priority", "status", "by", "channel"],
                     column_config={"created": "Created", "customer": "Customer",
                                    "message": st.column_config.TextColumn("Message", width="medium"),
                                    "priority": "Priority", "status": "Status", "by": "Resolved by",
                                    "channel": "Channel"})
        st.caption(f"{len(df):,} tickets")
    with right, card("bycat", "By category"):
        c = cats.assign(label=cats.category.str.replace("_", " ").str.capitalize())
        bars = alt.Chart(c).mark_bar(cornerRadiusTopRight=5, cornerRadiusBottomRight=5, size=16,
                                     color=PALETTE["teal"]).encode(
            x=alt.X("tickets:Q", title=None, axis=alt.Axis(tickCount=3)),
            y=alt.Y("label:N", sort="-x", title=None, axis=alt.Axis(labelLimit=130)),
            tooltip=[alt.Tooltip("label:N", title="Category"), "tickets:Q"])
        show(bars, height=250)
        ch = all_tickets.channel.value_counts().rename_axis("channel").reset_index(name="tickets")
        ch["channel"] = ch.channel.str.replace("_", " ").str.capitalize()
        st.markdown('<div class="k-section" style="margin-top:6px">By channel</div>', unsafe_allow_html=True)
        donut = alt.Chart(ch).mark_arc(innerRadius=52, cornerRadius=4, padAngle=0.02).encode(
            theta="tickets:Q",
            color=alt.Color("channel:N", scale=alt.Scale(range=[PALETTE["indigo"], PALETTE["teal"], PALETTE["amber"]])),
            tooltip=["channel:N", "tickets:Q"])
        show(donut, height=200)


# ---------------------------------------------------------------- copilot
@st.cache_data(ttl=60)
def _candidates():
    return db.query_df("""SELECT t.id, t.status, t.category, t.message, c.name AS customer, t.created_at
                          FROM support_tickets t JOIN customers c ON c.id = t.customer_id
                          WHERE t.category != 'escalated_by_ai'
                          ORDER BY (t.status = 'open') DESC, t.created_at DESC LIMIT 80""")


def _copilot():
    llm = get_llm()
    left, right = st.columns([3, 2], gap="medium")
    with left, card("copilot", "Let Asha handle a ticket",
                    "Open tickets are really resolved or escalated. Closed ones are replayed to measure what AI would do."):
        if llm is None:
            st.info("Add a Gemini API key to run the AI copilot (see the Shop Assistant page).")
            return
        tickets = _candidates()
        labels = {int(r.id): f"#{r.id} · {r.status.upper()} · {r.category.replace('_', ' ')} · {r.customer} · "
                             f"{r.message[:60]}" for r in tickets.itertuples()}
        tid = st.selectbox("Ticket", list(labels), format_func=labels.get, label_visibility="collapsed")
        row = tickets[tickets.id == tid].iloc[0]
        st.markdown(f"""<div style="background:#F8F9FC;border:1px solid #E6E8F0;border-radius:12px;padding:10px 14px">
            <span class="k-section-sub">{esc(row.customer)} · {esc(row.created_at)} ·
            {esc(row.category.replace('_', ' '))}</span><div style="margin-top:4px">“{esc(row.message)}”</div></div>""",
                    unsafe_allow_html=True)
        b1, b2 = st.columns(2)
        go = b1.button("Let Asha handle it", type="primary", icon=":material/auto_awesome:", use_container_width=True)
        batch = b2.button("Run on 3 open tickets", icon=":material/bolt:", use_container_width=True,
                          help="Asha handles the 3 oldest open tickets in a row.")
        if go:
            with st.spinner("Asha is working on the ticket…"):
                turn, outcome, agent = run_ticket(llm, tid)
            st.session_state["copilot_last"] = {"user": row.message, "turn": turn, "outcome": outcome}
            _candidates.clear()
            st.rerun()
        if batch:
            open_ids = db.query_df("SELECT id FROM support_tickets WHERE status = 'open' AND category != 'escalated_by_ai' "
                                   "ORDER BY created_at LIMIT 3").id.tolist()
            if not open_ids:
                st.info("No open tickets left: Asha has cleared the inbox.")
            bar = st.progress(0.0)
            for i, t in enumerate(open_ids, 1):
                run_ticket(llm, int(t))
                bar.progress(i / len(open_ids), f"Ticket {i}/{len(open_ids)} done")
            _candidates.clear()
            st.rerun()
        last = st.session_state.get("copilot_last")
        if last:
            tone = {"resolved": "good", "escalated": "amber", "error": "bad"}[last["outcome"]]
            st.markdown(badge({"resolved": "Resolved by AI", "escalated": "Handed to a human",
                               "error": "AI error: stays with humans"}[last["outcome"]], tone), unsafe_allow_html=True)
            show_turn(last)
    with right, card("airuns", "AI copilot history"):
        runs = recent_runs()
        if runs.empty:
            st.caption("No AI runs yet.")
        else:
            runs["outcome"] = runs.outcome.str.capitalize()
            runs["latency"] = (runs.latency_ms / 1000).round(1)
            st.dataframe(runs.style.map(status_styler, subset=["outcome"]), hide_index=True, use_container_width=True,
                         height=520, column_order=["ticket_id", "outcome", "actions", "latency", "message"],
                         column_config={"ticket_id": "Ticket", "message": st.column_config.TextColumn("Message"),
                                        "outcome": "Outcome", "actions": "Actions",
                                        "latency": st.column_config.NumberColumn("Time", format="%.1f s")})


# -------------------------------------------------------------- approvals
def _approvals(pending):
    st.caption("Actions above the AI's limits wait here: refunds over ₹1,000 or for cash on delivery orders, "
               "replacements on high-value orders, and every human handoff.")
    if pending.empty:
        with card("noapprovals"):
            st.markdown("**All clear.** Nothing is waiting for a human.")
        return
    for r in pending.itertuples():
        details = json.loads(r.details or "{}")
        with st.container(key=f"card-approval-{r.id}"):
            a, b = st.columns([4, 1], vertical_alignment="center")
            amount = f" · ₹{r.amount:,.0f}" if pd.notna(r.amount) and r.amount else ""  # escalations have no amount
            what = details.get("product") or details.get("priority", "")
            a.markdown(f"""{badge(ACTION_LABEL.get(r.action, r.action), "amber")} <b>{esc(r.customer or "Guest")}</b>
                <span class="k-section-sub">· {esc(r.order_number or "no order")}{amount} · {esc(what)} · by
                {esc(r.agent_slug or "agent")} · {esc(r.created_at)}</span>
                <div style="margin-top:6px;color:#334155">{esc(r.reason or "")}</div>""", unsafe_allow_html=True)
            approve_label = "Resolve" if r.action == "escalation" else "Approve"
            if b.button(approve_label, key=f"ok-{r.id}", type="primary", use_container_width=True):
                decide_action(int(r.id), True)
                st.rerun()
            if r.action != "escalation" and b.button("Reject", key=f"no-{r.id}", use_container_width=True):
                decide_action(int(r.id), False)
                st.rerun()
