import altair as alt
import streamlit as st

from kotler.analytics import ask as A
from kotler.llm import get_llm
from views.ui import PALETTE, badge, esc, page_header, show

EXAMPLES = [
    "Delivered revenue by month",
    "Which city tier has the highest RTO rate on COD orders?",
    "Top 5 products by units sold",
    "How many support tickets per category, and how many did the AI resolve?",
    "Which AI agent escalates to humans most often?",
    "Average order value by acquisition channel",
]


def _chart(res: A.AskResult) -> None:
    c, df = res.chart, res.rows
    if c.get("type") not in ("bar", "line"):
        return
    x_type = "O" if c["type"] == "line" else "N"   # months like 2026-03 are ordered labels, not timestamps
    enc = {"x": alt.X(f"{c['x']}:{x_type}", title=None, sort=None if c["type"] == "line" else "-y",
                      axis=alt.Axis(labelAngle=0 if len(df) <= 8 else -40, labelLimit=140)),
           "y": alt.Y(f"{c['y']}:Q", title=c["y"].replace("_", " ")),
           "tooltip": list(df.columns[:6])}
    if c.get("color"):
        enc["color"] = alt.Color(f"{c['color']}:N", legend=alt.Legend(orient="bottom", title=None))
    mark = (alt.Chart(df).mark_line(point=True, color=PALETTE["indigo"]) if c["type"] == "line"
            else alt.Chart(df).mark_bar(cornerRadiusEnd=4, color=PALETTE["indigo"]))
    show(mark.encode(**enc), 280)
    # A classic trap: the latest period is still running, so it always looks like a drop.
    end = A.data_end()
    if c["type"] == "line" and str(df[c["x"]].iloc[-1]) == end[:7]:
        st.caption(f"Note: {end[:7]} is incomplete (the data ends on {end}), so its value looks lower than it will be.")


def _show(res: A.AskResult, i: int) -> None:
    with st.chat_message("user"):
        st.markdown(esc(res.question), unsafe_allow_html=True)
    with st.chat_message("assistant", avatar=":material/query_stats:"):
        if res.error:
            st.warning(res.error)
            if res.sql:
                st.code(res.sql, language="sql")
            return
        if res.title:
            st.markdown(f"**{esc(res.title)}**", unsafe_allow_html=True)
        if res.answer_status == "verified":
            st.markdown(esc(res.answer) + " " + badge("numbers checked", "good"), unsafe_allow_html=True)
        elif res.answer_status == "withheld":
            st.markdown(badge("summary withheld", "amber") + " The written summary contained numbers that aren't in "
                        f"the result ({', '.join(res.ungrounded[:5])}), so it isn't shown. The table below is exact.",
                        unsafe_allow_html=True)
        if len(res.rows) == 1 and res.rows.shape[1] <= 3:
            cols = st.columns(res.rows.shape[1])
            for col, (k, v) in zip(cols, res.rows.iloc[0].items()):
                col.metric(k.replace("_", " "), f"{v:,.3g}" if isinstance(v, float) and abs(v) < 1 else
                           (f"{v:,.0f}" if isinstance(v, (int, float)) else str(v)))
        else:
            _chart(res)
            st.dataframe(res.rows, hide_index=True, use_container_width=True, height=min(38 + 35 * len(res.rows), 320))
        with st.expander("How I got this: SQL" + (f" (fixed after {res.attempts - 1} failed attempt)"
                                                   if res.attempts > 1 else "")):
            st.caption(res.explanation)
            st.code(res.sql, language="sql")
            st.download_button("Download CSV", res.rows.to_csv(index=False), f"kotler-answer-{i}.csv", "text/csv",
                               key=f"dl-{i}")


def render():
    page_header("Ask your data", "Questions in plain English (or Hinglish). Answers come from the database, with the "
                "SQL shown and every number in the summary checked.", "Analytics")
    llm = get_llm()
    st.session_state.setdefault("ask_history", [])
    hist: list[A.AskResult] = st.session_state.ask_history
    if not hist:
        st.markdown("**Try:**")
        cols = st.columns(3)
        for i, q in enumerate(EXAMPLES):
            if cols[i % 3].button(q, key=f"ex-{i}", use_container_width=True, disabled=llm is None):
                st.session_state.ask_pending = q
                st.rerun()
    for i, res in enumerate(hist):
        _show(res, i)
    q = st.chat_input("Ask a question about orders, customers, products, tickets, campaigns or the AI itself",
                      disabled=llm is None) or st.session_state.pop("ask_pending", None)
    if llm is None:
        st.info("Add a Gemini API key to ask questions (see README). The guardrails are covered by tests either way.")
    if q and llm is not None:
        with st.spinner("Writing SQL, running it, checking the answer…"):
            res = A.ask(llm, q[:500], [{"question": h.question, "sql": h.sql} for h in hist])
        hist.append(res)
        st.rerun()
    if hist and st.button("New conversation", icon=":material/refresh:"):
        st.session_state.ask_history = []
        st.rerun()
    with st.expander("What can't it see? (privacy)"):
        st.markdown("Names, phone numbers, emails, addresses and free-text messages are blocked **by the database "
                    "connection itself**, column by column, even inside allowed tables and even in a WHERE clause. "
                    "Counts and averages work; reading or filtering on personal data doesn't. The connection is "
                    "read-only, so nothing can be changed.")
