import pandas as pd
import streamlit as st

from kotler import crm
from views import inr
from views.ui import badge, card, kpi_strip, page_header, profile_header, status_styler

LANG = {"en": "English", "hinglish": "Hinglish", "hi": "Hindi"}


def _status(days) -> str:
    """Simple recency status. Phase 4 replaces this with RFM segments and a churn model."""
    if pd.isna(days):
        return "No orders"
    return "Active" if days <= 45 else "At risk" if days <= 120 else "Lapsed"


def render():
    page_header("Customer 360", "Every customer, their orders, preferences and support history in one place.", "CRM")

    df = crm.customer_summary()
    df["status"] = df.days_since_last_order.map(_status)
    counts = df.status.value_counts()
    kpi_strip([
        {"label": "Customers", "value": f"{len(df):,}", "sub": "with at least one order"},
        {"label": "Active", "value": f"{counts.get('Active', 0):,}", "delta_html": badge("≤ 45 days", "good"),
         "sub": "since last order"},
        {"label": "At risk", "value": f"{counts.get('At risk', 0):,}", "delta_html": badge("46–120 days", "amber"),
         "sub": "win them back"},
        {"label": "Lapsed", "value": f"{counts.get('Lapsed', 0):,}", "delta_html": badge("> 120 days", "bad"),
         "sub": "likely churned"},
    ])
    st.write("")

    with card("list", "All customers", "Click a row to open the full profile"):
        f1, f2 = st.columns([3, 2])
        search = f1.text_input("Search", placeholder="Search name, phone, email or city…", label_visibility="collapsed")
        status = f2.segmented_control("Status", ["Active", "At risk", "Lapsed"], label_visibility="collapsed")
        view = df
        if search:
            ids = set(crm.customer_summary(search).id)
            view = view[view.id.isin(ids)]
        if status:
            view = view[view.status == status]
        view = view.reset_index(drop=True)
        shown = view.assign(language=view.language.map(LANG), channel=view.channel.str.title(),
                            skin_type=view.skin_type.str.title(), tier=view.tier.map(lambda t: f"Tier {t}"))
        event = st.dataframe(
            shown.style.map(status_styler, subset=["status"]), hide_index=True, use_container_width=True, height=330,
            on_select="rerun", selection_mode="single-row",
            column_order=["name", "city", "skin_type", "language", "orders", "lifetime_value",
                          "days_since_last_order", "status"],
            column_config={
                "name": st.column_config.TextColumn("Customer"),
                "city": "City", "tier": "Tier", "skin_type": "Skin", "language": "Language", "channel": "Channel",
                "orders": st.column_config.NumberColumn("Orders"),
                "lifetime_value": st.column_config.ProgressColumn(
                    "Lifetime value", format="₹%d", min_value=0, max_value=float(df.lifetime_value.max() or 1)),
                "days_since_last_order": st.column_config.NumberColumn("Days since order", format="%d"),
                "status": "Status",
            },
        )
        st.caption(f"Showing {len(view):,} of {len(df):,} customers")

    rows = event.selection.rows
    if rows:
        st.write("")
        _profile(int(view.iloc[rows[0]]["id"]), view.iloc[rows[0]]["status"])


def _profile(customer_id: int, status: str):
    c = crm.get_customer(customer_id)
    orders = crm.customer_orders(customer_id)
    live = orders[orders.status != "cancelled"]
    tickets = crm.customer_tickets(customer_id)
    rto = int((orders.status == "rto").sum())

    with card("profile"):
        tone = {"Active": "good", "At risk": "amber", "Lapsed": "bad"}.get(status, "neutral")
        badges = (badge(status, tone) + badge(f"{(c['skin_type'] or 'unknown').title()} skin", "indigo")
                  + badge(LANG[c["preferred_language"]], "teal") + badge(c["acquisition_channel"].title(), "neutral")
                  + (badge(f"{rto} RTO", "bad") if rto else ""))
        profile_header(c["name"], f"{c['city']}, {c['state']} · {c['phone']} · {c['email']} · "
                                  f"customer since {c['created_at'][:10]}", badges)
    st.write("")
    kpi_strip([
        {"label": "Orders", "value": f"{len(live)}"},
        {"label": "Lifetime value", "value": inr(live.loc[live.status == "delivered", "total"].sum()),
         "sub": "delivered orders"},
        {"label": "Average order", "value": inr(live.total.mean() if len(live) else 0)},
        {"label": "Last order", "value": (orders.created_at.iloc[0][:10] if len(orders) else "–")},
        {"label": "Support tickets", "value": f"{len(tickets)}"},
    ])
    st.write("")
    with card("history"):
        tab_orders, tab_products, tab_tickets = st.tabs(["Orders", "Favourite products", "Support history"])
        with tab_orders:
            o = orders.assign(status=orders.status.str.replace("_", " ").str.capitalize().replace({"Rto": "RTO"}),
                              payment_method=orders.payment_method.str.upper())
            st.dataframe(o.style.map(status_styler, subset=["status"]), hide_index=True, use_container_width=True,
                         column_order=["order_number", "created_at", "items", "total", "payment_method", "status",
                                       "courier", "coupon_code"],
                         column_config={"order_number": "Order", "created_at": "Placed", "items": "Items",
                                        "total": st.column_config.NumberColumn("Total", format="₹%d"),
                                        "payment_method": "Payment", "status": "Status", "courier": "Courier",
                                        "coupon_code": "Coupon"})
        with tab_products:
            st.dataframe(crm.customer_top_products(customer_id), hide_index=True, use_container_width=True,
                         column_config={"name": "Product", "category": "Category", "units": "Units bought"})
        with tab_tickets:
            if tickets.empty:
                st.caption("No support tickets.")
            else:
                st.dataframe(tickets.style.map(status_styler, subset=["status", "priority"]), hide_index=True,
                             use_container_width=True,
                             column_order=["created_at", "category", "message", "priority", "status", "channel"],
                             column_config={"created_at": "Created", "category": "Category", "message": "Message",
                                            "priority": "Priority", "status": "Status", "channel": "Channel"})
