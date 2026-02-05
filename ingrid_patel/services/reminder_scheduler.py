# ingrid_patel/services/reminder_scheduler.py

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from ingrid_patel.db.connect import connect_guild_db
from ingrid_patel.db.repos.reminders_repo import list_due_reminders


def check_and_collect_tomorrow_reminders(
    guild_id: int,
    *,
    tz_name: str | None = None,
) -> list[tuple[int, int, str, str, int]]:
    """
    Returns rows due *tomorrow* in the provided timezone:
      (reminder_id, app_id, name, release_at_utc, remind_channel_id)

    If tz_name is missing/invalid, returns [] (guild not configured yet).
    """
    if not tz_name:
        return []

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        return []

    now_local = datetime.now(tz).replace(microsecond=0)

    tomorrow_start_local = (now_local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    day_after_start_local = tomorrow_start_local + timedelta(days=1)

    start_utc_iso = tomorrow_start_local.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    end_utc_iso = day_after_start_local.astimezone(timezone.utc).replace(microsecond=0).isoformat()

    conn = connect_guild_db(guild_id)
    try:
        return list_due_reminders(conn, start_utc_iso=start_utc_iso, end_utc_iso=end_utc_iso)
    finally:
        conn.close()
