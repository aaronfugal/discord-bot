import sqlite3

import sqlite3


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approved_users (
    discord_id TEXT PRIMARY KEY,
    username TEXT,
    is_admin INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS upcoming_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    app_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    release_at_utc TEXT NOT NULL,
    created_by_discord_id TEXT,
    created_at_utc TEXT NOT NULL,
    sent_at_utc TEXT
);

CREATE INDEX IF NOT EXISTS idx_upcoming_release_at ON upcoming_games(release_at_utc);
CREATE INDEX IF NOT EXISTS idx_upcoming_sent_at ON upcoming_games(sent_at_utc);
"""
# NOTE: We'll keep timestamps as ISO strings for now (simple + portable).
# We'll handle Mountain Time display in code later.


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.commit()
