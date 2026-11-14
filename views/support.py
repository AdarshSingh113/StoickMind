import streamlit as st

from kotler import crm


def render():
    st.title("Support tickets")
    s = crm.support_summary()
    c = st.columns(4)
    c[0].metric("Total tickets", f"{s['total']:,}")
    c[1].metric("Open", s["open"])
    c[2].metric("Avg time to resolve", f"{s['avg_hours']:.1f} h")
    c[3].metric("Resolved by AI", f"{s['ai_share']:.0%}",
                help="0% today — this is the baseline the Phase 3 support agent must beat.")

    status = st.segmented_control("Status", ["open", "escalated", "resolved"], default=None)
    df = crm.tickets(status)

    left, right = st.columns([2, 1])
    with left:
        st.dataframe(df, hide_index=True, use_container_width=True, height=420,
                     column_order=["created_at", "customer", "channel", "category", "priority",
                                   "status", "message", "order_number", "hours_to_resolve"])
    with right:
        st.markdown("**Tickets by category**")
        st.bar_chart(df.category.value_counts(), horizontal=True, color="#2e7d6b")
