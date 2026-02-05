# ingrid_patel/db/schema.py

from __future__ import annotations

import sqlite3
import logging

log = logging.getLogger(__name__)


def _has_column(conn: sqlite3.Connection, table: str, col: str) -> bool:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return any((row[1] == col) for row in cur.fetchall())


def init_schema(conn: sqlite3.Connection) -> None:
    """
    Create tables needed by the bot (idempotent).
    Lightweight migrations are handled by checking for missing columns.
    """

    # --- settings (per-guild) ---
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )

    # --- approved users (per-guild) ---
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS approved_users (
            discord_id            TEXT PRIMARY KEY,
            approved_at_utc       TEXT NOT NULL,
            approved_by_discord_id TEXT NOT NULL,
            note                  TEXT,
            revoked_at_utc        TEXT,
            revoked_by_discord_id TEXT,
            last_plex_use_at_utc  TEXT
        )
        """
    )

    # --- pending plex approval requests (per-guild) ---
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_requests (
            guild_id           INTEGER NOT NULL,
            discord_id         TEXT NOT NULL,
            requested_at_utc   TEXT NOT NULL,
            expires_at_utc     TEXT NOT NULL,
            request_channel_id INTEGER NOT NULL,
            request_message_id INTEGER NOT NULL,
            PRIMARY KEY (guild_id, discord_id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_approval_requests_expires
        ON approval_requests(expires_at_utc)
        """
    )

    # --- upcoming game reminders (per-guild) ---
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS upcoming_games (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            app_id             INTEGER NOT NULL,
            name               TEXT NOT NULL,
            release_at_utc      TEXT,
            release_precision   TEXT,
            release_date_text   TEXT,
            last_checked_at_utc TEXT,
            remind_channel_id   INTEGER,
            created_by_discord_id TEXT,
            created_at_utc      TEXT,
            sent_at_utc         TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_upcoming_games_due
        ON upcoming_games(sent_at_utc, release_at_utc)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_upcoming_games_app
        ON upcoming_games(app_id)
        """
    )

    # --- channel wishlist (per-guild) ---
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS channel_wishlist (
            channel_id        INTEGER NOT NULL,
            app_id            INTEGER NOT NULL,
            name              TEXT NOT NULL,
            added_by_discord_id TEXT,
            created_at_utc    TEXT,
            PRIMARY KEY (channel_id, app_id)
        )
        """
    )

    # --- tiny migrations (column adds) ---
    # If you ever ran an older DB missing some columns, this keeps you from crashing.
    # approved_users.last_plex_use_at_utc
    if not _has_column(conn, "approved_users", "last_plex_use_at_utc"):
        try:
            conn.execute("ALTER TABLE approved_users ADD COLUMN last_plex_use_at_utc TEXT")
        except Exception:
            pass

    # upcoming_games.remind_channel_id
    if not _has_column(conn, "upcoming_games", "remind_channel_id"):
        try:
            conn.execute("ALTER TABLE upcoming_games ADD COLUMN remind_channel_id INTEGER")
        except Exception:
            pass

    # upcoming_games.release_precision
    if not _has_column(conn, "upcoming_games", "release_precision"):
        try:
            conn.execute("ALTER TABLE upcoming_games ADD COLUMN release_precision TEXT")
        except Exception:
            pass

    conn.commit()
