# ingrid_patel/services/scheduler.py

from __future__ import annotations

import logging
from typing import Any
from datetime import datetime

import discord
from discord import Client
from discord.ext import tasks
from zoneinfo import ZoneInfo

from ingrid_patel.db.repos.settings_repo import get_setting, set_setting
from ingrid_patel.clients.steam_client import SteamClient
from ingrid_patel.services.reminder_scheduler import check_and_collect_tomorrow_reminders
from ingrid_patel.db.connect import connect_guild_db
from ingrid_patel.db.repos.wishlist_repo import list_wishlist
from ingrid_patel.db.repos.reminders_repo import (
    purge_expired_reminders,
    mark_sent,
    list_unsent_for_refresh,
    update_release_fields,
)
from ingrid_patel.utils.time import parse_steam_release_date
from ingrid_patel.settings import (
    TESTING_MODE,
    TEST_GUILD_ID,
    TEST_CHANNEL_ID,
    TEST_TIMEZONE,
)

log = logging.getLogger(__name__)





def _get_guild_timezone(guild_id: int) -> str | None:
    """
    Returns stored IANA timezone name (settings.timezone) or None if not configured.
    """
    if TESTING_MODE and int(guild_id) == int(TEST_GUILD_ID):
        return str(TEST_TIMEZONE)

    conn = connect_guild_db(guild_id)
    try:
        tz = (get_setting(conn, "timezone") or "").strip()
    finally:
        conn.close()
    return tz or None


def _get_guild_allowed_channel_id(guild_id: int) -> int | None:
    """
    Returns stored allowed channel id (settings.allowed_channel_id) or None if not configured.
    """
    if TESTING_MODE:
        return int(TEST_CHANNEL_ID) if int(guild_id) == int(TEST_GUILD_ID) else None

    conn = connect_guild_db(guild_id)
    try:
        v = (get_setting(conn, "allowed_channel_id") or "").strip()
    finally:
        conn.close()

    if not v.isdigit():
        return None

    try:
        cid = int(v)
        return cid if cid > 0 else None
    except Exception:
        return None


# -------------------------
# "Run once per day" gate
# -------------------------

def _in_local_window(now_local: datetime, *, hour: int, minute: int, window_seconds: int = 120) -> bool:
    """
    True if now_local is within [target, target + window_seconds).
    """
    target = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    delta = (now_local - target).total_seconds()
    return 0 <= delta < window_seconds


def _should_run_today(conn, *, key: str, local_ymd: str) -> bool:
    """
    Returns True if settings[key] != local_ymd. If True, caller should run then set it.
    """
    last = (get_setting(conn, key) or "").strip()
    return last != local_ymd


# -------------------------
# Discord send helpers
# -------------------------

async def _send_embeds_compat(
    channel: discord.abc.Messageable,
    *,
    content: str | None = None,
    embeds: list[discord.Embed] | None = None,
) -> None:
    """
    Send embeds in a way that works across discord.py / forks.
    - Prefer a single message with `embeds=[...]`.
    - Fallback to sending header + each embed individually if `embeds` kwarg isn't supported.
    """
    embeds = embeds or []

    # Nothing to embed -> just send content if present
    if not embeds:
        if content:
            await channel.send(content)
        return

    # Try modern signature: send(content=..., embeds=[...])
    try:
        await channel.send(content or None, embeds=embeds)
        return
    except TypeError:
        # Old lib that doesn't accept embeds=
        pass

    # Fallback: send header, then each embed as `embed=...`
    if content:
        await channel.send(content)

    for e in embeds:
        try:
            await channel.send(embed=e)
        except TypeError:
            # Truly ancient or different fork; last resort: drop embed and send title/url
            title = (getattr(e, "title", None) or "Item").strip()
            url = (getattr(e, "url", None) or "").strip()
            await channel.send(f"{title}\n{url}".strip())


def _plain_wishlist_lines(on_sale: list[dict[str, Any]], *, limit: int = 10) -> list[str]:
    lines: list[str] = []
    for s in on_sale[:limit]:
        name = (s.get("name") or "Game").strip()
        url = (s.get("store_url") or "").strip()
        disc = int(s.get("discount_percent") or 0)
        final = s.get("final")
        initial = s.get("initial")

        if final and initial:
            price = f"{final} (was {initial})"
        elif final:
            price = str(final)
        else:
            price = "See store"

        if url:
            lines.append(f"• **{name}** — {disc}% off — {price}\n  {url}")
        else:
            lines.append(f"• **{name}** — {disc}% off — {price}")

    return lines


# -------------------------
# Per-guild job runners
# -------------------------

async def _run_refresh_for_guild(client: Client, guild_id: int, tz_name: str, local_ymd: str) -> None:
    # Ensure shared http session exists
    try:
        http = await client.ensure_http_session()  # type: ignore[attr-defined]
    except Exception:
        log.exception("[refresh] ensure_http_session failed guild=%s", guild_id)
        return

    steam = SteamClient.from_env(session=http)

    try:
        conn = connect_guild_db(guild_id)
    except Exception:
        log.exception("[refresh] db open failed guild=%s", guild_id)
        return

    try:
        rows = list_unsent_for_refresh(conn)  # [(app_id, old_release_date_text), ...]
        if not rows:
            set_setting(conn, "last_run_refresh_ymd", local_ymd)
            return

        updated = 0
        checked = 0

        for (app_id, old_text) in rows:
            checked += 1
            try:
                details = await steam.get_app_details(int(app_id))
            except Exception:
                log.exception("[refresh] steam details failed app_id=%s guild=%s", app_id, guild_id)
                continue

            if not details:
                continue

            new_text = (details.release_date_text or "").strip() or None

            if new_text:
                iso, precision = parse_steam_release_date(new_text)
            else:
                iso, precision = (None, "unknown")

            # Keep sentinel behavior for ordering if unknown
            if iso is None:
                iso = "9999-12-31T00:00:00+00:00"
                if precision == "unknown":
                    precision = "unknown"

            old_norm = (old_text or "").strip()
            new_norm = (new_text or "").strip()
            if old_norm != new_norm:
                try:
                    update_release_fields(
                        conn,
                        app_id=int(app_id),
                        release_at_utc=iso,
                        release_date_text=new_text,
                        release_precision=precision,
                    )
                    updated += 1
                except Exception:
                    log.exception("[refresh] db update failed app_id=%s guild=%s", app_id, guild_id)

        set_setting(conn, "last_run_refresh_ymd", local_ymd)
        log.info(
            "[refresh] guild=%s tz=%s ymd=%s checked=%s updated=%s",
            guild_id, tz_name, local_ymd, checked, updated
        )

    except Exception:
        log.exception("[refresh] loop failed guild=%s", guild_id)
    finally:
        conn.close()


async def _run_reminders_for_guild(client: Client, guild_id: int, tz_name: str, local_ymd: str) -> None:
    # 1) Purge DB so it doesn't grow forever
    try:
        conn = connect_guild_db(guild_id)
        try:
            purged = purge_expired_reminders(conn)
            if purged:
                log.info("[reminders] purged %d expired reminder(s) guild=%s", purged, guild_id)
        finally:
            conn.close()
    except Exception:
        log.exception("[reminders] purge failed guild=%s", guild_id)

    # 2) Send tomorrow reminders (timezone-aware)
    rows = check_and_collect_tomorrow_reminders(guild_id, tz_name=tz_name)
    if not rows:
        conn = connect_guild_db(guild_id)
        try:
            set_setting(conn, "last_run_reminders_ymd", local_ymd)
        finally:
            conn.close()
        return

    # guild fallback is the configured allowed channel
    fallback_channel_id = _get_guild_allowed_channel_id(guild_id)

    conn = connect_guild_db(guild_id)
    try:
        for (rid, app_id, name, _release_at_utc, remind_channel_id) in rows:
            # Target order:
            # 1) reminder row’s remind_channel_id if set (and >0)
            # 2) guild allowed_channel_id if configured
            # 3) otherwise skip (setup required)
            target_channel_id: int | None = None

            if TESTING_MODE:
                target_channel_id = int(TEST_CHANNEL_ID)
            else:
                try:
                    if remind_channel_id is not None and int(remind_channel_id) > 0:
                        target_channel_id = int(remind_channel_id)
                except Exception:
                    target_channel_id = None

                if target_channel_id is None:
                    target_channel_id = fallback_channel_id

            if target_channel_id is None:
                log.warning("[reminders] no channel configured rid=%s guild=%s (run *setchannel)", rid, guild_id)
                continue

            channel = client.get_channel(int(target_channel_id))
            if not channel:
                log.warning("[reminders] channel %s not found guild=%s", target_channel_id, guild_id)
                continue

            msg = f"**{name}** is coming out soon! https://store.steampowered.com/app/{app_id}"

            try:
                await channel.send(msg)
            except Exception:
                log.exception("[reminders] send failed rid=%s guild=%s channel=%s", rid, guild_id, target_channel_id)
                continue

            try:
                mark_sent(conn, rid)
            except Exception:
                log.exception("[reminders] mark_sent failed rid=%s guild=%s", rid, guild_id)

        set_setting(conn, "last_run_reminders_ymd", local_ymd)
        log.info(
            "[reminders] processed %d reminder(s) guild=%s tz=%s ymd=%s",
            len(rows), guild_id, tz_name, local_ymd
        )

    finally:
        conn.close()


async def _run_wishlist_for_guild(client: Client, guild_id: int, tz_name: str, local_ymd: str) -> None:
    # Ensure shared http session exists
    try:
        http = await client.ensure_http_session()  # type: ignore[attr-defined]
    except Exception:
        log.exception("[wishlist] ensure_http_session failed guild=%s", guild_id)
        return

    steam = SteamClient.from_env(session=http)

    # Load wishlist rows
    try:
        conn = connect_guild_db(guild_id)
        try:
            rows = list_wishlist(conn)  # [(channel_id, app_id, name), ...]
        finally:
            conn.close()
    except Exception:
        log.exception("[wishlist] db read failed guild=%s", guild_id)
        return

    if not rows:
        conn = connect_guild_db(guild_id)
        try:
            set_setting(conn, "last_run_wishlist_ymd", local_ymd)
        finally:
            conn.close()
        return

    # Group by channel_id
    by_channel: dict[int, list[tuple[int, str]]] = {}
    for (channel_id, app_id, name) in rows:
        by_channel.setdefault(int(channel_id), []).append((int(app_id), str(name)))

    guild = client.get_guild(guild_id)

    for channel_id, items in by_channel.items():
        if TESTING_MODE and int(channel_id) != int(TEST_CHANNEL_ID):
            continue

        on_sale: list[dict[str, Any]] = []

        for app_id, _name in items:
            try:
                snap = await steam.get_price_snapshot(app_id)
            except Exception:
                log.exception("[wishlist] price fetch failed app_id=%s guild=%s", app_id, guild_id)
                continue

            if not snap:
                continue

            disc = snap.get("discount_percent") or 0
            if isinstance(disc, int) and disc > 0:
                on_sale.append(snap)

        if not on_sale:
            continue

        on_sale.sort(key=lambda x: int(x.get("discount_percent") or 0), reverse=True)

        channel = client.get_channel(int(channel_id))
        if not channel:
            log.warning("[wishlist] channel %s not found guild=%s", channel_id, guild_id)
            continue

        # If the bot cannot embed links in this channel, send a plain-text digest instead.
        try:
            if guild is not None and hasattr(channel, "permissions_for"):
                me = getattr(guild, "me", None)
                if me is not None:
                    perms = channel.permissions_for(me)  # type: ignore[attr-defined]
                    if not getattr(perms, "embed_links", True):
                        lines = _plain_wishlist_lines(on_sale, limit=10)
                        header = "🛒 **Channel wishlist sales today:**\n(Enable the bot's **Embed Links** permission to see rich cards.)"
                        await channel.send(header + ("\n" + "\n".join(lines) if lines else ""))
                        log.info("[wishlist] sent plaintext digest (no embed perm) guild=%s channel=%s", guild_id, channel_id)
                        continue
        except Exception:
            # If permission check fails, just attempt embeds normally.
            pass

        embeds: list[discord.Embed] = []
        for s in on_sale[:10]:
            name = (s.get("name") or "Game").strip()
            url = (s.get("store_url") or "").strip()
            header = (s.get("header_image") or "").strip()
            disc = int(s.get("discount_percent") or 0)

            final = s.get("final")
            initial = s.get("initial")

            title = f"{name} — {disc}% off"
            e = discord.Embed(title=title, url=url)

            if header:
                # Thumbnail is usually safer than large images, and works in more clients.
                e.set_thumbnail(url=header)

            if final and initial:
                e.add_field(name="Price", value=f"{final} (was {initial})", inline=False)
            elif final:
                e.add_field(name="Price", value=str(final), inline=False)

            embeds.append(e)

        try:
            # This is the key change: always send embeds in a compatibility-safe way.
            await _send_embeds_compat(channel, content="🛒 **Channel wishlist sales today:**", embeds=embeds)
            log.info("[wishlist] sent sale digest guild=%s channel=%s count=%s", guild_id, channel_id, len(on_sale))
        except discord.Forbidden:
            log.warning(
                "[wishlist] forbidden sending to channel guild=%s channel=%s (check Send Messages / Embed Links perms)",
                guild_id, channel_id
            )
        except Exception:
            log.exception("[wishlist] send failed guild=%s channel=%s", guild_id, channel_id)

    conn = connect_guild_db(guild_id)
    try:
        set_setting(conn, "last_run_wishlist_ymd", local_ymd)
    finally:
        conn.close()


# -------------------------
# Master tick (per-guild local times)
# -------------------------

@tasks.loop(seconds=30)
async def master_tick(client: Client) -> None:
    for g in client.guilds:
        guild_id = g.id
        if TESTING_MODE and int(guild_id) != int(TEST_GUILD_ID):
            continue

        tz_name = _get_guild_timezone(guild_id)
        if not tz_name:
            # Not configured yet -> do nothing scheduled for this guild.
            continue

        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            log.warning("[scheduler] invalid timezone guild=%s tz=%r (run *settimezone)", guild_id, tz_name)
            continue

        now_local = datetime.now(tz).replace(microsecond=0)
        local_ymd = now_local.date().isoformat()

        # Refresh at 17:55 local
        if _in_local_window(now_local, hour=17, minute=55, window_seconds=120):
            conn = connect_guild_db(guild_id)
            try:
                if not _should_run_today(conn, key="last_run_refresh_ymd", local_ymd=local_ymd):
                    continue
            finally:
                conn.close()

            await _run_refresh_for_guild(client, guild_id, tz_name, local_ymd)

        # Reminders at 18:00 local
        if _in_local_window(now_local, hour=18, minute=0, window_seconds=120):
            conn = connect_guild_db(guild_id)
            try:
                if not _should_run_today(conn, key="last_run_reminders_ymd", local_ymd=local_ymd):
                    continue
            finally:
                conn.close()

            await _run_reminders_for_guild(client, guild_id, tz_name, local_ymd)

        # Wishlist at 18:03 local
        if _in_local_window(now_local, hour=18, minute=3, window_seconds=120):
            conn = connect_guild_db(guild_id)
            try:
                if not _should_run_today(conn, key="last_run_wishlist_ymd", local_ymd=local_ymd):
                    continue
            finally:
                conn.close()

            await _run_wishlist_for_guild(client, guild_id, tz_name, local_ymd)


@master_tick.before_loop
async def before_master_tick() -> None:
    log.info("[scheduler] master tick starting")


_started = False

def start(client: Client) -> None:
    global _started
    if _started:
        return

    if not master_tick.is_running():
        master_tick.start(client)

    _started = True
    log.info("[scheduler] started (per-guild timezone)")
