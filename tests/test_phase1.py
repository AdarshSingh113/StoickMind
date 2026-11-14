"""Phase 1 tests: the generator is reproducible, the data is consistent,
and the planted business patterns really exist."""

from datetime import datetime

import pytest

from kotler import crm, db
from kotler.seed.generate import generate

END = datetime(2026, 11, 14, 20, 0, 0)


@pytest.fixture(scope="module")
def db_path(tmp_path_factory, monkeypatch_module):
    path = tmp_path_factory.mktemp("data") / "test.db"
    monkeypatch_module.setattr("kotler.config.DB_PATH", path)
    generate(n_customers=1200, months=12, seed=7, end_date=END, db_path=path)
    return path


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


def q(sql, path):
    return db.query_one(sql, db_path=path)


def test_reproducible(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    generate(200, 6, seed=1, end_date=END, db_path=a)
    generate(200, 6, seed=1, end_date=END, db_path=b)
    sql = "SELECT COUNT(*) n, ROUND(SUM(total), 2) s FROM orders"
    assert q(sql, a) == q(sql, b)


def test_order_totals_add_up(db_path):
    bad = q("""SELECT COUNT(*) n FROM orders
               WHERE ABS(subtotal - discount + shipping_fee - total) > 0.01""", db_path)
    assert bad["n"] == 0
    bad = q("""SELECT COUNT(*) n FROM orders o
               WHERE ABS(o.subtotal - (SELECT SUM(quantity * unit_price) FROM order_items
                                       WHERE order_id = o.id)) > 0.01""", db_path)
    assert bad["n"] == 0


def test_no_future_or_inconsistent_dates(db_path):
    end = END.strftime("%Y-%m-%d %H:%M:%S")
    assert q(f"SELECT COUNT(*) n FROM orders WHERE created_at > '{end}'", db_path)["n"] == 0
    assert q(f"SELECT COUNT(*) n FROM support_tickets WHERE created_at > '{end}'", db_path)["n"] == 0
    assert q("SELECT COUNT(*) n FROM orders WHERE delivered_at < created_at", db_path)["n"] == 0
    assert q("SELECT COUNT(*) n FROM orders WHERE status='delivered' AND delivered_at IS NULL", db_path)["n"] == 0


def test_planted_rto_pattern(db_path):
    """COD in tier-3 must be much riskier than prepaid anywhere."""
    df = crm.rto_by_tier()
    cod_t3 = df[(df.city_tier == "Tier 3") & (df.payment_method == "cod")].rto_pct.item()
    cod_t1 = df[(df.city_tier == "Tier 1") & (df.payment_method == "cod")].rto_pct.item()
    prepaid_max = df[df.payment_method == "prepaid"].rto_pct.max()
    assert cod_t3 > cod_t1 > prepaid_max


def test_kpis_are_sane(db_path):
    k = crm.kpis()
    assert k["orders"] > 2000
    assert 0 < k["net_revenue"] < k["gmv"]
    assert 400 < k["aov"] < 2000
    assert k["new_buyers"] == k["buyers"]  # all time: every buyer is new at some point
    assert 0.05 < k["rto_rate"] < 0.4


def test_customer_and_order_lookup(db_path):
    top = crm.customer_summary().iloc[0]
    c = crm.get_customer(phone="+91 " + top.phone)  # tolerant to country code / spaces
    assert c and c["id"] == top.id
    orders = crm.customer_orders(int(top.id))
    assert len(orders) >= top.orders
    o = crm.get_order(orders.order_number.iloc[0].lower())  # case-insensitive
    assert o["customer_id"] == top.id


def test_hinglish_tickets_exist(db_path):
    n = q("""SELECT COUNT(*) n FROM support_tickets t JOIN customers c ON c.id = t.customer_id
             WHERE c.preferred_language != 'en'""", db_path)["n"]
    assert n > 50


def test_orders_in_time_order_per_customer(db_path):
    bad = q("""SELECT COUNT(*) n FROM customers c
               WHERE c.created_at > (SELECT MIN(created_at) FROM orders o WHERE o.customer_id = c.id)""", db_path)
    assert bad["n"] == 0


def test_past_rto_predicts_future_rto(db_path):
    """Planted pattern: COD customers who refused before refuse again far more often."""
    df = db.query_df("""
        WITH cod AS (
          SELECT customer_id, status,
                 SUM(status = 'rto') OVER (PARTITION BY customer_id ORDER BY created_at
                                           ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS past_rto
          FROM orders WHERE payment_method = 'cod' AND status IN ('delivered', 'returned', 'rto'))
        SELECT COALESCE(past_rto, 0) > 0 AS had_rto, AVG(status = 'rto') AS rate
        FROM cod GROUP BY 1 ORDER BY 1""", db_path=db_path)
    no_history, with_history = df.rate.tolist()
    assert with_history > 2 * no_history


def test_period_kpis_new_buyers(db_path):
    k = crm.kpis("2026-10-15 00:00:00", "2026-11-14 20:00:01")
    assert 0 < k["new_buyers"] < k["buyers"]


def test_repeat_rate_and_cohorts(db_path):
    r = crm.repeat_rate_90d()
    assert r["customers"] > 300 and 0.15 < r["rate"] < 0.8
    cohorts = crm.cohort_retention()
    assert (cohorts["M0"] == 100).all()
    assert cohorts["M1"].dropna().between(0, 100).all()
    assert cohorts.iloc[-1][["M1", "M2"]].isna().all()  # newest cohort has no future


def test_names_look_indian(db_path):
    from kotler.seed import catalog
    surnames = {s for group in catalog.SURNAMES.values() for s in group}
    names = db.query_df("SELECT name FROM customers", db_path=db_path).name
    assert names.str.split().str[-1].isin(surnames).all()
