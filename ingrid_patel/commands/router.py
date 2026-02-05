# ingrid_patel/commands/router.py

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo
import asyncio
import re

import aiohttp

from ingrid_patel.utils.time import utc_now, parse_iso
from ingrid_patel.db.connect import connect_guild_db
from ingrid_patel.db.repos.approval_repo import touch_plex_use, revoke_user
from ingrid_patel.db.repos.settings_repo import get_setting, get_int_setting, set_setting
from ingrid_patel.settings import owner_ids, INACTIVITY_DAYS

from ingrid_patel.commands.help import handle_help
from ingrid_patel.commands.media import (
    handle_searchmovie,
    handle_searchshow,
    handle_plexmovie,
    handle_plexshow,
)
from ingrid_patel.commands.reminders import handle_addreminder, handle_listreminders
from ingrid_patel.commands.search import handle_searchgame
from ingrid_patel.commands.wishlist import handle_wishlist


@dataclass(frozen=True)
class CommandContext:
    guild_id: int
    channel_id: int
    author_id: int
    content: str
    http: aiohttp.ClientSession


def _is_admin(ctx: CommandContext) -> bool:
    return ctx.author_id in owner_ids()


def _parse_first_mention_id(content: str) -> int | None:
    m = re.search(r"<@!?(\d+)>", content or "")
    return int(m.group(1)) if m else None


def _is_still_active_approved(conn, discord_id: str, inactivity_days: int = INACTIVITY_DAYS) -> bool:
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
    if not row:
        return False

    approved_at_utc, last_plex_use_at_utc = row
    last_iso = last_plex_use_at_utc or approved_at_utc
    last_dt = parse_iso(last_iso)

    if utc_now() - last_dt > timedelta(days=inactivity_days):
        # Owners are never auto-revoked
        if discord_id.isdigit() and int(discord_id) in owner_ids():
            return True

        revoke_user(
            conn,
            discord_id=discord_id,
            revoked_by_discord_id="system",
            note=f"Auto-revoked: inactive > {inactivity_days} days",
        )
        return False

    return True


def _require_approved_sync(ctx: CommandContext) -> str | None:
    """
    Return None if allowed. Otherwise return a signal string for app.py to DM the admin.
    """
    if _is_admin(ctx):
        return None

    conn = connect_guild_db(ctx.guild_id)
    try:
        if _is_still_active_approved(conn, str(ctx.author_id)):
            return None

        # Format: __ACCESS_REQUEST__:guild_id:channel_id:author_id:command_text
        content = (ctx.content or "").strip()
        return f"__ACCESS_REQUEST__:{ctx.guild_id}:{ctx.channel_id}:{ctx.author_id}:{content}"
    finally:
        conn.close()


async def _require_approved(ctx: CommandContext) -> str | None:
    return await asyncio.to_thread(_require_approved_sync, ctx)


def _touch_plex_use_sync(guild_id: int, author_id: int) -> None:
    conn = connect_guild_db(guild_id)
    try:
        touch_plex_use(conn, str(author_id))
    finally:
        conn.close()


# -------------------------
# Timezone helpers
# -------------------------

_TZ_ALIASES: dict[str, str] = {
    "mt": "America/Denver",
    "mountain": "America/Denver",
    "mountain time": "America/Denver",
    "denver": "America/Denver",
    "mst": "America/Denver",  # ambiguous; pick your default
    "utc": "UTC",
    "gmt": "Etc/GMT",
}


def _normalize_tz_name(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return s

    key = re.sub(r"\s+", " ", s).strip().lower()
    if key in _TZ_ALIASES:
        return _TZ_ALIASES[key]

    # If user typed "america/denver" in lowercase, try canonicalizing casing.
    if "/" in s and s == s.lower():
        parts = s.split("/")
        parts = [p.capitalize() for p in parts]
        return "/".join(parts)

    return s


def _validate_tz_or_error(tz_name: str) -> tuple[bool, str]:
    candidate = _normalize_tz_name(tz_name)
    if not candidate:
        return False, "Usage: *settimezone <IANA timezone>\nExample: *settimezone America/Denver"

    try:
        ZoneInfo(candidate)
        return True, candidate
    except Exception:
        examples = "America/Denver, America/New_York, Europe/London, UTC"
        return False, f"⚠️ Invalid timezone `{tz_name}`.\nUse an IANA name like: {examples}"


# -------------------------
# Main router
# -------------------------

async def dispatch_command(ctx: CommandContext) -> str | None:
    content = (ctx.content or "").strip()
    if not content.startswith("*"):
        return None

    parts = content.split()
    cmd = parts[0].lower()

    # Help
    if cmd == "*help":
        out = handle_help(is_admin=_is_admin(ctx))

        if _is_admin(ctx):
            conn = connect_guild_db(ctx.guild_id)
            try:
                tz = get_setting(conn, "timezone")
                ch_id = get_int_setting(conn, "allowed_channel_id")
            finally:
                conn.close()

            tz_str = f"`{tz}`" if tz else "_(not set)_"
            ch_str = f"<#{ch_id}>" if ch_id else "_(not set)_"

            out += (
                "\n"
                "---\n"
                "## ⚙️ Current Server Settings\n"
                f"- **Allowed channel:** {ch_str}\n"
                f"- **Timezone:** {tz_str}\n"
            )

        return out

    # Steam
    if cmd == "*searchgame":
        return await handle_searchgame(ctx.http, ctx.author_id, ctx.content)

    # Reminders
    if cmd == "*addreminder":
        return await handle_addreminder(
            ctx.http,
            ctx.guild_id,
            ctx.channel_id,
            ctx.author_id,
            ctx.content,
        )

    if cmd == "*reminders":
        return await handle_listreminders(ctx)

    # Wishlist
    if cmd == "*wishlist":
        return await handle_wishlist(ctx)

    # ARR search
    if cmd == "*searchmovie":
        return await handle_searchmovie(ctx.http, ctx.author_id, ctx.content)

    if cmd == "*searchshow":
        return await handle_searchshow(ctx.http, ctx.author_id, ctx.content)

    # Protected actions
    if cmd == "*plexmovie":
        deny = await _require_approved(ctx)
        if deny:
            return deny
        out = await handle_plexmovie(ctx.http, ctx.content)
        if not _is_admin(ctx):
            await asyncio.to_thread(_touch_plex_use_sync, ctx.guild_id, ctx.author_id)
        return out

    if cmd == "*plexshow":
        deny = await _require_approved(ctx)
        if deny:
            return deny
        out = await handle_plexshow(ctx.http, ctx.content)
        if not _is_admin(ctx):
            await asyncio.to_thread(_touch_plex_use_sync, ctx.guild_id, ctx.author_id)
        return out

    # Admin-only
    if cmd == "*approve":
        if not _is_admin(ctx):
            return "Admins only."
        target_id = _parse_first_mention_id(ctx.content)
        if not target_id:
            return "Usage: *approve @user"
        if target_id in owner_ids():
            return "The bot owner is always approved."
        return f"__ADMIN_APPROVE__:{ctx.guild_id}:{target_id}:{ctx.author_id}"

    if cmd == "*revoke":
        if not _is_admin(ctx):
            return "Admins only."
        target_id = _parse_first_mention_id(ctx.content)
        if not target_id:
            return "Usage: *revoke @user"
        if target_id in owner_ids():
            return "❌ You cannot revoke the bot owner."
        return f"__ADMIN_REVOKE__:{ctx.guild_id}:{target_id}:{ctx.author_id}"

    if cmd == "*plexaccess":
        if not _is_admin(ctx):
            return "Admins only."
        return f"__ADMIN_PLEXACCESS__:{ctx.guild_id}"

    if cmd == "*setchannel":
        if not _is_admin(ctx):
            return "Admins only."

        m = re.search(r"<#(\d+)>", ctx.content or "")
        if m:
            ch_id = int(m.group(1))
        else:
            parts2 = (ctx.content or "").split()
            if len(parts2) < 2 or not parts2[1].isdigit():
                return "Usage: *setchannel <#channel>  OR  *setchannel <channel_id>"
            ch_id = int(parts2[1])

        conn = connect_guild_db(ctx.guild_id)
        try:
            set_setting(conn, "allowed_channel_id", str(ch_id))
        finally:
            conn.close()

        return f"✅ Allowed channel set to <#{ch_id}>"

    if cmd == "*settimezone":
        if not _is_admin(ctx):
            return "Admins only."

        parts2 = (ctx.content or "").split(maxsplit=1)
        tz_raw = parts2[1].strip() if len(parts2) > 1 else ""
        ok, canon_or_err = _validate_tz_or_error(tz_raw)
        if not ok:
            return canon_or_err

        tz_name = canon_or_err

        conn = connect_guild_db(ctx.guild_id)
        try:
            set_setting(conn, "timezone", tz_name)
        finally:
            conn.close()

        try:
            now_local = utc_now().astimezone(ZoneInfo(tz_name))
            now_str = now_local.strftime("%Y-%m-%d %I:%M %p")
            return f"✅ Timezone set to `{tz_name}` (now: {now_str})"
        except Exception:
            return f"✅ Timezone set to `{tz_name}`"

    # Unknown command fallback
    return "Check spelling. Run `*help` to see available commands."
