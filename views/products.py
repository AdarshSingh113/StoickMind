import altair as alt
import streamlit as st

from kotler import crm

LOW_STOCK = 10


def render():
    st.title("Products")
    df = crm.product_performance()

    low = df[df.stock <= LOW_STOCK]
    if not low.empty:
        st.error(f"{len(low)} product(s) at or below {LOW_STOCK} units: " + ", ".join(low.name))

    cats = st.multiselect("Category", sorted(df.category.unique()))
    if cats:
        df = df[df.category.isin(cats)]

    st.dataframe(df, hide_index=True, use_container_width=True, column_config={
        "id": None,
        "price": st.column_config.NumberColumn("Price (₹)", format="%d"),
        "gmv": st.column_config.NumberColumn("GMV (₹)", format="%d"),
        "rating": st.column_config.NumberColumn("Rating", format="%.1f ⭐"),
    })
    st.subheader("Top 10 by GMV")
    top = df.nlargest(10, "gmv")
    st.altair_chart(
        alt.Chart(top).mark_bar(color="#2e7d6b").encode(
            x=alt.X("gmv:Q", title="GMV (₹)"),
            y=alt.Y("name:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260)),
            tooltip=["name", "units_sold", "gmv"],
        ),
        use_container_width=True,
    )
