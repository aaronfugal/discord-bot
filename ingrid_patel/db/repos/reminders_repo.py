import sqlite3
from datetime import datetime, timezone
from typing import Optional, List, Tuple

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def add_reminder(
        conn: sqlite3.Connection,
        app_id: int,
        name: str,
        release_at_utc: str,
        created_by_discord_id: Optional[str],
) -> None:
    conn.execute(
        """
        INSERT INTO upcoming_games (app_id, name, release_at_utc, created_by_discord_id, created_at_utc, sent_at_utc)
        VALUES (?, ?, ?, ?, ?, NULL)
        """,
        (app_id, name, release_at_utc, created_by_discord_id, _utc_now_iso()),
    )
    conn.commit()


def list_pending_reminders(conn: sqlite3.Connection, now_utc_iso: str) -> List[Tuple[int, int, str, str]]:
    """
    Returns reminders that have NOT been sent and have NOT passed.
    Tuple: (id, app_id, name, release_at_utc)
    """
    cur = conn.execute(
        """
        SELECT id, app_id, name, release_at_utc
        FROM upcoming_games
        WHERE sent_at_utc IS NULL AND release_at_utc >= ?
        ORDER BY release_at_utc ASC
        """,
        (now_utc_iso,),
    )
    return cur.fetchall()


def list_due_reminders(conn: sqlite3.Connection, start_utc_iso: str, end_utc_iso: str) -> List[Tuple[int, int, str, str]]:
    """
    Returns reminders that should fire in [start,end], and are not sent.
    Tuple: (id, app_id, name, release_at_utc)
    """
    cur = conn.execute(
        """
        SELECT id, app_id, name, release_at_utc
        FROM upcoming_games
        WHERE sent_at_utc IS NULL AND release_at_utc BETWEEN ? AND ?
        ORDER BY release_at_utc ASC
        """,
        (start_utc_iso, end_utc_iso),
    )
    return cur.fetchall()


def mark_sent(conn: sqlite3.Connection, reminder_id: int) -> None:
    conn.execute(
        """
        UPDATE upcoming_games
        SET sent_at_utc = ?
        WHERE id = ?
        """,
        (_utc_now_iso(), reminder_id),
    )
    conn.commit()