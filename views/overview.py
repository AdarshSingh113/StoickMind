from datetime import datetime, timedelta

import streamlit as st

from kotler import crm
from views import inr

PERIODS = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90, "All time": None}


@st.cache_data(ttl=300)
def _period_kpis(days: int | None):
    """KPIs for the selected period and for the period just before it."""
    if days is None:
        return crm.kpis(), None
    end = datetime.fromisoformat(crm.data_end()) + timedelta(seconds=1)
    start, prev_start = end - timedelta(days=days), end - timedelta(days=2 * days)
    fmt = lambda d: d.strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731
    return crm.kpis(fmt(start), fmt(end)), crm.kpis(fmt(prev_start), fmt(start))


@st.cache_data(ttl=300)
def _tables():
    return crm.monthly_summary(), crm.channel_summary(), crm.rto_by_tier()


def _delta(cur: float, prev: dict | None, key: str, pts: bool = False) -> str | None:
    """Change vs previous period: % change, or percentage points for rates."""
    if not prev:
        return None
    if pts:
        return f"{(cur - prev[key]) * 100:+.1f} pts"
    return f"{(cur - prev[key]) / prev[key]:+.0%}" if prev[key] else None


def render():
    st.title("Business overview")
    label = st.segmented_control("Period", list(PERIODS), default="Last 30 days") or "All time"
    k, p = _period_kpis(PERIODS[label])
    if p:
        st.caption(f"Changes compared with the previous {PERIODS[label]} days.")

    c = st.columns(4)
    c[0].metric("GMV", inr(k["gmv"]), _delta(k["gmv"], p, "gmv"), help="Value of all non-cancelled orders")
    c[1].metric("Net revenue", inr(k["net_revenue"]), _delta(k["net_revenue"], p, "net_revenue"),
                help="Delivered and kept orders only")
    c[2].metric("Orders", f"{k['orders']:,}", _delta(k["orders"], p, "orders"))
    c[3].metric("Avg order value", inr(k["aov"]), _delta(k["aov"], p, "aov"))
    c = st.columns(4)
    c[0].metric("Buyers", f"{k['buyers']:,}", _delta(k["buyers"], p, "buyers"))
    c[1].metric("New buyers", f"{k['new_buyers']:,}", _delta(k["new_buyers"], p, "new_buyers"),
                help="Buyers whose first-ever order falls in this period")
    c[2].metric("COD share", f"{k['cod_share']:.0%}", _delta(k["cod_share"], p, "cod_share", pts=True),
                delta_color="inverse")
    c[3].metric("COD RTO rate", f"{k['rto_rate']:.1%}", _delta(k["rto_rate"], p, "rto_rate", pts=True),
                delta_color="inverse", help=f"COD shipments returned undelivered. "
                                            f"{inr(k['rto_value'])} of orders lost to RTO in this period.")

    monthly, channels, rto = _tables()
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
            "rto_pct": st.column_config.ProgressColumn("RTO %", format="%.1f%%", min_value=0, max_value=50),
        })
        st.caption("COD orders from tier-3 cities come back far more often. "
                   "Phase 4 builds a model that predicts this *before* shipping.")
