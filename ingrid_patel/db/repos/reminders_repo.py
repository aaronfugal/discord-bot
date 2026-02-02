# ingrid_patel/db/repos/reminders_repo.py

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Optional

from ingrid_patel.utils.time import utc_now_iso, utc_now, canonical_utc_iso


def reminder_exists(conn: sqlite3.Connection, app_id: int, remind_channel_id: int | None) -> bool:
    """
    True if an UNSENT reminder exists for this app_id in this channel scope.

    Note on scoping:
      - We scope reminders per-channel using remind_channel_id.
      - For backwards compatibility, NULL remind_channel_id is treated as 0.
    """
    cur = conn.execute(
        """
        SELECT 1
        FROM upcoming_games
        WHERE app_id = ?
          AND sent_at_utc IS NULL
          AND COALESCE(remind_channel_id, 0) = COALESCE(?, 0)
        LIMIT 1
        """,
        (int(app_id), int(remind_channel_id or 0)),
    )
    return cur.fetchone() is not None

def list_upcoming_reminders_for_channel(
    conn: sqlite3.Connection,
    *,
    channel_id: int,
) -> list[tuple[int, int, str, Optional[str], str, str]]:
    """
    Returns rows for THIS channel only:
      (id, app_id, name, release_at_utc, release_date_text, release_precision)
    Only unsent reminders.
    """
    cur = conn.execute(
        """
        SELECT
            id,
            app_id,
            name,
            release_at_utc,
            COALESCE(release_date_text, ''),
            COALESCE(release_precision, 'unknown')
        FROM upcoming_games
        WHERE sent_at_utc IS NULL
          AND COALESCE(remind_channel_id, 0) = ?
        ORDER BY (release_at_utc IS NULL) ASC, release_at_utc ASC
        """,
        (int(channel_id),),
    )
    return cur.fetchall()



def add_reminder_if_missing(
    conn: sqlite3.Connection,
    *,
    app_id: int,
    name: str,
    release_at_utc: Optional[str],
    release_date_text: Optional[str],
    release_precision: Optional[str],
    created_by_discord_id: Optional[str],
    remind_channel_id: Optional[int],
) -> bool:
    """
    Insert a reminder if one doesn't already exist for (app_id, remind_channel_id) and isn't sent.

    Returns:
      - True if inserted
      - False if it already existed
    """
    if reminder_exists(conn, app_id, remind_channel_id):
        return False

    # Keep your existing sentinel behavior for unknown release dates
    if release_at_utc is None:
        release_at_utc = "9999-12-31T00:00:00+00:00"
    else:
        release_at_utc = canonical_utc_iso(release_at_utc)


    conn.execute(
        """
        INSERT INTO upcoming_games (
            app_id,
            name,
            release_at_utc,
            release_precision,
            release_date_text,
            last_checked_at_utc,
            remind_channel_id,
            created_by_discord_id,
            created_at_utc,
            sent_at_utc
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
            int(app_id),
            str(name),
            release_at_utc,
            (release_precision or "unknown"),
            release_date_text,
            utc_now_iso(),
            int(remind_channel_id) if remind_channel_id is not None else None,
            created_by_discord_id,
            utc_now_iso(),
        ),
    )
    conn.commit()
    return True


def remove_reminder(conn: sqlite3.Connection, *, app_id: int, remind_channel_id: int | None) -> bool:
    """
    Remove an UNSENT reminder for (app_id, remind_channel_id).
    Returns True if removed, False if none existed.
    """
    cur = conn.execute(
        """
        DELETE FROM upcoming_games
        WHERE app_id = ?
          AND sent_at_utc IS NULL
          AND COALESCE(remind_channel_id, 0) = COALESCE(?, 0)
        """,
        (int(app_id), int(remind_channel_id or 0)),
    )
    conn.commit()
    return (cur.rowcount or 0) > 0


def list_upcoming_reminders(conn: sqlite3.Connection) -> list[tuple[int, int, str, Optional[str], str]]:
    """
    Returns rows:
      (id, app_id, name, release_at_utc, release_date_text)
    Only unsent reminders.
    """
    cur = conn.execute(
        """
        SELECT
            id,
            app_id,
            name,
            release_at_utc,
            COALESCE(release_date_text, '')
        FROM upcoming_games
        WHERE sent_at_utc IS NULL
        ORDER BY (release_at_utc IS NULL) ASC, release_at_utc ASC
        """
    )
    return cur.fetchall()


def list_due_reminders(
    conn: sqlite3.Connection,
    *,
    start_utc_iso: str,
    end_utc_iso: str,
) -> list[tuple[int, int, str, str, int]]:
    """
    Returns rows due between [start_utc_iso, end_utc_iso]:
      (id, app_id, name, release_at_utc, remind_channel_id)
    Only unsent reminders with non-null release_at_utc.
    """
    cur = conn.execute(
        """
        SELECT id, app_id, name, release_at_utc, COALESCE(remind_channel_id, 0)
        FROM upcoming_games
        WHERE sent_at_utc IS NULL
          AND release_at_utc IS NOT NULL
          AND release_at_utc BETWEEN ? AND ?
        ORDER BY release_at_utc ASC
        """,
        (start_utc_iso, end_utc_iso),
    )
    return cur.fetchall()


def list_unsent_for_refresh(conn: sqlite3.Connection) -> list[tuple[int, str]]:
    """
    Returns:
      (app_id, release_date_text)
    for all unsent reminders (used by refresh job).
    """
    cur = conn.execute(
        """
        SELECT app_id, COALESCE(release_date_text,'')
        FROM upcoming_games
        WHERE sent_at_utc IS NULL
        """,
    )
    return cur.fetchall()


def update_release_fields(
    conn: sqlite3.Connection,
    *,
    app_id: int,
    release_at_utc: Optional[str],
    release_date_text: Optional[str],
    release_precision: Optional[str],
) -> None:
    """
    Update release fields for UNSENT reminders for app_id.
    We normalize timestamps so SQLite ordering is consistent.
    """
    norm_release = canonical_utc_iso(release_at_utc)

    conn.execute(
        """
        UPDATE upcoming_games
        SET release_at_utc = ?,
            release_date_text = ?,
            release_precision = ?,
            last_checked_at_utc = ?
        WHERE app_id = ? AND sent_at_utc IS NULL
        """,
        (
            norm_release,
            release_date_text,
            (release_precision or "unknown"),
            utc_now_iso(),
            int(app_id),
        ),
    )
    conn.commit()



def mark_sent(conn: sqlite3.Connection, reminder_id: int) -> None:
    """
    Mark a reminder row as sent (by row id).
    """
    conn.execute(
        """
        UPDATE upcoming_games
        SET sent_at_utc = ?
        WHERE id = ?
        """,
        (utc_now_iso(), int(reminder_id)),
    )
    conn.commit()


def purge_expired_reminders(conn: sqlite3.Connection) -> int:
    """
    Delete:
      - anything already sent, OR
      - day-precision reminders older than ~36 hours (your existing window)
    Returns number of rows removed.
    """
    cutoff = (utc_now() - timedelta(hours=36)).isoformat()
    cur = conn.execute(
        """
        DELETE FROM upcoming_games
        WHERE sent_at_utc IS NOT NULL
           OR (
                release_at_utc IS NOT NULL
            AND release_precision = 'day'
            AND release_at_utc < ?
           )
        """,
        (cutoff,),
    )
    conn.commit()
    return cur.rowcount or 0
