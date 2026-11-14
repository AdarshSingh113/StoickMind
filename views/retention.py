import streamlit as st

from kotler import crm
from views.ui import card, kpi_strip, page_header


def _heat(value) -> str:
    """Indigo background, stronger for higher retention (0% -> none, 40%+ -> full)."""
    if value is None or value != value:  # empty / NaN
        return ""
    alpha = min(float(value) / 40, 1) * 0.85
    text = "#ffffff" if alpha > 0.5 else "#1f2937"
    return f"background-color: rgba(79, 70, 229, {alpha:.2f}); color: {text}"


@st.cache_data(ttl=300)
def _load():
    return crm.repeat_rate_90d(), crm.cohort_retention(max_months=6)


def render():
    page_header("Retention", "Do customers come back? The single most important health metric for a D2C brand.",
                "Customers")
    r, cohorts = _load()
    m1 = cohorts["M1"].dropna()
    best = cohorts.loc[cohorts["M1"].idxmax()] if len(m1) else None

    kpi_strip([
        {"label": "90-day repeat rate", "value": f"{r['rate']:.0%}",
         "help": "Of customers who first bought 90+ days ago, the share who ordered again within 90 days.",
         "sub": "bought again within 90 days"},
        {"label": "Customers measured", "value": f"{r['customers']:,}", "sub": "first order 90+ days ago"},
        {"label": "Avg month-1 retention", "value": f"{m1.mean():.0f}%" if len(m1) else "–",
         "sub": "ordered again the next month"},
        {"label": "Best cohort", "value": best["cohort"] if best is not None else "–",
         "sub": f"{best['M1']:.0f}% came back in month 1" if best is not None else ""},
    ])
    st.write("")

    with card("cohorts", "Monthly cohorts",
              "Rows: month of first purchase · M1 = % who ordered again 1 month later, M2 after 2 months…"):
        month_cols = [col for col in cohorts.columns if col.startswith("M")]
        shown = cohorts.copy()
        for col in month_cols:
            shown[col] = cohorts[col].map(lambda v: "" if v != v else f"{v:.0f}%")
        st.dataframe(
            shown.style.apply(lambda col: [_heat(v) for v in cohorts[col.name]], subset=month_cols[1:]),
            hide_index=True, use_container_width=True, height="content",
            column_config={"cohort": "Cohort", "customers": st.column_config.NumberColumn("Customers")},
        )
        st.caption("How to read it: if M1 drops for recent cohorts, newly acquired customers are lower quality "
                   "(check the channel) or the first experience got worse. Blank cells haven't happened yet.")
