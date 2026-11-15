"""COD return-to-origin (RTO) predictor: which cash-on-delivery orders will be refused at the door?

Every RTO costs forward + return shipping and blocks stock for a week. If we can spot risky COD orders
at checkout, we can confirm them on WhatsApp or nudge the customer to prepay.

Rules that keep this honest:
1. ONLY information available WHEN THE ORDER IS PLACED. A past RTO counts only if that earlier order's
   outcome was already known (its expected delivery date had passed) when the new order came in.
2. No made-up signals. The simulated `address_quality` column is NOT used; address features are derived
   from the address TEXT, as a real store would have to.
3. Time-based split: train on older orders, test on the newest 25%.
4. The decision threshold is chosen by RUPEES SAVED, not accuracy (see `savings_curve`).
5. Prefer the simpler, explainable model unless the complex one is clearly better (> 0.01 AUC).
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from kotler import db

FINISHED = ("delivered", "returned", "rto")
NUMERIC = ["tier", "is_first_order", "prior_orders", "prior_delivered", "prior_rto", "order_value", "items",
           "used_coupon", "night_order", "vague_address"]
BINARY = {"is_first_order", "used_coupon", "night_order", "vague_address"}
CATEGORICAL = ["channel"]

# Reason text for a feature, depending on its actual value (a reason must describe THIS order).
def _reason(feature: str, v: float) -> str | None:
    return {
        "tier": f"tier-{v:.0f} city" if v >= 2 else None,
        "is_first_order": "first order from this customer" if v else None,
        "prior_rto": f"{v:.0f} earlier parcel(s) refused" if v else None,
        "prior_delivered": "no earlier successful delivery" if v == 0 else None,
        "prior_orders": "new customer" if v == 0 else None,
        "order_value": f"high order value (₹{v:,.0f})",
        "night_order": "placed between midnight and 5 am" if v else None,
        "vague_address": "vague address (no house number or pincode)" if v else None,
        "used_coupon": "used a coupon" if v else None,
        "items": f"{v:.0f} items",
    }.get(feature)


def address_features(addr: str) -> dict:
    """One clear signal instead of four overlapping ones (overlapping features split the effect between
    them and can even flip a sign: 'multicollinearity'). Vague = no house/flat number OR no pincode."""
    a = (addr or "").lower()
    first_part = a.split(",")[0] if a else ""
    has_number = bool(re.search(r"\d", first_part))
    has_pincode = bool(re.search(r"\b\d{6}\b", a))
    return {"vague_address": int(not (has_number and has_pincode))}


def order_frame(statuses: tuple | None = None) -> pd.DataFrame:
    """COD orders with features as of the moment each order was placed."""
    df = db.query_df("""
        SELECT o.id, o.order_number, o.customer_id, o.created_at, o.expected_delivery, o.status, o.payment_method,
               o.total AS order_value, o.coupon_code, o.shipping_address, p.tier, c.acquisition_channel AS channel,
               c.name AS customer, c.city,
               (SELECT SUM(quantity) FROM order_items WHERE order_id = o.id) AS items
        FROM orders o JOIN pincodes p ON p.pincode = o.shipping_pincode JOIN customers c ON c.id = o.customer_id
        WHERE o.status != 'cancelled'
        ORDER BY o.customer_id, o.created_at""")
    df["created_at"] = pd.to_datetime(df.created_at)
    df["expected_delivery"] = pd.to_datetime(df.expected_delivery)

    # Customer history known at order time: earlier orders whose outcome was known by then.
    prior_orders, prior_delivered, prior_rto = [], [], []
    for _, g in df.groupby("customer_id", sort=False):
        times, exp, status = g.created_at.values, g.expected_delivery.values, g.status.values
        for i in range(len(g)):
            known = (np.arange(len(g)) < i) & (exp < times[i])
            prior_orders.append(int(i))
            prior_delivered.append(int(((status == "delivered") | (status == "returned"))[known].sum()))
            prior_rto.append(int((status == "rto")[known].sum()))
    df["prior_orders"], df["prior_delivered"], df["prior_rto"] = prior_orders, prior_delivered, prior_rto
    df["is_first_order"] = (df.prior_orders == 0).astype(int)
    df["night_order"] = (df.created_at.dt.hour < 5).astype(int)
    df["used_coupon"] = df.coupon_code.notna().astype(int)
    addr = pd.DataFrame([address_features(a) for a in df.shipping_address], index=df.index)
    df = pd.concat([df, addr], axis=1)
    df = df[df.payment_method == "cod"]
    if statuses:
        df = df[df.status.isin(statuses)]
    df["rto"] = (df.status == "rto").astype(int)
    return df.sort_values("created_at").reset_index(drop=True)


def _prep() -> ColumnTransformer:
    return ColumnTransformer([
        ("num", Pipeline([("imp", SimpleImputer(strategy="median")), ("sc", StandardScaler())]), NUMERIC),
        ("cat", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL)])


def train_rto() -> tuple[Pipeline, dict, pd.DataFrame]:
    df = order_frame(FINISHED)
    cut = int(len(df) * 0.75)
    train, test = df.iloc[:cut], df.iloc[cut:]
    X = NUMERIC + CATEGORICAL
    models = {
        "logistic_regression": Pipeline([("prep", _prep()), ("model", LogisticRegression(max_iter=3000, C=0.5,
                                                                                          class_weight="balanced"))]),
        "gradient_boosting": Pipeline([("prep", _prep()), ("model", HistGradientBoostingClassifier(
            max_depth=3, learning_rate=0.05, max_iter=250, class_weight="balanced", random_state=0))]),
    }
    # Baseline: the RTO rate of the order's city tier (what a COD rule "block tier-3" would use).
    tier_rate = train.groupby("tier").rto.mean()
    results = {"baseline_tier_rate": {
        "roc_auc": round(roc_auc_score(test.rto, test.tier.map(tier_rate).fillna(train.rto.mean())), 3)}}
    probs = {}
    for name, m in models.items():
        m.fit(train[X], train.rto)
        p = m.predict_proba(test[X])[:, 1]
        probs[name] = p
        top = np.argsort(-p)[: max(1, len(p) // 10)]
        results[name] = {"roc_auc": round(roc_auc_score(test.rto, p), 3), "pr_auc": round(average_precision_score(test.rto, p), 3),
                         "top10pct_rto_rate": round(float(test.rto.iloc[top].mean()), 3)}
    best = "gradient_boosting" if results["gradient_boosting"]["roc_auc"] > results["logistic_regression"]["roc_auc"] + 0.01 \
        else "logistic_regression"
    scored_test = test.assign(risk=probs[best])
    final = models[best]
    final.fit(df[X], df.rto)  # retrain on everything for scoring new orders
    explainer = models["logistic_regression"] if best == "logistic_regression" else \
        Pipeline([("prep", _prep()), ("model", LogisticRegression(max_iter=3000, C=0.5, class_weight="balanced"))]).fit(df[X], df.rto)
    metrics = {"model": best, "train_orders": len(train), "test_orders": len(test),
               "test_rto_rate": round(float(test.rto.mean()), 3), "results": results,
               "drivers": drivers(explainer),
               "beats_baseline": results[best]["roc_auc"] > results["baseline_tier_rate"]["roc_auc"]}
    final.explainer = explainer  # attach for per-order reasons
    return final, metrics, scored_test


def drivers(explainer: Pipeline) -> list[dict]:
    """Global effect of each feature (logistic coefficients on standardised inputs)."""
    coefs = explainer.named_steps["model"].coef_[0][: len(NUMERIC)]
    order = np.argsort(-np.abs(coefs))
    return [{"feature": NUMERIC[i], "effect": round(float(coefs[i]), 3),
             "direction": "raises risk" if coefs[i] > 0 else "lowers risk"} for i in order[:8]]


def explain(model: Pipeline, row: pd.Series, n: int = 3) -> list[str]:
    """Top reasons pushing ONE order's risk up: coefficient x standardised value."""
    exp = getattr(model, "explainer", model)
    prep, lr = exp.named_steps["prep"], exp.named_steps["model"]
    scaler = prep.named_transformers_["num"].named_steps["sc"]
    imputed = prep.named_transformers_["num"].named_steps["imp"].transform(pd.DataFrame([row[NUMERIC]]))[0]
    z = (imputed - scaler.mean_) / scaler.scale_
    contrib = lr.coef_[0][: len(NUMERIC)] * z
    reasons = []
    for i in np.argsort(-contrib):
        if contrib[i] <= 0.05 or len(reasons) == n:
            break
        text = _reason(NUMERIC[i], float(row[NUMERIC[i]]))
        if text:  # skip effects that don't describe this order (e.g. "not a first order" pushing risk up)
            reasons.append(text)
    return reasons


def savings_curve(scored: pd.DataFrame, rto_cost: float = 160.0, prevent_rate: float = 0.5,
                  lose_good_rate: float = 0.05, margin_rate: float = 0.45) -> pd.DataFrame:
    """Net rupees saved if we intervene (WhatsApp confirmation / prepaid nudge) on orders above each threshold.

    rto_cost       cost of one RTO: forward + return shipping + handling
    prevent_rate   share of would-be RTOs that the intervention prevents (cancelled before shipping or converted)
    lose_good_rate share of GENUINE buyers who drop off because of the extra step
    margin_rate    gross margin lost on each genuine order that drops off
    """
    rows = []
    for th in np.round(np.arange(0.05, 0.96, 0.05), 2):
        flagged = scored[scored.risk >= th]
        caught = int(flagged.rto.sum())
        good = flagged[flagged.rto == 0]
        saved = caught * prevent_rate * rto_cost
        lost = len(good) * lose_good_rate * (good.order_value.mean() if len(good) else 0) * margin_rate
        rows.append({"threshold": th, "flagged_orders": len(flagged), "flagged_pct": round(len(flagged) / max(len(scored), 1), 3),
                     "rtos_caught": caught, "rto_recall": round(caught / max(int(scored.rto.sum()), 1), 3),
                     "net_saving_inr": round(saved - lost, 0)})
    return pd.DataFrame(rows)


def score_open_orders(model: Pipeline) -> pd.DataFrame:
    """Risk for COD orders that haven't been delivered yet: what to do before they ship."""
    df = order_frame(("placed", "shipped", "out_for_delivery"))
    if df.empty:
        return df
    df["risk"] = model.predict_proba(df[NUMERIC + CATEGORICAL])[:, 1]
    df["reasons"] = [", ".join(explain(model, r)) for _, r in df.iterrows()]
    return df.sort_values("risk", ascending=False)
