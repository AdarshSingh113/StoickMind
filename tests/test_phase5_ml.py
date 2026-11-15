"""Phase 5 tests: no data leakage, planted patterns recovered, honest baselines, SQL guardrails."""

import json
import warnings
from datetime import datetime, timedelta

import pandas as pd
import pytest

from kotler import db
from kotler.llm import FakeLLM, text_response
from kotler.ml import customer_models as CM
from kotler.ml import rto as R
from kotler.ml import segment_builder as SB
from kotler.ml.features import customer_features, store_now
from kotler.ml.segments import SEGMENTS, frequency_score, rfm, segment_for
from kotler.seed.generate import generate

warnings.filterwarnings("ignore")
END = datetime(2026, 11, 14, 20, 0, 0)
FMT = "%Y-%m-%d %H:%M:%S"


@pytest.fixture(scope="module", autouse=True)
def database(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    path = tmp_path_factory.mktemp("p5") / "p5.db"
    mp.setattr("kotler.config.DB_PATH", path)
    generate(n_customers=1500, months=12, seed=42, end_date=END, db_path=path)
    db.ensure_schema(path)
    yield path
    mp.undo()


@pytest.fixture(scope="module")
def trained():
    from kotler.ml import pipeline
    return pipeline.train_all()


# --------------------------------------------------------------- leakage
def test_features_ignore_the_future():
    as_of = store_now() - timedelta(days=60)
    before = customer_features(as_of).set_index("customer_id")
    cid = int(before.index[0])
    # add an order AFTER as_of: features as of as_of must not change
    with db.get_conn() as conn:
        conn.execute("INSERT INTO orders (order_number, customer_id, created_at, status, payment_method, subtotal, total, "
                     "shipping_address, shipping_pincode, address_quality) SELECT 'KTL-999999', id, ?, 'delivered', 'cod', "
                     "999, 999, 'x', pincode, 1 FROM customers WHERE id = ?",
                     ((as_of + timedelta(days=1)).strftime(FMT), cid))
    try:
        after = customer_features(as_of).set_index("customer_id")
        pd.testing.assert_series_equal(before.loc[cid], after.loc[cid])
    finally:
        with db.get_conn() as conn:
            conn.execute("DELETE FROM orders WHERE order_number = 'KTL-999999'")


def test_feature_values_match_raw_orders():
    f = customer_features().set_index("customer_id")
    cid = int(f.frequency.idxmax())
    raw = db.query_df("SELECT created_at, status, total FROM orders WHERE customer_id = ? AND status != 'cancelled'", (cid,))
    assert f.loc[cid, "frequency"] == len(raw)
    assert f.loc[cid, "monetary"] == round(raw[raw.status == "delivered"].total.sum())
    assert f.loc[cid, "rto_count"] == (raw.status == "rto").sum()


def test_churn_labels_come_only_from_the_following_window():
    as_of = store_now() - timedelta(days=90)
    frame = CM.training_frame(as_of).set_index("customer_id")
    end = (as_of + timedelta(days=90)).strftime(FMT)
    buyers = set(db.query_df("SELECT DISTINCT customer_id FROM orders WHERE status != 'cancelled' AND created_at >= ? "
                             "AND created_at < ?", (as_of.strftime(FMT), end)).customer_id)
    assert set(frame.index[frame.churned == 0]) == buyers & set(frame.index)


def test_training_snapshots_never_overlap_the_test_period():
    assert min(CM.TRAIN_OFFSETS) - CM.HORIZON >= CM.HORIZON  # every training label window ends by T-90


def test_rto_history_only_counts_outcomes_known_at_order_time():
    df = R.order_frame()
    raw = db.query_df("SELECT id, customer_id, created_at, expected_delivery, status FROM orders WHERE status != 'cancelled'")
    raw["created_at"], raw["expected_delivery"] = pd.to_datetime(raw.created_at), pd.to_datetime(raw.expected_delivery)
    for _, row in df.sample(150, random_state=1).iterrows():
        earlier = raw[(raw.customer_id == row.customer_id) & (raw.created_at < row.created_at)]
        known = earlier[earlier.expected_delivery < row.created_at]
        assert row.prior_rto == (known.status == "rto").sum()


# ---------------------------------------------------------------- RFM
@pytest.mark.parametrize("r,f,m,expected", [(5, 5, 5, "Champions"), (5, 1, 2, "New customers"), (4, 1, 1, "Promising"),
                                            (1, 3, 5, "Can't lose them"), (2, 4, 4, "At risk"), (1, 1, 1, "Lost"),
                                            (2, 1, 1, "Hibernating"), (3, 4, 5, "Loyal")])
def test_segment_mapping(r, f, m, expected):
    assert segment_for(r, f, m) == expected


def test_frequency_bins_handle_many_one_order_customers():
    assert frequency_score(pd.Series([1, 1, 2, 3, 4, 6, 20])).tolist() == [1, 1, 2, 3, 4, 5, 5]


def test_every_customer_gets_a_known_segment_and_champions_spend_most():
    f = customer_features()
    seg = rfm(f)
    assert len(seg) == len(f) and set(seg.segment) <= set(SEGMENTS)
    spend = f.merge(seg, on="customer_id").groupby("segment").monetary.mean()
    assert spend.idxmax() in ("Champions", "Loyal")


# --------------------------------------------------------------- models
def test_models_beat_their_baselines(trained):
    assert trained["churn"]["beats_baseline"] and trained["clv"]["beats_baseline"] and trained["rto"]["beats_baseline"]
    assert trained["churn"]["results"][trained["churn"]["model"]]["roc_auc"] > 0.75


def test_rto_model_rediscovers_planted_patterns(trained):
    effects = {d["feature"]: d["effect"] for d in trained["rto"]["drivers"]}
    assert max(effects, key=lambda k: abs(effects[k])) == "prior_rto"   # strongest signal: past refusals
    assert effects["prior_rto"] > 0 and effects["vague_address"] > 0 and effects["tier"] > 0
    best = trained["rto"]["results"][trained["rto"]["model"]]
    assert best["top10pct_rto_rate"] > 1.8 * trained["rto"]["test_rto_rate"]   # riskiest 10% really are riskier


def test_rto_reasons_describe_the_actual_order(trained):
    from kotler.ml.pipeline import load_model
    model = load_model("rto")
    scored = R.score_open_orders(model)
    for _, row in scored.iterrows():
        if row.vague_address == 0:
            assert "vague address" not in row.reasons
        if row.prior_rto == 0:
            assert "refused" not in row.reasons


@pytest.mark.parametrize("addr,vague", [("H.No. 438, Tata Chowk, Bareilly - 243044", 0), ("opp temple, main road, Satna", 1),
                                        ("Gurleen house, Darbhanga", 1), ("47/292, MG Road, Pune - 411001", 0)])
def test_address_features(addr, vague):
    assert R.address_features(addr)["vague_address"] == vague


def test_savings_curve_sanity(trained):
    scored = pd.DataFrame(trained["rto_test_scores"])
    curve = R.savings_curve(scored)
    assert curve.flagged_orders.is_monotonic_decreasing
    assert curve.net_saving_inr.max() > 0
    # if interventions are useless and costly, intervening never pays off
    assert R.savings_curve(scored, prevent_rate=0.0, lose_good_rate=0.2).net_saving_inr.max() <= 0


def test_scores_tables_contain_no_personal_data(trained):
    cols = db.query_df("PRAGMA table_info(customer_features)").name.tolist()
    assert not {"name", "phone", "email", "shipping_address"} & set(cols)
    assert db.query_one("SELECT COUNT(*) AS n FROM customer_scores")["n"] == len(customer_features())


# ------------------------------------------------------- segment builder
@pytest.mark.parametrize("sql", [
    "DROP TABLE customers", "SELECT customer_id FROM customer_features; DELETE FROM orders",
    "SELECT id AS customer_id, name, phone FROM customers",
    "SELECT c.customer_id, x.phone FROM customer_features c JOIN customers x ON x.id = c.customer_id",
    "UPDATE customer_features SET churn_risk = 0", "SELECT name AS customer_id FROM sqlite_master",
    "ATTACH DATABASE 'x.db' AS x", "PRAGMA table_info(customers)", "SELECT tier FROM customer_features",
    "SELECT customer_id FROM customer_features WHERE load_extension('x') IS NULL",
])
def test_unsafe_sql_is_blocked(sql, trained):
    with pytest.raises(SB.UnsafeQuery):
        SB.run_query(sql)


def test_runaway_query_is_stopped(trained):
    slow = ("SELECT a.customer_id FROM customer_features a, customer_features b, customer_features c "
            "WHERE a.tier + b.tier + c.tier = -1")
    with pytest.raises(SB.UnsafeQuery, match="too long"):
        SB.run_query(slow, timeout_s=0.3)


def _answer(sql, why="ok"):
    return text_response(json.dumps({"sql": sql, "explanation": why}))


def test_builder_returns_matching_customers(trained):
    sql = "SELECT customer_id, tier FROM customer_features WHERE tier = 3"
    res = SB.build_segment(FakeLLM([_answer(sql)]), "tier 3 customers")
    assert res["error"] is None and len(res["rows"]) > 0 and (res["rows"].tier == 3).all()


def test_builder_self_corrects_a_broken_query_once(trained):
    llm = FakeLLM([_answer("SELECT customer_id FROM customer_features WHERE tierr = 3"),
                   _answer("SELECT customer_id FROM customer_features WHERE tier = 3")])
    res = SB.build_segment(llm, "tier 3")
    assert res["attempts"] == 2 and res["error"] is None and "no such column" in llm.calls[1][-1]["content"]


def test_builder_never_retries_a_forbidden_query(trained):
    llm = FakeLLM([_answer("SELECT id AS customer_id, phone FROM customers")])
    res = SB.build_segment(llm, "phone numbers of everyone")
    assert res["attempts"] == 1 and "Not allowed" in res["error"] and res["rows"].empty


def test_save_and_list_segments(trained):
    SB.save_segment("Tier 3", "tier 3 customers", "SELECT customer_id FROM customer_features WHERE tier = 3", "x")
    saved = SB.saved_segments()
    assert saved.name.tolist() == ["Tier 3"] and saved.customers.iloc[0] > 0
