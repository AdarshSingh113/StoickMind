import streamlit as st

from kotler import crm
from views import inr


@st.cache_data(ttl=300)
def _load():
    return crm.kpis(), crm.monthly_summary(), crm.channel_summary(), crm.rto_by_tier()


def render():
    st.title("Business overview")
    k, monthly, channels, rto = _load()

    c = st.columns(4)
    c[0].metric("GMV", inr(k["gmv"]), help="Value of all non-cancelled orders")
    c[1].metric("Net revenue", inr(k["net_revenue"]), help="Delivered and kept orders only")
    c[2].metric("Orders", f"{k['orders']:,}")
    c[3].metric("Avg order value", inr(k["aov"]))
    c = st.columns(4)
    c[0].metric("Buyers", f"{k['buyers']:,}")
    c[1].metric("Repeat purchase rate", f"{k['repeat_rate']:.0%}", help="Buyers with 2+ orders")
    c[2].metric("COD share", f"{k['cod_share']:.0%}")
    c[3].metric("COD RTO rate", f"{k['rto_rate']:.1%}", help="COD shipments returned undelivered",
                delta=f"{inr(k['rto_value'])} lost to RTO", delta_color="inverse")

    st.subheader("Monthly trend")
    st.bar_chart(monthly.set_index("month")[["net_revenue", "rto_loss"]], stack=True,
                 color=["#2e7d6b", "#d1495b"], height=320)

    left, right = st.columns(2)
    with left:
        st.subheader("Acquisition channels")
        st.dataframe(channels, hide_index=True, use_container_width=True, column_config={
            "net_revenue": st.column_config.NumberColumn("Net revenue (₹)", format="%d"),
            "revenue_per_customer": st.column_config.NumberColumn("₹ / customer", format="%d"),
        })
    with right:
        st.subheader("RTO by city tier")
        st.dataframe(rto, hide_index=True, use_container_width=True, column_config={
            "rto_pct": st.column_config.ProgressColumn("RTO %", format="%.1f%%", min_value=0, max_value=40),
        })
        st.caption("COD orders from tier-3 cities come back far more often. "
                   "Phase 4 builds a model that predicts this *before* shipping.")
