# ingrid_patel/db/connect.py


from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from ingrid_patel.settings import DATA_DIR
from ingrid_patel.db.schema import init_schema

log = logging.getLogger(__name__)

_SQLITE_BUSY_TIMEOUT_MS = 30_000


def _apply_sqlite_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.execute(f"PRAGMA busy_timeout = {_SQLITE_BUSY_TIMEOUT_MS};")


def connect_guild_db(guild_id: int) -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    db_path: Path = DATA_DIR / f"{guild_id}.db"

    conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row

    _apply_sqlite_pragmas(conn)

    # Create tables + apply migrations
    init_schema(conn)

    log.info("[db] connect_guild_db guild_id=%s db_path=%s", guild_id, db_path)
    return conn
