"""Eval history: every offline evaluation run is stored, so we can see trends and catch REGRESSIONS.

Offline evals (fixed test cases, run on purpose)  vs  online monitoring (real traffic, the traces).
You need both: evals tell you whether a change made the agent better BEFORE customers see it; traces tell you
what actually happens with real customers.

A regression = a case that passed in the previous run and fails now. That's the first thing to look at after
changing a prompt, a tool or the model, because the overall pass rate can stay the same while a different case
breaks (one fixed, one broken = "no change" in the headline number).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from kotler import config, db

SCHEMA = """
CREATE TABLE IF NOT EXISTS eval_runs (
    id          INTEGER PRIMARY KEY,
    suite       TEXT NOT NULL,          -- shopping, helpdesk, ask_data
    model       TEXT,
    started_at  TEXT NOT NULL,
    cases       INTEGER NOT NULL,
    passed      INTEGER NOT NULL,
    avg_latency_ms INTEGER,
    source      TEXT UNIQUE             -- result file name, so importing twice is harmless
);
CREATE TABLE IF NOT EXISTS eval_results (
    id          INTEGER PRIMARY KEY,
    run_id      INTEGER NOT NULL REFERENCES eval_runs(id) ON DELETE CASCADE,
    case_id     TEXT NOT NULL,
    passed      INTEGER NOT NULL,
    failed_checks TEXT,                 -- comma list
    latency_ms  INTEGER,
    reply       TEXT,
    error       TEXT
);
"""


def ensure_tables() -> None:
    with db.get_conn() as conn:
        conn.executescript(SCHEMA)


def _case_id(row: dict) -> str:
    c = row.get("case")
    return str(c.get("id") if isinstance(c, dict) else c)


def save_run(suite: str, model: str | None, rows: list[dict], started_at: str | None = None,
             source: str | None = None) -> int | None:
    """Store one run. `rows` are the eval scripts' result dicts (case, passed, checks, latency_ms, reply, error)."""
    ensure_tables()
    if source and db.query_one("SELECT id FROM eval_runs WHERE source = ?", (source,)):
        return None
    lat = [r.get("latency_ms") or 0 for r in rows]
    with db.get_conn() as conn:
        run_id = conn.execute(
            "INSERT INTO eval_runs (suite, model, started_at, cases, passed, avg_latency_ms, source) VALUES (?,?,?,?,?,?,?)",
            (suite, model, started_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(rows),
             sum(bool(r.get("passed")) for r in rows), int(sum(lat) / len(lat)) if lat else None, source)).lastrowid
        for r in rows:
            fails = [k for k, v in (r.get("checks") or {}).items() if v is False]
            conn.execute("INSERT INTO eval_results (run_id, case_id, passed, failed_checks, latency_ms, reply, error) "
                         "VALUES (?,?,?,?,?,?,?)", (run_id, _case_id(r), int(bool(r.get("passed"))), ",".join(fails),
                                                    r.get("latency_ms"), (r.get("reply") or "")[:2000], r.get("error")))
    return run_id


def import_result_files(folder: Path | None = None) -> int:
    """Load result files written by earlier eval runs (data/evals/<suite>-YYYYmmdd-HHMMSS.json)."""
    folder = folder or config.DATA_DIR / "evals"
    n = 0
    for path in sorted(folder.glob("*-*.json")) if folder.exists() else []:
        suite, _, stamp = path.stem.partition("-")
        try:
            data = json.loads(path.read_text())
            started = datetime.strptime(stamp, "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, OSError):
            continue
        if save_run(suite, data.get("model"), data.get("results", []), started, source=path.name):
            n += 1
    return n


def runs(suite: str | None = None) -> pd.DataFrame:
    ensure_tables()
    q = "SELECT *, ROUND(100.0 * passed / MAX(cases, 1), 0) AS pass_pct FROM eval_runs"
    df = db.query_df(q + (" WHERE suite = ?" if suite else "") + " ORDER BY started_at", (suite,) if suite else ())
    # A FULL run covers the whole suite; partial runs (--only a few cases, e.g. re-checking a fix) aren't
    # comparable with full ones: "3/3 passed" after "25/26" isn't an improvement.
    df["full"] = df.cases >= df.groupby("suite").cases.transform("max") * 0.8
    return df


def results(run_id: int) -> pd.DataFrame:
    return db.query_df("SELECT case_id, passed, failed_checks, latency_ms, reply, error FROM eval_results "
                       "WHERE run_id = ? ORDER BY passed, case_id", (run_id,))


def compare(suite: str) -> dict | None:
    """Latest FULL run vs the previous full run, case by case (only cases present in both)."""
    r = runs(suite)
    r = r[r.full]
    if len(r) < 2:
        return None
    prev, last = int(r.iloc[-2].id), int(r.iloc[-1].id)
    a = results(prev).set_index("case_id").passed
    b = results(last).set_index("case_id").passed
    both = a.index.intersection(b.index)
    return {"previous": prev, "latest": last,
            "regressions": sorted(c for c in both if a[c] and not b[c]),
            "fixed": sorted(c for c in both if not a[c] and b[c]),
            "still_failing": sorted(c for c in both if not a[c] and not b[c]),
            "compared": len(both)}
