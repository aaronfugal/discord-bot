# ingrid_patel/commands/reminders.py

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Optional

import aiohttp

from ingrid_patel.clients.steam_client import SteamClient
from ingrid_patel.db.connect import connect_guild_db
from ingrid_patel.db.repos.reminders_repo import (
    add_reminder_if_missing,
    list_upcoming_reminders_for_channel,
    purge_expired_reminders,
    list_upcoming_reminders,
)
from ingrid_patel.utils.time import parse_steam_release_date


def _parse_int(s: str) -> int | None:
    s = (s or "").strip()
    return int(s) if s.isdigit() else None


def _db_list_upcoming_sync(*, guild_id: int):
    conn = connect_guild_db(guild_id)
    try:
        purge_expired_reminders(conn)
        return list_upcoming_reminders(conn)
    finally:
        conn.close()


async def handle_addreminder(
    session: aiohttp.ClientSession,
    guild_id: int,
    channel_id: int,
    author_id: int,
    content: str,
) -> str:
    """
    Usage:
      *addreminder <steam_appid>
    """
    parts = (content or "").split()
    if len(parts) < 2:
        return "Usage: *addreminder <steam_appid>\nExample: *addreminder 620"

    app_id = _parse_int(parts[1])
    if app_id is None:
        return "App ID must be a number. Example: *addreminder 620"

    return await add_reminder_for_appid(
        session,
        guild_id=guild_id,
        author_id=author_id,
        channel_id=int(channel_id),
        app_id=app_id,
    )


async def handle_listreminders(ctx) -> str:
    """
    Lists upcoming reminders for THIS channel as __UI__:REMINDERS so app.py renders embeds.
    """
    if not ctx.guild_id or not ctx.channel_id:
        return "⚠️ This command only works in a server channel."

    def _db_read():
        conn = connect_guild_db(int(ctx.guild_id))
        try:
            purge_expired_reminders(conn)
            return list_upcoming_reminders_for_channel(conn, channel_id=int(ctx.channel_id))
        finally:
            conn.close()

    rows = await asyncio.to_thread(_db_read)

    items: list[dict[str, object]] = []
    for (_rid, app_id, name, _release_at_utc, release_date_text, release_precision) in rows:
        app_id = int(app_id)
        items.append(
            {
                "app_id": app_id,
                "name": str(name),
                "release_date_text": (release_date_text or "").strip(),
                "release_precision": (release_precision or "unknown"),
                "store_url": f"https://store.steampowered.com/app/{app_id}",
                "header_image": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg",
            }
        )

    payload = {"channel_id": int(ctx.channel_id), "items": items}
    return "__UI__:REMINDERS:" + json.dumps(payload, ensure_ascii=False)



async def add_reminder_for_appid(
    session: aiohttp.ClientSession,
    *,
    guild_id: int,
    author_id: int,
    channel_id: int,
    app_id: int,
) -> str:
    """
    Fetch Steam app details and insert a reminder row if missing.
    Stores:
      - release_date_text (as displayed by Steam)
      - release_at_utc (ISO string if we could parse a concrete date)
      - release_precision (year/month/day/unknown)
    """
    steam = SteamClient.from_env(session=session)

    try:
        details = await steam.get_app_details(app_id)
    except Exception as e:
        return f"Steam request failed for App ID {app_id}: {e}"

    if not details:
        return f"Could not find Steam app details for App ID {app_id}."

    release_text = (details.release_date_text or "").strip() or None
    if release_text:
        release_iso, precision = parse_steam_release_date(release_text)
    else:
        release_iso, precision = (None, "unknown")

    def _db_add_or_skip() -> bool:
        conn = connect_guild_db(guild_id)
        try:
            purge_expired_reminders(conn)
            return add_reminder_if_missing(
                conn,
                app_id=app_id,
                name=details.name,
                release_at_utc=release_iso,
                release_date_text=release_text,
                release_precision=precision,
                created_by_discord_id=str(author_id),
                remind_channel_id=int(channel_id),
            )
        finally:
            conn.close()

    inserted = await asyncio.to_thread(_db_add_or_skip)

    when = release_text or "TBA"
    if not inserted:
        return f"ℹ️ Reminder already exists: **{details.name}** — {when}"
    return f"✅ Reminder added: **{details.name}** — {when}\n{details.store_url}"
