import altair as alt
import pandas as pd
import streamlit as st

from kotler import crm
from views.ui import PALETTE, badge, card, kpi_strip, page_header, show, status_styler


def render():
    page_header("Support tickets", "Every customer question and complaint, across WhatsApp, email and website chat.",
                "Support")
    s = crm.support_summary()
    all_tickets = crm.tickets()
    cats = crm.ticket_categories()
    status_share = cats.loc[cats.category == "order_status", "tickets"].sum() / max(cats.tickets.sum(), 1)

    kpi_strip([
        {"label": "Total tickets", "value": f"{s['total']:,}", "sub": "all time"},
        {"label": "Open", "value": f"{s['open']}",
         "delta_html": badge(f"{s['escalated']} escalated", "bad" if s["escalated"] else "neutral")},
        {"label": "Avg time to resolve", "value": f"{s['avg_hours']:.1f} h", "sub": "human agents"},
        {"label": "Resolved by AI", "value": f"{s['ai_share']:.0%}", "delta_html": badge("baseline", "neutral"),
         "sub": "Phase 3 target: 60%+", "help": "The Phase 3 support agent must beat this baseline."},
        {"label": "'Where is my order?'", "value": f"{status_share:.0%}", "sub": "of all tickets: automatable"},
    ])
    st.write("")

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
        df = df.assign(category=df.category.str.replace("_", " ").str.capitalize(),
                       channel=df.channel.str.replace("_", " ").str.capitalize(),
                       created=pd.to_datetime(df.created_at).dt.strftime("%d %b, %H:%M"),
                       priority=df.priority.str.capitalize(), status=df.status.str.capitalize())
        st.dataframe(df.style.map(status_styler, subset=["priority", "status"]), hide_index=True,
                     use_container_width=True, height=470,
                     column_order=["created", "customer", "message", "priority", "status", "channel"],
                     column_config={
                         "created": "Created", "customer": "Customer",
                         "message": st.column_config.TextColumn("Message", width="medium"),
                         "category": "Category", "priority": "Priority", "status": "Status", "channel": "Channel",
                         "order_number": "Order",
                         "hours_to_resolve": st.column_config.NumberColumn("Resolved in", format="%.1f h"),
                     })
        st.caption(f"{len(df):,} tickets")
    with right, card("bycat", "By category"):
        c = cats.assign(label=cats.category.str.replace("_", " ").str.capitalize())
        bars = alt.Chart(c).mark_bar(cornerRadiusTopRight=5, cornerRadiusBottomRight=5, size=16,
                                     color=PALETTE["teal"]).encode(
            x=alt.X("tickets:Q", title=None, axis=alt.Axis(tickCount=3)),
            y=alt.Y("label:N", sort="-x", title=None, axis=alt.Axis(labelLimit=130)),
            tooltip=[alt.Tooltip("label:N", title="Category"), "tickets:Q"])
        show(bars, height=230)
        ch = all_tickets.channel.value_counts().rename_axis("channel").reset_index(name="tickets")
        ch["channel"] = ch.channel.str.replace("_", " ").str.capitalize()
        st.markdown('<div class="k-section" style="margin-top:6px">By channel</div>', unsafe_allow_html=True)
        donut = alt.Chart(ch).mark_arc(innerRadius=52, cornerRadius=4, padAngle=0.02).encode(
            theta="tickets:Q",
            color=alt.Color("channel:N", scale=alt.Scale(range=[PALETTE["indigo"], PALETTE["teal"], PALETTE["amber"]])),
            tooltip=["channel:N", "tickets:Q"])
        show(donut, height=200)
