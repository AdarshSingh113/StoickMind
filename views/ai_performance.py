import altair as alt
import pandas as pd
import streamlit as st

from kotler import config
from kotler.obs import evals, impact, metrics
from views.ui import PALETTE, badge, card, esc, kpi_strip, page_header, show

STATUS_TONE = {"ok": "good", "corrected": "amber", "fallback": "amber", "fail_safe": "bad", "error": "bad",
               "running": "neutral"}
EVIDENCE_TONE = {"measured": "good", "modelled": "indigo", "simulated": "amber"}


def _v(x, fmt="{:.0f}", none="–"):
    return none if x is None or (isinstance(x, float) and pd.isna(x)) else fmt.format(x)


def render():
    page_header("AI performance", "Is the AI fast, reliable and good, what does it cost, and what is it worth?",
                "Evaluation & observability")
    c1, c2 = st.columns([1, 1])
    days = c1.segmented_control("Period", [1, 7, 30, 0], default=30, format_func=lambda d: "All time" if d == 0 else
                                f"{d} day{'s' if d > 1 else ''}", key="perf-days") or None
    include_eval = c2.toggle("Include eval runs", value=False, help="Traffic from offline evaluations (channel 'eval').")
    s = metrics.summary(days, include_eval)
    kpi_strip([
        {"label": "Agent replies", "value": f"{s['agent_turns']:,}", "sub": f"{s['conversations']} conversations"},
        {"label": "Reply time p50 / p95", "value": f"{s['p50_s']:.1f}s / {s['p95_s']:.1f}s",
         "sub": "median / slowest 5%"},
        {"label": "Safety checks stepped in", "value": f"{s['guard_rate']:.0%}",
         "sub": f"errors {s['error_rate']:.0%} · escalated {s['escalation_rate']:.0%}"},
        {"label": "AI cost (est.)", "value": f"₹{s['cost_inr']:,.2f}",
         "sub": f"₹{s['cost_per_conversation_inr']:.2f}/conversation · {s['tokens']:,} tokens"},
    ])
    st.write("")
    tabs = st.tabs(["Agents", "Traces", "Cost", "Evals", "Business impact"])
    with tabs[0]:
        _agents(days, include_eval, s)
    with tabs[1]:
        _traces(days, include_eval)
    with tabs[2]:
        _cost(days, include_eval)
    with tabs[3]:
        _evals()
    with tabs[4]:
        _impact(days or 30)


def _empty():
    st.info("No AI activity in this period yet. Chat in **Shop Assistant**, the **Helpdesk** copilot, Telegram or the "
            "website widget: every AI call is traced automatically and shows up here.")


def _agents(days, include_eval, s):
    df = metrics.per_agent(days, include_eval)
    if df.empty:
        _empty()
        return
    with card("perf-agents", "Agent scorecard", "Speed, safety and quality per agent. Success = the LLM judge's verdict"):
        view = pd.DataFrame({
            "Agent": df.agent, "Replies": df.turns,
            "p50 s": df.p50_s.round(1), "p95 s": df.p95_s.round(1), "Errors %": df.error_pct.round(1),
            "Checks %": df.guard_pct.round(1), "Fail-safe %": df.fail_safe_pct.round(1),
            "Escalated %": df.escalation_pct.round(1), "Tokens": df.tokens_per_turn.round(0),
            "₹/conv.": df.cost_per_conv_inr.round(3),
            "Judge success %": df.success_pct.round(0), "Score /5": df.avg_score.round(1)})
        st.dataframe(view, hide_index=True, use_container_width=True)
    a, b = st.columns(2, gap="medium")
    with a, card("perf-tools", "Tools", "How often each tool runs, fails, and how long it takes"):
        t = metrics.tool_stats(days)
        st.dataframe(t, hide_index=True, use_container_width=True) if not t.empty else st.caption("No tool calls.")
    with b, card("perf-guards", "Safety checks", "How often each guard had to step in"):
        g = metrics.guard_stats(days)
        st.dataframe(g, hide_index=True, use_container_width=True) if not g.empty else st.caption("None fired. 🎉")
    d = metrics.daily(days or 90, include_eval)
    if len(d) > 1:
        with card("perf-daily", "Replies and slowest-5% reply time per day"):
            base = alt.Chart(d).encode(x=alt.X("day:T", title=None))
            bars = base.mark_bar(color=PALETTE["indigo_soft"], stroke=PALETTE["indigo"]).encode(
                y=alt.Y("turns:Q", title="replies"))
            line = base.mark_line(color=PALETTE["rose"], point=True).encode(y=alt.Y("p95_s:Q", title="p95 seconds"))
            show(alt.layer(bars, line).resolve_scale(y="independent"), 220)


def _traces(days, include_eval):
    tr = metrics.traces(days, include_eval)
    if tr.empty:
        _empty()
        return
    f1, f2, f3 = st.columns(3)
    kinds = f1.multiselect("Kind", sorted(tr.kind.unique()), placeholder="All kinds")
    statuses = f2.multiselect("Status", sorted(tr.status.unique()), placeholder="All statuses")
    q = f3.text_input("Search question", placeholder="e.g. refund")
    if kinds:
        tr = tr[tr.kind.isin(kinds)]
    if statuses:
        tr = tr[tr.status.isin(statuses)]
    if q:
        tr = tr[tr.input.fillna("").str.contains(q, case=False, regex=False)]
    left, right = st.columns([2, 3], gap="medium")
    with left, card("tr-list", f"{len(tr)} traces", "Newest first"):
        top = tr.head(200)
        labels = {int(r.id): f"#{r.id} · {r.kind} · {r.name or ''} · {r.status} · {_v(r.latency_ms / 1000 if r.latency_ms == r.latency_ms else None, '{:.1f}s')}"
                  for r in top.itertuples()}
        if not labels:
            st.caption("Nothing matches.")
            return
        pick = st.radio("Trace", list(labels), format_func=labels.get, label_visibility="collapsed")
    d = metrics.trace_detail(pick)
    t = d["trace"]
    with right, card("tr-detail", f"Trace #{t['id']} · {t['kind']} · {t['name'] or ''}",
                     f"{t['started_at']} · channel {t['channel'] or '–'} · conversation {t['conversation_id'] or '–'}"):
        st.markdown(badge(t["status"], STATUS_TONE.get(t["status"], "neutral")) + " "
                    + (badge("escalated to a human", "amber") if t["escalated"] else ""), unsafe_allow_html=True)
        if t["input"]:
            st.markdown(f"**In:** {esc(t['input'][:600])}", unsafe_allow_html=True)
        if t["output"]:
            st.markdown(f"**Out:** {esc(t['output'][:900])}", unsafe_allow_html=True)
        if t["error"]:
            st.error(t["error"])
        # The waterfall: every LLM call and tool call in order, with its duration.
        steps = [{"step": f"LLM · {r.model}", "ms": r.latency_ms or 0, "type": "LLM call",
                  "detail": f"{r.prompt_tokens}+{r.completion_tokens} tokens · {r.tool_calls} tool calls · {r.status}",
                  "at": r.created_at, "order": r.id * 2} for r in d["llm_calls"].itertuples()]
        steps += [{"step": f"{s.type} · {s.name}", "ms": s.latency_ms or 0, "type": s.type.title(),
                   "detail": ("ok" if s.ok else "FAILED ") + (s.detail or ""), "at": s.created_at, "order": i * 2 + 1}
                  for i, s in enumerate(d["spans"].itertuples())]
        if steps:
            w = pd.DataFrame(steps).sort_values("at", kind="stable")
            w["n"] = range(1, len(w) + 1)
            w["label"] = w.n.astype(str) + ". " + w.step
            chart = alt.Chart(w).mark_bar(cornerRadiusEnd=4).encode(
                y=alt.Y("label:N", sort=None, title=None, axis=alt.Axis(labelLimit=260)),
                x=alt.X("ms:Q", title="milliseconds"),
                color=alt.Color("type:N", scale=alt.Scale(domain=["LLM call", "Tool", "Guard"],
                                                          range=[PALETTE["indigo"], PALETTE["teal"], PALETTE["rose"]]),
                                legend=alt.Legend(orient="bottom", title=None)),
                tooltip=["step", "ms", "detail"])
            show(chart, 80 + 32 * len(w))
        if d["meta"]:
            with st.expander("Metadata (tools, guards, SQL…)"):
                st.json(d["meta"])
        if not d["children"].empty:
            st.caption("Child traces")
            st.dataframe(d["children"], hide_index=True, use_container_width=True)


def _cost(days, include_eval):
    f = metrics.cost_by_feature(days, include_eval)
    if f.empty:
        _empty()
        return
    a, b = st.columns([3, 2], gap="medium")
    with a, card("cost-feature", "Where the tokens go", "Estimated cost by AI feature"):
        chart = alt.Chart(f).mark_bar(cornerRadiusEnd=4, color=PALETTE["indigo"]).encode(
            y=alt.Y("feature:N", sort="-x", title=None), x=alt.X("cost_inr:Q", title="₹ (estimated)"),
            tooltip=["feature", "calls", "tokens", alt.Tooltip("cost_inr:Q", format=".3f")])
        show(chart, 60 + 34 * len(f))
    with b, card("cost-assume", "Pricing assumptions", "Edit in kotler/config.py or KOTLER_LLM_PRICES"):
        st.dataframe(pd.DataFrame([{"model": m, "input $/1M": p[0], "output $/1M": p[1]}
                                   for m, p in config.LLM_PRICES_USD_PER_M.items() if m != "fake"]),
                     hide_index=True, use_container_width=True)
        st.caption(f"1 US$ = ₹{config.USD_INR:.0f}. On Gemini's free tier you pay ₹0: these numbers answer "
                   "\"what would it cost at scale?\". 1,000 conversations ≈ "
                   f"₹{metrics.summary(days, include_eval)['cost_per_conversation_inr'] * 1000:,.0f}.")
    calls = metrics.llm_calls(days, include_eval)
    with card("cost-models", "Model usage", "Fallback = the main model was overloaded and the backup answered"):
        m = calls.groupby(["model", "status"]).agg(calls=("id", "count"), avg_ms=("latency_ms", "mean"),
                                                    tokens=("prompt_tokens", "sum")).reset_index()
        m["avg_ms"] = m.avg_ms.round(0)
        st.dataframe(m, hide_index=True, use_container_width=True)


def _evals():
    evals.import_result_files()
    r = evals.runs()
    if r.empty:
        st.info("No eval runs yet. Run `python -m kotler.evals.shopping`, `…helpdesk` or `…ask_data` with a Gemini key.")
        return
    full = r[r.full]
    with card("ev-trend", "Pass rate per full run", "Partial re-runs (a few cases, e.g. checking a fix) are left out"):
        chart = alt.Chart(full).mark_line(point=True).encode(
            x=alt.X("started_at:T", title=None), y=alt.Y("pass_pct:Q", title="pass %", scale=alt.Scale(domain=[0, 100])),
            color=alt.Color("suite:N", legend=alt.Legend(orient="bottom", title=None)),
            tooltip=["suite", "started_at", "cases", "passed", "model"])
        show(chart, 220)
    cols = st.columns(max(1, len(full.suite.unique())), gap="medium")
    for col, suite in zip(cols, sorted(full.suite.unique())):
        c = evals.compare(suite)
        last = full[full.suite == suite].iloc[-1]
        with col, card(f"ev-{suite}", suite.replace("_", " ").title(),
                       f"Latest full run: {last.passed}/{last.cases} · {last.started_at[:16]}"):
            if not c:
                st.caption("Needs two full runs to compare.")
                continue
            st.markdown(badge(f"{len(c['regressions'])} regression{'s' if len(c['regressions']) != 1 else ''}", "bad" if c["regressions"] else "good") + " "
                        + badge(f"{len(c['fixed'])} fixed", "good" if c["fixed"] else "neutral"), unsafe_allow_html=True)
            for k, label in (("regressions", "Broke since last run"), ("fixed", "Fixed since last run"),
                             ("still_failing", "Still failing")):
                if c[k]:
                    st.markdown(f"**{label}:** " + ", ".join(f"`{x}`" for x in c[k]))
    with card("ev-runs", "All runs"):
        pick = st.selectbox("Run", r.id[::-1].tolist(), format_func=lambda i: (lambda x: f"#{i} · {x.suite} · "
                            f"{x.started_at[:16]} · {x.passed}/{x.cases}{'' if x.full else ' (partial)'}")(
                                r.set_index("id").loc[i]))
        res = evals.results(int(pick))
        st.dataframe(res, hide_index=True, use_container_width=True,
                     column_config={"passed": st.column_config.CheckboxColumn("passed")})


def _impact(days):
    df = impact.impact(days)
    measured = df[df.evidence == "measured"].inr.sum()
    kpi_strip([{"label": f"Measured net value ({days} days)", "value": f"₹{measured:,.0f}",
                "sub": "support handled by AI minus AI cost"}] +
              [{"label": r.lever.split(" (")[0], "value": f"₹{r.inr:,.0f}", "sub": f"{r.evidence} · {r.period}"}
               for r in df[df.evidence != "measured"].itertuples()])
    st.write("")
    for r in df.itertuples():
        with card(f"imp-{r.Index}", r.lever, r.period):
            st.markdown(f"<div style='font-size:1.4rem;font-weight:650'>₹{r.inr:,.0f}</div>"
                        + badge(r.evidence, EVIDENCE_TONE.get(r.evidence, "neutral")), unsafe_allow_html=True)
            st.caption(r.how)
    st.caption(f"Assumption: a human-handled support conversation costs ₹{impact.HUMAN_COST_PER_CONVERSATION:.0f} "
               "(₹25,000/month ÷ 22 days × 25 conversations). Measured = counted from real activity; modelled = model "
               "prediction on past data; simulated = Phase 6 simulator. Only measured values are added up.")
