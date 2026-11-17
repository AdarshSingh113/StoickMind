"""Database access helpers.

Why a thin helper instead of an ORM (like SQLAlchemy)?
- You learn real SQL, which every data/AI role expects.
- The AI agents in later phases will call these same functions as "tools",
  so keeping them small and explicit makes them easy to reason about.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pandas as pd

from kotler import config

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: Path | str | None = None) -> sqlite3.Connection:
    path = Path(db_path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # rows behave like dicts: row["name"]
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_conn(db_path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Open a connection, commit on success, roll back on error, always close."""
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Columns added after a table was first created. CREATE TABLE IF NOT EXISTS doesn't change an existing table, so
# databases created by an older version get these with ALTER TABLE: a tiny, dependency-free "migration".
MIGRATIONS = {
    "products": {"image_url": "TEXT"},
    "orders": {"source": "TEXT NOT NULL DEFAULT 'store'", "ai_ref": "TEXT"},
    "agents": {"handoff_rules": "TEXT"},
}


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())
    for table, cols in MIGRATIONS.items():
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col, ddl in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
    # Every product has a packshot (kotler/web/media/products); fill in any that are missing.
    from kotler.seed.images import image_url
    missing = conn.execute("SELECT id, name FROM products WHERE image_url IS NULL").fetchall()
    conn.executemany("UPDATE products SET image_url = ? WHERE id = ?", [(image_url(r[1]), r[0]) for r in missing])


def reset_db(db_path: Path | str | None = None) -> Path:
    """Delete and recreate an empty database. Returns the path."""
    path = Path(db_path or config.DB_PATH)
    if path.exists():
        path.unlink()
    with get_conn(path) as conn:
        init_schema(conn)
    return path


def query_df(sql: str, params: tuple | dict = (), db_path: Path | str | None = None) -> pd.DataFrame:
    """Run a SELECT and return a pandas DataFrame (handy for dashboards & ML)."""
    with get_conn(db_path) as conn:
        return pd.read_sql_query(sql, conn, params=params)


def query_one(sql: str, params: tuple | dict = (), db_path: Path | str | None = None) -> dict | None:
    with get_conn(db_path) as conn:
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row else None


def ensure_schema(db_path: Path | str | None = None) -> None:
    """Create any tables that are missing (safe to run on every start-up)."""
    with get_conn(db_path) as conn:
        init_schema(conn)
