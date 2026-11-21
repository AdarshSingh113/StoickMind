"""Listening tables: watch terms, mentions (deduplicated), scan runs, briefs, settings. Plus data retention."""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from kotler import config, db

FMT = "%Y-%m-%d %H:%M:%S"
TERM_KINDS = ("brand", "product", "category", "competitor")

# YouTube's developer policies: API data such as comment text must be refreshed or deleted within 30 days.
# We delete. Other sources are kept 90 days, enough for monthly trends.
RETENTION_DAYS = {"youtube": 30}
DEFAULT_RETENTION_DAYS = 90

SCHEMA = """
CREATE TABLE IF NOT EXISTS listening_terms (
    id INTEGER PRIMARY KEY, term TEXT NOT NULL UNIQUE COLLATE NOCASE,
    kind TEXT NOT NULL CHECK (kind IN ('brand', 'product', 'category', 'competitor')),
    active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS listening_mentions (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,                 -- youtube | bluesky | news
    external_id TEXT NOT NULL,            -- the source's own id: never stored twice
    url TEXT, author TEXT, title TEXT,    -- title = context: the video title or the news headline
    text TEXT NOT NULL, published_at TEXT, fetched_at TEXT NOT NULL,
    likes INTEGER NOT NULL DEFAULT 0,
    term_id INTEGER, term TEXT, term_kind TEXT,
    language TEXT,
    sentiment TEXT,                       -- positive | neutral | negative | mixed
    kind TEXT,                            -- complaint | praise | question | recommendation | comparison | news | other
    aspects TEXT,                         -- JSON list: results, side_effects, price, packaging, ...
    ingredients TEXT,                     -- JSON list found in the text by code: vitamin c, niacinamide, ...
    gist TEXT,                            -- one-line English paraphrase (AI)
    alert TEXT,                           -- e.g. skin_reaction (brand terms only)
    relevant INTEGER,                     -- 1/0: really about what it was found for (AI); NULL = not judged
    text_hash TEXT,                       -- normalised text: the same repost under a new id is stored once
    labelled_by TEXT,                     -- ai | rules
    UNIQUE (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_mentions_published ON listening_mentions(published_at);
CREATE INDEX IF NOT EXISTS idx_mentions_hash ON listening_mentions(text_hash);
CREATE TABLE IF NOT EXISTS listening_runs (
    id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
    trigger TEXT, fetched INTEGER NOT NULL DEFAULT 0, new INTEGER NOT NULL DEFAULT 0,
    labelled INTEGER NOT NULL DEFAULT 0, youtube_units INTEGER NOT NULL DEFAULT 0, report TEXT
);
CREATE TABLE IF NOT EXISTS listening_briefs (
    id INTEGER PRIMARY KEY, created_at TEXT NOT NULL, method TEXT NOT NULL,   -- google_search | collected
    terms TEXT, text TEXT NOT NULL, sources TEXT, warnings TEXT
);
CREATE TABLE IF NOT EXISTS listening_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

DEFAULT_TERMS = [("vitamin c serum", "category"), ("niacinamide serum", "category"),
                 ("sunscreen for oily skin", "category"), ("neem face wash", "product")]
DEFAULT_SETTINGS = {"every_hours": "0", "sources": json.dumps(["youtube", "bluesky", "news"])}


def now() -> str:
    return datetime.now().strftime(FMT)


MIGRATIONS = {"relevant": "INTEGER", "text_hash": "TEXT"}


def text_hash(text: str) -> str:
    import hashlib
    import re
    norm = re.sub(r"\s+", " ", re.sub(r"https?://\S+|[^\w\s]", " ", (text or "").lower())).strip()
    return hashlib.sha1(norm.encode()).hexdigest()[:16]


def ensure_tables() -> None:
    with db.get_conn() as conn:
        have = {r[1] for r in conn.execute("PRAGMA table_info(listening_mentions)")}
        if have:                         # tables from an earlier version of this round: add the new columns
            for col, ddl in MIGRATIONS.items():
                if col not in have:
                    conn.execute(f"ALTER TABLE listening_mentions ADD COLUMN {col} {ddl}")
        conn.executescript(SCHEMA)
        if not conn.execute("SELECT 1 FROM listening_terms LIMIT 1").fetchone() and \
                not conn.execute("SELECT 1 FROM listening_settings WHERE key = 'seeded'").fetchone():
            # First run: your brand plus a few market terms that real people actually talk about.
            terms = [(config.BRAND_NAME.rstrip("."), "brand"), *DEFAULT_TERMS]
            conn.executemany("INSERT OR IGNORE INTO listening_terms (term, kind, created_at) VALUES (?,?,?)",
                             [(t, k, now()) for t, k in terms])
            conn.execute("INSERT INTO listening_settings (key, value) VALUES ('seeded', '1')")
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO listening_settings (key, value) VALUES (?, ?)", (k, v))


# ------------------------------------------------------------------ settings
def setting(key: str) -> str:
    ensure_tables()
    row = db.query_one("SELECT value FROM listening_settings WHERE key = ?", (key,))
    return row["value"] if row else DEFAULT_SETTINGS.get(key, "")


def set_setting(key: str, value: str) -> None:
    ensure_tables()
    with db.get_conn() as conn:
        conn.execute("INSERT INTO listening_settings (key, value) VALUES (?, ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def enabled_sources() -> list[str]:
    try:
        return [s for s in json.loads(setting("sources")) if isinstance(s, str)]
    except ValueError:
        return []


# ------------------------------------------------------------------ terms
def terms(active_only: bool = False) -> list[dict]:
    ensure_tables()
    q = "SELECT id, term, kind, active, created_at FROM listening_terms"
    return db.query_df(q + (" WHERE active = 1" if active_only else "") + " ORDER BY kind = 'brand' DESC, id"
                       ).to_dict("records")


def add_term(term: str, kind: str) -> dict:
    term = " ".join((term or "").split())
    if not 2 <= len(term) <= 60:
        raise ValueError("A watch term must be 2-60 characters.")
    if kind not in TERM_KINDS:
        raise ValueError(f"Kind must be one of: {', '.join(TERM_KINDS)}.")
    ensure_tables()
    if len(terms()) >= 20:
        raise ValueError("At most 20 watch terms (each one uses API quota on every scan).")
    with db.get_conn() as conn:
        try:
            conn.execute("INSERT INTO listening_terms (term, kind, created_at) VALUES (?,?,?)", (term, kind, now()))
        except Exception as e:
            raise ValueError(f"'{term}' is already a watch term.") from e
    return db.query_one("SELECT id, term, kind, active, created_at FROM listening_terms WHERE term = ?", (term,))


def set_term_active(term_id: int, active: bool) -> None:
    with db.get_conn() as conn:
        conn.execute("UPDATE listening_terms SET active = ? WHERE id = ?", (int(active), term_id))


def delete_term(term_id: int) -> None:
    with db.get_conn() as conn:
        conn.execute("DELETE FROM listening_terms WHERE id = ?", (term_id,))


# ------------------------------------------------------------------ mentions
def save_mentions(items: list[dict]) -> list[int]:
    """Insert new mentions; already-seen ones (same source + id) are skipped. Returns the ids of new rows."""
    new = []
    with db.get_conn() as conn:
        for m in items:
            h = text_hash(m["text"])
            if conn.execute("SELECT 1 FROM listening_mentions WHERE text_hash = ? LIMIT 1", (h,)).fetchone():
                continue                 # a copy of something we already have (reposts, scheduled spam)
            cur = conn.execute(
                "INSERT OR IGNORE INTO listening_mentions (source, external_id, url, author, title, text, published_at, "
                "fetched_at, likes, term_id, term, term_kind, ingredients, alert, text_hash) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (m["source"], m["external_id"], m.get("url"), (m.get("author") or "")[:80], (m.get("title") or "")[:300],
                 m["text"][:2000], m.get("published_at"), now(), int(m.get("likes") or 0), m.get("term_id"),
                 m.get("term"), m.get("term_kind"), json.dumps(m.get("ingredients") or []), m.get("alert"), h))
            if cur.rowcount:
                new.append(cur.lastrowid)
    return new


def purge_expired() -> int:
    """Delete mentions past their source's retention period."""
    removed = 0
    with db.get_conn() as conn:
        for source, days in RETENTION_DAYS.items():
            cutoff = (datetime.now() - timedelta(days=days)).strftime(FMT)
            removed += conn.execute("DELETE FROM listening_mentions WHERE source = ? AND fetched_at < ?",
                                    (source, cutoff)).rowcount
        cutoff = (datetime.now() - timedelta(days=DEFAULT_RETENTION_DAYS)).strftime(FMT)
        removed += conn.execute(f"DELETE FROM listening_mentions WHERE source NOT IN "
                                f"({','.join('?' * len(RETENTION_DAYS))}) AND fetched_at < ?",
                                (*RETENTION_DAYS, cutoff)).rowcount
    return removed
