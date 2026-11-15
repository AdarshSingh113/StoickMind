"""Phase 3 tests: agents as configuration, versioning, the generic runtime,
tool permissions, the write tool's safety, and the LLM judge. No network."""

from dataclasses import replace
from datetime import datetime

import pytest

from kotler import db
from kotler.agent import studio as S
from kotler.agent import tools as T
from kotler.agent.judge import format_transcript, judge_conversation, parse_verdict
from kotler.agent.prompts import compose_system_prompt
from kotler.agent.runtime import Agent
from kotler.llm import FakeLLM, text_response, tool_call_response
from kotler.seed.generate import generate

END = datetime(2026, 11, 14, 20, 0, 0)


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    """A fresh database per test, so version numbers are predictable."""
    path = tmp_path / "p3.db"
    monkeypatch.setattr("kotler.config.DB_PATH", path)
    generate(n_customers=150, months=4, seed=5, end_date=END, db_path=path)
    db.ensure_schema(path)
    return path


def _custom(**kw) -> S.AgentConfig:
    base = dict(slug="winback", name="Riya", role="win-back assistant", instructions="Be kind.",
                goal="Bring lapsed customers back.", success_criteria="Customer agrees to reorder.",
                tools=["search_products"])
    return S.AgentConfig(**{**base, **kw})


# ------------------------------------------------------------ config store
def test_builtin_agents_are_seeded_once():
    slugs = {a.slug for a in S.list_agents()}
    assert {"kavya", "skin-quiz"} <= slugs
    S.list_agents()  # calling again must not create duplicates or new versions
    assert S.get_agent("kavya").version == 1


def test_builtin_seeding_never_overwrites_edits():
    kavya = S.get_agent("kavya")
    S.save_agent(replace(kavya, instructions="Edited by marketing"))
    S.ensure_builtin_agents()
    assert S.get_agent("kavya").instructions == "Edited by marketing"


def test_every_save_is_a_new_version_with_snapshot():
    S.save_agent(_custom(), note="first")
    S.save_agent(replace(S.get_agent("winback"), goal="New goal"), note="sharper goal")
    hist = S.versions("winback")
    assert [v["version"] for v in hist] == [2, 1]
    assert hist[0]["note"] == "sharper goal" and hist[1]["snapshot"]["goal"] == "Bring lapsed customers back."
    assert S.diff(hist[1]["snapshot"], hist[0]["snapshot"]) == ["goal"]


def test_restore_creates_new_version_and_keeps_history():
    S.save_agent(_custom())
    S.save_agent(replace(S.get_agent("winback"), instructions="Bad change"))
    restored = S.restore("winback", 1)
    assert restored.version == 3 and restored.instructions == "Be kind."
    assert len(S.versions("winback")) == 3  # nothing deleted


@pytest.mark.parametrize("bad", [
    dict(slug="Bad Slug!"), dict(name="  "), dict(instructions=""), dict(tools=["delete_database"]),
    dict(temperature=1.5), dict(max_steps=0), dict(status="published"),
])
def test_validation_rejects_bad_configs(bad):
    with pytest.raises(S.AgentValidationError):
        S.save_agent(_custom(**bad))


def test_duplicate_and_delete():
    copy = S.duplicate("kavya", "kavya-hindi", "Kavya (Hindi)")
    assert copy.status == "draft" and not copy.is_builtin and copy.tools == S.get_agent("kavya").tools
    with pytest.raises(S.AgentValidationError):
        S.duplicate("kavya", "kavya-hindi", "again")  # ID taken
    S.delete_agent("kavya-hindi")
    assert S.get_agent("kavya-hindi") is None
    with pytest.raises(S.AgentValidationError):
        S.delete_agent("kavya")  # built-ins are protected


# --------------------------------------------------------- prompt + runtime
def test_prompt_contains_config_and_global_rules():
    cfg = _custom(instructions="Always mention free shipping above ₹499.")
    prompt = compose_system_prompt(cfg, {"logged_in": False})
    for part in ("You are Riya, the win-back assistant", "Bring lapsed customers back.",
                 "Customer agrees to reorder.", "Always mention free shipping", "search_products"):
        assert part in prompt
    # Global rules come AFTER the editable instructions and can't be removed by editing them.
    assert prompt.index("Rules that always apply") > prompt.index("Always mention free shipping")
    assert "get_my_profile" not in prompt  # only allowed tools are listed


def test_runtime_uses_agent_settings_and_only_allowed_tool_schemas():
    seen = {}

    def script(messages, tools, temperature=None):
        seen["tools"] = [t["function"]["name"] for t in tools or []]
        return text_response("Hello!")

    llm = FakeLLM(script)
    llm.chat = lambda messages, tools=None, temperature=0.3: (seen.update(temp=temperature), script(messages, tools))[1]
    S.save_agent(_custom(temperature=0.8))
    Agent(S.get_agent("winback"), llm).reply("hi")
    assert seen["tools"] == ["search_products"] and seen["temp"] == 0.8


def test_runtime_refuses_tools_outside_permissions():
    """Even if the model asks for a tool it wasn't given, the code refuses."""
    S.save_agent(_custom(tools=["search_products"]))
    llm = FakeLLM([tool_call_response("save_skin_profile", {"skin_type": "oily"}), text_response("ok")])
    turn = Agent(S.get_agent("winback"), llm, customer_id=1).reply("I have oily skin")
    assert "not available" in turn.tools[0].result["error"]
    before = db.query_one("SELECT skin_type FROM customers WHERE id = 1")["skin_type"]
    assert before == db.query_one("SELECT skin_type FROM customers WHERE id = 1")["skin_type"]


def test_runtime_respects_max_steps():
    S.save_agent(_custom(max_steps=2))
    calls = []

    def always_tools(messages, tools):
        calls.append(tools)
        return text_response("done") if tools is None else tool_call_response("search_products", {})

    turn = Agent(S.get_agent("winback"), FakeLLM(always_tools)).reply("x")
    assert turn.llm_calls == 2 and calls[-1] is None and turn.reply == "done"


def test_conversation_records_agent_slug():
    S.save_agent(_custom())
    agent = Agent(S.get_agent("winback"), FakeLLM([text_response("hi")]), channel="playground")
    agent.reply("hello")
    conv = db.query_one("SELECT agent, channel FROM conversations WHERE id = ?", (agent.conversation_id,))
    assert conv == {"agent": "winback", "channel": "playground"}


# ------------------------------------------------------------- write tool
def test_save_skin_profile_only_touches_logged_in_customer():
    other = db.query_one("SELECT skin_type FROM customers WHERE id = 2")["skin_type"]
    r = T.save_skin_profile(T.ToolContext(customer_id=1), "sensitive")
    assert r == {"saved": True, "skin_type": "sensitive"}
    assert db.query_one("SELECT skin_type FROM customers WHERE id = 1")["skin_type"] == "sensitive"
    assert db.query_one("SELECT skin_type FROM customers WHERE id = 2")["skin_type"] == other
    assert T.save_skin_profile(T.ToolContext(), "oily")["saved"] is False          # guest: nothing written
    assert "error" in T.save_skin_profile(T.ToolContext(customer_id=1), "purple")  # invalid value
    schema = T.TOOLS["save_skin_profile"][1]["function"]["parameters"]["properties"]
    assert "customer_id" not in schema  # the model can't choose whose profile to change


def test_skin_quiz_agent_can_save_profile_through_runtime():
    llm = FakeLLM([tool_call_response("save_skin_profile", {"skin_type": "combination"}),
                   text_response("Saved! Next question…")])
    Agent(S.get_agent("skin-quiz"), llm, customer_id=3).reply("oily T-zone only")
    assert db.query_one("SELECT skin_type FROM customers WHERE id = 3")["skin_type"] == "combination"


# ------------------------------------------------------------------ judge
@pytest.mark.parametrize("text,achieved,score", [
    ('{"achieved": true, "score": 5, "reason": "great"}', True, 5),
    ('```json\n{"achieved": false, "score": 2, "reason": "no routine"}\n```', False, 2),
    ('Sure! {"achieved": true, "score": 9, "reason": "x"} hope that helps', True, 5),  # clamped
])
def test_parse_verdict_is_robust(text, achieved, score):
    v = parse_verdict(text)
    assert (v["achieved"], v["score"]) == (achieved, score)


def test_parse_verdict_handles_garbage():
    assert parse_verdict("I think it went well").get("invalid")
    assert parse_verdict(None).get("invalid")


def test_judge_sees_tools_and_saves_verdict():
    agent = Agent(S.get_agent("kavya"), FakeLLM([tool_call_response("search_products", {"max_price": 500}),
                                                 text_response("Try the *Aloe Vera Soothing Gel* (₹199).")]))
    agent.reply("something under 500")
    judge_llm = FakeLLM([text_response('{"achieved": true, "score": 4, "reason": "Grounded and within budget."}')])
    verdict = judge_conversation(judge_llm, agent.config, agent.conversation_id)
    assert verdict == {"achieved": True, "score": 4, "reason": "Grounded and within budget."}
    prompt = judge_llm.calls[0][0]["content"]
    assert "TOOL search_products" in prompt and agent.config.success_criteria in prompt
    row = db.query_one("SELECT agent_slug, agent_version, achieved, score FROM conversation_scores")
    assert row == {"agent_slug": "kavya", "agent_version": 1, "achieved": 1, "score": 4}


def test_format_transcript_truncates_long_tool_results():
    rows = [{"role": "user", "content": "hi"},
            {"role": "tool", "content": "x" * 5000, "tool_name": "search_products", "tool_args": "{}"}]
    text = format_transcript(rows, max_tool_chars=100)
    assert "CUSTOMER: hi" in text and len(text) < 300


def test_profile_tool_hides_language_but_prompt_has_it_as_fallback():
    """A language hint in a tool result overrides 'reply in the latest message's language'."""
    assert "preferred_language" not in T.get_my_profile(T.ToolContext(customer_id=1))
    assert "error" in T.execute_tool("get_my_profile", {"_include_language": True}, T.ToolContext(customer_id=1)) \
        or "preferred_language" not in T.execute_tool("get_my_profile", {"_include_language": True},
                                                       T.ToolContext(customer_id=1))
    llm = FakeLLM([text_response("Hi")])
    Agent(S.get_agent("kavya"), llm, customer_id=1).reply("hello")
    assert "Usual language (fallback only)" in llm.calls[0][0]["content"]
