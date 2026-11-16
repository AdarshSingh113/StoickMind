"""Fixes for problems found when running the agents on real Gemini (see README: evaluation results)."""

import json
from datetime import datetime

import pytest

from kotler import db
from kotler.llm import FakeLLM, text_response
from kotler.marketing import campaigns as C
from kotler.ml.features import PRODUCT_CATEGORIES, customer_features
from kotler.ml.segment_builder import build_segment
from kotler.seed.generate import generate

END = datetime(2026, 11, 14, 20, 0, 0)


@pytest.fixture(autouse=True)
def database(tmp_path, monkeypatch):
    path = tmp_path / "fix.db"
    monkeypatch.setattr("kotler.config.DB_PATH", path)
    generate(n_customers=100, months=4, seed=9, end_date=END, db_path=path)
    db.ensure_schema(path)
    return path


# ---- {days} was used as a duration ("before {days} pass") or without a unit ("It's been {days} since")
@pytest.mark.parametrize("bad", ["It's been {days} since your *{product}*", "Use it before {days} pass, *{product}*",
                                 "Results in just {days} with *{product}*"])
def test_days_must_read_as_days_ago(bad):
    with pytest.raises(C.InvalidTemplate, match="days ago"):
        C.validate_template(bad, has_offer=False)


def test_days_used_correctly_is_fine():
    C.validate_template("Hi {first_name}, {days} days since your *{product}*!", has_offer=False)
    C.validate_template("{first_name}, {days} din ho gaye *{product}* ko", has_offer=False)


def _variant(en):
    return {"angle": "x", "en": en, "hinglish": "Hi {first_name}, *{product}* {days} din pehle liya tha."}


def test_ai_templates_get_one_retry_with_the_reason():
    bad = {"A": _variant("It's been {days} since *{product}*"), "B": _variant("Hi {first_name}, *{product}* again?")}
    good = {"A": _variant("Hi {first_name}, {days} days since *{product}*."), "B": _variant("Hi {first_name}, *{product}*?")}
    llm = FakeLLM([text_response(json.dumps(bad)), text_response(json.dumps(good))])
    t, source = C.generate_templates(llm, "replenishment", 0)
    assert source == "ai" and "{days} days" in t["A"]["en"]
    assert "days ago" in llm.calls[1][-1]["content"]               # the model was told what was wrong
    assert "the days since they bought this product" in llm.calls[0][0]["content"]


def test_templates_fall_back_after_two_bad_drafts():
    bad = {"A": _variant("It's been {days} since *{product}*"), "B": _variant("x *{product}*")}
    _, source = C.generate_templates(FakeLLM([text_response(json.dumps(bad))] * 2), "win_back", 0)
    assert source == "fallback"


# ---- "bought serums twice but never sunscreen" had no data behind it, so the model improvised a wrong filter
def test_per_category_order_counts():
    f = customer_features().set_index("customer_id")
    assert {f"orders_{c}" for c in PRODUCT_CATEGORIES} <= set(f.columns)
    cid = int(f.index[0])
    direct = db.query_one("""SELECT COUNT(DISTINCT o.id) AS n FROM orders o JOIN order_items i ON i.order_id = o.id
                             JOIN products p ON p.id = i.product_id
                             WHERE o.customer_id = ? AND p.category = 'serum' AND o.status != 'cancelled'""", (cid,))["n"]
    assert f.loc[cid, "orders_serum"] == direct


def test_segment_builder_says_when_data_is_missing():
    llm = FakeLLM([text_response('{"sql": "", "explanation": "There is no email engagement data."}')])
    r = build_segment(llm, "customers who opened our last email")
    assert r["error"].startswith("Can't build this segment") and "email" in r["error"] and len(llm.calls) == 1
