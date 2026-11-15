"""Phase 2 tests. No network: a FakeLLM plays the model, so we test OUR code,
the tools, the agent loop, memory and safety, deterministically and for free."""

import json
from datetime import datetime

import pytest

from kotler import db
from kotler.agent import tools as T
from kotler.agent.shopping import MAX_STEPS, ShoppingAgent
from kotler.llm import FakeLLM, LLMError, LLMResponse, text_response, tool_call_response
from kotler.seed.generate import generate

END = datetime(2026, 11, 14, 20, 0, 0)


@pytest.fixture(scope="module", autouse=True)
def database(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    path = tmp_path_factory.mktemp("p2") / "p2.db"
    mp.setattr("kotler.config.DB_PATH", path)
    generate(n_customers=300, months=6, seed=3, end_date=END, db_path=path)
    db.ensure_schema(path)
    yield path
    mp.undo()


CTX = T.ToolContext()


# ------------------------------------------------------------------- tools
def test_search_respects_budget_and_skin_type():
    r = T.search_products(CTX, skin_type="dry", max_price=500)
    assert r["products"]
    for p in r["products"]:
        assert p["price_inr"] <= 500
        assert "dry" in p["suits_skin_types"] or "all" in p["suits_skin_types"]
        assert p["in_stock"]


def test_hinglish_concern_synonyms():
    """'pimples' / 'daane' must find acne products."""
    for word in ("pimples", "daane", "acne"):
        top = T.search_products(CTX, concern=word, skin_type="oily")["products"][0]
        assert "acne" in top["concerns"], word


def test_category_word_does_not_hide_products():
    names = [p["name"] for p in T.search_products(CTX, query="moisturizer", category="moisturizer",
                                                  skin_type="dry", max_price=500)["products"]]
    assert "Ceramide Barrier Repair Cream" in names


def test_unknown_concern_is_flagged_not_invented():
    r = T.search_products(CTX, concern="hair fall")
    assert "note" in r  # tells the model nothing targets it, so it can say so honestly


def test_out_of_stock_never_recommended():
    oos = db.query_df("SELECT name FROM products WHERE stock = 0").name.tolist()
    shown = {p["name"] for p in T.search_products(CTX, limit=8)["products"]}
    assert not shown & set(oos)


@pytest.mark.parametrize("skin,concern,budget", [("dry", None, 1000), ("oily", "acne", 1500),
                                                 ("combination", "dark spots", 1200), ("sensitive", None, 1300)])
def test_routine_within_budget_and_suitable(skin, concern, budget):
    r = T.build_routine(CTX, skin, concern, budget)
    assert r["within_budget"] and r["total_inr"] <= budget
    assert {s["step"] for s in r["steps"]} >= {"cleanse", "moisturize", "protect"}
    for s in r["steps"]:
        assert skin in s["suits_skin_types"] or "all" in s["suits_skin_types"]


def test_routine_with_concern_includes_treatment_when_affordable():
    steps = [s["step"] for s in T.build_routine(CTX, "oily", "acne", 1500)["steps"]]
    assert "treat" in steps


def test_routine_impossible_budget_is_reported():
    r = T.build_routine(CTX, "oily", None, 200)  # not even a cleanser fits
    assert not r["within_budget"] and "note" in r


def test_tight_budget_drops_optional_steps_by_priority():
    """₹800 can't buy a complete oily routine: keep cleanser + sunscreen, mention the upgrade."""
    r = T.build_routine(CTX, "oily", "acne", 800)
    steps = [s["step"] for s in r["steps"]]
    assert r["within_budget"] and r["total_inr"] <= 800
    assert steps[0] == "cleanse" and "protect" in steps
    assert not r["complete"] and r["skipped_steps"] and "complete routine costs" in r["note"]


def test_night_routine_has_no_sunscreen():
    steps = [s["step"] for s in T.build_routine(CTX, "dry", None, None, "night")["steps"]]
    assert "protect" not in steps and steps[0] == "cleanse"


def test_profile_hides_personal_data():
    p = T.get_my_profile(T.ToolContext(customer_id=1))
    assert p["logged_in"]
    flat = str(p)
    for secret in ("phone", "email", "address", "@example.com"):
        assert secret not in flat
    assert T.get_my_profile(T.ToolContext()) == {"logged_in": False}


def test_profile_tool_takes_no_customer_id_from_model():
    """The model can't pick whose profile to read: identity comes from the session."""
    schema = T.TOOLS["get_my_profile"][1]["function"]["parameters"]
    assert schema["properties"] == {}
    r = T.execute_tool("get_my_profile", {"customer_id": 2}, T.ToolContext(customer_id=None))
    assert "error" in r or r == {"logged_in": False}


def test_bad_tool_calls_return_errors_not_exceptions():
    assert "error" in T.execute_tool("search_products", {"max_price": "cheap"}, CTX)
    assert "error" in T.execute_tool("delete_database", {}, CTX)
    assert "error" in T.execute_tool("get_product_details", {"product_id": 99999}, CTX)


def test_tool_schemas_are_valid():
    for name, (fn, schema) in T.TOOLS.items():
        assert schema["function"]["name"] == name
        params = schema["function"]["parameters"]
        assert params["type"] == "object"
        assert set(params["required"]) <= set(params["properties"])


# -------------------------------------------------------------- agent loop
def test_agent_calls_tool_then_answers():
    llm = FakeLLM([
        tool_call_response("search_products", {"skin_type": "dry", "max_price": 500}),
        text_response("Try *Shea Butter Deep Nourish Moisturizer* (₹349)."),
    ])
    agent = ShoppingAgent(llm)
    turn = agent.reply("moisturizer for dry skin under 500")

    assert turn.reply.startswith("Try")
    assert [t.name for t in turn.tools] == ["search_products"]
    assert turn.llm_calls == 2
    # The second LLM call must contain the tool result, linked by tool_call_id.
    second = llm.calls[1]
    assert second[-2]["role"] == "assistant" and second[-2]["tool_calls"]
    assert second[-1]["role"] == "tool" and second[-1]["tool_call_id"] == "call_1"
    result = json.loads(second[-1]["content"])
    assert result["products"] and all(p["price_inr"] <= 500 for p in result["products"])


def test_agent_remembers_previous_turns():
    llm = FakeLLM([text_response("Is your skin oily or dry?"), text_response("Got it, oily.")])
    agent = ShoppingAgent(llm)
    agent.reply("suggest a face wash")
    agent.reply("oily")
    contents = [m["content"] for m in llm.calls[1] if m["role"] in ("user", "assistant")]
    assert contents == ["suggest a face wash", "Is your skin oily or dry?", "oily"]


def test_agent_stops_runaway_tool_loops():
    def always_tools(messages, tools):
        if tools is None:  # last step: tools withheld, model must answer
            return text_response("Here's what I found.")
        return tool_call_response("search_products", {})
    llm = FakeLLM(always_tools)
    turn = ShoppingAgent(llm).reply("anything")
    assert turn.llm_calls == MAX_STEPS
    assert turn.reply == "Here's what I found."


def test_agent_survives_llm_failure():
    def broken(messages, tools):
        raise LLMError("429 quota", "I'm getting a lot of questions right now. Please try again in a minute.")
    turn = ShoppingAgent(FakeLLM(broken)).reply("hi")
    assert turn.error and "try again" in turn.reply


def test_conversation_is_stored():
    llm = FakeLLM([tool_call_response("get_my_profile", {}), text_response("Hi Ananya!")])
    agent = ShoppingAgent(llm, customer_id=1)
    agent.reply("hi")
    rows = db.query_df("SELECT role, tool_name FROM messages WHERE conversation_id = ? ORDER BY id",
                       (agent.conversation_id,))
    assert rows.role.tolist() == ["user", "tool", "assistant"]
    assert rows.tool_name.iloc[1] == "get_my_profile"
    conv = db.query_one("SELECT customer_id, agent FROM conversations WHERE id = ?", (agent.conversation_id,))
    assert conv == {"customer_id": 1, "agent": "kavya"}  # conversations record which agent handled them


def test_system_prompt_is_personalised():
    llm = FakeLLM([text_response("ok")])
    ShoppingAgent(llm, customer_id=1).reply("hi")
    system = llm.calls[0][0]["content"]
    first_name = db.query_one("SELECT name FROM customers WHERE id = 1")["name"].split()[0]
    assert first_name in system and "Recommend ONLY products returned by tools" in system


def test_empty_model_answer_gets_fallback():
    turn = ShoppingAgent(FakeLLM([LLMResponse(content="", raw={"role": "assistant", "content": ""})])).reply("hi")
    assert turn.reply  # never show the customer an empty bubble


def test_whatsapp_formatting_converted_for_web():
    from views.shop_assistant import whatsapp_to_markdown as f
    out = f("Options:\n1. *Neem Face Wash* (₹299)\n2. *Gel Sunscreen*\nKya aapko kuch aur chahiye?")
    assert "**Neem Face Wash**" in out and "**Gel Sunscreen**" in out
    assert "**Gel Sunscreen**  \n  \nKya" in out  # list closed before the follow-up question
    assert f("**already bold** and 2*3*4") == "**already bold** and 2*3*4"


# ------------------------------------------------------- native Gemini backend
def test_gemini_message_translation():
    """OpenAI-style history -> Gemini format: roles, tool calls and grouped tool results."""
    from kotler.llm import GeminiLLM
    msgs = [
        {"role": "system", "content": "You are Kavya"},
        {"role": "user", "content": "dry skin moisturizer"},
        {"role": "assistant", "content": None, "tool_calls": [
            {"id": "a", "type": "function", "function": {"name": "search_products", "arguments": '{"skin_type": "dry"}'}},
            {"id": "b", "type": "function", "function": {"name": "get_my_profile", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "a", "content": '{"count": 1}'},
        {"role": "tool", "tool_call_id": "b", "content": '{"logged_in": false}'},
        {"role": "assistant", "content": "Try the Ceramide cream."},
    ]
    system, contents = GeminiLLM.to_gemini(msgs)
    assert system == {"parts": [{"text": "You are Kavya"}]}
    assert [c["role"] for c in contents] == ["user", "model", "user", "model"]
    assert contents[1]["parts"][0]["functionCall"] == {"name": "search_products", "args": {"skin_type": "dry"}}
    results = contents[2]["parts"]  # both tool results in ONE user turn, matched to their function names
    assert [r["functionResponse"]["name"] for r in results] == ["search_products", "get_my_profile"]
    assert results[0]["functionResponse"]["response"] == {"count": 1}


def test_gemini_replays_native_parts_unchanged():
    """Gemini's thought signatures must be sent back exactly as received."""
    from kotler.llm import GeminiLLM
    parts = [{"functionCall": {"name": "search_products", "args": {}}, "thoughtSignature": "abc123"}]
    _, contents = GeminiLLM.to_gemini([{"role": "assistant", "content": None, "_gemini_parts": parts,
                                         "tool_calls": [{"id": "x", "function": {"name": "search_products",
                                                                                  "arguments": "{}"}}]}])
    assert contents[0]["parts"] == parts


class _Resp:
    def __init__(self, status, data):
        self.status_code, self._data, self.text = status, data, json.dumps(data)

    def json(self):
        return self._data


def _gemini_ok(parts):
    return _Resp(200, {"candidates": [{"content": {"role": "model", "parts": parts}}],
                       "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5}})


def test_gemini_parses_tool_calls_and_falls_back_when_overloaded(monkeypatch):
    from kotler.llm import GeminiLLM
    llm = GeminiLLM(model="main-model", api_key="test", max_retries=0)
    llm.fallbacks = ["backup-model"]
    seen = []

    def fake_post(url, json, timeout, headers):
        seen.append(url.split("/models/")[1])
        assert headers == {"x-goog-api-key": "test"}
        if "main-model" in url:
            return _Resp(503, {"error": {"message": "high demand"}})
        return _gemini_ok([{"functionCall": {"name": "search_products", "args": {"skin_type": "oily"}}}])

    monkeypatch.setattr(llm._requests, "post", fake_post)
    resp = llm.chat([{"role": "user", "content": "hi"}], tools=T.TOOL_SCHEMAS)
    assert seen == ["main-model:generateContent", "backup-model:generateContent"]
    assert llm.last_model == "backup-model"
    assert resp.tool_calls[0].name == "search_products" and resp.tool_calls[0].arguments == {"skin_type": "oily"}
    assert resp.raw["tool_calls"][0]["function"]["name"] == "search_products"
    assert resp.prompt_tokens == 10


def test_gemini_bad_key_is_not_retried(monkeypatch):
    from kotler.llm import GeminiLLM
    llm = GeminiLLM(model="m", api_key="bad", max_retries=2)
    calls = []
    monkeypatch.setattr(llm._requests, "post",
                        lambda *a, **k: calls.append(1) or _Resp(400, {"error": {"message": "API key not valid"}}))
    with pytest.raises(LLMError) as e:
        llm.chat([{"role": "user", "content": "hi"}])
    assert len(calls) == 1 and "configured" in e.value.user_message


def test_gemini_schema_drops_empty_parameters():
    from kotler.llm import GeminiLLM
    decl = GeminiLLM._schema(T.TOOLS["get_my_profile"][1])
    assert "parameters" not in decl  # Gemini rejects objects with no properties
    assert "parameters" in GeminiLLM._schema(T.TOOLS["search_products"][1])
