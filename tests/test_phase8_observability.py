"""Phase 8 tests: tracing, metrics and cost, eval history, business impact, and Ask-your-data guardrails."""

import json
import threading
from datetime import datetime

import pandas as pd
import pytest

from kotler import config, db
from kotler.agent import studio as S
from kotler.agent.runtime import Agent
from kotler.analytics import ask as A
from kotler.evals.ask_data import execution_match
from kotler.llm import FakeLLM, LLMError, LLMResponse, text_response, tool_call_response
from kotler.obs import evals, impact, metrics
from kotler.obs.trace import current_trace_id, ensure_tables, trace
from kotler.seed.generate import generate

END = datetime(2026, 11, 14, 20, 0, 0)


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    path = tmp_path / "p8.db"
    monkeypatch.setattr("kotler.config.DB_PATH", path)
    monkeypatch.setattr("kotler.config.DATA_DIR", tmp_path)
    generate(n_customers=120, months=4, seed=8, end_date=END, db_path=path)
    db.ensure_schema(path)
    ensure_tables()
    return path


def tokens(text, p=100, c=20):
    r = text_response(text)
    r.prompt_tokens, r.completion_tokens = p, c
    return r


def calls():
    return db.query_df("SELECT * FROM llm_calls ORDER BY id")


def traces_df():
    return db.query_df("SELECT * FROM ai_traces ORDER BY id")


# ------------------------------------------------------------------ tracing
def test_every_llm_call_is_logged_even_outside_a_trace():
    FakeLLM([tokens("hi")]).chat([{"role": "user", "content": "x"}])
    c = calls()
    assert len(c) == 1 and c.trace_id.isna().all() and c.prompt_tokens[0] == 100 and c.status[0] == "ok"


def test_calls_inside_a_trace_are_attached_and_traces_nest():
    llm = FakeLLM([tokens("a"), tokens("b")])
    with trace("outer", "x") as outer:
        llm.chat([])
        with trace("inner", "y"):
            llm.chat([])
        assert current_trace_id() == outer.id
    assert current_trace_id() is None
    t, c = traces_df(), calls()
    assert t.parent_id.tolist()[1] == t.id[0] and c.trace_id.tolist() == [t.id[0], t.id[1]]
    assert (t.status == "ok").all() and t.latency_ms.notna().all()


def test_llm_errors_are_logged_and_reraised():
    with pytest.raises(LLMError), trace("x"):
        FakeLLM([]).chat([])
    assert calls().status[0] == "error" and traces_df().status[0] == "error"


def test_traces_do_not_leak_between_threads():
    seen = {}

    def worker(name):
        with trace("t", name) as t:
            threading.Event().wait(0.05)
            seen[name] = (t.id, current_trace_id())
    ts = [threading.Thread(target=worker, args=(n,)) for n in "ab"]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert all(tid == cur for tid, cur in seen.values()) and seen["a"][0] != seen["b"][0]


def test_logging_failure_never_breaks_the_ai(monkeypatch):
    monkeypatch.setattr("kotler.obs.trace.db.get_conn", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    with trace("x") as t:
        assert FakeLLM([text_response("still works")]).chat([]).content == "still works"
    assert t.id is None


def test_agent_turn_trace_has_tools_and_status():
    llm = FakeLLM([tool_call_response("search_products", {"skin_type": "oily"}), tokens("Here are some options.")])
    Agent(S.get_agent("kavya"), llm, customer_id=1).reply("face wash for oily skin")
    t = traces_df().iloc[0]
    assert (t["kind"], t["name"], t["status"], t["escalated"]) == ("agent_turn", "kavya", "ok", 0)
    assert json.loads(t.meta)["tools"] == ["search_products"]
    spans = db.query_df("SELECT * FROM trace_spans")
    assert spans.type.tolist() == ["tool"] and spans.ok[0] == 1
    assert (calls().trace_id == t.id).all() and len(calls()) == 2


def test_invented_price_is_traced_as_fail_safe():
    llm = FakeLLM([text_response("Our serum is ₹12345."), text_response("Still ₹12345.")])
    Agent(S.get_agent("kavya"), llm).reply("price of the serum?")
    assert traces_df().status[0] == "fail_safe"
    guards = db.query_df("SELECT name FROM trace_spans WHERE type = 'guard'").name.tolist()
    assert guards == ["claim_check", "fail_safe"]


# ------------------------------------------------------------------ metrics
def test_cost_and_summary():
    assert metrics.cost_inr("gemini-3.5-flash", 1_000_000, 0) == pytest.approx(0.30 * config.USD_INR)
    llm = FakeLLM([tokens("ok", 1000, 100)] * 3)
    llm.model = "gemini-3.5-flash"
    for _ in range(3):
        Agent(S.get_agent("kavya"), llm).reply("hello")
    s = metrics.summary(30)
    assert s["agent_turns"] == 3 and s["conversations"] == 3 and s["tokens"] == 3300
    assert s["cost_inr"] == pytest.approx(3 * metrics.cost_inr("gemini-3.5-flash", 1000, 100))
    a = metrics.per_agent(30)
    assert a.agent.tolist() == ["kavya"] and a.turns[0] == 3 and a.error_pct[0] == 0


def test_eval_traffic_is_excluded_by_default():
    Agent(S.get_agent("kavya"), FakeLLM([text_response("hi")]), channel="eval").reply("hello")
    assert metrics.summary(30)["agent_turns"] == 0 and metrics.summary(30, include_eval=True)["agent_turns"] == 1


# ------------------------------------------------------------------ eval history
def _rows(results: dict) -> list[dict]:
    return [{"case": {"id": k}, "passed": v, "checks": {"x": v}, "latency_ms": 10} for k, v in results.items()]


def test_regressions_compare_full_runs_only():
    evals.save_run("shopping", "m", _rows({"a": True, "b": False, "c": True}), "2026-11-01 10:00:00")
    evals.save_run("shopping", "m", _rows({"a": False, "b": True, "c": True}), "2026-11-02 10:00:00")
    evals.save_run("shopping", "m", _rows({"b": False}), "2026-11-03 10:00:00")       # partial re-run
    c = evals.compare("shopping")
    assert c["regressions"] == ["a"] and c["fixed"] == ["b"] and c["compared"] == 3


def test_result_files_import_once(tmp_path):
    folder = tmp_path / "evals"
    folder.mkdir()
    (folder / "helpdesk-20261115-170036.json").write_text(json.dumps({"model": "m", "results": [
        {"case": "refund", "passed": True, "checks": {"a": True}, "latency_ms": 5}]}))
    assert evals.import_result_files(folder) == 1 and evals.import_result_files(folder) == 0
    r = evals.runs("helpdesk")
    assert r.started_at[0] == "2026-11-15 17:00:36" and r.passed[0] == 1


# ------------------------------------------------------------------ impact
def test_impact_counts_unescalated_helpdesk_conversations():
    for _ in range(2):
        Agent(S.get_agent("asha"), FakeLLM([text_response("Happy to help!")]), customer_id=1).reply("where is my order")
    df = impact.impact(30)
    support = df[df.lever.str.startswith("Support")].iloc[0]
    assert support["count"] == 2 and support.inr == 2 * impact.HUMAN_COST_PER_CONVERSATION
    assert support.evidence == "measured" and set(df.evidence) <= {"measured", "modelled", "simulated"}


# ------------------------------------------------------------------ ask your data: guardrails
@pytest.mark.parametrize("sql, reason", [
    ("SELECT name FROM customers", "customers.name"),
    ("SELECT * FROM customers", "customers.name"),
    ("SELECT COUNT(*) FROM customers WHERE phone LIKE '98%'", "customers.phone"),   # no filtering on PII either
    ("SELECT shipping_address FROM orders", "orders.shipping_address"),
    ("SELECT content FROM messages", "table messages"),
    ("SELECT * FROM pragma_table_info('customers')", "pragma_table_info"),
    ("SELECT 1; DELETE FROM orders", "one SQL statement"),
    ("DELETE FROM orders", "Only SELECT"),
    ("WITH RECURSIVE r(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM r) SELECT MAX(x) FROM r", "too long"),
])
def test_unsafe_queries_are_refused(sql, reason):
    with pytest.raises(A.UnsafeQuery, match=reason):
        A.run_sql(sql)


def test_aggregates_over_allowed_tables_work():
    df = A.run_sql("SELECT p.tier, COUNT(*) AS customers FROM customers c JOIN pincodes p USING (pincode) GROUP BY 1")
    assert df.customers.sum() == 120
    assert "name" not in A.schema_text().split("customers(")[1].split(")")[0].split(", ")


def test_grounding_check():
    df = pd.DataFrame({"tier": [1, 2], "revenue": [123456.4, 5000.0], "share": [0.123, 0.4]})
    assert A.ungrounded_numbers("Tier 1 brought ₹1,23,456, 12.3% of the total; tier 2 ₹5,000.", df) == []
    assert A.ungrounded_numbers("Together they made ₹128,456.", df) == ["128456"]   # a sum the model computed


def test_chart_validation():
    df = pd.DataFrame({"city": ["a", "b"], "orders": [3, 4], "label": ["x", "y"]})
    assert A.validate_chart({"type": "bar", "x": "city", "y": "orders"}, df)["type"] == "bar"
    assert A.validate_chart({"type": "bar", "x": "city", "y": "nope"}, df) == {"type": "none"}
    assert A.validate_chart({"type": "bar", "x": "city", "y": "label"}, df) == {"type": "none"}   # not numeric
    assert A.validate_chart({"type": "line", "x": "city", "y": "orders"}, df)["type"] == "bar"    # x isn't a date


def spec(sql, chart=None):
    return text_response(json.dumps({"sql": sql, "title": "T", "explanation": "e",
                                     "chart": chart or {"type": "none"}}))


# ------------------------------------------------------------------ ask your data: pipeline
def test_ask_verified_answer_and_trace():
    n = db.query_one("SELECT COUNT(*) AS n FROM orders")["n"]
    llm = FakeLLM([spec("SELECT COUNT(*) AS orders FROM orders"), text_response(f"We have {n:,} orders.")])
    res = A.ask(llm, "how many orders?")
    assert res.error is None and res.rows.orders[0] == n and res.answer_status == "verified"
    assert "2026-11-14" in llm.calls[0][0]["content"]          # 'today' = end of the data
    t = traces_df().iloc[-1]
    assert t.kind == "ask_data" and json.loads(t.meta)["sql"].startswith("SELECT COUNT")


def test_ask_withholds_an_answer_with_made_up_numbers():
    llm = FakeLLM([spec("SELECT COUNT(*) AS orders FROM orders"), text_response("We have 999999 orders."),
                   text_response("Roughly 888888 orders.")])
    res = A.ask(llm, "how many orders?")
    assert res.answer == "" and res.answer_status == "withheld" and res.ungrounded == ["888888"]
    assert len(res.rows) == 1   # the exact table is still shown


def test_ask_fixes_a_blocked_column_once():
    llm = FakeLLM([spec("SELECT name, city FROM customers"), spec("SELECT city, COUNT(*) AS n FROM customers GROUP BY city"),
                   text_response("Here is the split by city.")])
    res = A.ask(llm, "customers by city")
    assert res.attempts == 2 and res.error is None and "customers.name" in llm.calls[1][-1]["content"]


def test_ask_never_retries_a_write():
    res = A.ask(FakeLLM([spec("SELECT 1 AS x FROM orders WHERE 0"), text_response("No data matched.")]), "x")
    assert res.error is None
    res = A.ask(FakeLLM([spec("DELETE FROM orders")]), "delete everything")
    assert res.error and "Only SELECT" in res.error and res.attempts == 1  # refused, not retried
    assert db.query_one("SELECT COUNT(*) AS n FROM orders")["n"] > 0


def test_followups_see_previous_sql():
    llm = FakeLLM([spec("SELECT 1 AS x"), text_response("1")])
    A.ask(llm, "and by month?", [{"question": "revenue by tier", "sql": "SELECT tier FROM pincodes"}])
    assert "revenue by tier" in llm.calls[0][0]["content"] and "SELECT tier FROM pincodes" in llm.calls[0][0]["content"]


def test_execution_match_treats_numbers_as_text_the_same():
    gold = pd.DataFrame({"tier": [1, 2], "revenue": [100.0, 50.0]})
    assert execution_match(pd.DataFrame({"tier": ["1", "2"], "revenue_inr": [100.0, 50.0]}), gold)
    assert not execution_match(pd.DataFrame({"tier": ["1", "3"], "revenue_inr": [100.0, 50.0]}), gold)


def test_execution_match_ignores_names_order_and_extra_columns():
    gold = pd.DataFrame({"a": ["x", "y"], "b": [1.0, 2.0]})
    assert execution_match(pd.DataFrame({"cat": ["y", "x"], "n": [2, 1]}), gold)
    assert execution_match(pd.DataFrame({"cat": ["y", "x"], "share": [0.6, 0.3], "n": [2, 1]}), gold)
    assert not execution_match(pd.DataFrame({"cat": ["y", "x"], "n": [2, 5]}), gold)


def test_llm_response_dataclass_unchanged():
    assert LLMResponse(content="x").tool_calls == []
