"""Churn and lifetime-value (CLV) models.

CHURN: "will this customer place NO order in the next 90 days?"
CLV:   "how much will this customer spend (delivered) in the next 90 days?"  (x4 for a rough 12-month CLV)

How we validate: a TIME-BASED BACKTEST, not a random split.
    train: features as of T-180 days  ->  label = what happened in (T-180, T-90]
    test:  features as of T-90 days   ->  label = what happened in (T-90,  T]
The test period is entirely after the training period, like real life: you train on the past and
predict the future. (A random split would mix periods and look better than reality.)
Then the final model is retrained on the most recent window and scores every customer as of today.

Every model must beat a BASELINE:
    churn: "the longer since the last order, the likelier they churn" (recency alone)
    CLV:   "they'll spend the same as in their last 90 days"
If ML can't beat a one-line rule, the rule wins.
"""

from __future__ import annotations

from datetime import timedelta

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.inspection import permutation_importance
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, mean_absolute_error, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from kotler import db
from kotler.ml.features import CATEGORICAL, NUMERIC, customer_features, store_now

HORIZON = 90  # days

# Numeric features used by the models. `avg_days_between_orders` is NaN for one-order customers (imputed).
MODEL_NUMERIC = NUMERIC + ["avg_days_between_orders"]


def _future(as_of, horizon: int = HORIZON) -> pd.DataFrame:
    """Per customer: did they order in (as_of, as_of+horizon], and how much delivered value?"""
    end = as_of + timedelta(days=horizon)
    df = db.query_df("""SELECT customer_id, COUNT(*) AS orders,
                               SUM(CASE WHEN status = 'delivered' THEN total ELSE 0 END) AS spend
                        FROM orders WHERE status != 'cancelled' AND created_at >= ? AND created_at < ?
                        GROUP BY customer_id""",
                     (as_of.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")))
    return df.set_index("customer_id")


def training_frame(as_of) -> pd.DataFrame:
    """Features as of `as_of` + labels from the following HORIZON days."""
    f = customer_features(as_of).set_index("customer_id")
    fut = _future(as_of)
    f["churned"] = (~f.index.isin(fut.index)).astype(int)
    f["future_spend"] = fut.spend.reindex(f.index).fillna(0.0)
    return f.reset_index()


# Small data trick: STACK several historical snapshots to get more training rows. Every training label
# window ends before the test period starts (T-90), so nothing leaks from the test period.
TRAIN_OFFSETS = (180, 210, 240, 270)   # backtest training snapshots (labels end at T-90 at the latest)
FINAL_OFFSETS = (90, 120, 150, 180)    # final model: most recent complete windows (labels end at T)


def stacked_frame(now, offsets) -> pd.DataFrame:
    return pd.concat([training_frame(now - timedelta(days=d)) for d in offsets], ignore_index=True)


def _preprocessor() -> ColumnTransformer:
    num = Pipeline([("impute", SimpleImputer(strategy="median")), ("scale", StandardScaler())])
    cat = OneHotEncoder(handle_unknown="ignore", min_frequency=10)
    return ColumnTransformer([("num", num, MODEL_NUMERIC), ("cat", cat, CATEGORICAL)])


def _importance(model, X, y, scoring: str, n: int = 8) -> list[dict]:
    imp = permutation_importance(model, X, y, scoring=scoring, n_repeats=5, random_state=0)
    cols = MODEL_NUMERIC + CATEGORICAL
    order = np.argsort(-imp.importances_mean)[:n]
    return [{"feature": cols[i], "importance": round(float(imp.importances_mean[i]), 4)} for i in order]


def train_churn(now=None) -> tuple[Pipeline, dict]:
    now = now or store_now()
    train = stacked_frame(now, TRAIN_OFFSETS)
    test = training_frame(now - timedelta(days=HORIZON))
    Xtr, ytr, Xte, yte = train[MODEL_NUMERIC + CATEGORICAL], train.churned, test[MODEL_NUMERIC + CATEGORICAL], test.churned

    candidates = {
        "logistic_regression": Pipeline([("prep", _preprocessor()),
                                         ("model", LogisticRegression(max_iter=2000, C=0.5))]),
        "gradient_boosting": Pipeline([("prep", _preprocessor()),
                                       ("model", HistGradientBoostingClassifier(max_depth=4, learning_rate=0.06,
                                                                                max_iter=250, random_state=0))]),
    }
    results = {"baseline_recency": {
        "roc_auc": round(roc_auc_score(yte, test.recency_days), 3),
        "pr_auc": round(average_precision_score(yte, test.recency_days), 3)}}
    fitted = {}
    for name, pipe in candidates.items():
        pipe.fit(Xtr, ytr)
        p = pipe.predict_proba(Xte)[:, 1]
        results[name] = {"roc_auc": round(roc_auc_score(yte, p), 3), "pr_auc": round(average_precision_score(yte, p), 3),
                         "brier": round(brier_score_loss(yte, p), 3)}
        fitted[name] = pipe
    best = max(fitted, key=lambda k: results[k]["roc_auc"])
    importance = _importance(fitted[best], Xte, yte, "roc_auc")

    # Retrain the winner on the most recent complete windows, then it scores today's customers.
    final = candidates[best]
    recent = stacked_frame(now, FINAL_OFFSETS)
    final.fit(recent[MODEL_NUMERIC + CATEGORICAL], recent.churned)
    metrics = {"model": best, "horizon_days": HORIZON, "train_rows": len(train), "test_rows": len(test),
               "test_churn_rate": round(float(yte.mean()), 3), "results": results, "importance": importance,
               "beats_baseline": results[best]["roc_auc"] > results["baseline_recency"]["roc_auc"]}
    return final, metrics


def train_clv(now=None) -> tuple[Pipeline, dict]:
    now = now or store_now()
    train = stacked_frame(now, TRAIN_OFFSETS)
    test = training_frame(now - timedelta(days=HORIZON))
    Xtr, ytr, Xte, yte = train[MODEL_NUMERIC + CATEGORICAL], train.future_spend, test[MODEL_NUMERIC + CATEGORICAL], test.future_spend

    model = Pipeline([("prep", _preprocessor()),
                      ("model", HistGradientBoostingRegressor(loss="poisson", max_depth=4, learning_rate=0.06,
                                                              max_iter=250, random_state=0))])
    model.fit(Xtr, ytr)
    pred = np.clip(model.predict(Xte), 0, None)
    baseline = test.spend_90d.values  # "same as their last 90 days"

    def spearman(a, b):
        return round(float(pd.Series(a).rank().corr(pd.Series(b).rank())), 3)

    results = {"baseline_last_90d": {"mae": round(mean_absolute_error(yte, baseline), 1), "rank_corr": spearman(baseline, yte)},
               "mean_prediction": {"mae": round(mean_absolute_error(yte, np.full(len(yte), ytr.mean())), 1)},
               "gradient_boosting": {"mae": round(mean_absolute_error(yte, pred), 1), "rank_corr": spearman(pred, yte)}}
    # Top-decile capture: share of next-90-day revenue that comes from the 10% we rank highest.
    top = np.argsort(-pred)[: max(1, len(pred) // 10)]
    results["gradient_boosting"]["top10pct_revenue_share"] = round(float(yte.iloc[top].sum() / max(yte.sum(), 1)), 3)
    importance = _importance(model, Xte, yte, "neg_mean_absolute_error")
    recent = stacked_frame(now, FINAL_OFFSETS)
    model.fit(recent[MODEL_NUMERIC + CATEGORICAL], recent.future_spend)
    metrics = {"model": "gradient_boosting (poisson)", "horizon_days": HORIZON, "results": results,
               "importance": importance,
               "beats_baseline": results["gradient_boosting"]["mae"] < results["baseline_last_90d"]["mae"]}
    return model, metrics
