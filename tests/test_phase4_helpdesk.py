"""Phase 4 tests: policies + retrieval, and every guardrail of the order tools.
Each test sets up exactly the order state it needs, so results don't depend on random data."""

from datetime import datetime, timedelta

import pytest

from kotler import db, policy
from kotler.agent import support_tools as ST
from kotler.agent.copilot import ai_stats, run_ticket
from kotler.agent.retrieval import search_policies
from kotler.agent.studio import get_agent
from kotler.agent.tools import TOOLS, WRITE_TOOLS, ToolContext
from kotler.llm import FakeLLM, text_response, tool_call_response
from kotler.seed.generate import generate

END = datetime(2026, 11, 14, 20, 0, 0)
FMT = "%Y-%m-%d %H:%M:%S"


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    path = tmp_path / "p4.db"
    monkeypatch.setattr("kotler.config.DB_PATH", path)
    generate(n_customers=150, months=4, seed=9, end_date=END, db_path=path)
    db.ensure_schema(path)
    return path


def make_order(customer_id=1, status="delivered", payment="prepaid", total=500.0, delivered_days_ago=2) -> dict:
    """Reshape one of the customer's orders into exactly the state a test needs."""
    oid = db.query_one("SELECT id FROM orders WHERE customer_id = ? ORDER BY id LIMIT 1", (customer_id,))["id"]
    now = ST.store_now()
    delivered = (now - timedelta(days=delivered_days_ago)).strftime(FMT) if status in ("delivered", "returned") else None
    with db.get_conn() as conn:
        conn.execute("UPDATE orders SET status = ?, payment_method = ?, total = ?, delivered_at = ?, "
                     "expected_delivery = ? WHERE id = ?",
                     (status, payment, total, delivered, (now + timedelta(days=2)).strftime(FMT), oid))
    return db.query_one("SELECT o.*, c.phone FROM orders o JOIN customers c ON c.id = o.customer_id WHERE o.id = ?", (oid,))


def first_item(order_id):
    return db.query_one("SELECT p.name FROM order_items oi JOIN products p ON p.id = oi.product_id "
                        "WHERE oi.order_id = ?", (order_id,))["name"]


def me(customer_id=1):
    return ToolContext(customer_id=customer_id, agent_slug="asha")


# ------------------------------------------------------- policies + RAG
RETRIEVAL_CASES = {
    "what is your return policy": "returns", "mera paisa wapas kab aayega": "refunds", "pump toota hua aaya": "damaged",
    "can I cancel after shipping": "cancellation", "I got rashes from the serum": "allergic_reaction",
    "give me a coupon code": "discounts", "when will my order be delivered": "shipping", "COD available?": "cod",
    "refund for cash on delivery order": "refunds", "what time is support open": "contact",
    "order cancel karna hai": "cancellation", "product leak ho raha tha": "damaged",
}


@pytest.mark.parametrize("query,expected", RETRIEVAL_CASES.items())
def test_retrieval_finds_the_right_policy(query, expected):
    assert search_policies(query, 1)[0]["policy"] == expected


def test_policy_text_and_code_share_the_same_numbers():
    text = " ".join(policy.POLICIES.values())
    assert f"{policy.RETURN_WINDOW_DAYS} days of delivery" in text
    assert f"₹{policy.AUTO_REFUND_LIMIT:,.0f}" in text and f"{policy.MAX_DISCOUNT_PCT}%" in text


# ------------------------------------------------------------- identity
def test_guest_sees_nothing_until_verified():
    o = make_order()
    ctx = ToolContext()
    assert "not verified" in ST.get_order_status(ctx, o["order_number"])["error"]
    assert "not verified" in ST.list_my_orders(ctx)["error"]


def test_verification_binds_customer_and_locks_after_three_failures():
    o = make_order()
    ctx = ToolContext()
    wrong = ST.verify_order(ctx, o["order_number"], "0000" if not o["phone"].endswith("0000") else "1111")
    unknown = ST.verify_order(ctx, "KTL-999999", o["phone"][-4:])
    assert wrong["note"] == unknown["note"]  # same answer: doesn't reveal whether the order exists
    ST.verify_order(ctx, o["order_number"], "1234" if not o["phone"].endswith("1234") else "4321")
    locked = ST.verify_order(ctx, o["order_number"], o["phone"][-4:])  # correct, but too late
    assert locked.get("locked") and ctx.customer_id is None

    ctx2 = ToolContext()
    ok = ST.verify_order(ctx2, o["order_number"].lower().replace("ktl-", ""), f"+91 {o['phone']}")
    assert ok["verified"] and ctx2.customer_id == o["customer_id"]


def test_cannot_access_another_customers_order():
    other = make_order(customer_id=2)
    r = ST.get_order_status(me(1), other["order_number"])
    assert "error" in r and "No order" in r["error"]
    assert "error" in ST.cancel_order(me(1), other["order_number"], "x")
    assert "error" in ST.request_refund(me(1), other["order_number"], "x")


# ---------------------------------------------------------- cancellation
def test_cancel_before_shipping():
    o = make_order(status="placed", payment="prepaid", total=650)
    r = ST.cancel_order(me(), o["order_number"], "changed mind")
    assert r["cancelled"] and "₹650" in r["refund"]
    assert db.query_one("SELECT status FROM orders WHERE id = ?", (o["id"],))["status"] == "cancelled"
    assert db.query_one("SELECT action, status FROM order_actions") == {"action": "cancel", "status": "done"}


def test_cannot_cancel_after_shipping():
    o = make_order(status="shipped")
    r = ST.cancel_order(me(), o["order_number"], "too slow")
    assert r["cancelled"] is False
    assert db.query_one("SELECT status FROM orders WHERE id = ?", (o["id"],))["status"] == "shipped"


def test_cod_cancellation_has_nothing_to_refund():
    o = make_order(status="placed", payment="cod")
    assert "nothing to refund" in ST.cancel_order(me(), o["order_number"], "x")["refund"]


# --------------------------------------------------------------- coupons
@pytest.mark.parametrize("pct", [0, 11, 50, 90])
def test_discount_above_limit_is_refused(pct):
    r = ST.offer_discount(me(), pct, "customer asked")
    assert r["issued"] is False
    assert db.query_one("SELECT COUNT(*) AS n FROM coupons_issued")["n"] == 0


def test_discount_once_per_cooldown():
    first = ST.offer_discount(me(), 10, "keep order")
    second = ST.offer_discount(me(), 5, "again")
    assert first["issued"] and first["code"].startswith("CARE10-")
    assert second["issued"] is False and second["existing_coupon"] == first["code"]
    assert ST.offer_discount(ToolContext(), 5, "guest")["error"]


# ---------------------------------------------------- damaged / refunds
def test_damaged_item_small_order_is_replaced_automatically():
    o = make_order(total=900, delivered_days_ago=3)
    r = ST.report_damaged_item(me(), o["order_number"], first_item(o["id"]), "pump broken")
    assert r["accepted"] and r["status"].startswith("approved")
    again = ST.report_damaged_item(me(), o["order_number"], first_item(o["id"]), "pump broken")
    assert again["already_raised"]  # no duplicate replacements


def test_damaged_item_high_value_needs_approval():
    o = make_order(total=policy.REPLACEMENT_AUTO_LIMIT + 1, delivered_days_ago=1)
    r = ST.report_damaged_item(me(), o["order_number"], first_item(o["id"]), "cracked jar")
    assert "care team" in r["status"]
    assert db.query_one("SELECT status FROM order_actions WHERE action = 'replacement'")["status"] == "pending_approval"


def test_damaged_item_outside_window_or_wrong_product():
    late = make_order(delivered_days_ago=policy.RETURN_WINDOW_DAYS + 3)
    assert ST.report_damaged_item(me(), late["order_number"], first_item(late["id"]), "x")["accepted"] is False
    o = make_order(delivered_days_ago=1)
    r = ST.report_damaged_item(me(), o["order_number"], "Unicorn Shampoo", "x")
    assert r["accepted"] is False and r["items_in_order"]


def test_refund_rules():
    small = make_order(total=800, payment="prepaid", delivered_days_ago=2)
    r = ST.request_refund(me(), small["order_number"], "didn't suit me")
    assert r["status"].startswith("approved") and r["amount_inr"] == 800


@pytest.mark.parametrize("payment,total", [("prepaid", policy.AUTO_REFUND_LIMIT + 200), ("cod", 300)])
def test_large_or_cod_refunds_need_a_human(payment, total):
    o = make_order(total=total, payment=payment, delivered_days_ago=2)
    r = ST.request_refund(me(), o["order_number"], "damaged")
    assert r["accepted"] and "care team" in r["status"]
    assert db.query_one("SELECT status FROM order_actions WHERE action = 'refund'")["status"] == "pending_approval"


def test_refund_refused_when_not_delivered_or_late():
    assert ST.request_refund(me(), make_order(status="shipped")["order_number"], "x")["accepted"] is False
    late = make_order(delivered_days_ago=policy.RETURN_WINDOW_DAYS + 1)
    assert ST.request_refund(me(), late["order_number"], "x")["accepted"] is False


# ----------------------------------------------------- escalation + humans
def test_escalation_creates_ticket_and_approval_item():
    r = ST.escalate_to_human(me(), "Customer threatens consumer court over late refund", "high")
    assert r["escalated"] and r["a_human_will_reply"] == "within 1 hour"
    t = db.query_one("SELECT status, priority, category FROM support_tickets ORDER BY id DESC LIMIT 1")
    assert t == {"status": "escalated", "priority": "high", "category": "escalated_by_ai"}
    pending = ST.pending_actions()
    assert pending.action.tolist() == ["escalation"]
    ST.decide_action(int(pending.id.iloc[0]), True, "Priya")
    assert db.query_one("SELECT status, resolved_by FROM support_tickets ORDER BY id DESC LIMIT 1") == \
        {"status": "resolved", "resolved_by": "human"}
    assert ST.pending_actions().empty


def test_guest_escalation_asks_for_contact():
    r = ST.escalate_to_human(ToolContext(), "guest wants a human", "medium")
    assert r["escalated"] and "phone number or email" in r["note"]


def test_human_can_reject_and_decisions_are_final():
    o = make_order(total=2000, delivered_days_ago=1)
    ST.request_refund(me(), o["order_number"], "x")
    aid = int(ST.pending_actions().id.iloc[0])
    assert ST.decide_action(aid, False, "Priya")["ok"]
    assert ST.decide_action(aid, True, "Priya")["ok"] is False  # already decided


# ------------------------------------------------------- agent + copilot
def test_asha_has_only_support_tools_and_they_are_flagged():
    asha = get_agent("asha")
    assert asha.status == "live" and set(asha.tools) <= set(TOOLS)
    assert {"cancel_order", "request_refund", "offer_discount"} <= WRITE_TOOLS
    assert "save_skin_profile" not in asha.tools


def test_copilot_resolves_open_ticket():
    o = make_order(status="shipped")
    with db.get_conn() as conn:
        tid = conn.execute("INSERT INTO support_tickets (customer_id, order_id, created_at, channel, category, priority, "
                           "status, message) VALUES (1, ?, ?, 'whatsapp', 'order_status', 'medium', 'open', ?)",
                           (o["id"], END.strftime(FMT), f"Where is {o['order_number']}?")).lastrowid
    llm = FakeLLM([tool_call_response("get_order_status", {"order_number": o["order_number"]}),
                   text_response("It's on the way with the courier.")])
    turn, outcome, _ = run_ticket(llm, tid)
    assert outcome == "resolved" and turn.tools[0].result["status"] == "shipped"
    assert db.query_one("SELECT status, resolved_by FROM support_tickets WHERE id = ?", (tid,)) == \
        {"status": "resolved", "resolved_by": "ai"}
    assert ai_stats()["resolved_rate"] == 1


def test_copilot_escalation_outcome():
    with db.get_conn() as conn:
        tid = conn.execute("INSERT INTO support_tickets (customer_id, created_at, channel, category, priority, status, "
                           "message) VALUES (1, ?, 'email', 'allergic_reaction', 'high', 'open', 'burning rash!')",
                           (END.strftime(FMT),)).lastrowid
    llm = FakeLLM([tool_call_response("escalate_to_human", {"summary": "reaction", "priority": "high"}),
                   text_response("Please stop using it; our care team will call you within the hour.")])
    _, outcome, _ = run_ticket(llm, tid)
    assert outcome == "escalated"
    assert db.query_one("SELECT status FROM support_tickets WHERE id = ?", (tid,))["status"] == "escalated"


# ------------------------------------------------------------- language
@pytest.mark.parametrize("text,expected", [
    ("order KTL-100776 mein lip balm leak ho raha tha, refund chahiye", "hinglish"),
    ("Bhai order abhi tak nahi aaya", "hinglish"), ("800 ke andar", "hinglish"),
    ("Where is my order? It's been 6 days", "en"), ("Give me 50% off or I'm cancelling", "en"),
    ("मेरा ऑर्डर कहाँ है", "hi"), ("ok", None), ("4821", None),
])
def test_language_detection(text, expected):
    from kotler.agent.language import detect_language
    assert detect_language(text) == expected


def test_language_note_is_sent_but_not_stored():
    from kotler.agent.runtime import Agent
    llm = FakeLLM([text_response("Aapka order ship ho gaya hai.")])
    agent = Agent(get_agent("asha"), llm, customer_id=1)
    agent.reply("mera order kab aayega bhai")
    assert "Reply in Hinglish" in llm.calls[0][-1]["content"]
    stored = db.query_one("SELECT content FROM messages WHERE conversation_id = ? AND role = 'user'",
                          (agent.conversation_id,))["content"]
    assert stored == "mera order kab aayega bhai"


def test_english_reply_to_hinglish_customer_is_rewritten_once():
    from kotler.agent.runtime import Agent
    llm = FakeLLM([text_response("Your order has shipped with Delhivery, tracking AWB123."),
                   text_response("Aapka order Delhivery se ship ho gaya hai, tracking AWB123 hai.")])
    turn = Agent(get_agent("asha"), llm, customer_id=1).reply("mera order kab aayega bhai")
    assert turn.reply.startswith("Aapka order") and "AWB123" in turn.reply and turn.llm_calls == 2
    assert "Keep every fact" in llm.calls[1][0]["content"]


def test_english_customer_gets_no_rewrite():
    from kotler.agent.runtime import Agent
    llm = FakeLLM([text_response("Your order has shipped.")])
    turn = Agent(get_agent("asha"), llm, customer_id=1).reply("Where is my order please?")
    assert turn.llm_calls == 1


# ------------------------------------------------------ claim verification
from types import SimpleNamespace as _T  # noqa: E402

from kotler.agent.claims import find_unbacked_claims  # noqa: E402

_ALLOWED = {"escalate_to_human", "cancel_order", "request_refund", "report_damaged_item", "offer_discount"}


@pytest.mark.parametrize("reply,traces,n_problems", [
    # the two real failures found by the evals
    ("I am escalating this to our senior care team. Your reference number is #8800001875.", [], 2),
    ("I have escalated this to our care team as a priority (Ref: #HUM-9921).", [], 2),
    # backed by a successful tool call: fine
    ("I have escalated this (Ref: ESC-5).", [_T(name="escalate_to_human", result={"escalated": True, "reference": "ESC-5"})], 0),
    ("Your order has been successfully cancelled.", [_T(name="cancel_order", result={"cancelled": True})], 0),
    # the tool ran but FAILED: claiming success is still wrong
    ("Your order has been successfully cancelled.", [_T(name="cancel_order", result={"cancelled": False})], 1),
    # offers are not claims
    ("Would you like me to escalate this to our care team?", [], 0),
    ("I can cancel it for you if you confirm.", [], 0),
    # Hinglish
    ("Maine escalate kar diya hai, team aapse contact karegi.", [], 1),
    ("Maine damage report raise kar di hai (Reference: RPL-1).",
     [_T(name="report_damaged_item", result={"accepted": True, "reference": "RPL-1"})], 0),
    # invented coupon
    ("I've issued a 10% coupon: CARE10-AB12CD", [], 2),
])
def test_claim_checker(reply, traces, n_problems):
    assert len(find_unbacked_claims(reply, traces, _ALLOWED)) == n_problems


def test_false_claim_gets_corrected_by_calling_the_tool():
    from kotler.agent.runtime import Agent
    llm = FakeLLM([text_response("I have escalated this to our team (Ref: #HUM-1)."),  # lie
                   tool_call_response("escalate_to_human", {"summary": "rash", "priority": "high"}),
                   text_response("Sorry about this. I've escalated it to our care team (reference ESC-1).")])
    turn = Agent(get_agent("asha"), llm, customer_id=1).reply("burning rash after the serum")
    assert "Automatic check failed" in llm.calls[1][-1]["content"]
    assert [t.name for t in turn.tools] == ["escalate_to_human"] and "ESC-1" in turn.reply
    assert turn.guard and db.query_one("SELECT COUNT(*) AS n FROM order_actions WHERE action='escalation'")["n"] == 1


def test_persistent_false_claim_triggers_fail_safe_escalation():
    from kotler.agent.runtime import Agent
    llm = FakeLLM(lambda messages, tools: text_response("I have escalated this, ref #HUM-77."))
    turn = Agent(get_agent("asha"), llm, customer_id=1).reply("I want to talk to a manager NOW")
    assert "#HUM-77" not in turn.reply and "care team" in turn.reply
    real = db.query_one("SELECT action, status FROM order_actions")
    assert real == {"action": "escalation", "status": "pending_approval"}  # a real human will see it
    assert any("fail-safe" in g for g in turn.guard)


def test_shopping_agent_has_no_claim_checks():
    """Kavya can't act, so her replies aren't checked for action claims."""
    from kotler.agent.runtime import Agent
    llm = FakeLLM([text_response("I've passed it to our team, they will help.")])
    turn = Agent(get_agent("kavya"), llm).reply("hi")
    assert turn.llm_calls == 1 and not turn.guard


# ---------------------------------------------------------- price grounding
from kotler.agent.claims import find_ungrounded_prices  # noqa: E402

_ROUTINE = _T(name="build_routine", result={"steps": [{"price_inr": 299.0}, {"price_inr": 449.0}], "total_inr": 748.0,
                                             "note": "The cheapest complete routine costs ₹1396."})


@pytest.mark.parametrize("reply,traces,context,n", [
    ("**Glow & Co. Neem Face Wash** (₹250), Serum (₹350). Total ₹750", [], ["800 ke andar"], 1),  # the real failure
    ("Neem (₹299) + Sunscreen (₹449) = ₹748. Complete: ₹1,396. Budget ₹800", [_ROUTINE], ["800 ke andar"], 0),
    ("Total ₹747", [_ROUTINE], [], 1),
    ("Great choice, the Neem Face Wash is ₹299.", [], ["1. Neem Face Wash (₹299)"], 0),  # repeated from earlier reply
    ("No prices in this reply.", [], [], 0),
])
def test_price_grounding(reply, traces, context, n):
    assert len(find_ungrounded_prices(reply, traces, context)) == n


def test_invented_prices_trigger_correction_with_real_tool():
    from kotler.agent.runtime import Agent
    llm = FakeLLM([text_response("Try **Magic Glow Serum** (₹123)."),
                   tool_call_response("search_products", {"skin_type": "oily", "max_price": 600}),
                   text_response("No problem.")])
    turn = Agent(get_agent("kavya"), llm).reply("serum for oily skin under 600")
    assert "Automatic check failed" in llm.calls[1][-1]["content"]
    assert [t.name for t in turn.tools] == ["search_products"] and "₹123" not in turn.reply


def test_quiz_budget_options_from_instructions_are_not_flagged():
    """False alarm found in a real run: '(under ₹800 / ₹800-1500 / above ₹1500)' comes from the quiz instructions."""
    from kotler.agent.runtime import Agent
    llm = FakeLLM([text_response("4. Budget for the whole routine? (under ₹800 / ₹800-1500 / above ₹1500)")])
    turn = Agent(get_agent("skin-quiz"), llm).reply("no, products don't sting")
    assert turn.llm_calls == 1 and not turn.guard
