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


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text())


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
