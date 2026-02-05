# ingrid_patel/db/repos/wishlist_repo.py

from __future__ import annotations

import sqlite3
from typing import Optional

from ingrid_patel.utils.time import utc_now_iso


def is_in_wishlist(conn: sqlite3.Connection, *, channel_id: int, app_id: int) -> bool:
    cur = conn.execute(
        """
        SELECT 1
        FROM channel_wishlist
        WHERE channel_id = ? AND app_id = ?
        LIMIT 1
        """,
        (int(channel_id), int(app_id)),
    )
    return cur.fetchone() is not None


def add_to_wishlist_if_missing(
    conn: sqlite3.Connection,
    *,
    channel_id: int,
    app_id: int,
    name: str,
    added_by_discord_id: Optional[str],
) -> bool:
    """
    Returns True if inserted, False if already existed.
    """
    if is_in_wishlist(conn, channel_id=channel_id, app_id=app_id):
        return False

    conn.execute(
        """
        INSERT INTO channel_wishlist (
            channel_id,
            app_id,
            name,
            added_by_discord_id,
            created_at_utc
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (int(channel_id), int(app_id), str(name), (added_by_discord_id or None), utc_now_iso()),
    )
    conn.commit()
    return True


def remove_from_wishlist(conn: sqlite3.Connection, *, channel_id: int, app_id: int) -> bool:
    """
    Returns True if removed, False if nothing was removed.
    """
    cur = conn.execute(
        """
        DELETE FROM channel_wishlist
        WHERE channel_id = ? AND app_id = ?
        """,
        (int(channel_id), int(app_id)),
    )
    conn.commit()
    return (cur.rowcount or 0) > 0


def list_wishlist(conn: sqlite3.Connection) -> list[tuple[int, int, str]]:
    """
    Returns rows: (channel_id, app_id, name)
    """
    cur = conn.execute(
        """
        SELECT channel_id, app_id, name
        FROM channel_wishlist
        ORDER BY channel_id ASC, created_at_utc ASC
        """
    )
    return [(int(r[0]), int(r[1]), str(r[2])) for r in cur.fetchall()]
