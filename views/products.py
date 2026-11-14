import altair as alt
import streamlit as st

from kotler import crm
from views import inr
from views.ui import PALETTE, badge, card, kpi_strip, page_header, show

LOW_STOCK = 10


def render():
    page_header("Products", "Catalogue performance and stock health.", "Catalogue")
    df = crm.product_performance()
    df["category_label"] = df.category.str.replace("_", " ").str.title()
    low = df[df.stock <= LOW_STOCK]
    out = df[df.stock == 0]
    best = df.iloc[0]

    kpi_strip([
        {"label": "Products", "value": f"{len(df)}", "sub": f"{df.category.nunique()} categories"},
        {"label": "Catalogue GMV", "value": inr(df.gmv.sum()), "sub": "all time"},
        {"label": "Best seller", "value": inr(best.gmv), "sub": best["name"]},
        {"label": "Stock alerts", "value": f"{len(low)}",
         "delta_html": badge(f"{len(out)} out of stock", "bad") if len(out) else badge("none out", "good"),
         "sub": f"≤ {LOW_STOCK} units"},
    ])
    st.write("")

    if len(low):
        with card("alerts", "Restock soon", "Sorted by how much revenue each product brings"):
            cols = st.columns(min(len(low), 4))
            for col, (_, r) in zip(cols, low.sort_values("gmv", ascending=False).head(4).iterrows()):
                tone, label = ("bad", "Out of stock") if r.stock == 0 else ("amber", f"{r.stock} left")
                col.markdown(f"""<div style="border:1px solid {PALETTE['border']};border-radius:12px;padding:12px 14px">
                    <div style="font-weight:600;font-size:.9rem;line-height:1.3;min-height:2.4em">{r['name']}</div>
                    <div style="margin-top:6px;display:flex;justify-content:space-between;align-items:center">
                    {badge(label, tone)}<span style="color:{PALETTE['slate']};font-size:.8rem">{r.units_sold} sold</span>
                    </div></div>""", unsafe_allow_html=True)
        st.write("")

    with card("top", "Top 10 products by GMV"):
        top = df.nlargest(10, "gmv")
        bars = alt.Chart(top).mark_bar(cornerRadiusTopRight=5, cornerRadiusBottomRight=5, color=PALETTE["indigo"],
                                       size=16).encode(
            x=alt.X("gmv:Q", title=None, axis=alt.Axis(labelExpr="'₹' + format(datum.value / 1000, '.0f') + 'K'",
                                                         tickCount=5)),
            y=alt.Y("name:N", sort="-x", title=None, axis=alt.Axis(labelLimit=260, labelFontSize=12)),
            tooltip=[alt.Tooltip("name:N", title="Product"), alt.Tooltip("units_sold:Q", title="Units"),
                     alt.Tooltip("gmv:Q", title="GMV ₹", format=",.0f")])
        labels = bars.mark_text(align="left", dx=6, fontSize=11, color=PALETTE["slate"]).encode(
            text=alt.Text("gmv:Q", format=",.0f"))
        show(alt.layer(bars, labels), height=330)
    st.write("")

    with card("catalogue", "Catalogue"):
        cats = st.multiselect("Category", sorted(df.category_label.unique()), placeholder="All categories",
                              label_visibility="collapsed")
        view = df[df.category_label.isin(cats)] if cats else df
        st.dataframe(view, hide_index=True, use_container_width=True, height=420,
                     column_order=["name", "category_label", "skin_types", "price", "stock", "rating", "units_sold", "gmv"],
                     column_config={
                         "name": st.column_config.TextColumn("Product"),
                         "category_label": "Category",
                         "skin_types": "Skin types",
                         "price": st.column_config.NumberColumn("Price", format="₹%d"),
                         "stock": st.column_config.NumberColumn("Stock"),
                         "rating": st.column_config.NumberColumn("Rating", format="%.1f ★"),
                         "units_sold": st.column_config.NumberColumn("Sold"),
                         "gmv": st.column_config.ProgressColumn("GMV", format="₹%d", min_value=0,
                                                                max_value=float(df.gmv.max())),
                     })
