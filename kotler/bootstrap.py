"""One place that makes a fresh machine ready: demo database, schema, channel tables, built-in agents.

Every entry point calls this (the API server at startup, the Telegram polling bot), so a brand-new Codespace or
Render container works on the first message instead of failing with "no such table".
"""

from __future__ import annotations

from kotler import config, db


def prepare() -> None:
    if not config.DB_PATH.exists():
        from kotler.seed.generate import generate
        print(f"No database yet: creating demo data at {config.DB_PATH} …")
        generate()
    db.ensure_schema()
    from kotler.channels import core
    core.ensure_tables()
    from kotler.agent.studio import ensure_builtin_agents
    ensure_builtin_agents()
