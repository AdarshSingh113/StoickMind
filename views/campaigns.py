import json
import re

import altair as alt
import pandas as pd
import streamlit as st

from kotler import db
from kotler.llm import get_llm
from kotler.marketing import campaigns as C
from kotler.marketing import journeys as J
from kotler.marketing import simulator, stats
from kotler.ml import pipeline
from kotler.ml.segment_builder import saved_segments
from views import inr
from views.ui import PALETTE, badge, card, esc, kpi_strip, page_header, show

JOURNEY_LABEL = {"replenishment": "Replenishment", "win_back": "Win-back", "cross_sell": "Complete your routine",
                 "second_order": "Second order", "segment": "Saved segment"}


@st.cache_data(ttl=300, show_spinner=False)
def _overview(key: str):
    return J.journey_overview()


@st.cache_data(ttl=300, show_spinner=False)
def _audience(journey: str, key: str):
    return J.audience(journey)


def render():
    page_header("Campaigns", "Retention journeys and AI-written WhatsApp campaigns, measured against a holdout group.",
                "Marketing")
    C.ensure_tables()
    key = str(db.query_one("SELECT MAX(created_at) AS t FROM orders")["t"])
    with st.spinner("Preparing customer scores…"):
        pipeline.ensure_trained()
    overview = _overview(key)
    camps = C.list_campaigns()
    measured = camps[camps.status == "measured"]
    kpi_strip([
        {"label": "Customers in journeys", "value": f"{int(overview.customers.sum()):,}", "sub": "today"},
        {"label": "Value in journeys", "value": inr(overview.value_12m.sum()), "sub": "predicted 12-month value"},
        {"label": "Campaigns", "value": f"{len(camps)}", "sub": f"{len(measured)} measured"},
        {"label": "Messages sent", "value": f"{int(camps.messaged.fillna(0)[camps.status != 'draft'].sum()):,}",
         "sub": f"≈ ₹{C.MESSAGE_COST_INR:.2f} each"},
    ])
    st.write("")
    flash = st.session_state.pop("campaign-flash", None)
    if flash:
        st.success(flash, icon=":material/check_circle:")
    t1, t2, t3, t4 = st.tabs(["Journeys", "New campaign", "Results", "Outbox"])
    with t1:
        _journeys(overview, key)
    with t2:
        _new_campaign(key)
    with t3:
        _results(camps)
    with t4:
        _outbox(camps)


# --------------------------------------------------------------- journeys
def _journeys(overview: pd.DataFrame, key: str):
    cols = st.columns(2, gap="medium")
    for i, r in enumerate(overview.itertuples()):
        with cols[i % 2], card(f"journey-{r.journey}"):
            st.markdown(f"""<div class="k-insight-head"><span class="k-insight-title">{JOURNEY_LABEL[r.journey]}</span>
                {badge(f"{r.customers:,} customers", "indigo")} {badge(f"churn risk {r.avg_churn_risk:.0%}", "amber")}</div>
                <div class="k-insight-body">{esc(r.description)}</div>
                <span class="k-insight-metric">{inr(r.value_12m)} predicted 12-month value</span>""", unsafe_allow_html=True)
            a = _audience(r.journey, key)
            st.dataframe(a.head(4), hide_index=True, use_container_width=True,
                         column_order=["first_name", "segment", "product_name", "reason"],
                         column_config={"first_name": "Customer", "segment": "Segment", "product_name": "Product",
                                        "reason": "Why"})
    st.caption("Create a campaign for any journey in the **New campaign** tab.")


# ---------------------------------------------------------- new campaign
def _new_campaign(key: str):
    llm = get_llm()
    segs = saved_segments()
    options = {f"journey:{j}": f"Journey · {JOURNEY_LABEL[j]}" for j in J.JOURNEYS}
    options |= {f"segment:{r.id}": f"Saved segment · {r.name}" for r in segs.itertuples()}
    left, right = st.columns([3, 2], gap="medium")
    with left, card("nc-setup", "1. Audience and offer"):
        choice = st.selectbox("Audience", list(options), format_func=options.get)
        kind, ref = choice.split(":", 1)
        if kind == "journey":
            journey, aud = ref, _audience(ref, key)
            desc = J.JOURNEYS[ref]
        else:
            row = segs[segs.id == int(ref)].iloc[0]
            journey, aud, desc = "segment", J.audience_from_segment(row.sql), row.request
        c1, c2 = st.columns(2)
        offer = c1.slider("Discount", 0, C.MAX_CAMPAIGN_DISCOUNT, 0, 5, format="%d%%",
                          help=f"Capped at {C.MAX_CAMPAIGN_DISCOUNT}%. Every buyer gets it, even those who'd buy anyway.")
        holdout = c2.slider("Holdout (control group)", 0.05, 0.5, 0.2, 0.05, format="%.2f",
                            help="Share of the audience that gets NO message, to measure the true effect.")
        name = st.text_input("Campaign name", value=f"{JOURNEY_LABEL[journey]} · {pd.Timestamp.now():%d %b}")
        n = len(aud)
        excluded = C.exclusions(aud.customer_id.astype(int).tolist()) if n else {}
        eligible = n - len(excluded)
        control = int(eligible * holdout)
        base = float(aud.churn_risk.map(simulator.base_probability).mean()) if n else 0.05
        need = stats.sample_size_per_group(max(base, 0.01), 0.3)
        st.markdown(f"{badge(f'{n:,} in audience', 'indigo')} {badge(f'{len(excluded)} excluded', 'neutral')} "
                    f"{badge(f'≈ {control} in control', 'teal')}", unsafe_allow_html=True)
        if control < need:
            st.warning(f"**Power check:** to reliably detect a 30% lift on a ~{base:.0%} buying rate you need about "
                       f"**{need:,} customers per group**; this control group has ≈ {control}. The result will likely be "
                       "inconclusive: fine for learning, but don't over-read it.", icon=":material/analytics:")
    with right, card("nc-preview", "Audience preview"):
        st.dataframe(aud.head(50), hide_index=True, use_container_width=True, height=300,
                     column_order=["first_name", "language", "product_name", "price", "reason"],
                     column_config={"first_name": "Customer", "language": "Lang", "product_name": "Product",
                                    "price": st.column_config.NumberColumn("Price", format="₹%.0f"), "reason": "Why"})
    st.write("")
    with card("nc-templates", "2. Messages: two variants (A/B), English + Hinglish",
              "Placeholders: {first_name} {product} {price} {days}" + (" {discount} {code}" if offer else "")
              + ". Prices and discounts are filled in by code, never typed."):
        tkey = f"tpl-{choice}-{offer}"
        b1, b2 = st.columns([1, 3], vertical_alignment="center")
        if b1.button("Write with AI" if llm else "Load templates", icon=":material/auto_awesome:", use_container_width=True):
            with st.spinner("Writing two variants…"):
                st.session_state[tkey] = C.generate_templates(llm, journey, offer)
        if tkey not in st.session_state:
            st.session_state[tkey] = C.generate_templates(None, journey, offer)
        templates, source = st.session_state[tkey]
        b2.markdown(badge("Written by AI" if source == "ai" else "Built-in templates (AI unavailable or not used)",
                          "indigo" if source == "ai" else "neutral"), unsafe_allow_html=True)
        edited, errors = {}, []
        va, vb = st.columns(2, gap="medium")
        for col, v in ((va, "A"), (vb, "B")):
            with col:
                st.markdown(f"**Variant {v}** · {esc(templates[v].get('angle', ''))}")
                en = st.text_area(f"{v} English", templates[v]["en"], height=110, key=f"{tkey}-{v}-en")
                hi = st.text_area(f"{v} Hinglish", templates[v]["hinglish"], height=110, key=f"{tkey}-{v}-hi")
                edited[v] = {"angle": templates[v].get("angle", ""), "en": en, "hinglish": hi}
                for lang, text in (("English", en), ("Hinglish", hi)):
                    try:
                        C.validate_template(text, bool(offer))
                    except C.InvalidTemplate as e:
                        errors.append(f"Variant {v} {lang}: {e}")
        for e in errors:
            st.error(e, icon=":material/block:")
        if not errors and len(aud):
            st.markdown("**Preview**")
            for r in aud.head(3).to_dict("records"):
                lang = "en" if r["language"] == "en" else "hinglish"
                msg = C.render(edited["A"][lang], r, offer, f"KTL0{offer}" if offer else None)
                html = re.sub(r"\*([^*]+)\*", r"<b>\1</b>", esc(msg))  # WhatsApp *bold*
                st.markdown(f"""<div style="background:#ECFDF3;border-radius:12px 12px 12px 4px;padding:10px 14px;
                    margin:6px 0;max-width:620px;font-size:.92rem">{html}</div>""", unsafe_allow_html=True)
    st.write("")
    if st.button("Create and send campaign", type="primary", icon=":material/send:", disabled=bool(errors) or not len(aud)):
        try:
            cid = C.create_campaign(name, journey, edited, source, offer, holdout, audience_df=aud, audience_desc=desc)
            sent = C.send_campaign(cid)
            st.session_state["campaign-flash"] = (f"Campaign #{cid} sent to {sent:,} customers (simulated). "
                                                  "Measure it in the Results tab.")
            _overview.clear()
            st.rerun()  # the campaign list at the top of the page was loaded before this campaign existed
        except ValueError as e:
            st.error(str(e))


# ---------------------------------------------------------------- results
def _results(camps: pd.DataFrame):
    sent = camps[camps.status != "draft"]
    if sent.empty:
        st.info("No campaigns yet. Create one in the New campaign tab.")
        return
    labels = {int(r.id): f"#{r.id} · {r.name} · {r.status}" for r in sent.itertuples()}
    cid = st.selectbox("Campaign", list(labels), format_func=labels.get)
    camp = sent[sent.id == cid].iloc[0]
    st.markdown(f"""<div style="background:#FEF6E7;border-radius:12px;padding:10px 14px;color:#92400E;font-size:.88rem">
        <b>Simulated customers.</b> We can't message thousands of real people for free, so a simulator plays the customers
        for 14 days (assumptions in <code>kotler/marketing/simulator.py</code>). The analysis below is exactly what you'd
        run on real orders.</div>""", unsafe_allow_html=True)
    st.write("")
    if camp.status == "sent":
        if st.button("Measure results (simulate the next 14 days)", type="primary", icon=":material/science:"):
            simulator.simulate(int(cid))
            st.rerun()
        return
    c1, c2, c3 = st.columns(3)
    margin = c1.slider("Gross margin", 0.2, 0.8, 0.45, 0.05, key=f"m-{cid}")
    msg_cost = c2.number_input("Cost per message (₹)", 0.0, 5.0, C.MESSAGE_COST_INR, 0.1, key=f"c-{cid}")
    r = stats.analyze(int(cid), margin, msg_cost)
    tone = "good" if r["significant"] and r["net_profit"] > 0 else "amber" if r["significant"] else "neutral"
    c3.markdown(badge("Significant" if r["significant"] else "Not significant", tone), unsafe_allow_html=True)

    kpi_strip([
        {"label": "Naive 'orders from campaign'", "value": f"{r['naive_orders']}", "sub": "messaged customers who bought"},
        {"label": "Incremental orders", "value": f"{r['incremental_orders']:.0f}", "sub": "caused by the campaign",
         "help": "(treated rate - control rate) × treated customers"},
        {"label": "Uplift", "value": f"{r['abs_uplift'] * 100:+.1f} pts",
         "delta_html": badge(f"p = {r['p_value']:.3f}", tone), "sub": f"{r['treated_rate']:.1%} vs {r['control_rate']:.1%}"},
        {"label": "Incremental revenue", "value": inr(r["incremental_revenue"])},
        # A profit estimate from an uplift that could be luck is itself a guess: say so instead of celebrating it.
        {"label": "Net profit", "value": inr(r["net_profit"]),
         "delta_html": (badge(f"ROI {r['roi']:+.0%}" if r["roi"] is not None else "–", "good" if r["net_profit"] > 0 else "bad")
                        if r["significant"] else badge("not reliable: uplift not significant", "neutral")),
         "sub": "" if r["significant"] else "estimate only"},
    ])
    st.write("")
    st.markdown(f"""<div style="background:#fff;border:1px solid #E6E8F0;border-radius:14px;padding:14px 18px">
        <div class="k-section">Verdict</div><div style="margin-top:4px;color:#334155">{esc(stats.verdict(r))}</div></div>""",
                unsafe_allow_html=True)
    st.write("")
    left, right = st.columns([3, 2], gap="medium")
    with left, card("res-ci", "Conversion rate by group", "Bars: 95% confidence interval. Overlapping bars = could be luck"):
        g = r["groups"].copy()
        g["label"] = g.group.map({"A": "Variant A", "B": "Variant B", "control": "Control (no message)"})
        base = alt.Chart(g).encode(y=alt.Y("label:N", title=None, sort=["Variant A", "Variant B", "Control (no message)"]))
        bars = base.mark_rule(strokeWidth=10, opacity=0.25, color=PALETTE["indigo"]).encode(
            x=alt.X("ci_low:Q", title="Bought within 14 days", axis=alt.Axis(format="%")), x2="ci_high:Q")
        dots = base.mark_point(filled=True, size=160, color=PALETTE["indigo"]).encode(
            x="rate:Q", tooltip=["label", "customers", "conversions", alt.Tooltip("rate:Q", format=".1%"),
                                 alt.Tooltip("ci_low:Q", format=".1%"), alt.Tooltip("ci_high:Q", format=".1%")])
        show(alt.layer(bars, dots), height=200)
        ab = r["ab"]
        st.markdown(f"**A vs B:** {'Variant ' + ab['winner'] + ' wins' if ab['winner'] else 'no clear winner'} "
                    f"(p = {ab['p_value']:.3f}).")
    with right, card("res-cost", "Where the money went"):
        rows = pd.DataFrame([
            {"item": "Incremental gross profit", "inr": r["incremental_revenue"] * margin},
            {"item": "Message cost", "inr": -r["message_cost"]},
            {"item": "Discounts (incl. people who'd buy anyway)", "inr": -r["discount_cost"]},
            {"item": "Net profit", "inr": r["net_profit"]}])
        st.dataframe(rows, hide_index=True, use_container_width=True,
                     column_config={"item": "", "inr": st.column_config.NumberColumn("₹", format="₹%.0f")})
        st.caption(f"Templates: {'AI-written' if camp.template_source == 'ai' else 'built-in'} · offer {camp.offer_pct}% · "
                   f"holdout {camp.holdout_pct:.0%}")


# ----------------------------------------------------------------- outbox
def _outbox(camps: pd.DataFrame):
    if camps.empty:
        st.info("No messages yet.")
        return
    labels = {int(r.id): f"#{r.id} · {r.name}" for r in camps.itertuples()}
    cid = st.selectbox("Campaign", list(labels), format_func=labels.get, key="outbox-camp")
    m = C.members(cid)
    m["status"] = m.apply(lambda x: "excluded: " + x.exclusion_reason if x.grp == "excluded"
                          else "control (no message)" if x.grp == "control" else "sent" if x.sent_at else "queued", axis=1)
    with card("outbox", "Messages", "WhatsApp (simulated). Phase 7 sends to real test numbers."):
        st.dataframe(m, hide_index=True, use_container_width=True, height=460,
                     column_order=["name", "grp", "language", "message", "status"],
                     column_config={"name": "Customer", "grp": "Group", "language": "Lang",
                                    "message": st.column_config.TextColumn("Message", width="large"), "status": "Status"})
    _ = json
