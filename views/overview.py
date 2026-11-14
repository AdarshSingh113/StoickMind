from datetime import datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from kotler import crm
from views import inr
from views.ui import PALETTE, card, delta_badge, inr_axis, insight, kpi_strip, page_header, show

PERIODS = {"7 days": 7, "30 days": 30, "90 days": 90, "All time": None}


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
def _data():
    return (crm.monthly_summary(), crm.channel_summary(), crm.rto_by_tier(), crm.category_by_month(6),
            crm.product_performance(), crm.support_summary(), crm.ticket_categories(), crm.repeat_rate_90d())


def _chg(cur, prev, key):
    return None if not prev or not prev[key] else (cur - prev[key]) / prev[key]


def _pts(cur, prev, key):
    return None if not prev else cur - prev[key]


def render():
    top_l, top_r = st.columns([3, 2], vertical_alignment="bottom")
    with top_l:
        page_header("Business overview", "Revenue, customers and delivery health for Glow & Co.", "Dashboard")
    with top_r:
        label = st.segmented_control("Period", list(PERIODS), default="30 days", label_visibility="collapsed") \
            or "All time"
    k, p = _period_kpis(PERIODS[label])
    monthly, channels, rto, cats, prods, support, tcats, repeat = _data()
    vs = f"vs previous {label}" if p else "all time"

    kpi_strip([
        {"label": "Gross merchandise value", "value": inr(k["gmv"]), "delta_html": delta_badge(_chg(k["gmv"], p, "gmv")),
         "sub": vs, "help": "Value of all non-cancelled orders"},
        {"label": "Net revenue", "value": inr(k["net_revenue"]),
         "delta_html": delta_badge(_chg(k["net_revenue"], p, "net_revenue")), "sub": vs,
         "help": "Delivered and kept orders only"},
        {"label": "Orders", "value": f"{k['orders']:,}", "delta_html": delta_badge(_chg(k["orders"], p, "orders")), "sub": vs},
        {"label": "Average order value", "value": inr(k["aov"]), "delta_html": delta_badge(_chg(k["aov"], p, "aov")), "sub": vs},
    ])
    st.write("")
    kpi_strip([
        {"label": "Buyers", "value": f"{k['buyers']:,}", "delta_html": delta_badge(_chg(k["buyers"], p, "buyers")), "sub": vs},
        {"label": "New buyers", "value": f"{k['new_buyers']:,}",
         "delta_html": delta_badge(_chg(k["new_buyers"], p, "new_buyers")), "sub": vs,
         "help": "Buyers whose first-ever order is in this period"},
        {"label": "COD share", "value": f"{k['cod_share']:.0%}",
         "delta_html": delta_badge(_pts(k["cod_share"], p, "cod_share"), good_when_up=False, unit="pts"), "sub": vs},
        {"label": "COD RTO rate", "value": f"{k['rto_rate']:.1%}",
         "delta_html": delta_badge(_pts(k["rto_rate"], p, "rto_rate"), good_when_up=False, unit="pts"),
         "sub": f"{inr(k['rto_value'])} lost", "help": "COD parcels refused at the door and shipped back"},
    ])

    st.write("")
    _insights(rto, prods, support, tcats, repeat)

    st.write("")
    left, right = st.columns([3, 2], gap="medium")
    with left, card("revenue", "Monthly net revenue", "Bars: delivered revenue · line: month-on-month growth"):
        _revenue_chart(monthly)
    with right, card("customers", "New vs returning buyers", "Buyers per month"):
        _buyers_chart(monthly)

    left, right = st.columns([2, 3], gap="medium")
    with left, card("rto", "RTO by city tier", "% of finished COD and prepaid shipments returned"):
        _rto_chart(rto)
    with right, card("cats", "Top categories", "GMV per category, last 6 months"):
        _category_table(cats)

    left, right = st.columns(2, gap="medium")
    with left, card("aov", "Average order value", "Per month"):
        _aov_chart(monthly)
    with right, card("channels", "Acquisition channels", "Which channels bring the most valuable customers"):
        ch = channels.copy()
        ch["channel"] = ch.channel.str.title()
        ch["revenue"] = ch.net_revenue.map(inr)
        ch["per_customer"] = ch.revenue_per_customer.map(lambda v: f"₹{v:,.0f}")
        st.dataframe(ch, hide_index=True, use_container_width=True,
                     column_order=["channel", "customers", "net_revenue", "revenue", "per_customer"],
                     column_config={
                         "channel": st.column_config.TextColumn("Channel"),
                         "customers": st.column_config.NumberColumn("Customers"),
                         "net_revenue": st.column_config.ProgressColumn("Share", format=" ", min_value=0,
                                                                        max_value=float(ch.net_revenue.max())),
                         "revenue": st.column_config.TextColumn("Net revenue"),
                         "per_customer": st.column_config.TextColumn("Per customer"),
                     })


# --------------------------------------------------------------- insights
def _insights(rto, prods, support, tcats, repeat):
    st.markdown('<div class="k-section" style="margin:2px 0 8px">AI insights & recommendations</div>',
                unsafe_allow_html=True)
    t3 = rto[(rto.city_tier == "Tier 3") & (rto.payment_method == "cod")].rto_pct
    t3 = float(t3.iloc[0]) if len(t3) else 0.0
    low = prods[prods.stock <= 10].sort_values("gmv", ascending=False)
    status_share = 0.0
    if len(tcats) and tcats.tickets.sum():
        status_share = float(tcats.loc[tcats.category == "order_status", "tickets"].sum() / tcats.tickets.sum())

    c1, c2 = st.columns(2, gap="medium")
    with c1:
        insight("rto", "COD returns are expensive", "High",
                f"{t3:.0f}% of COD orders to tier-3 cities come back undelivered. "
                "Confirming risky orders or nudging them to prepaid would cut this.",
                "RTO predictor arrives in Phase 4")
    with c2:
        if len(low):
            names = ", ".join(low.name.head(2))
            insight("stock", "Best-sellers running out", "High",
                    f"{len(low)} products are at 10 units or fewer, including {names}.",
                    f"{inr(low.gmv.head(2).sum())} GMV at risk", "products", "Restock")
        else:
            insight("stock", "Stock levels healthy", "Good", "No product is below 10 units.", "All in stock")
    c3, c4 = st.columns(2, gap="medium")
    with c3:
        insight("support", "Most tickets are 'where is my order?'", "Medium",
                f"{status_share:.0%} of support tickets ask for order status, and humans take "
                f"{support['avg_hours']:.0f}h on average to reply. An AI agent can answer these instantly.",
                f"{support['open']} open now", "support", "View tickets")
    with c4:
        insight("retention", "Repeat purchase health", "Low",
                f"{repeat['rate']:.0%} of customers buy again within 90 days. Replenishment reminders for "
                "favourite products are the easiest way to raise this.",
                f"{repeat['customers']:,} customers measured", "retention", "View cohorts")


# ----------------------------------------------------------------- charts
def _label_partial(monthly: pd.DataFrame) -> pd.DataFrame:
    df = monthly.copy()
    df["label"] = pd.to_datetime(df.month).dt.strftime("%b %y")
    df.loc[df.index[-1], "label"] += " (MTD)"   # current month is still in progress
    df["partial"] = False
    df.loc[df.index[-1], "partial"] = True
    return df


def _revenue_chart(monthly):
    df = _label_partial(monthly)
    order = df.label.tolist()
    x = alt.X("label:N", sort=order, title=None, axis=alt.Axis(labelAngle=0))
    bars = alt.Chart(df).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5, size=22).encode(
        x=x, y=alt.Y("net_revenue:Q", axis=inr_axis()),
        color=alt.condition("datum.partial", alt.value("#A5B4FC"), alt.value(PALETTE["indigo"])),
        tooltip=[alt.Tooltip("label:N", title="Month"), alt.Tooltip("net_revenue:Q", title="Net revenue ₹", format=",.0f"),
                 alt.Tooltip("orders:Q", title="Orders"), alt.Tooltip("growth_pct:Q", title="Growth %")])
    # Growth % is meaningless while revenue is tiny (₹5K -> ₹20K = +300%), so start once it's meaningful.
    meaningful = df.net_revenue.shift(1) >= 150_000
    growth = df[~df.partial & meaningful].dropna(subset=["growth_pct"])
    line = alt.Chart(growth).mark_line(color=PALETTE["teal"], strokeWidth=2.5,
                                       point=alt.OverlayMarkDef(color=PALETTE["teal"], size=45, filled=True)).encode(
        x=x, y=alt.Y("growth_pct:Q", title="Growth %", axis=alt.Axis(format=".0f", labelExpr="datum.value + '%'",
                                                                      tickCount=4, grid=False)),
        tooltip=[alt.Tooltip("label:N", title="Month"), alt.Tooltip("growth_pct:Q", title="Growth %")])
    show(alt.layer(bars, line).resolve_scale(y="independent"), height=280)


def _buyers_chart(monthly):
    df = _label_partial(monthly)
    long = df.melt(id_vars=["label"], value_vars=["new_buyers", "returning_buyers"], var_name="type", value_name="count")
    long["type"] = long.type.map({"new_buyers": "New", "returning_buyers": "Returning"})
    chart = alt.Chart(long).mark_area(opacity=.85, interpolate="monotone", line={"strokeWidth": 1.5}).encode(
        x=alt.X("label:N", sort=df.label.tolist(), title=None, axis=alt.Axis(labelAngle=0, labelOverlap=True)),
        y=alt.Y("count:Q", stack=True, title=None),
        color=alt.Color("type:N", scale=alt.Scale(domain=["New", "Returning"], range=["#A5B4FC", PALETTE["teal"]])),
        tooltip=[alt.Tooltip("label:N", title="Month"), alt.Tooltip("type:N", title="Buyers"),
                 alt.Tooltip("count:Q", title="Count")])
    show(chart, height=280)


def _rto_chart(rto):
    chart = alt.Chart(rto).mark_bar(cornerRadiusTopLeft=5, cornerRadiusTopRight=5).encode(
        x=alt.X("city_tier:N", title=None, axis=alt.Axis(labelAngle=0)),
        xOffset=alt.XOffset("payment_method:N"),
        y=alt.Y("rto_pct:Q", title=None, axis=alt.Axis(labelExpr="datum.value + '%'", tickCount=5)),
        color=alt.Color("payment_method:N", scale=alt.Scale(domain=["cod", "prepaid"], range=[PALETTE["rose"], "#CBD5E1"]),
                        legend=alt.Legend(labelExpr="datum.label == 'cod' ? 'Cash on delivery' : 'Prepaid'")),
        tooltip=["city_tier:N", "payment_method:N", alt.Tooltip("rto_pct:Q", title="RTO %"), "shipments:Q"])
    text = chart.mark_text(dy=-8, fontSize=11, color=PALETTE["slate"]).encode(text=alt.Text("rto_pct:Q", format=".0f"))
    show(alt.layer(chart, text), height=262)


def _category_table(cats):
    if cats.empty:
        st.info("No sales yet.")
        return
    table = cats.copy()
    table.index = table.index.str.replace("_", " ").str.title()
    table.index.name = "Category"
    table.columns = pd.to_datetime(table.columns).strftime("%b %y")
    vmax = float(table.values.max())

    def heat(v):
        a = 0.08 + 0.72 * (v / vmax if vmax else 0)
        return f"background-color: rgba(20,184,166,{a:.2f}); color: {'#fff' if a > .5 else '#0F172A'}"

    shown = table.map(lambda v: f"₹{v / 1000:.1f}K")
    st.dataframe(shown.style.apply(lambda col: [heat(v) for v in table[col.name]]),
                 use_container_width=True, height="content")


def _aov_chart(monthly):
    df = _label_partial(monthly)
    lo, hi = float(df.aov.min()), float(df.aov.max())
    chart = alt.Chart(df).mark_area(
        interpolate="step-after", clip=True, line={"color": PALETTE["indigo"], "strokeWidth": 2},
        color=alt.Gradient(gradient="linear", x1=1, x2=1, y1=1, y2=0,
                           stops=[alt.GradientStop(color="#FFFFFF", offset=0),
                                  alt.GradientStop(color="#C7D2FE", offset=1)])).encode(
        x=alt.X("label:N", sort=df.label.tolist(), title=None, axis=alt.Axis(labelAngle=0, labelOverlap=True)),
        y=alt.Y("aov:Q", axis=inr_axis(), scale=alt.Scale(domain=[round(lo * 0.8, -2), round(hi * 1.05, -2)])),
        tooltip=[alt.Tooltip("label:N", title="Month"), alt.Tooltip("aov:Q", title="AOV ₹", format=",.0f")])
    show(chart, height=250)
