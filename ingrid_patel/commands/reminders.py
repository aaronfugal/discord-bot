import sqlite3
from datetime import datetime, timezone, timedelta

from ingrid_patel.db.connect import connect_guild_db
from ingrid_patel.db.repos.reminders_repo import add_reminder, list_pending_reminders
from ingrid_patel.utils.time import format_release_mt


def _parse_int(s: str) -> int | None:
    s = s.strip()
    if not s.isdigit():
        return None
    return int(s)


def handle_addreminder(guild_id: int, author_id: int, content: str) -> str:
    """
    Expected: "*addreminder <steam_appid> <release_iso_utc>"
    For now: we require both appid + release time (backend hardcode/testing).
    We'll add assisted Steam lookup next.
    """
    parts = content.split()
    if len(parts) < 3:
        return "Usage: *addreminder <steam_appid> <release_iso_utc>\nExample: *addreminder 570 2026-01-10T02:00:00+00:00"

    app_id = _parse_int(parts[1])
    if app_id is None:
        return "App ID must be a number. Example: *addreminder 570 2026-01-10T02:00:00+00:00"

    release_iso = parts[2].strip()
    try:
        dt = datetime.fromisoformat(release_iso)
        if dt.tzinfo is None:
            return "Release time must include timezone. Use UTC like: 2026-01-10T02:00:00+00:00"
    except Exception:
        return "Invalid ISO datetime. Example: 2026-01-10T02:00:00+00:00"

    # name is temporary until assisted lookup exists
    name = f"Steam App {app_id}"

    conn = connect_guild_db(guild_id)
    try:
        add_reminder(
            conn,
            app_id=app_id,
            name=name,
            release_at_utc=release_iso,
            created_by_discord_id=str(author_id),
        )
    finally:
        conn.close()

    return f"Added reminder: **{name}** — releases {format_release_mt(release_iso)}"


def handle_listreminders(guild_id: int) -> str:
    conn = connect_guild_db(guild_id)
    try:
        now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        rows = list_pending_reminders(conn, now_iso)
    finally:
        conn.close()

    if not rows:
        return "No upcoming reminders."

    lines = ["Upcoming reminders:"]
    for (_id, app_id, name, release_at_utc) in rows:
        lines.append(f"- **{name}** (App {app_id}) — {format_release_mt(release_at_utc)}")
    return "\n".join(lines)
