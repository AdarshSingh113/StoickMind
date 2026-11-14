import streamlit as st

from kotler import crm
from views import inr


def render():
    st.title("Customer 360")
    search = st.text_input("Search by name, phone, email or city", placeholder="e.g. Jaipur or 98765")
    df = crm.customer_summary(search or None)
    st.caption(f"{len(df):,} customers")

    event = st.dataframe(
        df, hide_index=True, use_container_width=True, height=320,
        on_select="rerun", selection_mode="single-row",
        column_order=["name", "phone", "city", "tier", "skin_type", "language", "channel",
                      "orders", "lifetime_value", "days_since_last_order"],
        column_config={
            "lifetime_value": st.column_config.NumberColumn("Lifetime value (₹)", format="%d"),
            "days_since_last_order": st.column_config.NumberColumn("Days since last order"),
        },
    )
    rows = event.selection.rows
    if not rows:
        st.info("Select a customer above to open their 360° profile.")
        return
    _profile(int(df.iloc[rows[0]]["id"]))


def _profile(customer_id: int):
    c = crm.get_customer(customer_id)
    orders = crm.customer_orders(customer_id)
    live = orders[orders.status != "cancelled"]

    st.divider()
    st.subheader(c["name"])
    st.caption(f"📞 {c['phone']} · ✉️ {c['email']} · 📍 {c['city']}, {c['state']} · "
               f"Customer since {c['created_at'][:10]} via {c['acquisition_channel']}")
    lang = {"en": "English", "hinglish": "Hinglish", "hi": "Hindi"}[c["preferred_language"]]
    st.markdown(f":blue-badge[Skin: {(c['skin_type'] or 'unknown').title()}] :violet-badge[Language: {lang}]")

    m = st.columns(3)
    m[0].metric("Orders", len(live))
    m[1].metric("Lifetime value", inr(live.loc[live.status == "delivered", "total"].sum()))
    m[2].metric("Avg order", inr(live.total.mean() if len(live) else 0))

    rto = (orders.status == "rto").sum()
    if rto:
        st.warning(f"{rto} past COD order(s) returned undelivered (RTO).")

    tab_orders, tab_products, tab_tickets = st.tabs(["Orders", "Favourite products", "Support history"])
    with tab_orders:
        st.dataframe(orders, hide_index=True, use_container_width=True,
                     column_order=["order_number", "created_at", "status", "payment_method", "total",
                                   "coupon_code", "items", "courier", "tracking_number"])
    with tab_products:
        st.dataframe(crm.customer_top_products(customer_id), hide_index=True, use_container_width=True)
    with tab_tickets:
        t = crm.customer_tickets(customer_id)
        if t.empty:
            st.write("No support tickets.")
        else:
            st.dataframe(t, hide_index=True, use_container_width=True)
