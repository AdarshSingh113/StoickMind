"""Train all models, save them, and write today's scores into the database.

Run:  python -m kotler.ml.pipeline

Outputs
- data/models/{churn,clv,rto}.joblib  trained models
- data/models/metrics.json            backtest metrics + when and on what data they were trained
- table customer_features             today's features (the ONLY table the segment builder may query)
- table customer_scores               segment, churn probability, predicted value per customer

The app retrains automatically when the data has changed since the last training (e.g. new orders),
which takes about 10 seconds on the demo data.
"""

from __future__ import annotations

import json
import time
import warnings
from datetime import datetime

import joblib
import numpy as np

from kotler import config, db
from kotler.ml import customer_models, rto
from kotler.ml.features import customer_features, store_now
from kotler.ml.segments import rfm

MODEL_DIR = config.DATA_DIR / "models"


def _paths():
    d = config.DB_PATH.parent / "models" if config.DB_PATH.parent != config.DATA_DIR else MODEL_DIR
    return d, d / "metrics.json"


def train_all() -> dict:
    warnings.filterwarnings("ignore")
    started = time.perf_counter()
    model_dir, metrics_path = _paths()
    model_dir.mkdir(parents=True, exist_ok=True)
    churn, churn_m = customer_models.train_churn()
    clv, clv_m = customer_models.train_clv()
    rto_model, rto_m, rto_scored = rto.train_rto()
    for name, m in (("churn", churn), ("clv", clv), ("rto", rto_model)):
        joblib.dump(m, model_dir / f"{name}.joblib")
    curve = rto.savings_curve(rto_scored)
    metrics = {"trained_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "data_end": str(store_now()),
               "seconds": round(time.perf_counter() - started, 1), "churn": churn_m, "clv": clv_m, "rto": rto_m,
               "rto_test_scores": rto_scored[["risk", "rto", "order_value"]].round(4).to_dict("list")}
    metrics_path.write_text(json.dumps(metrics, indent=1, default=str))
    refresh_scores(churn, clv)
    metrics["rto_best_threshold"] = float(curve.loc[curve.net_saving_inr.idxmax(), "threshold"])
    metrics_path.write_text(json.dumps(metrics, indent=1, default=str))
    return metrics


def refresh_scores(churn=None, clv=None) -> None:
    model_dir, _ = _paths()
    churn = churn or joblib.load(model_dir / "churn.joblib")
    clv = clv or joblib.load(model_dir / "clv.joblib")
    f = customer_features()
    X = f[customer_models.MODEL_NUMERIC + customer_models.CATEGORICAL]
    seg = rfm(f).set_index("customer_id")
    scores = f[["customer_id"]].copy()
    scores["segment"] = scores.customer_id.map(seg.segment)
    scores["rfm"] = scores.customer_id.map(seg.rfm)
    scores["churn_risk"] = churn.predict_proba(X)[:, 1].round(3)
    scores["predicted_spend_90d"] = np.clip(clv.predict(X), 0, None).round(0)
    scores["clv_12m"] = (scores.predicted_spend_90d * 4).round(0)  # simple annualisation (see docs)
    scores["value_at_risk"] = (scores.clv_12m * scores.churn_risk).round(0)
    scores["scored_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    feats = f.drop(columns=["name"]).merge(scores[["customer_id", "segment", "churn_risk", "clv_12m"]], on="customer_id")
    with db.get_conn() as conn:
        scores.to_sql("customer_scores", conn, if_exists="replace", index=False)
        feats.to_sql("customer_features", conn, if_exists="replace", index=False)


def load_metrics() -> dict | None:
    _, metrics_path = _paths()
    return json.loads(metrics_path.read_text()) if metrics_path.exists() else None


def ensure_trained() -> dict:
    """Train if there are no models yet, or the data changed since training."""
    m = load_metrics()
    model_dir, _ = _paths()
    stale = (m is None or m.get("data_end") != str(store_now())
             or not all((model_dir / f"{n}.joblib").exists() for n in ("churn", "clv", "rto")))
    try:
        has_scores = db.query_one("SELECT COUNT(*) AS n FROM customer_scores")["n"] > 0
    except Exception:
        has_scores = False
    if stale or not has_scores:
        m = train_all()
    return m


def load_model(name: str):
    model_dir, _ = _paths()
    return joblib.load(model_dir / f"{name}.joblib")


if __name__ == "__main__":
    m = train_all()
    print(f"Trained in {m['seconds']}s on data up to {m['data_end']}")
    for k in ("churn", "clv", "rto"):
        print(f"  {k:<6} model={m[k]['model']:<28} beats baseline: {m[k]['beats_baseline']}")
        print(f"         {json.dumps(m[k]['results'])}")
    print(f"  RTO threshold with the highest net saving: {m['rto_best_threshold']}")
