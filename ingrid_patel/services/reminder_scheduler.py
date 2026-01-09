from datetime import datetime, timezone, timedelta

from ingrid_patel.db.connect import connect_guild_db
from ingrid_patel.db.repos.reminders_repo import list_due_reminders, mark_sent


REMINDER_WINDOW_SECONDS = 60  # check next 60s


def check_and_collect_due_reminders(guild_id: int) -> list[tuple[int, int, str, str]]:
    """
    Returns reminders due to fire now.
    Each tuple: (id, app_id, name, release_at_utc)
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)
    window_end = now + timedelta(seconds=REMINDER_WINDOW_SECONDS)

    conn = connect_guild_db(guild_id)
    try:
        rows = list_due_reminders(
            conn,
            start_utc_iso=now.isoformat(),
            end_utc_iso=window_end.isoformat(),
        )
        for (rid, *_rest) in rows:
            mark_sent(conn, rid)
        return rows
    finally:
        conn.close()
