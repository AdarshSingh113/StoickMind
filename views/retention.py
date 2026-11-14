import streamlit as st

from kotler import crm


def _heat(value) -> str:
    """Green background, stronger for higher retention (0% -> none, 40%+ -> full)."""
    if value is None or value != value:  # empty / NaN
        return ""
    alpha = min(float(value) / 40, 1) * 0.85
    text = "#ffffff" if alpha > 0.5 else "#1f2937"
    return f"background-color: rgba(46, 125, 107, {alpha:.2f}); color: {text}"


@st.cache_data(ttl=300)
def _load():
    return crm.repeat_rate_90d(), crm.cohort_retention(max_months=6)


def render():
    st.title("Retention")
    r, cohorts = _load()

    c = st.columns(2)
    c[0].metric("90-day repeat rate", f"{r['rate']:.0%}",
                help="Of customers who first bought 90+ days ago, the share who ordered again within 90 days.")
    c[1].metric("Customers measured", f"{r['customers']:,}",
                help="Customers whose first order is old enough to have had a full 90-day window.")

    st.subheader("Monthly cohorts")
    st.caption("Each row is the group of customers who first bought in that month. "
               "M1 = % of them who ordered again one calendar month later, M2 two months later, and so on. "
               "Blank cells are months that haven't happened yet for that cohort.")
    month_cols = [col for col in cohorts.columns if col.startswith("M")]
    # Show text ("27%" or blank) but colour by the underlying numbers.
    shown = cohorts.copy()
    for col in month_cols:
        shown[col] = cohorts[col].map(lambda v: "" if v != v else f"{v:.0f}%")
    st.dataframe(
        shown.style.apply(lambda col: [_heat(v) for v in cohorts[col.name]], subset=month_cols[1:]),
        hide_index=True, use_container_width=True,
    )
    st.info("How to read it: if M1 drops sharply for recent cohorts, newly acquired customers are lower "
            "quality (check the acquisition channel) or the first-order experience got worse. "
            "Phase 4's churn and RFM models build on exactly this view.")
