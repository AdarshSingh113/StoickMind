from dataclasses import replace

import pandas as pd
import streamlit as st

from kotler import db
from kotler.agent import studio as S
from kotler.agent.judge import agent_scorecard, judge_conversation
from kotler.agent.prompts import compose_system_prompt
from kotler.agent.runtime import Agent
from kotler.agent.tools import TOOLS, WRITE_TOOLS, ToolContext, get_my_profile
from kotler.llm import get_llm
from views.shop_assistant import show_turn
from views.ui import badge, card, esc, kpi_strip, page_header


def _tool_label(name: str) -> str:
    desc = TOOLS[name][1]["function"]["description"].split(". ")[0]
    return f"{name}{' ✎' if name in WRITE_TOOLS else ''} · {desc}"


@st.cache_data(ttl=600)
def _customers():
    return db.query_df("""SELECT c.id, c.name, c.city, c.skin_type FROM customers c
                          JOIN orders o ON o.customer_id = c.id GROUP BY c.id ORDER BY COUNT(o.id) DESC LIMIT 40""")


def render():
    page_header("Agent Studio", "Create and improve AI agents without writing code: instructions, goal, "
                "success criteria and tools.", "AI agents")
    agents = S.list_agents()
    by_slug = {a.slug: a for a in agents}
    stats = db.query_one("""SELECT (SELECT COUNT(*) FROM conversations WHERE channel != 'eval') AS convs,
                                   (SELECT COUNT(*) FROM conversation_scores) AS judged,
                                   (SELECT AVG(achieved) FROM conversation_scores) AS success""")
    kpi_strip([
        {"label": "Agents", "value": f"{len(agents)}", "sub": f"{sum(a.status == 'live' for a in agents)} live"},
        {"label": "Conversations", "value": f"{stats['convs']:,}", "sub": "all agents"},
        {"label": "Judged", "value": f"{stats['judged']:,}", "sub": "scored against success criteria"},
        {"label": "Success rate", "value": f"{(stats['success'] or 0):.0%}" if stats["judged"] else "–",
         "sub": "judged conversations"},
        {"label": "Tools", "value": f"{len(TOOLS)}", "sub": f"{len(WRITE_TOOLS)} can change data"},
    ])
    st.write("")

    slug = st.session_state.get("studio_slug")
    if slug not in by_slug:
        slug = "kavya" if "kavya" in by_slug else agents[0].slug
    left, right = st.columns([1, 3], gap="medium")
    with left:
        _agent_list(agents, slug)
    with right:
        _editor(by_slug[slug])


# ------------------------------------------------------------------ list
def _agent_list(agents, current):
    st.markdown('<div class="k-section" style="margin-bottom:6px">Your agents</div>', unsafe_allow_html=True)
    for a in agents:
        selected = a.slug == current
        with st.container(key=f"card-agentlist-{a.slug}"):
            tone = "good" if a.status == "live" else "neutral"
            st.markdown(f"""<div style="display:flex;justify-content:space-between;align-items:center;gap:6px">
                <span style="font-weight:650">{esc(a.name)}</span>{badge(a.status.capitalize(), tone)}</div>
                <div class="k-section-sub">{esc(a.role)} · v{a.version}</div>""", unsafe_allow_html=True)
            if st.button("Editing" if selected else "Open", key=f"open-{a.slug}", use_container_width=True,
                         type="primary" if selected else "secondary", disabled=selected):
                st.session_state["studio_slug"] = a.slug
                st.rerun()
    with st.popover("New agent", icon=":material/add:", use_container_width=True):
        template = st.selectbox("Start from", list(S.TEMPLATES))
        name = st.text_input("Name shown to customers", placeholder="e.g. Riya")
        slug = st.text_input("ID", placeholder="e.g. winback-agent", help="Lowercase letters, numbers and dashes.")
        if st.button("Create draft", type="primary", use_container_width=True):
            try:
                if S.get_agent(slug.strip()):
                    raise S.AgentValidationError(f"An agent with ID '{slug}' already exists.")
                cfg = S.save_agent(replace(S.TEMPLATES[template], slug=slug.strip(), name=name.strip(),
                                           status="draft"), note=f"Created from template '{template}'")
                st.session_state["studio_slug"] = cfg.slug
                st.rerun()
            except S.AgentValidationError as e:
                st.error(str(e))


# ---------------------------------------------------------------- editor
def _editor(agent: S.AgentConfig):
    with card("agent-head"):
        a, b = st.columns([1, 1], vertical_alignment="center")
        status = badge("Live", "good") if agent.status == "live" else badge("Draft", "neutral")
        builtin = badge("Built-in", "indigo") if agent.is_builtin else ""
        a.markdown(f"""<div class="k-agent"><div class="k-agent-avatar">{esc(agent.name[:1])}</div><div>
            <div class="k-section">{esc(agent.name)} · {esc(agent.role)}</div>
            <div class="k-section-sub" style="font-size:.84rem">{status} {builtin} {badge(f"v{agent.version}", "neutral")}
            {badge(f"{len(agent.tools)} tools", "teal")}</div></div></div>""", unsafe_allow_html=True)
        c1, c2, c3 = b.columns(3)
        if agent.status == "draft":
            if c1.button("Publish", type="primary", use_container_width=True, icon=":material/rocket_launch:"):
                S.set_status(agent.slug, "live")
                st.rerun()
        elif c1.button("Pause", use_container_width=True, icon=":material/pause:", help="Unpublish (back to draft)"):
            S.set_status(agent.slug, "draft")
            st.rerun()
        with c2.popover("Copy", icon=":material/content_copy:", use_container_width=True):
            new_name = st.text_input("Name", value=f"{agent.name} copy", key="dup-name")
            new_slug = st.text_input("ID", value=f"{agent.slug}-copy", key="dup-slug")
            if st.button("Create copy", use_container_width=True):
                try:
                    st.session_state["studio_slug"] = S.duplicate(agent.slug, new_slug.strip(), new_name.strip()).slug
                    st.rerun()
                except S.AgentValidationError as e:
                    st.error(str(e))
        if c3.button("Delete", use_container_width=True, icon=":material/delete:", disabled=agent.is_builtin,
                     help="Built-in agents can't be deleted" if agent.is_builtin else "Delete this agent"):
            S.delete_agent(agent.slug)
            st.session_state.pop("studio_slug", None)
            st.rerun()

        if agent.description:
            st.caption(agent.description)
    st.write("")
    design, playground, history, performance = st.tabs(["Design", "Playground", "Versions", "Performance"])
    with design:
        _design(agent)
    with playground:
        _playground(agent)
    with history:
        _versions(agent)
    with performance:
        _performance(agent)


def _design(agent: S.AgentConfig):
    with st.form(f"design-{agent.slug}-{agent.version}", border=False):
        with card("design-who", "Identity"):
            c1, c2 = st.columns(2)
            name = c1.text_input("Name shown to customers", agent.name)
            role = c2.text_input("Role", agent.role, help="Completes: 'You are {name}, the {role} of Glow & Co.'")
            description = st.text_input("Internal description", agent.description)
        st.write("")
        with card("design-ctx", "Context & instructions", "What the agent should do, step by step"):
            instructions = st.text_area("Instructions", agent.instructions, height=300, label_visibility="collapsed")
        st.write("")
        g, s = st.columns(2, gap="medium")
        with g, card("design-goal", "Agent's goal", "A brief statement of the agent's purpose"):
            goal = st.text_area("Goal", agent.goal, height=110, label_visibility="collapsed")
        with s, card("design-success", "Success criteria", "Used in the prompt AND by the judge"):
            success = st.text_area("Success criteria", agent.success_criteria, height=110,
                                   label_visibility="collapsed")
        st.write("")
        with card("design-tools", "Tools & settings", "What the agent is allowed to do. ✎ = changes data"):
            tools = st.multiselect("Allowed tools", list(TOOLS), default=agent.tools, format_func=_tool_label)
            c1, c2 = st.columns(2)
            temperature = c1.slider("Creativity (temperature)", 0.0, 1.0, float(agent.temperature), 0.1,
                                    help="Lower = more consistent and factual. Higher = more varied wording.")
            max_steps = c2.slider("Max tool steps per message", 1, 8, int(agent.max_steps),
                                  help="Upper bound on LLM calls per customer message. Limits cost and loops.")
            note = st.text_input("What did you change?", placeholder="e.g. Ask budget before skin type")
        submitted = st.form_submit_button("Save new version", type="primary", icon=":material/save:")
    if submitted:
        try:
            saved = S.save_agent(replace(agent, name=name.strip(), role=role.strip(), description=description.strip(),
                                         instructions=instructions, goal=goal, success_criteria=success, tools=tools,
                                         temperature=temperature, max_steps=max_steps), note=note.strip())
            st.toast(f"Saved {saved.name} v{saved.version}", icon=":material/check_circle:")
            _reset_playground(agent.slug)
            st.rerun()
        except S.AgentValidationError as e:
            st.error(str(e))
    with st.expander("See the full system prompt sent to the model"):
        st.caption("Your instructions are combined with global safety rules that every agent must follow.")
        st.code(compose_system_prompt(agent, {"logged_in": False}), language="markdown", wrap_lines=True)


# ------------------------------------------------------------ playground
def _reset_playground(slug: str):
    st.session_state.pop(f"pg-agent-{slug}", None)
    st.session_state.pop(f"pg-turns-{slug}", None)
    st.session_state.pop(f"pg-verdict-{slug}", None)


def _playground(agent: S.AgentConfig):
    llm = get_llm()
    if llm is None:
        st.info("Add a Gemini API key to test agents here (see the Shop Assistant page for how).")
        return
    customers = _customers()
    labels = {None: "Guest (not logged in)"} | {int(r.id): f"{r.name} · {r.city} · {r.skin_type} skin"
                                                for r in customers.itertuples()}
    c1, c2, c3 = st.columns([3, 1, 1], vertical_alignment="bottom")
    customer_id = c1.selectbox("Test as", list(labels), format_func=labels.get, key=f"pg-cust-{agent.slug}",
                               on_change=_reset_playground, args=(agent.slug,))
    c2.button("Reset", on_click=_reset_playground, args=(agent.slug,), use_container_width=True,
              icon=":material/refresh:")
    judge = c3.button("Evaluate", use_container_width=True, icon=":material/grading:",
                      help="An LLM judge scores this conversation against the success criteria.")

    key = f"pg-agent-{agent.slug}"
    if key not in st.session_state or st.session_state[key].config.version != agent.version:
        st.session_state[key] = Agent(agent, llm, customer_id=customer_id, channel="playground")
        st.session_state[f"pg-turns-{agent.slug}"] = []
    runner: Agent = st.session_state[key]
    turns = st.session_state[f"pg-turns-{agent.slug}"]

    if judge:
        with st.spinner("Judging the conversation…"):
            st.session_state[f"pg-verdict-{agent.slug}"] = judge_conversation(llm, agent, runner.conversation_id)
        st.rerun()  # refresh the KPI strip and Performance tab with the new verdict
    verdict = st.session_state.get(f"pg-verdict-{agent.slug}")
    if verdict:
        tone = "good" if verdict["achieved"] else "bad"
        st.markdown(f"""<div style="border:1px solid #E6E8F0;border-radius:12px;padding:12px 14px;background:#fff">
            {badge("Success criteria met" if verdict["achieved"] else "Not met yet", tone)}
            {badge(f"Score {verdict['score']}/5", "indigo")}
            <div style="margin-top:6px;color:#475569;font-size:.9rem">{esc(verdict["reason"])}</div></div>""",
                    unsafe_allow_html=True)

    with st.container(height=520, border=False):
        if not turns:
            st.caption(f"Say hi to {agent.name} as a customer would. Tool calls appear under each reply.")
        for t in turns:
            show_turn(t)
    prompt = st.chat_input(f"Message {agent.name}…", key=f"pg-input-{agent.slug}")
    if prompt:
        with st.spinner(f"{agent.name} is thinking…"):
            turn = runner.reply(prompt)
        turns.append({"user": prompt, "turn": turn})
        st.session_state.pop(f"pg-verdict-{agent.slug}", None)
        st.rerun()
    st.caption(f"Conversation #{runner.conversation_id} · v{agent.version} · "
               f"{'logged in' if ToolContext(customer_id).customer_id else 'guest'}")


# -------------------------------------------------------------- versions
def _versions(agent: S.AgentConfig):
    rows = S.versions(agent.slug)
    st.caption("Every save is a new version. Restoring creates a new version from an old one; history is never lost.")
    for i, v in enumerate(rows):
        prev = rows[i + 1]["snapshot"] if i + 1 < len(rows) else None
        changed = S.diff(prev, v["snapshot"]) if prev else ["created"]
        status_change = prev and prev.get("status") != v["snapshot"].get("status")
        with st.container(key=f"card-ver-{agent.slug}-{v['version']}"):
            a, b = st.columns([5, 1], vertical_alignment="center")
            tags = " ".join(badge(c.replace("_", " "), "indigo") for c in changed)
            if status_change:
                tags += " " + badge(f"status → {v['snapshot']['status']}", "teal")
            current = badge("Current", "good") if v["version"] == agent.version else ""
            a.markdown(f"""<b>v{v['version']}</b> {current} <span class="k-section-sub">· {esc(v['created_at'])}</span>
                <div style="margin-top:4px">{tags or badge('no content change', 'neutral')}</div>
                <div class="k-section-sub" style="margin-top:4px">{esc(v['note'] or '')}</div>""",
                       unsafe_allow_html=True)
            if v["version"] != agent.version and b.button("Restore", key=f"restore-{agent.slug}-{v['version']}",
                                                            use_container_width=True):
                S.restore(agent.slug, v["version"])
                _reset_playground(agent.slug)
                st.rerun()


# ----------------------------------------------------------- performance
def _performance(agent: S.AgentConfig):
    usage = db.query_one("""SELECT COUNT(DISTINCT c.id) AS convs,
                                   COUNT(m.id) FILTER (WHERE m.role = 'user') AS messages,
                                   AVG(m.latency_ms) FILTER (WHERE m.role = 'assistant') AS latency,
                                   AVG(m.prompt_tokens + m.completion_tokens) FILTER (WHERE m.role = 'assistant') AS tokens
                            FROM conversations c LEFT JOIN messages m ON m.conversation_id = c.id
                            WHERE c.agent = ?""", (agent.slug,))
    tool_use = db.query_df("""SELECT m.tool_name AS tool, COUNT(*) AS calls FROM messages m
                              JOIN conversations c ON c.id = m.conversation_id
                              WHERE c.agent = ? AND m.role = 'tool' GROUP BY m.tool_name ORDER BY calls DESC""",
                           (agent.slug,))
    kpi_strip([
        {"label": "Conversations", "value": f"{usage['convs'] or 0:,}"},
        {"label": "Customer messages", "value": f"{usage['messages'] or 0:,}"},
        {"label": "Avg reply time", "value": f"{(usage['latency'] or 0) / 1000:.1f}s"},
        {"label": "Avg tokens / reply", "value": f"{usage['tokens'] or 0:,.0f}"},
    ])
    st.write("")
    a, b = st.columns(2, gap="medium")
    with a, card("perf-judge", "Success by version", "From conversations judged in the Playground"):
        sc = agent_scorecard(agent.slug)["by_version"]
        if sc.empty:
            st.caption("No judged conversations yet. Chat in the Playground and press Evaluate.")
        else:
            st.dataframe(sc.assign(version=sc.version.map(lambda v: f"v{v}")), hide_index=True,
                         use_container_width=True, column_config={
                             "success_pct": st.column_config.ProgressColumn("Success", format="%d%%", min_value=0,
                                                                            max_value=100),
                             "avg_score": st.column_config.NumberColumn("Avg score", format="%.1f / 5")})
    with b, card("perf-tools", "Tool usage"):
        if tool_use.empty:
            st.caption("No tool calls yet.")
        else:
            st.dataframe(tool_use, hide_index=True, use_container_width=True, column_config={
                "calls": st.column_config.ProgressColumn("Calls", format="%d", min_value=0,
                                                         max_value=int(tool_use.calls.max()))})
    recent = db.query_df("""SELECT s.created_at, 'v' || s.agent_version AS version, s.achieved, s.score, s.reason
                            FROM conversation_scores s WHERE s.agent_slug = ? ORDER BY s.id DESC LIMIT 10""",
                         (agent.slug,))
    if not recent.empty:
        st.write("")
        with card("perf-recent", "Latest verdicts"):
            recent["achieved"] = recent.achieved.map({1: "Met", 0: "Not met"})
            st.dataframe(recent, hide_index=True, use_container_width=True, column_config={
                "created_at": "When", "version": "Version", "achieved": "Criteria", "score": "Score",
                "reason": st.column_config.TextColumn("Judge's reason", width="large")})
    _ = pd  # pandas used implicitly via dataframes
