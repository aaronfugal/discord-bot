# ingrid_patel/db/repos/approval_repo.py

from __future__ import annotations

import sqlite3
from ingrid_patel.utils.time import utc_now_iso, canonical_utc_iso


def get_active_approved_user(conn: sqlite3.Connection, discord_id: str) -> tuple[str, str | None] | None:
    """
    Returns (approved_at_utc, last_plex_use_at_utc) if user is approved and not revoked, else None.
    """
    cur = conn.execute(
        """
        SELECT approved_at_utc, last_plex_use_at_utc
        FROM approved_users
        WHERE discord_id = ? AND revoked_at_utc IS NULL
        LIMIT 1
        """,
        (discord_id,),
    )
    row = cur.fetchone()
    return row if row else None


def approve_user(
    conn: sqlite3.Connection,
    *,
    discord_id: str,
    approved_by_discord_id: str,
    note: str | None = None,
) -> None:
    """
    Insert a new approved user if they don't exist, update them if they do exist.
    If they existed but were revoked, un-revoke them.

    Also initializes last_plex_use_at_utc to NULL (touch_plex_use will set it on first use).
    """
    conn.execute(
        """
        INSERT INTO approved_users (
            discord_id,
            approved_at_utc,
            approved_by_discord_id,
            note,
            revoked_at_utc,
            revoked_by_discord_id,
            last_plex_use_at_utc
        )
        VALUES (?, ?, ?, ?, NULL, NULL, NULL)
        ON CONFLICT(discord_id) DO UPDATE SET
            approved_at_utc=excluded.approved_at_utc,
            approved_by_discord_id=excluded.approved_by_discord_id,
            note=excluded.note,
            revoked_at_utc=NULL,
            revoked_by_discord_id=NULL
        """,
        (discord_id, utc_now_iso(), approved_by_discord_id, note),
    )
    conn.commit()


def revoke_user(
    conn: sqlite3.Connection,
    *,
    discord_id: str,
    revoked_by_discord_id: str,
    note: str | None = None,
) -> None:
    """
    Mark user as revoked (no-op if already revoked or not present).
    """
    conn.execute(
        """
        UPDATE approved_users
        SET revoked_at_utc = ?, revoked_by_discord_id = ?, note = COALESCE(?, note)
        WHERE discord_id = ? AND revoked_at_utc IS NULL
        """,
        (utc_now_iso(), revoked_by_discord_id, note, discord_id),
    )
    conn.commit()


def list_approved(conn: sqlite3.Connection) -> list[tuple[str, str, str | None, str]]:
    """
    Returns active approved users:
      (discord_id, approved_at_utc, last_plex_use_at_utc, note)

    NOTE: This matches the app.py __ADMIN_PLEXACCESS__ handler that computes "time left".
    """
    cur = conn.execute(
        """
        SELECT
            discord_id,
            approved_at_utc,
            last_plex_use_at_utc,
            COALESCE(note, '')
        FROM approved_users
        WHERE revoked_at_utc IS NULL
        ORDER BY approved_at_utc ASC
        """
    )
    return cur.fetchall()


def get_pending_request(
    conn: sqlite3.Connection,
    *,
    guild_id: int,
    discord_id: str,
) -> tuple[int, str, str, str, int, int] | None:
    cur = conn.execute(
        """
        SELECT guild_id, discord_id, requested_at_utc, expires_at_utc, request_channel_id, request_message_id
        FROM approval_requests
        WHERE guild_id = ? AND discord_id = ?
        LIMIT 1
        """,
        (guild_id, discord_id),
    )
    return cur.fetchone()


def upsert_pending_request(
    conn: sqlite3.Connection,
    *,
    guild_id: int,
    discord_id: str,
    requested_at_utc: str,
    expires_at_utc: str,
    request_channel_id: int,
    request_message_id: int,
) -> None:
    conn.execute(
        """
        INSERT INTO approval_requests (
            guild_id, discord_id, requested_at_utc, expires_at_utc, request_channel_id, request_message_id
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(guild_id, discord_id) DO UPDATE SET
            requested_at_utc=excluded.requested_at_utc,
            expires_at_utc=excluded.expires_at_utc,
            request_channel_id=excluded.request_channel_id,
            request_message_id=excluded.request_message_id
        """,
        (guild_id, discord_id, requested_at_utc, expires_at_utc, request_channel_id, request_message_id),
    )
    conn.commit()


def delete_pending_request(conn: sqlite3.Connection, *, guild_id: int, discord_id: str) -> None:
    conn.execute(
        """
        DELETE FROM approval_requests
        WHERE guild_id = ? AND discord_id = ?
        """,
        (guild_id, discord_id),
    )
    conn.commit()


def delete_pending_request_by_message(
    conn: sqlite3.Connection,
    *,
    guild_id: int,
    request_message_id: int,
) -> tuple[str, int] | None:
    cur = conn.execute(
        """
        SELECT discord_id, request_channel_id
        FROM approval_requests
        WHERE guild_id = ? AND request_message_id = ?
        LIMIT 1
        """,
        (guild_id, request_message_id),
    )
    row = cur.fetchone()
    if not row:
        return None

    discord_id, request_channel_id = row
    conn.execute(
        """
        DELETE FROM approval_requests
        WHERE guild_id = ? AND request_message_id = ?
        """,
        (guild_id, request_message_id),
    )
    conn.commit()
    return (discord_id, request_channel_id)


def list_expired_pending_requests(
    conn: sqlite3.Connection,
    *,
    now_utc_iso: str,
) -> list[tuple[int, str, int, int]]:
    cur = conn.execute(
        """
        SELECT guild_id, discord_id, request_channel_id, request_message_id
        FROM approval_requests
        WHERE expires_at_utc <= ?
        ORDER BY expires_at_utc ASC
        """,
        (now_utc_iso,),
    )
    return cur.fetchall()


def touch_plex_use(conn: sqlite3.Connection, discord_id: str) -> None:
    """
    Update last_plex_use_at_utc for an approved, non-revoked user.

    Safe no-op if user is not approved or already revoked (won't crash).
    """
    conn.execute(
        """
        UPDATE approved_users
        SET last_plex_use_at_utc = ?
        WHERE discord_id = ? AND revoked_at_utc IS NULL
        """,
        (utc_now_iso(), discord_id),
    )
    conn.commit()


def list_inactive_approved_users(conn: sqlite3.Connection, *, cutoff_utc_iso: str) -> list[str]:
    """
    Approved users who haven't used plex commands since before cutoff
    (or have never used plex commands at all).
    """
    cur = conn.execute(
        """
        SELECT discord_id
        FROM approved_users
        WHERE revoked_at_utc IS NULL
          AND (last_plex_use_at_utc IS NULL OR last_plex_use_at_utc < ?)
        """,
        (cutoff_utc_iso,),
    )
    return [row[0] for row in cur.fetchall()]
