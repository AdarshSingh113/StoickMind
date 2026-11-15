import altair as alt
import pandas as pd
import streamlit as st

from kotler import db
from kotler.llm import get_llm
from kotler.ml import pipeline
from kotler.ml import rto as rto_mod
from kotler.ml import segment_builder as SB
from kotler.ml.features import customer_features
from kotler.ml.segments import SEGMENTS, rfm, segment_summary
from views import inr
from views.ui import PALETTE, badge, card, esc, kpi_strip, page_header, show

SEG_COLORS = {"Champions": "#4F46E5", "Loyal": "#6366F1", "Potential loyalists": "#818CF8", "New customers": "#14B8A6",
              "Promising": "#5EEAD4", "Need attention": "#F59E0B", "About to sleep": "#FBBF24", "At risk": "#F43F5E",
              "Can't lose them": "#BE123C", "Hibernating": "#94A3B8", "Lost": "#CBD5E1"}


@st.cache_resource(ttl=600, show_spinner="Training models on the latest data (about 10 seconds)…")
def _models(data_key: str):
    metrics = pipeline.ensure_trained()
    return metrics, pipeline.load_model("rto")


@st.cache_data(ttl=600)
def _segments(data_key: str):
    f = customer_features()
    seg = rfm(f)
    return f, seg, segment_summary(f, seg)


def render():
    page_header("Customer Intelligence", "Segments, churn and lifetime value, COD risk, and a plain-English segment "
                "builder. Classic machine learning, measured honestly against simple baselines.", "Customer data platform")
    data_key = str(db.query_one("SELECT MAX(created_at) AS t FROM orders")["t"])
    metrics, rto_model = _models(data_key)
    scores = db.query_df("""SELECT s.*, c.name, c.city FROM customer_scores s JOIN customers c ON c.id = s.customer_id""")
    feats, seg, summary = _segments(data_key)

    champ = summary[summary.segment == "Champions"]
    kpi_strip([
        {"label": "Customers scored", "value": f"{len(scores):,}", "sub": f"models trained {metrics['trained_at'][:16]}"},
        {"label": "Champions", "value": f"{int(champ.customers.sum()) if len(champ) else 0:,}",
         "sub": f"{float(champ.revenue_share.sum()) if len(champ) else 0:.0%} of revenue"},
        {"label": "Value at risk", "value": inr(scores.value_at_risk.sum()),
         "help": "Sum over customers of predicted 12-month value × churn probability.", "sub": "next 12 months"},
        {"label": "Likely to churn", "value": f"{(scores.churn_risk >= 0.7).mean():.0%}", "sub": "churn risk ≥ 70%"},
        {"label": "COD RTO model", "value": f"AUC {metrics['rto']['results'][metrics['rto']['model']]['roc_auc']:.2f}",
         "delta_html": badge(f"baseline {metrics['rto']['results']['baseline_tier_rate']['roc_auc']:.2f}", "neutral")},
    ])
    st.write("")
    t1, t2, t3, t4 = st.tabs(["Segments", "Churn & value", "COD risk", "Segment builder"])
    with t1:
        _segments_tab(summary, seg)
    with t2:
        _churn_tab(metrics, scores)
    with t3:
        _rto_tab(metrics, rto_model)
    with t4:
        _builder_tab()


# --------------------------------------------------------------- segments
def _segments_tab(summary: pd.DataFrame, seg: pd.DataFrame):
    left, right = st.columns([7, 4], gap="medium")
    with left, card("seg-table", "RFM segments", "Recency, frequency and monetary scores (1-5) mapped to named groups"):
        st.dataframe(summary, hide_index=True, use_container_width=True, height=420,
                     column_order=["segment", "customers", "revenue_share", "action"],
                     column_config={
                         "segment": "Segment", "customers": "Customers",
                         "revenue_share": st.column_config.ProgressColumn("Revenue share", format="percent", min_value=0,
                                                                          max_value=float(summary.revenue_share.max())),
                         "avg_recency": st.column_config.NumberColumn("Days since order", format="%.0f"),
                         "avg_orders": st.column_config.NumberColumn("Orders", format="%.1f"),
                         "avg_value": st.column_config.NumberColumn("Avg spend", format="₹%.0f"),
                         "action": st.column_config.TextColumn("Suggested action", width="medium")})
    with right, card("seg-chart", "Customers vs revenue", "Few customers drive most revenue"):
        long = summary.melt(id_vars="segment", value_vars=["customers", "revenue"], var_name="metric")
        long["share"] = long.groupby("metric").value.transform(lambda v: v / v.sum())
        long["metric"] = long.metric.map({"customers": "Share of customers", "revenue": "Share of revenue"})
        chart = alt.Chart(long).mark_bar(cornerRadiusEnd=4, size=11).encode(
            y=alt.Y("segment:N", sort=list(SEGMENTS), title=None, axis=alt.Axis(labelLimit=140)),
            x=alt.X("share:Q", title=None, axis=alt.Axis(format="%", tickCount=4)),
            yOffset="metric:N",
            color=alt.Color("metric:N", scale=alt.Scale(range=["#CBD5E1", PALETTE["indigo"]])),
            tooltip=["segment", "metric", alt.Tooltip("share:Q", format=".1%")])
        show(chart, height=400)
    st.write("")
    with card("rfm-grid", "Recency × frequency", "Each cell: number of customers. Top-right = best customers"):
        grid = seg.groupby(["r", "f"]).size().reset_index(name="customers")
        heat = alt.Chart(grid).mark_rect(cornerRadius=4).encode(
            x=alt.X("f:O", title="Frequency score (1 = one order … 5 = 6+ orders)", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("r:O", title="Recency score (5 = most recent)", sort="descending"),
            color=alt.Color("customers:Q", scale=alt.Scale(scheme="purples"), legend=None),
            tooltip=["r", "f", "customers"])
        text = heat.mark_text(fontSize=12).encode(text="customers:Q",
                                                  color=alt.condition("datum.customers > 80", alt.value("white"),
                                                                      alt.value("#0F172A")))
        show(alt.layer(heat, text), height=260)


# ---------------------------------------------------------- churn & value
def _model_card(key: str, title: str, m: dict, metric: str, baseline_key: str, higher_better: bool = True):
    best = m["results"][m["model"] if m["model"] in m["results"] else "gradient_boosting"]
    base = m["results"][baseline_key]
    with card(key, title, f"Backtest on a later period the model never saw · model: {m['model'].replace('_', ' ')}"):
        rows = [{"model": k.replace("_", " "), metric: v.get(metric)} for k, v in m["results"].items() if metric in v]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        better = (best[metric] > base[metric]) if higher_better else (best[metric] < base[metric])
        st.markdown(badge("Beats the simple baseline" if better else "Does NOT beat the baseline",
                          "good" if better else "bad"), unsafe_allow_html=True)


def _churn_tab(metrics: dict, scores: pd.DataFrame):
    a, b = st.columns(2, gap="medium")
    with a:
        _model_card("m-churn", "Churn model: no order in the next 90 days", metrics["churn"], "roc_auc", "baseline_recency")
        st.caption("Honest note: recency alone already gets AUC 0.78. Machine learning adds a little (≈ +0.03), "
                   "mostly from purchase frequency and 90-day activity. Small data, small gains.")
    with b:
        _model_card("m-clv", "Value model: delivered spend in the next 90 days", metrics["clv"], "mae",
                    "baseline_last_90d", higher_better=False)
        st.caption("MAE = average error in ₹ per customer (lower is better). 12-month value ≈ 4 × the 90-day "
                   "prediction, a deliberate simplification.")
    st.write("")
    with card("risk-list", "High-value customers slipping away",
              "Sorted by value at risk = predicted 12-month value × churn probability"):
        top = scores.sort_values("value_at_risk", ascending=False).head(25)
        st.dataframe(top, hide_index=True, use_container_width=True, column_order=[
            "name", "city", "segment", "churn_risk", "clv_12m", "value_at_risk"], column_config={
            "name": "Customer", "city": "City", "segment": "Segment",
            "churn_risk": st.column_config.ProgressColumn("Churn risk", format="percent", min_value=0, max_value=1),
            "clv_12m": st.column_config.NumberColumn("12-month value", format="₹%.0f"),
            "value_at_risk": st.column_config.NumberColumn("Value at risk", format="₹%.0f")})


# ----------------------------------------------------------------- RTO
def _rto_tab(metrics: dict, model):
    m = metrics["rto"]
    a, b = st.columns([1, 1], gap="medium")
    with a:
        _model_card("m-rto", "COD refusal (RTO) predictor", m, "roc_auc", "baseline_tier_rate")
        best = m["results"][m["model"]]
        st.caption(f"The riskiest 10% of COD orders in the test period had a {best['top10pct_rto_rate']:.0%} RTO rate, "
                   f"vs {m['test_rto_rate']:.0%} on average. Baseline = 'tier-3 cities are risky'.")
    with b, card("rto-drivers", "What drives refusals", "Effect of each signal (standardised); red raises risk"):
        d = pd.DataFrame(m["drivers"])
        d["label"] = d.feature.str.replace("_", " ")
        chart = alt.Chart(d).mark_bar(cornerRadiusEnd=4, size=14).encode(
            y=alt.Y("label:N", sort="-x", title=None),
            x=alt.X("effect:Q", title=None),
            color=alt.condition("datum.effect > 0", alt.value(PALETTE["rose"]), alt.value(PALETTE["teal"])),
            tooltip=["label", "effect", "direction"])
        show(chart, height=250)

    st.write("")
    with card("rto-sim", "Savings simulator", "Intervene (WhatsApp confirmation or prepaid nudge) on orders above a "
                                              "risk threshold. Change the assumptions; the best threshold moves."):
        c1, c2, c3, c4 = st.columns(4)
        cost = c1.number_input("Cost of one RTO (₹)", 50, 600, 160, 10, help="Forward + return shipping + handling.")
        prevent = c2.slider("RTOs prevented by intervening", 0.1, 0.9, 0.5, 0.05)
        lose = c3.slider("Genuine buyers lost by the extra step", 0.0, 0.3, 0.05, 0.01)
        margin = c4.slider("Gross margin", 0.2, 0.8, 0.45, 0.05)
        scored = pd.DataFrame(metrics["rto_test_scores"])
        curve = rto_mod.savings_curve(scored, cost, prevent, lose, margin)
        best_row = curve.loc[curve.net_saving_inr.idxmax()]
        line = alt.Chart(curve).mark_line(color=PALETTE["indigo"], strokeWidth=2.5, point=True).encode(
            x=alt.X("threshold:Q", title="Risk threshold"), y=alt.Y("net_saving_inr:Q", title="Net saving on test orders (₹)"),
            tooltip=["threshold", "flagged_orders", "rtos_caught", "rto_recall", "net_saving_inr"])
        rule = alt.Chart(pd.DataFrame({"t": [best_row.threshold]})).mark_rule(color=PALETTE["rose"], strokeDash=[4, 4]).encode(x="t:Q")
        show(alt.layer(line, rule), height=240)
        st.markdown(f"**Best threshold {best_row.threshold:.2f}**: flag {best_row.flagged_pct:.0%} of COD orders, catch "
                    f"{best_row.rto_recall:.0%} of refusals, net saving **₹{best_row.net_saving_inr:,.0f}** on "
                    f"{len(scored)} test orders.")
        st.session_state["rto_threshold"] = float(best_row.threshold)

    st.write("")
    with card("rto-open", "Open COD orders to act on now", "Not yet delivered, scored with today's model"):
        open_orders = rto_mod.score_open_orders(model)
        if open_orders.empty:
            st.caption("No open COD orders.")
            return
        th = st.session_state.get("rto_threshold", metrics.get("rto_best_threshold", 0.35))
        def action(risk: float, status: str) -> str:
            if risk < th:
                return "Ship normally" if status == "placed" else "No action"
            if status == "placed":  # still in our warehouse: we can confirm or convert before shipping
                return "Call before shipping" if risk >= max(0.75, th) else "WhatsApp confirm / prepaid nudge"
            return "Call before delivery attempt"  # already with the courier

        open_orders["action"] = [action(r, s_) for r, s_ in zip(open_orders.risk, open_orders.status)]
        open_orders["status"] = open_orders.status.str.replace("_", " ").str.capitalize()
        st.dataframe(open_orders, hide_index=True, use_container_width=True, height=380, column_order=[
            "order_number", "city", "status", "risk", "action", "reasons"], column_config={
            "order_number": "Order", "customer": "Customer", "city": "City", "status": "Status",
            "order_value": st.column_config.NumberColumn("Value", format="₹%.0f"),
            "risk": st.column_config.ProgressColumn("RTO risk", format="percent", min_value=0, max_value=1),
            "action": "Recommended action", "reasons": st.column_config.TextColumn("Why", width="large")})


# ---------------------------------------------------------- segment builder
EXAMPLES = ["Tier-3 customers with oily skin who haven't ordered in 60 days",
            "High-value customers likely to churn", "People who bought serums at least twice but never sunscreen",
            "Instagram customers with 2+ refused COD parcels"]


def _builder_tab():
    left, right = st.columns([3, 2], gap="medium")
    with left, card("builder", "Describe a segment in plain English",
                    "The AI writes the SQL; code checks it can only read anonymous customer features"):
        llm = get_llm()
        if llm is None:
            st.info("Add a Gemini API key to use the segment builder (see the Shop Assistant page).")
        req = st.text_area("Who do you want to reach?", placeholder=EXAMPLES[0], height=80, key="seg-req")
        cols = st.columns(2)
        for i, ex in enumerate(EXAMPLES):
            if cols[i % 2].button(ex, key=f"ex{i}", use_container_width=True):
                st.session_state["seg-req-run"] = ex
        go = st.button("Build segment", type="primary", icon=":material/filter_alt:", disabled=llm is None)
        request = st.session_state.pop("seg-req-run", None) or (req if go else None)
        if request and llm is not None:
            with st.spinner("Writing and checking the query…"):
                st.session_state["seg-result"] = SB.build_segment(llm, request)
        res = st.session_state.get("seg-result")
        if res:
            st.markdown(f"**Request:** {esc(res['request'])}")
            if res["explanation"]:
                st.markdown(f"**How the AI read it:** {esc(res['explanation'])}")
            if res["sql"]:
                st.code(res["sql"], language="sql", wrap_lines=True)
            if res["error"]:
                st.error(res["error"], icon=":material/block:")
            elif not res["rows"].empty or res["sql"]:
                rows = res["rows"]
                names = db.query_df("SELECT id AS customer_id, name, city FROM customers")
                preview = rows.merge(names, on="customer_id", how="left")
                count_badge = badge(f"{len(rows):,} customers", "indigo")
                attempts_badge = badge(f"{res['attempts']} attempt(s)", "neutral")
                st.markdown(f"{count_badge} {attempts_badge}", unsafe_allow_html=True)
                st.dataframe(preview.head(200), hide_index=True, use_container_width=True, height=260)
                n1, n2 = st.columns([3, 1], vertical_alignment="bottom")
                name = n1.text_input("Save as", placeholder="e.g. Tier-3 oily lapsed")
                if n2.button("Save segment", use_container_width=True, disabled=not name):
                    SB.save_segment(name, res["request"], res["sql"], res["explanation"])
                    st.toast(f"Saved segment '{name}'", icon=":material/check_circle:")
    with right, card("saved", "Saved segments", "Used by campaigns in Phase 6"):
        saved = SB.saved_segments()
        if saved.empty:
            st.caption("No saved segments yet.")
        else:
            st.dataframe(saved, hide_index=True, use_container_width=True, column_order=["name", "customers", "request"],
                         column_config={"name": "Segment", "customers": "Customers", "request": "Description"})
