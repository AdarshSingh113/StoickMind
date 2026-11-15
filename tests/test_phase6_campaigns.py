"""Phase 6 tests: journeys, campaign guardrails, template safety, assignment, simulator and statistics."""

import json
import warnings
from datetime import datetime

import pytest

from kotler import db
from kotler.llm import FakeLLM, text_response
from kotler.marketing import campaigns as C
from kotler.marketing import journeys as J
from kotler.marketing import simulator, stats
from kotler.seed.generate import generate

warnings.filterwarnings("ignore")
END = datetime(2026, 11, 14, 20, 0, 0)


@pytest.fixture(scope="module", autouse=True)
def database(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    path = tmp_path_factory.mktemp("p6") / "p6.db"
    mp.setattr("kotler.config.DB_PATH", path)
    generate(n_customers=1500, months=12, seed=42, end_date=END, db_path=path)
    db.ensure_schema(path)
    from kotler.ml import pipeline
    pipeline.train_all()
    C.ensure_tables()
    yield path
    mp.undo()


def _clear_campaigns():
    with db.get_conn() as conn:
        conn.execute("DELETE FROM campaign_members")
        conn.execute("DELETE FROM campaigns")


# --------------------------------------------------------------- journeys
@pytest.mark.parametrize("journey", list(J.JOURNEYS))
def test_journey_audiences_promote_only_in_stock_products(journey):
    a = J.audience(journey)
    assert len(a) > 0 and a.customer_id.is_unique
    stock = db.query_df("SELECT id, stock FROM products").set_index("id").stock
    assert (a.product_id.map(stock) > 0).all()


def test_journey_rules():
    assert J.audience("second_order").pipe(lambda a: True)
    feats = db.query_df("SELECT customer_id, frequency, recency_days, segment FROM customer_features").set_index("customer_id")
    so = J.audience("second_order")
    assert (feats.loc[so.customer_id, "frequency"] == 1).all() and feats.loc[so.customer_id, "recency_days"].between(10, 30).all()
    wb = J.audience("win_back")
    assert feats.loc[wb.customer_id, "segment"].isin(J.WIN_BACK_SEGMENTS).all()


def test_cross_sell_only_suggests_never_bought_categories():
    a = J.audience("cross_sell")
    cats = db.query_df("SELECT o.customer_id, p.category FROM order_items oi JOIN orders o ON o.id = oi.order_id "
                       "AND o.status != 'cancelled' JOIN products p ON p.id = oi.product_id").groupby("customer_id").category.apply(set)
    target = db.query_df("SELECT id, category FROM products").set_index("id").category
    for r in a.head(200).itertuples():
        assert target[r.product_id] not in cats[r.customer_id]


# -------------------------------------------------------------- templates
@pytest.mark.parametrize("text,offer", [
    ("Restock *{product}* now for ₹299!", False), ("Get 20% off {product}", True), ("Hi {name}, buy {product}", False),
    ("Hello {first_name}", False), ("Use {code} on {product}", False), ("Broken {product", False),
    ("{product} for Rs 299", False), ("x" * 700 + "{product}", False),
])
def test_bad_templates_are_rejected(text, offer):
    with pytest.raises(C.InvalidTemplate):
        C.validate_template(text, offer)


def test_good_template_renders_without_leftover_placeholders():
    t = C.validate_template("Hi {first_name}, *{product}* for {price}, code {code} gives {discount} off", True)
    msg = C.render(t, {"first_name": "Asha", "product_name": "Neem Face Wash", "price": 299.0, "days_since": 40}, 10, "KTL110")
    assert msg == "Hi Asha, *Neem Face Wash* for ₹299, code KTL110 gives 10% off"


def _ai(a_en, a_hi="Hi {first_name}, *{product}* {price} mein lijiye", b_en="Try *{product}* for {price}, {first_name}",
        b_hi="{first_name}, *{product}* sirf {price} mein"):
    return text_response(json.dumps({"A": {"angle": "x", "en": a_en, "hinglish": a_hi},
                                     "B": {"angle": "y", "en": b_en, "hinglish": b_hi}}))


def test_ai_templates_used_when_valid_else_fallback():
    good, src = C.generate_templates(FakeLLM([_ai("Hi {first_name}! Restock *{product}* for {price}.")]), "replenishment", 0)
    assert src == "ai" and good["A"]["en"].startswith("Hi {first_name}! Restock")
    bad, src = C.generate_templates(FakeLLM([_ai("Restock *{product}* for just ₹199!")]), "replenishment", 0)
    assert src == "fallback" and "₹" not in bad["A"]["en"]
    none, src = C.generate_templates(None, "win_back", 0)
    assert src == "fallback"


def test_offer_line_is_added_by_code():
    t, _ = C.generate_templates(None, "cross_sell", 10)
    assert all("{code}" in v[lang] for v in t.values() for lang in ("en", "hinglish"))


# ------------------------------------------------------------ assignment
def test_assignment_is_deterministic_and_balanced():
    groups = [C.assign_group(7, cid, 0.2) for cid in range(20_000)]
    assert groups == [C.assign_group(7, cid, 0.2) for cid in range(20_000)]
    share = {g: groups.count(g) / len(groups) for g in ("A", "B", "control")}
    assert abs(share["control"] - 0.2) < 0.015 and abs(share["A"] - share["B"]) < 0.02
    assert [C.assign_group(8, c, 0.2) for c in range(200)] != groups[:200]  # different campaign, different split


# ------------------------------------------------------------- guardrails
def test_campaign_guardrails():
    _clear_campaigns()
    t, src = C.generate_templates(None, "replenishment", 0)
    with pytest.raises(ValueError, match="capped"):
        C.create_campaign("x", "replenishment", t, src, offer_pct=40)
    with pytest.raises(ValueError, match="Holdout"):
        C.create_campaign("x", "replenishment", t, src, holdout_pct=0.0)


def test_open_tickets_excluded_and_frequency_cap():
    _clear_campaigns()
    aud = J.audience("cross_sell")
    upset = int(aud.customer_id.iloc[0])
    with db.get_conn() as conn:
        conn.execute("INSERT INTO support_tickets (customer_id, created_at, channel, category, priority, status, message) "
                     "VALUES (?, '2026-11-14 10:00:00', 'whatsapp', 'refund', 'high', 'open', 'where is my refund')", (upset,))
    t, src = C.generate_templates(None, "cross_sell", 0)
    c1 = C.create_campaign("first", "cross_sell", t, src, audience_df=aud)
    m1 = C.members(c1).set_index("customer_id")
    assert m1.loc[upset, "grp"] == "excluded" and "support ticket" in m1.loc[upset, "exclusion_reason"]
    C.send_campaign(c1)
    c2 = C.create_campaign("second", "cross_sell", t, src, audience_df=aud)
    m2 = C.members(c2)
    messaged_before = set(m1[m1.grp.isin(["A", "B"])].index)
    assert set(m2[m2.grp.isin(["A", "B"])].customer_id).isdisjoint(messaged_before)  # nobody twice in 7 days


def test_messages_are_personalised_and_in_the_right_language():
    _clear_campaigns()
    t, src = C.generate_templates(None, "replenishment", 10)
    cid = C.create_campaign("lang", "replenishment", t, src, offer_pct=10)
    m = C.members(cid)
    sent = m[m.grp.isin(["A", "B"])]
    assert not sent.message.str.contains(r"\{").any()
    assert sent.message.str.contains(f"KTL{cid}10").all()
    hing = sent[sent.language != "en"]
    assert len(hing) and hing.message.str.contains("lijiye|kijiye|mein", regex=True).all()
    assert m[m.grp == "control"].message.isna().all()  # control gets nothing


# --------------------------------------------------------- simulator+stats
def test_known_statistics():
    z, p = stats.two_proportion_z(60, 300, 40, 300)
    assert round(z, 2) == 2.19 and round(p, 3) == 0.028
    lo, hi = stats.wilson(30, 100)
    assert (round(lo, 3), round(hi, 3)) == (0.219, 0.396)
    assert 1760 <= stats.sample_size_per_group(0.10, 0.30) <= 1790


def test_message_lift_rules():
    base = simulator.message_lift("Hi {first_name}, *{product}*", "win_back", 0, False)
    assert base == pytest.approx(0.75)
    assert simulator.message_lift("*{product}*", "win_back", 10, True) == pytest.approx(0.6 + 0.3 + 0.1)
    assert simulator.message_lift("x" * 300 + "{product}", "cross_sell", 0, False) == pytest.approx(0.05)


def test_simulation_is_reproducible():
    _clear_campaigns()
    t, src = C.generate_templates(None, "win_back", 0)
    cid = C.create_campaign("repro", "win_back", t, src)
    C.send_campaign(cid)
    simulator.simulate(cid)
    first = C.members(cid)[["customer_id", "converted", "revenue"]]
    simulator.simulate(cid)
    assert first.equals(C.members(cid)[["customer_id", "converted", "revenue"]])


def test_stats_rediscover_the_simulators_hidden_lift():
    """On a big synthetic audience the analysis must find the planted effect: the point of a simulator."""
    _clear_campaigns()
    t = {"A": {"angle": "", "en": "Hi {first_name}, *{product}* {price}", "hinglish": "Hi {first_name}, *{product}* {price}"},
         "B": {"angle": "", "en": "Hi {first_name}, *{product}* {price}", "hinglish": "Hi {first_name}, *{product}* {price}"}}
    with db.get_conn() as conn:
        cid = conn.execute("INSERT INTO campaigns (name, journey, channel, offer_pct, holdout_pct, templates, status, created_at,"
                           " sent_at) VALUES ('big', 'win_back', 'whatsapp', 0, 0.3, ?, 'sent', 'now', 'now')",
                           (json.dumps(t),)).lastrowid
        rows = [(cid, 100000 + i, C.assign_group(cid, 100000 + i, 0.3), 1, 300.0, 900.0, 0.4, "en", "msg", "now")
                for i in range(20_000)]
        conn.executemany("INSERT INTO campaign_members (campaign_id, customer_id, grp, product_id, price, aov, churn_risk, "
                         "language, message, sent_at) VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    simulator.simulate(cid)
    r = stats.analyze(cid)
    true_lift = simulator.message_lift(t["A"]["en"], "win_back", 0, False)  # 0.75
    assert r["significant"] and r["p_value"] < 0.001
    # Test the ABSOLUTE uplift against its standard error. (Relative uplift is much noisier: the small control
    # rate sits in the denominator. Across 5 seeds it ranged 0.65-0.96 around the true 0.75.)
    p0 = simulator.base_probability(0.4)
    expected_abs = p0 * true_lift
    g = r["groups"].set_index("group")
    n_t, n_c = g.loc[["A", "B"], "customers"].sum(), g.loc["control", "customers"]
    se = ((p0 * (1 + true_lift)) * (1 - p0 * (1 + true_lift)) / n_t + p0 * (1 - p0) / n_c) ** 0.5
    assert abs(r["abs_uplift"] - expected_abs) < 3 * se
    assert r["naive_orders"] > r["incremental_orders"] > 0          # naive attribution overstates
    assert r["ab"]["winner"] is None                                 # identical variants: no false winner
    assert r["discount_cost"] == 0


def test_small_campaign_is_called_inconclusive():
    _clear_campaigns()
    t, src = C.generate_templates(None, "second_order", 0)
    cid = C.create_campaign("small", "second_order", t, src)
    C.send_campaign(cid)
    simulator.simulate(cid)
    r = stats.analyze(cid)
    if not r["significant"]:
        assert "Inconclusive" in stats.verdict(r) or "No evidence" in stats.verdict(r)
