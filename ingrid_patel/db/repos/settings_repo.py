# ingrid_patel/db/repos/settings_repo.py

from __future__ import annotations

import sqlite3
from typing import Optional


def get_setting(conn: sqlite3.Connection, key: str) -> Optional[str]:
    """
    Returns the setting value as a stripped string, or None if missing/NULL/blank.
    """
    cur = conn.execute("SELECT value FROM settings WHERE key = ? LIMIT 1", (key,))
    row = cur.fetchone()
    if not row:
        return None

    try:
        val = row["value"]
    except Exception:
        val = row[0]

    if val is None:
        return None

    s = str(val).strip()
    return s or None


def get_int_setting(conn: sqlite3.Connection, key: str) -> Optional[int]:
    """
    Returns an int setting or None if missing/invalid.
    """
    s = get_setting(conn, key)
    if not s:
        return None
    try:
        n = int(s)
        return n
    except Exception:
        return None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    """
    Upserts the setting. Always commits.
    """
    conn.execute(
        """
        INSERT INTO settings(key, value)
        VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, str(value)),
    )
    conn.commit()


def set_setting_if_changed(conn: sqlite3.Connection, key: str, value: str) -> bool:
    """
    Sets and commits only if the value differs from what's stored.
    Returns True if an update occurred, False otherwise.
    """
    new_val = str(value)
    cur = conn.execute("SELECT value FROM settings WHERE key = ? LIMIT 1", (key,))
    row = cur.fetchone()

    old_val = None
    if row:
        try:
            old_val = row["value"]
        except Exception:
            old_val = row[0]

    # Normalize NULL vs string, and avoid writing if identical
    if old_val is not None and str(old_val) == new_val:
        return False

    conn.execute(
        """
        INSERT INTO settings(key, value)
        VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, new_val),
    )
    conn.commit()
    return True
