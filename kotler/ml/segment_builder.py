"""Plain-English segment builder ("text-to-SQL") with guardrails.

A marketer types: "tier-3 customers with oily skin who haven't ordered in 60 days".
The LLM writes SQL, we run it, and the result becomes a saved segment for campaigns (Phase 6).

Letting a model write SQL against a real database is dangerous: it could DELETE data, read
phone numbers, or run a query that never ends. The guardrails are in CODE, not the prompt:

1. The model may only query ONE table, `customer_features`, which holds no names, phones,
   emails or addresses. Even a malicious query can't reach personal data.
2. The query runs on a READ-ONLY connection, so writes are refused by SQLite itself.
3. A SQLite AUTHORIZER inspects every operation SQLite performs: only SELECT and reading
   `customer_features` (plus built-in functions) are allowed; everything else is denied.
4. One statement only; results capped at 5,000 rows; queries stopped after ~2 seconds.
5. If the SQL errors, the model sees the error once and may fix it (self-correction).
The generated SQL is always shown to the user: never hide what the AI did.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import datetime

import pandas as pd

from kotler import config, db
from kotler.llm import LLMError

TABLE = "customer_features"
MAX_ROWS = 5000

COLUMNS = {
    "customer_id": "integer id (always select it)",
    "city": "city name, e.g. 'Mumbai', 'Jaipur', 'Darbhanga'",
    "tier": "city tier: 1 = metro, 2 = mid-size, 3 = small town",
    "skin_type": "'oily' | 'dry' | 'combination' | 'sensitive' | 'normal'",
    "language": "'en' | 'hinglish' | 'hi'",
    "channel": "how they were acquired: 'instagram' | 'google' | 'whatsapp' | 'facebook' | 'referral' | 'influencer'",
    "frequency": "number of orders (excluding cancelled)",
    "monetary": "total delivered spend in ₹",
    "aov": "average order value in ₹",
    "orders_30d": "orders in the last 30 days", "orders_90d": "orders in the last 90 days",
    "spend_90d": "delivered spend in the last 90 days, ₹",
    "cod_share": "share of orders paid cash on delivery, 0-1",
    "rto_count": "number of COD parcels refused at the door", "rto_rate": "rto_count / frequency, 0-1",
    "returns_count": "orders returned after delivery", "coupon_share": "share of orders that used a coupon, 0-1",
    "recency_days": "days since the last order", "tenure_days": "days since the first order",
    "avg_days_between_orders": "average gap between orders in days (NULL for one-order customers)",
    "categories_bought": "number of different product categories bought",
    "top_category": "most bought category: 'face_wash' | 'moisturizer' | 'serum' | 'sunscreen' | 'toner' | "
                    "'lip_care' | 'eye_care' | 'body_care' | 'kit'",
    "tickets": "support tickets raised", "complaints": "damage / allergy / refund tickets",
    "segment": "RFM segment: 'Champions' | 'Loyal' | 'Potential loyalists' | 'New customers' | 'Promising' | "
               "'Need attention' | 'About to sleep' | 'At risk' | \"Can't lose them\" | 'Hibernating' | 'Lost'",
    "churn_risk": "predicted probability of NOT ordering in the next 90 days, 0-1",
    "clv_12m": "predicted delivered spend over the next 12 months, ₹",
}

PROMPT = """You write SQLite queries for a skincare brand's marketing team.
Table `customer_features` (one row per customer) has exactly these columns:
{columns}

Write ONE SQLite SELECT statement that returns the customers matching the request.
Rules: query only `customer_features`; always select customer_id first, then the columns used in the filter;
no other tables; no comments. Interpret vague words sensibly (e.g. "high value" = clv_12m >= 3000,
"inactive" = recency_days > 60, "big spenders" = monetary >= 5000) and say how you interpreted them.

Reply with ONLY this JSON:
{{"sql": "SELECT ...", "explanation": "one sentence in plain English, including any interpretation"}}

Request: {request}"""


class UnsafeQuery(ValueError):
    pass


def _authorizer(action, arg1, arg2, dbname, source):
    if action == sqlite3.SQLITE_SELECT:
        return sqlite3.SQLITE_OK
    if action == sqlite3.SQLITE_READ:
        return sqlite3.SQLITE_OK if arg1 == TABLE else sqlite3.SQLITE_DENY
    if action == sqlite3.SQLITE_FUNCTION:
        return sqlite3.SQLITE_OK if (arg2 or "").lower() not in {"load_extension", "readfile", "writefile"} else sqlite3.SQLITE_DENY
    return sqlite3.SQLITE_DENY  # INSERT, UPDATE, DELETE, DROP, PRAGMA, ATTACH, temp tables...


def validate(sql: str) -> str:
    s = (sql or "").strip().rstrip(";").strip()
    if not s:
        raise UnsafeQuery("Empty query.")
    if ";" in s:
        raise UnsafeQuery("Only one SQL statement is allowed.")
    if not re.match(r"(?is)^\s*(select|with)\b", s):
        raise UnsafeQuery("Only SELECT queries are allowed.")
    return s


def run_query(sql: str, max_rows: int = MAX_ROWS, timeout_s: float = 2.0) -> pd.DataFrame:
    s = validate(sql)
    conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    try:
        conn.set_authorizer(_authorizer)
        deadline = time.monotonic() + timeout_s
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
        try:
            df = pd.read_sql_query(f"SELECT * FROM ({s}) LIMIT {int(max_rows)}", conn)
        except Exception as e:  # pandas wraps sqlite errors
            msg = str(e)
            if "not authorized" in msg or "prohibited" in msg:
                raise UnsafeQuery(f"Not allowed: queries may only read the {TABLE} table.") from e
            if "interrupted" in msg:
                raise UnsafeQuery("Query took too long and was stopped.") from e
            raise
    finally:
        conn.close()
    if "customer_id" not in df.columns:
        raise UnsafeQuery("The query must return customer_id.")
    return df


def _parse(text: str | None) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("The model didn't return JSON.")
    data = json.loads(m.group(0))
    return {"sql": str(data.get("sql", "")).strip(), "explanation": str(data.get("explanation", "")).strip()}


def build_segment(llm, request: str) -> dict:
    """Natural language -> SQL -> customers. Returns sql, explanation, rows, attempts, error."""
    cols = "\n".join(f"- {c}: {d}" for c, d in COLUMNS.items())
    messages = [{"role": "user", "content": PROMPT.format(columns=cols, request=request)}]
    out = {"request": request, "sql": "", "explanation": "", "rows": pd.DataFrame(), "attempts": 0, "error": None}
    for attempt in range(2):
        out["attempts"] = attempt + 1
        try:
            resp = llm.chat(messages, tools=None, temperature=0)
            parsed = _parse(resp.content)
            out.update(parsed)
            out["rows"] = run_query(parsed["sql"])
            out["error"] = None
            return out
        except LLMError as e:
            out["error"] = e.user_message
            return out
        except UnsafeQuery as e:
            out["error"] = str(e)
            return out  # never retry a forbidden query: show why it was refused
        except Exception as e:  # SQL error or bad JSON: give the model one chance to fix it
            out["error"] = f"{type(e).__name__}: {e}"
            messages += [{"role": "assistant", "content": resp.content if "resp" in locals() else ""},
                         {"role": "user", "content": f"That failed with: {out['error'][:300]}. Fix it and reply with "
                                                     "the same JSON format."}]
    return out


# ------------------------------------------------------------ saved segments
def save_segment(name: str, request: str, sql: str, explanation: str) -> int:
    rows = run_query(sql)
    with db.get_conn() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS saved_segments (
            id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, request TEXT, sql TEXT NOT NULL, explanation TEXT,
            customers INTEGER, created_at TEXT NOT NULL)""")
        cur = conn.execute("INSERT OR REPLACE INTO saved_segments (name, request, sql, explanation, customers, created_at) "
                           "VALUES (?,?,?,?,?,?)", (name.strip(), request, validate(sql), explanation, len(rows),
                                                    datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        return cur.lastrowid


def saved_segments() -> pd.DataFrame:
    try:
        return db.query_df("SELECT * FROM saved_segments ORDER BY created_at DESC")
    except Exception:
        return pd.DataFrame(columns=["id", "name", "request", "sql", "explanation", "customers", "created_at"])
