"""Ask your data: a business question in plain English -> SQL -> table, chart and a short VERIFIED answer.

"How much revenue did each city tier bring last month?"  ->  SELECT ... GROUP BY tier  ->  bar chart + 2 sentences.

It extends Phase 5's segment builder (one table, customers only) to the whole business: orders, products,
tickets, campaigns, even the AI's own traces ("which agent escalates most?"). More reach = more risk, so:

1. COLUMN-LEVEL ACCESS CONTROL. The SQLite authorizer is told about every column a query reads. Personal data
   (names, phones, emails, addresses, free-text messages) is blocked even inside allowed tables. Aggregates
   ("customers per city") work; reading phone numbers does not, however the question is worded.
2. Read-only connection, one SELECT only, row cap, time limit (as in Phase 5).
3. The CHART is chosen by the model but VALIDATED in code: the columns must exist and the value axis must be
   numeric, otherwise we fall back to a table.
4. GROUNDED ANSWERS. The model writes the 1-3 sentence summary AFTER seeing the result. Then code checks that every
   number in the summary appears in the result. A summary with a number we can't find (a made-up total, a wrong
   percentage) gets one retry, and is otherwise WITHHELD: the table is shown without it. A wrong sentence is worse
   than no sentence, because people read the sentence and skip the table.
5. The SQL is always shown. Follow-up questions ("and by month?") see the previous question and SQL.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field

import pandas as pd

from kotler import config, db
from kotler.llm import LLMError

MAX_ROWS = 1000
PREVIEW_ROWS = 40

# table -> description. Only these tables can be read.
TABLES = {
    "orders": "one row per order. status: placed|shipped|out_for_delivery|delivered|cancelled|rto|returned "
              "(rto = COD parcel refused at the door). payment_method: cod|prepaid. total = amount paid in ₹ "
              "(revenue = SUM(total) of delivered orders unless asked otherwise). created_at 'YYYY-MM-DD HH:MM:SS'",
    "order_items": "products in each order: order_id, product_id, quantity, unit_price (₹ at time of purchase)",
    "products": "catalogue: category face_wash|moisturizer|serum|sunscreen|toner|lip_care|eye_care|body_care|kit, "
                "price, mrp, stock, rating, skin_types / concerns (comma lists)",
    "customers": "customers (no names or contacts): city, state, pincode, skin_type, preferred_language "
                 "en|hinglish|hi, acquisition_channel, created_at = signup date",
    "pincodes": "pincode -> city, state, tier (1 metro, 2 mid-size, 3 small town)",
    "support_tickets": "category order_status|damaged_product|refund|product_query|discount_request|allergic_reaction, "
                       "priority, status open|resolved|escalated, resolved_by ai|human, channel, created_at, resolved_at",
    "customer_features": "one row per customer, ML features: tier, frequency, monetary, aov, recency_days, rto_rate, "
                         "segment (RFM), churn_risk 0-1, clv_12m ₹ ...",
    "customer_scores": "per customer: segment, churn_risk 0-1, predicted_spend_90d, clv_12m, value_at_risk (₹)",
    "campaigns": "retention campaigns: journey, channel, offer_pct, status draft|sent|measured",
    "campaign_members": "per campaign and customer: grp A|B|control|excluded, converted 0/1, revenue",
    "order_actions": "actions AI agents took: action cancel|refund|replacement|coupon|escalation, "
                     "status done|pending_approval|approved|rejected, amount ₹, agent_slug",
    "conversation_scores": "LLM-judge verdicts per AI conversation: agent_slug, achieved 0/1, score 1-5",
    "ai_traces": "one row per AI task: kind (agent_turn, judge, ask_data...), name = agent slug, channel, "
                 "latency_ms, status ok|corrected|fail_safe|error, escalated 0/1, started_at",
    "llm_calls": "every LLM call: model, latency_ms, prompt_tokens, completion_tokens, status ok|fallback|error",
}

# Personal or free-text columns: blocked even though their table is allowed.
BLOCKED = {
    ("customers", "name"), ("customers", "phone"), ("customers", "email"),
    ("orders", "shipping_address"), ("support_tickets", "message"), ("campaign_members", "message"),
    ("order_actions", "details"), ("order_actions", "reason"), ("conversation_scores", "reason"),
    ("ai_traces", "input"), ("ai_traces", "output"), ("ai_traces", "error"), ("ai_traces", "meta"),
}

PROMPT = """You are a data analyst for {brand}, an Indian D2C skincare brand. Write ONE SQLite query that answers
the question.

Tables (only these exist for you):
{schema}

Rules:
- One SELECT (WITH ... SELECT allowed). SQLite dialect: dates are TEXT, use date(), strftime('%Y-%m', created_at).
- The data ends on {data_end}. "Today", "this month", "last 30 days" are relative to {data_end}, NOT the real date.
- Never select personal columns (names, phones, emails, addresses, message texts): they are blocked.
- Give columns short readable aliases (e.g. revenue_inr, orders, month). Round money to 0 decimals, rates to 3.
- Return at most a few dozen rows for a chart: aggregate, ORDER BY something meaningful, LIMIT if needed.
{history}
Reply with ONLY this JSON:
{{"sql": "...", "title": "short chart title", "explanation": "one sentence: what the query does and how you
interpreted vague words", "chart": {{"type": "bar" | "line" | "none", "x": "column", "y": "column",
"color": "column or null"}}}}
Use "line" only when x is a date or month. Use "none" for a single number or a list that isn't comparable.

Question: {question}"""

ANSWER_PROMPT = """Question: {question}
The query returned {n} rows. {preview_note}
{csv}

Answer the question in 1-3 short sentences for a busy founder. Rules: use ONLY numbers that appear in the result
above (copy them; you may round money to whole rupees and write fractions like 0.123 as 12.3%). Do not add, sum,
average or compute new numbers. Do not write lakh/crore/k. If the result is empty, say no data matched."""


class UnsafeQuery(ValueError):
    pass


@dataclass
class AskResult:
    question: str
    sql: str = ""
    title: str = ""
    explanation: str = ""
    chart: dict = field(default_factory=dict)
    rows: pd.DataFrame = field(default_factory=pd.DataFrame)
    answer: str = ""
    answer_status: str = "none"      # verified | withheld | none
    ungrounded: list[str] = field(default_factory=list)
    attempts: int = 0
    error: str | None = None


# ------------------------------------------------------------------ guarded execution
def schema_text() -> str:
    lines = []
    with sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True) as conn:
        for table, desc in TABLES.items():
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})") if (table, r[1]) not in BLOCKED]
            if cols:
                lines.append(f"- {table}({', '.join(cols)}): {desc}")
    return "\n".join(lines)


def validate(sql: str) -> str:
    s = (sql or "").strip().rstrip(";").strip()
    s = re.sub(r"^```(?:sql)?|```$", "", s).strip()
    if not s:
        raise UnsafeQuery("Empty query.")
    if ";" in s:
        raise UnsafeQuery("Only one SQL statement is allowed.")
    if not re.match(r"(?is)^\s*(select|with)\b", s):
        raise UnsafeQuery("Only SELECT queries are allowed.")
    return s


def run_sql(sql: str, max_rows: int = MAX_ROWS, timeout_s: float = 3.0) -> pd.DataFrame:
    s = validate(sql)
    denied: list[str] = []

    def authorizer(action, arg1, arg2, dbname, source):
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_READ:
            if arg1 not in TABLES:
                denied.append(f"table {arg1}")
                return sqlite3.SQLITE_DENY
            if (arg1, arg2) in BLOCKED:
                denied.append(f"{arg1}.{arg2} (personal data)")
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_FUNCTION:
            ok = (arg2 or "").lower() not in {"load_extension", "readfile", "writefile", "fts3_tokenizer"}
            return sqlite3.SQLITE_OK if ok else sqlite3.SQLITE_DENY
        denied.append("a write or schema operation")
        return sqlite3.SQLITE_DENY

    conn = sqlite3.connect(f"file:{config.DB_PATH}?mode=ro", uri=True)
    try:
        conn.set_authorizer(authorizer)
        deadline = time.monotonic() + timeout_s
        conn.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 10_000)
        try:
            return pd.read_sql_query(f"SELECT * FROM ({s}) LIMIT {int(max_rows)}", conn)
        except Exception as e:
            msg = str(e)
            if denied or "not authorized" in msg or "prohibited" in msg:
                raise UnsafeQuery("Not allowed to read " + ", ".join(dict.fromkeys(denied or ["that"])) + ".") from e
            if "interrupted" in msg:
                raise UnsafeQuery("The query took too long and was stopped.") from e
            raise
    finally:
        conn.close()


# ------------------------------------------------------------------ chart + grounding
def validate_chart(chart: dict | None, df: pd.DataFrame) -> dict:
    """Keep the model's chart only if it makes sense for the actual result."""
    c = chart or {}
    kind, x, y, color = c.get("type"), c.get("x"), c.get("y"), c.get("color")
    if df.empty or len(df) < 2 or kind not in ("bar", "line") or x not in df.columns or y not in df.columns:
        return {"type": "none"}
    if not pd.api.types.is_numeric_dtype(df[y]):
        return {"type": "none"}
    if kind == "line" and not df[x].astype(str).str.match(r"^\d{4}-\d{2}").all():
        kind = "bar"
    return {"type": kind, "x": x, "y": y, "color": color if color in df.columns and color not in (x, y) else None}


NUM = re.compile(r"(?<![\w.])-?\d[\d,]*(?:\.\d+)?")


def _numbers(text: str) -> list[float]:
    out = []
    for m in NUM.findall(text or ""):
        try:
            out.append(float(m.replace(",", "")))
        except ValueError:
            pass
    return out


def ungrounded_numbers(answer: str, df: pd.DataFrame, question: str = "") -> list[str]:
    """Numbers in the answer that can't be found in the result (allowing rounding and fraction -> percent)."""
    allowed: set[float] = {float(len(df))}
    allowed.update(_numbers(question))
    for col in df.columns:
        allowed.update(_numbers(str(col)))
        for v in df[col].head(MAX_ROWS):
            if isinstance(v, (int, float)) and not pd.isna(v):
                allowed.add(float(v))
                if -1 <= v <= 1:
                    allowed.add(float(v) * 100)        # 0.123 -> 12.3 %
            elif isinstance(v, str):
                allowed.update(_numbers(v))           # dates, months, codes
    bad = []
    for x in _numbers(answer):
        if not any(abs(x - a) <= max(0.51, 0.006 * abs(a)) for a in allowed):
            bad.append(f"{x:g}")
    return bad


# ------------------------------------------------------------------ the pipeline
def _parse(text: str | None) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("The model didn't return JSON.")
    return json.loads(m.group(0))


def data_end() -> str:
    return (db.query_one("SELECT MAX(created_at) AS d FROM orders")["d"] or "")[:10]


def ask(llm, question: str, history: list[dict] | None = None) -> AskResult:
    from kotler.obs.trace import trace
    with trace("ask_data", "ask_data", input=question) as t:
        res = _ask(llm, question, history or [])
        t.status = ("error" if res.error else "corrected" if res.attempts > 1 or res.answer_status == "withheld"
                    else "ok")
        t.error, t.output = res.error, res.answer or f"{len(res.rows)} rows"
        t.meta = {"sql": res.sql, "attempts": res.attempts, "answer_status": res.answer_status,
                  "ungrounded": res.ungrounded}
        if res.answer_status == "withheld":
            t.span("guard", "number_grounding", ok=False, detail=", ".join(res.ungrounded))
        return res


def _ask(llm, question: str, history: list[dict]) -> AskResult:
    res = AskResult(question=question)
    hist = ""
    if history:
        hist = "\nEarlier in this conversation (the new question may refer to these):\n" + "\n".join(
            f"Q: {h['question']}\nSQL: {h['sql']}" for h in history[-3:] if h.get("sql")) + "\n"
    messages = [{"role": "user", "content": PROMPT.format(brand=config.BRAND_NAME, schema=schema_text(),
                                                          data_end=data_end(), history=hist, question=question)}]
    for attempt in range(2):
        res.attempts = attempt + 1
        content = ""
        try:
            content = llm.chat(messages, tools=None, temperature=0).content or ""
            spec = _parse(content)
            res.sql = validate(str(spec.get("sql", "")))
            res.title = str(spec.get("title", ""))[:80]
            res.explanation = str(spec.get("explanation", ""))[:300]
            res.rows = run_sql(res.sql)
            res.chart = validate_chart(spec.get("chart"), res.rows)
            res.error = None
            break
        except LLMError as e:
            res.error = e.user_message
            return res
        except Exception as e:  # bad JSON, SQL error, or a blocked column: one chance to fix it
            res.error = str(e) if isinstance(e, UnsafeQuery) else f"{type(e).__name__}: {e}"
            if any(k in res.error for k in ("write or schema", "Only SELECT", "one SQL statement")):
                return res  # never retry an attempt to change data: refuse and show why
            messages += [{"role": "assistant", "content": content},
                         {"role": "user", "content": f"That failed: {res.error[:300]}. Fix the query (don't read "
                                                     "blocked columns) and reply with the same JSON format."}]
    if res.error:
        return res
    _answer(llm, res)
    return res


def _answer(llm, res: AskResult) -> None:
    df = res.rows
    csv = df.head(PREVIEW_ROWS).to_csv(index=False)
    note = f"First {PREVIEW_ROWS} rows:" if len(df) > PREVIEW_ROWS else "Result:"
    messages = [{"role": "user", "content": ANSWER_PROMPT.format(question=res.question, n=len(df), preview_note=note,
                                                                 csv=csv)}]
    for _ in range(2):
        try:
            text = (llm.chat(messages, tools=None, temperature=0).content or "").strip()
        except LLMError:
            return  # the table and chart are still useful without a summary
        bad = ungrounded_numbers(text, df.head(PREVIEW_ROWS), res.question)
        if not bad:
            res.answer, res.answer_status, res.ungrounded = text, "verified", []
            return
        res.ungrounded = bad
        messages += [{"role": "assistant", "content": text},
                     {"role": "user", "content": f"These numbers are not in the result: {', '.join(bad)}. Rewrite using "
                                                 "only numbers copied from the result."}]
    res.answer, res.answer_status = "", "withheld"
