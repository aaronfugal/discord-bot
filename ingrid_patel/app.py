# ingrid_patel/app.py

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Optional

import aiohttp
import discord
import asyncio
from discord import Client, Intents, Embed, Interaction
from zoneinfo import ZoneInfo

from ingrid_patel.bootstrap import load_env
from ingrid_patel.services import scheduler
from ingrid_patel.utils.time import utc_now, parse_iso, parse_steam_release_date
from ingrid_patel.commands.reminders import add_reminder_for_appid
from ingrid_patel.commands.router import CommandContext, dispatch_command
from ingrid_patel.db.connect import connect_guild_db
from ingrid_patel.db.repos.settings_repo import get_setting
from ingrid_patel.db.repos.wishlist_repo import (
    is_in_wishlist,
    add_to_wishlist_if_missing,
    remove_from_wishlist,
)
from ingrid_patel.db.repos.approval_repo import (
    approve_user,
    revoke_user,
    list_approved,
    touch_plex_use,
)
from ingrid_patel.db.repos.reminders_repo import reminder_exists, remove_reminder
from ingrid_patel.settings import (
    owner_ids,
    HTTP_TIMEOUT_SECONDS,
)

log = logging.getLogger(__name__)


def _steam_header_img(app_id: int) -> str:
    return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"


def _parse_ui(resp: str) -> tuple[str, dict[str, Any]] | None:
    if not isinstance(resp, str) or not resp.startswith("__UI__:"):
        return None
    try:
        _pfx, kind, json_blob = resp.split(":", 2)
        payload = json.loads(json_blob)
        if not isinstance(payload, dict):
            return None
        return kind, payload
    except Exception:
        log.exception("Failed to parse UI payload")
        return None


def _truncate(s: str, max_len: int) -> str:
    s = (s or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1].rstrip() + "…"


def _fmt_platforms(p: dict[str, Any] | None) -> str:
    if not isinstance(p, dict):
        return "Unknown"
    parts = []
    if p.get("windows"):
        parts.append("Windows")
    if p.get("mac"):
        parts.append("Mac")
    if p.get("linux"):
        parts.append("Linux")
    return ", ".join(parts) if parts else "Unknown"


def _safe_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        return int(x)
    except Exception:
        return None


def _get_allowed_channel_id(guild_id: int) -> int | None:
    conn = connect_guild_db(int(guild_id))
    try:
        val = get_setting(conn, "allowed_channel_id")
    finally:
        conn.close()

    if not val:
        return None
    val = str(val).strip()
    if not val.isdigit():
        return None
    cid = int(val)
    return cid if cid > 0 else None


def _get_guild_timezone(guild_id: int) -> str | None:
    """
    Returns settings.timezone or None if not configured/blank.
    """
    conn = connect_guild_db(int(guild_id))
    try:
        val = get_setting(conn, "timezone")
    finally:
        conn.close()

    if not val:
        return None
    tz = str(val).strip()
    return tz or None


def _cmd_name(content: str) -> str:
    text = (content or "").strip()
    if not text.startswith("*"):
        return ""
    return (text.split(maxsplit=1)[0] or "").lower()



def _is_admin_anywhere_command(content: str) -> bool:
    # Allowed anywhere AFTER channel is configured, but only for owner
    return _cmd_name(content) in (
        "*help",
        "*setchannel",
        "*settimezone",
    )



def _is_preconfig_allowed_command(content: str) -> bool:
    """
    Commands allowed from ANY channel BEFORE *setchannel has been configured.
    Keep this list tight to avoid spam.
    """
    text = (content or "").strip()
    if not text.startswith("*"):
        return False
    cmd = (text.split(maxsplit=1)[0] or "").lower()

    return cmd in (
        # setup / docs
        "*help", "*setchannel", "*settimezone",

        # safe/read-only commands
        "*searchgame", "*searchmovie", "*searchshow",
        "*wishlist", "*reminders",
    )



def _should_show_reminder_button(data: dict[str, Any], *, guild_id: int | None) -> bool:
    """
    Show reminder button unless we are confident the game released before *today*
    in the guild's configured timezone.

    - If timezone not configured, fail-open: show button.
    - If Steam date isn't precise day, fail-open: show button.
    """
    release_text = (data.get("release_date_text") or "").strip()
    if not release_text:
        return True

    iso, precision = parse_steam_release_date(release_text)

    # If Steam gives "Coming Soon"/"TBA"/weird stuff -> fail open (show)
    if iso is None:
        return True

    # Anchors are not reliable for "already released" decisions -> show
    if precision != "day":
        return True

    # Need a real tz to compare to "today" meaningfully
    if not guild_id:
        return True

    tz_name = _get_guild_timezone(int(guild_id))
    if not tz_name:
        return True

    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        return True

    try:
        dt_utc = parse_iso(iso)
    except Exception:
        return True

    today_local = datetime.now(tz).date()
    release_local = dt_utc.astimezone(tz).date()

    return release_local >= today_local


def _build_game_detail_embed(data: dict[str, Any]) -> Embed:
    # data is what steam_client.get_app_details_rich() returns
    app_id = _safe_int(data.get("app_id"))
    name = (data.get("name") or "Game").strip()
    store_url = (data.get("store_url") or "").strip()

    e = Embed(title=name, url=store_url)

    header = (data.get("header_image") or "").strip()
    if header:
        e.set_thumbnail(url=header)
    elif app_id:
        e.set_thumbnail(url=_steam_header_img(app_id))

    short_desc = _truncate((data.get("short_description") or "").strip(), 800)
    if short_desc:
        e.description = short_desc

    release_text = (data.get("release_date_text") or "").strip() or "Unknown"
    coming = data.get("coming_soon")
    release_line = release_text + (" (coming soon)" if coming is True else "")
    e.add_field(name="Release", value=_truncate(release_line, 256), inline=True)

    devs = data.get("developers") or []
    pubs = data.get("publishers") or []
    if isinstance(devs, list) and devs:
        e.add_field(name="Developer", value=_truncate(", ".join(map(str, devs)), 256), inline=True)
    if isinstance(pubs, list) and pubs:
        e.add_field(name="Publisher", value=_truncate(", ".join(map(str, pubs)), 256), inline=True)

    e.add_field(name="Platforms", value=_fmt_platforms(data.get("platforms")), inline=True)

    genres = data.get("genres") or []
    if isinstance(genres, list) and genres:
        e.add_field(name="Genres", value=_truncate(", ".join(map(str, genres[:10])), 512), inline=False)

    cats = data.get("categories") or []
    if isinstance(cats, list) and cats:
        e.add_field(name="Categories", value=_truncate(", ".join(map(str, cats[:10])), 512), inline=False)

    # Price
    price = data.get("price")
    price_str = None
    if isinstance(price, dict):
        if price.get("type") == "free":
            price_str = "Free"
        elif price.get("type") == "paid":
            final = price.get("final")
            initial = price.get("initial")
            disc = price.get("discount_percent")
            if final and initial and isinstance(disc, int) and disc > 0:
                price_str = f"{final} (was {initial}, {disc}% off)"
            elif final:
                price_str = str(final)

    if price_str:
        e.add_field(name="Price", value=_truncate(price_str, 256), inline=True)

    dlc_count = data.get("dlc_count")
    if isinstance(dlc_count, int) and dlc_count >= 0:
        e.add_field(name="DLC", value=str(dlc_count), inline=True)

    meta = data.get("metacritic_score")
    if isinstance(meta, int):
        e.add_field(name="Metacritic", value=str(meta), inline=True)

    reviews = data.get("reviews")
    if isinstance(reviews, dict):
        desc = (reviews.get("review_score_desc") or "").strip()
        total = reviews.get("total_reviews")
        pct = reviews.get("percent_positive")
        bits = []
        if desc:
            bits.append(desc)
        if pct is not None:
            bits.append(f"{pct}% positive")
        if isinstance(total, int):
            bits.append(f"{total:,} reviews")
        if bits:
            e.add_field(name="Reviews", value=_truncate(" — ".join(bits), 256), inline=False)

    min_req = _truncate((data.get("pc_minimum") or "").strip(), 900)
    rec_req = _truncate((data.get("pc_recommended") or "").strip(), 900)
    if min_req:
        e.add_field(name="PC Minimum", value=min_req, inline=False)
    if rec_req:
        e.add_field(name="PC Recommended", value=rec_req, inline=False)

    about = _truncate((data.get("about_the_game") or "").strip(), 900)
    if about:
        e.add_field(name="About", value=about, inline=False)

    langs = _truncate((data.get("supported_languages") or "").strip(), 500)
    if langs:
        e.add_field(name="Languages", value=langs, inline=False)

    return e


def _build_result_embeds(kind: str, payload: dict[str, Any]) -> list[Embed]:
    if kind == "WISHLIST":
        items = payload.get("items") or []
        if not isinstance(items, list) or not items:
            return [Embed(title="Wishlist", description="No games on this channel’s wishlist.")]

        embeds: list[Embed] = []
        for s in items[:10]:
            name = (s.get("name") or "Game").strip()
            url = (s.get("store_url") or "").strip()
            header = (s.get("header_image") or "").strip()
            disc = int(s.get("discount_percent") or 0)

            final = s.get("final")
            initial = s.get("initial")
            is_free = bool(s.get("is_free"))

            title = f"{name}"
            if disc > 0:
                title = f"{name} — {disc}% off"

            e = Embed(title=title, url=url)

            if header:
                e.set_thumbnail(url=header)

            if is_free:
                e.add_field(name="Price", value="Free", inline=False)
            elif final and initial and disc > 0:
                e.add_field(name="Price", value=f"{final} (was {initial})", inline=False)
            elif final:
                e.add_field(name="Price", value=str(final), inline=False)
            else:
                e.add_field(name="Price", value="(Price unavailable)", inline=False)

            embeds.append(e)

        return embeds
    
    if kind == "REMINDERS":
        items = payload.get("items") or []
        if not isinstance(items, list) or not items:
            return [Embed(title="Reminders", description="No upcoming reminders for this channel.")]

        embeds: list[Embed] = []
        for it in items[:10]:
            if not isinstance(it, dict):
                continue

            name = (it.get("name") or "Game").strip()
            url = (it.get("store_url") or "").strip()
            header = (it.get("header_image") or "").strip()
            release_text = (it.get("release_date_text") or "").strip() or "TBA"

            e = Embed(title=name, url=url if url else None)
            if header:
                e.set_thumbnail(url=header)
            e.add_field(name="Release", value=_truncate(release_text, 256), inline=False)

            embeds.append(e)

        return embeds or [Embed(title="Reminders", description="No upcoming reminders for this channel.")]


    # --- GAME DETAIL (single) ---
    if kind == "GAME_DETAIL":
        data = payload.get("data")
        if not isinstance(data, dict) or not data:
            return [Embed(title="No details", description="No details returned from Steam.")]
        return [_build_game_detail_embed(data)]

    # --- SEARCH LISTS ---
    query = (payload.get("query") or "").strip()
    results = payload.get("results") or []
    if not isinstance(results, list) or not results:
        return [Embed(title="No results", description=f"No results for: `{query}`")]

    embeds: list[Embed] = []

    for i, r in enumerate(results[:10], start=1):
        if not isinstance(r, dict):
            continue

        if kind == "GAME_SEARCH":
            app_id = _safe_int(r.get("id"))
            name = (r.get("name") or "").strip()
            if not app_id or not name:
                continue
            store_url = f"https://store.steampowered.com/app/{app_id}"
            e = Embed(title=f"{i}. {name}", url=store_url)
            e.set_thumbnail(url=_steam_header_img(app_id))
            embeds.append(e)

        elif kind == "MOVIE_SEARCH":
            title = (r.get("title") or "").strip()
            year = r.get("year") or "?"
            poster = (r.get("poster") or "").strip()
            if not title:
                continue
            e = Embed(title=f"{i}. {title} ({year})")
            if poster:
                e.set_thumbnail(url=poster)
            embeds.append(e)

        elif kind == "SHOW_SEARCH":
            title = (r.get("title") or "").strip()
            year = r.get("year") or "?"
            poster = (r.get("poster") or "").strip()
            if not title:
                continue
            e = Embed(title=f"{i}. {title} ({year})")
            if poster:
                e.set_thumbnail(url=poster)
            embeds.append(e)

    return embeds[:10] or [Embed(title="No results", description=f"No results for: `{query}`")]


class BotClient(Client):
    def __init__(self, *, intents: Intents) -> None:
        super().__init__(intents=intents)
        self.http_session: aiohttp.ClientSession | None = None
        self._request_cooldown: dict[tuple[int, int], datetime] = {}

    async def ensure_http_session(self) -> aiohttp.ClientSession:
        if self.http_session and not self.http_session.closed:
            return self.http_session

        timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
        connector = aiohttp.TCPConnector(limit=50, ttl_dns_cache=300, enable_cleanup_closed=True)
        self.http_session = aiohttp.ClientSession(timeout=timeout, connector=connector)
        log.info("[http] aiohttp ClientSession created")
        return self.http_session

    async def close(self) -> None:
        try:
            if self.http_session and not self.http_session.closed:
                await self.http_session.close()
                log.info("[http] aiohttp ClientSession closed")
        finally:
            await super().close()

    async def dm_admin_access_request(
        self,
        *,
        guild_id: int,
        channel_id: int,
        requester_id: int,
        command_text: str,
    ) -> bool:
        key = (guild_id, requester_id)
        now = utc_now()
        last = self._request_cooldown.get(key)
        if last and (now - last) < timedelta(minutes=5):
            return True

        self._request_cooldown[key] = now

        gids = owner_ids()
        if not gids:
            return False

        guild = self.get_guild(guild_id)
        guild_name = guild.name if guild else str(guild_id)
        ch_hint = f"<#{channel_id}>" if channel_id else f"(channel {channel_id})"

        msg = (
            "🔐 **Plex access requested**\n"
            f"- **Guild:** {guild_name}\n"
            f"- **User:** <@{requester_id}> (`{requester_id}`)\n"
            f"- **Channel:** {ch_hint}\n"
            f"- **Attempted:** `{command_text}`\n\n"
            f"To approve: `*approve <@{requester_id}>`\n"
            f"To revoke: `*revoke <@{requester_id}>`"
        )

        sent_any = False
        for admin_id in gids:
            try:
                user = await self.fetch_user(admin_id)
                await user.send(msg)
                sent_any = True
            except Exception:
                log.exception("Failed to DM admin_id=%s", admin_id)

        return sent_any


def create_client() -> BotClient:
    intents = Intents.default()
    intents.message_content = True
    return BotClient(intents=intents)


class _ReminderToggleButton(discord.ui.Button):
    def __init__(self, *, in_reminders: bool) -> None:
        label = "🗑 Remove reminder" if in_reminders else "🔔 Remind this channel"
        style = discord.ButtonStyle.danger if in_reminders else discord.ButtonStyle.success
        super().__init__(label=label, style=style)
        self.in_reminders = in_reminders

    async def callback(self, interaction: Interaction) -> None:
        view = self.view
        if not isinstance(view, GameDetailActionsView):
            await interaction.response.send_message("Internal error: view mismatch.", ephemeral=True)
            return
        await view.toggle_reminder(interaction)


class _WishlistToggleButton(discord.ui.Button):
    def __init__(self, *, in_wishlist: bool) -> None:
        label = "🗑 Remove from channel wishlist" if in_wishlist else "⭐ Add to channel wishlist"
        style = discord.ButtonStyle.danger if in_wishlist else discord.ButtonStyle.success
        super().__init__(label=label, style=style)
        self.in_wishlist = in_wishlist

    async def callback(self, interaction: Interaction) -> None:
        view = self.view
        if not isinstance(view, GameDetailActionsView):
            await interaction.response.send_message("Internal error: view mismatch.")
            return
        await view.toggle_wishlist(interaction)


class GameDetailActionsView(discord.ui.View):
    """
    Combined View for GAME_DETAIL:
      - optional reminder button
      - wishlist add/remove button
    """

    def __init__(
        self,
        client: BotClient,
        *,
        guild_id: int,
        channel_id: int,
        app_id: int,
        game_name: str,
        show_reminder: bool,
        in_wishlist: bool,
        in_reminders: bool,
    ) -> None:
        super().__init__(timeout=20 * 60)
        self.client = client
        self.guild_id = int(guild_id)
        self.channel_id = int(channel_id)
        self.app_id = int(app_id)
        self.game_name = (game_name or "").strip() or "Game"

        self._show_reminder = bool(show_reminder)
        self._in_wishlist = bool(in_wishlist)
        self._in_reminders = bool(in_reminders)

        # Add wishlist toggle button
        self.add_item(_WishlistToggleButton(in_wishlist=self._in_wishlist))

        # Add reminder toggle button only if you already decided it should show
        if self._show_reminder:
            self.add_item(_ReminderToggleButton(in_reminders=self._in_reminders))

    async def toggle_reminder(self, interaction: Interaction) -> None:
        await interaction.response.defer()

        if not interaction.guild_id or not interaction.channel:
            await interaction.channel.send("⚠️ Reminders only work in a server channel.")
            return

        try:
            if self._in_reminders:
                # REMOVE
                def _db_remove() -> bool:
                    conn = connect_guild_db(self.guild_id)
                    try:
                        return remove_reminder(conn, app_id=self.app_id, remind_channel_id=self.channel_id)
                    finally:
                        conn.close()

                removed = await asyncio.to_thread(_db_remove)
                self._in_reminders = False

                # Rebuild view to flip button state
                new_view = GameDetailActionsView(
                    self.client,
                    guild_id=self.guild_id,
                    channel_id=self.channel_id,
                    app_id=self.app_id,
                    game_name=self.game_name,
                    show_reminder=self._show_reminder,
                    in_wishlist=self._in_wishlist,
                    in_reminders=self._in_reminders,
                )
                await interaction.message.edit(view=new_view)

                if removed:
                    await interaction.channel.send(f"🗑 Removed reminder: **{self.game_name}**")
                else:
                    await interaction.channel.send(f"ℹ️ No reminder existed for **{self.game_name}**")
                return

            # ADD
            http = await self.client.ensure_http_session()
            msg = await add_reminder_for_appid(
                http,
                guild_id=self.guild_id,
                author_id=int(interaction.user.id),
                channel_id=self.channel_id,
                app_id=self.app_id,
            )
            self._in_reminders = True

            new_view = GameDetailActionsView(
                self.client,
                guild_id=self.guild_id,
                channel_id=self.channel_id,
                app_id=self.app_id,
                game_name=self.game_name,
                show_reminder=self._show_reminder,
                in_wishlist=self._in_wishlist,
                in_reminders=self._in_reminders,
            )
            await interaction.message.edit(view=new_view)
            await interaction.channel.send(msg)

        except Exception:
            log.exception(
                "Reminder toggle failed app_id=%s guild=%s channel=%s",
                self.app_id, self.guild_id, self.channel_id
            )
            await interaction.channel.send("⚠️ Reminder update failed. Check logs.")

    async def toggle_wishlist(self, interaction: Interaction) -> None:
        await interaction.response.defer()

        if not interaction.guild_id or not interaction.channel:
            await interaction.channel.send("⚠️ Wishlist only works in a server channel.")
            return

        def _db_toggle() -> bool:
            conn = connect_guild_db(self.guild_id)
            try:
                if is_in_wishlist(conn, channel_id=self.channel_id, app_id=self.app_id):
                    remove_from_wishlist(conn, channel_id=self.channel_id, app_id=self.app_id)
                    return False
                else:
                    add_to_wishlist_if_missing(
                        conn,
                        channel_id=self.channel_id,
                        app_id=self.app_id,
                        name=self.game_name,
                        added_by_discord_id=str(interaction.user.id),
                    )
                    return True
            finally:
                conn.close()

        try:
            now_in = await asyncio.to_thread(_db_toggle)
            self._in_wishlist = now_in

            # Rebuild the view (swap button label/style)
            new_view = GameDetailActionsView(
                self.client,
                guild_id=self.guild_id,
                channel_id=self.channel_id,
                app_id=self.app_id,
                game_name=self.game_name,
                show_reminder=self._show_reminder,
                in_wishlist=self._in_wishlist,
                in_reminders=self._in_reminders,
            )

            await interaction.message.edit(view=new_view)

            if now_in:
                await interaction.channel.send(f"⭐ Added **{self.game_name}** to this channel’s wishlist.")
            else:
                await interaction.channel.send(f"🗑 Removed **{self.game_name}** from this channel’s wishlist.")

        except Exception:
            log.exception("Wishlist toggle failed app_id=%s guild=%s channel=%s", self.app_id, self.guild_id, self.channel_id)
            await interaction.channel.send("⚠️ Wishlist update failed. Check logs.")


class ResultButtonsView(discord.ui.View):
    def __init__(self, client: BotClient, kind: str, payload: dict[str, Any]) -> None:
        super().__init__(timeout=20 * 60)
        self.client = client
        self.kind = kind
        self.payload = payload

        self._author_id = _safe_int(payload.get("author_id"))
        self._results: list[dict[str, Any]] = [
            r for r in (payload.get("results") or [])[:10] if isinstance(r, dict)
        ]

        for i in range(len(self._results)):
            self.add_item(_ResultButton(index=i, label=f"{i+1}"))

    async def interaction_check(self, interaction: Interaction) -> bool:
        if self._author_id and interaction.user.id != self._author_id:
            await interaction.response.send_message("This menu isn’t for you. Run your own search.")
            return False
        return True

    async def run_selection(self, interaction: Interaction, index: int) -> None:
        if index < 0 or index >= len(self._results):
            await interaction.response.send_message("Invalid selection.")
            return

        r = self._results[index]

        cmd: str | None = None
        pretty: str | None = None

        if self.kind == "GAME_SEARCH":
            app_id = _safe_int(r.get("id"))
            name = (r.get("name") or "").strip()
            if app_id:
                cmd = f"*searchgame {app_id}"
                pretty = name or None

        elif self.kind == "MOVIE_SEARCH":
            tmdb = _safe_int(r.get("id") or r.get("tmdb"))
            title = (r.get("title") or "").strip()
            year = r.get("year") or "?"
            if tmdb:
                cmd = f"*plexmovie {tmdb}"
                pretty = f"{title} ({year})" if title else None

        elif self.kind == "SHOW_SEARCH":
            tvdb = _safe_int(r.get("id") or r.get("tvdb"))
            title = (r.get("title") or "").strip()
            year = r.get("year") or "?"
            if tvdb:
                cmd = f"*plexshow {tvdb}"
                pretty = f"{title} ({year})" if title else None

        if not cmd:
            await interaction.response.send_message("Invalid selection data.")
            return

        http = await self.client.ensure_http_session()
        ctx = CommandContext(
            guild_id=interaction.guild_id or 0,
            channel_id=interaction.channel_id or 0,
            author_id=interaction.user.id,
            content=cmd,
            http=http,
        )

        await interaction.response.defer()

        out = await dispatch_command(ctx)
        if not out:
            return

        ui = _parse_ui(out)
        if ui:
            kind, payload = ui
            embeds = _build_result_embeds(kind, payload)

            if kind in ("GAME_SEARCH", "MOVIE_SEARCH", "SHOW_SEARCH"):
                view = ResultButtonsView(self.client, kind, payload)
                await interaction.channel.send(embeds=embeds, view=view)
                return

            if kind == "GAME_DETAIL":
                data = payload.get("data") or {}
                app_id = _safe_int(data.get("app_id"))
                name = (data.get("name") or "").strip() or "Game"
                if not app_id:
                    await interaction.followup.send("⚠️ Invalid game details payload.")
                    return

                show_reminder = _should_show_reminder_button(data, guild_id=interaction.guild_id)

                def _db_check() -> tuple[bool, bool]:
                    conn = connect_guild_db(interaction.guild_id or 0)
                    try:
                        in_wl = is_in_wishlist(conn, channel_id=interaction.channel_id or 0, app_id=app_id)
                        in_rem = reminder_exists(conn, app_id=app_id, remind_channel_id=interaction.channel_id or 0)
                        return in_wl, in_rem
                    finally:
                        conn.close()

                in_wl, in_rem = await asyncio.to_thread(_db_check)

                view = GameDetailActionsView(
                    self.client,
                    guild_id=interaction.guild_id or 0,
                    channel_id=interaction.channel_id or 0,
                    app_id=app_id,
                    game_name=name,
                    show_reminder=show_reminder,
                    in_wishlist=in_wl,
                    in_reminders=in_rem,
                )
                await interaction.channel.send(embeds=embeds, view=view)
                return

        # Access request flow
        if out.startswith("__ACCESS_REQUEST__:"):
            try:
                _pfx, gid_s, chid_s, uid_s, cmd_text = out.split(":", 4)
                gid = int(gid_s)
                chid = int(chid_s)
                uid = int(uid_s)
            except Exception:
                gid = interaction.guild_id or 0
                chid = interaction.channel_id or 0
                uid = interaction.user.id
                cmd_text = cmd

            sent = await self.client.dm_admin_access_request(
                guild_id=gid,
                channel_id=chid,
                requester_id=uid,
                command_text=cmd_text,
            )
            if sent:
                await interaction.channel.send("🔐 Access request sent to the admin.")
            else:
                await interaction.channel.send("🔐 Access denied. Admin could not be notified.")
            return

        # Simplified success messages for ARR adds
        if cmd.startswith("*plexmovie "):
            if out.startswith("Added."):
                await interaction.channel.send(f"✅ {pretty or 'Movie'} added.")
                return
            if out.startswith("Already added"):
                await interaction.channel.send(f"ℹ️ {pretty or 'Movie'} already added (on Plex or in the download queue).")
                return
            if out.startswith("Failed."):
                await interaction.channel.send(f"❌ Failed to add {pretty or 'movie'}. ({out})")
                return

        if cmd.startswith("*plexshow "):
            if out.startswith("Added."):
                await interaction.channel.send(f"✅ {pretty or 'Show'} added.")
                return
            if out.startswith("Already added"):
                await interaction.channel.send(f"ℹ️ {pretty or 'Show'} already added (on Plex or in the download queue).")
                return
            if out.startswith("Failed."):
                await interaction.channel.send(f"❌ Failed to add {pretty or 'show'}. ({out})")
                return

        await interaction.channel.send(out)


class _ResultButton(discord.ui.Button):
    def __init__(self, *, index: int, label: str) -> None:
        super().__init__(style=discord.ButtonStyle.primary, label=label)
        self._index = index

    async def callback(self, interaction: Interaction) -> None:
        view = self.view
        if not isinstance(view, ResultButtonsView):
            await interaction.response.send_message("Internal error: view mismatch.")
            return
        await view.run_selection(interaction, self._index)


async def _should_process_message(client: BotClient, message: discord.Message, content: str) -> bool:
    """
    Centralizes channel gating so on_message stays small.

    Rules:
    - Ignore non-commands (anything not starting with '*')
    - If allowed_channel_id is NOT configured:
        - allow only _is_preconfig_allowed_command()
        - if a command was attempted but not allowed, show setup hint
    - If allowed_channel_id IS configured:
        - allow commands in the allowed channel
        - allow admin-anywhere commands ONLY for bot owners
        - ignore commands in other channels for everyone else
    """
    content = (content or "")

    # only react to commands
    if not content.strip().startswith("*"):
        return False

    guild_id = int(message.guild.id)
    allowed = _get_allowed_channel_id(guild_id)

    # Not configured yet
    if allowed is None:
        if _is_preconfig_allowed_command(content):
            return True

        # If they tried a command, guide them (but don't spam on normal chat)
        await message.channel.send(
            "⚙️ This server hasn’t configured the bot yet.\n"
            "An admin should run: `*setchannel #channel`\n"
            "Optional but recommended: `*settimezone America/Denver`"
        )
        return False

    # Configured: allowed channel gets everything
    if int(message.channel.id) == int(allowed):
        return True

    # Other channels: only owner can run admin-anywhere commands
    if _is_admin_anywhere_command(content) and int(message.author.id) in owner_ids():
        return True

    # otherwise, silently ignore
    return False


async def _handle_dispatch_output(
    client: BotClient,
    message: discord.Message,
    *,
    content: str,
    resp: str,
) -> None:
    """
    Contains all the "what do we do with dispatch_command() output" logic.
    This is basically your current try-block content after resp is returned.
    """

    # --- UI payloads ---
    ui = _parse_ui(resp)
    if ui:
        kind, payload = ui
        embeds = _build_result_embeds(kind, payload)

        if kind == "GAME_SEARCH":
            results = payload.get("results") or []
            has_results = isinstance(results, list) and len(results) > 0

            if has_results:
                await message.channel.send(
                    "**CLICK A TITLE TO OPEN STEAM. USE THE NUMBERED BUTTONS BELOW TO VIEW DETAILS IN DISCORD.**"
                )
                view = ResultButtonsView(client, kind, payload)
                await message.channel.send(embeds=embeds, view=view)
            else:
                await message.channel.send(embeds=embeds)
            return

        if kind == "WISHLIST":
            await message.channel.send(embeds=embeds)
            return
        
        if kind == "REMINDERS":
            await message.channel.send(embeds=embeds)
            return


        if kind in ("MOVIE_SEARCH", "SHOW_SEARCH"):
            view = ResultButtonsView(client, kind, payload)
            await message.channel.send(embeds=embeds, view=view)
            return

        if kind == "GAME_DETAIL":
            data = payload.get("data") or {}
            app_id = _safe_int(data.get("app_id"))
            name = (data.get("name") or "").strip() or "Game"
            if not app_id:
                await message.channel.send("⚠️ Invalid game details payload.")
                return

            show_reminder = _should_show_reminder_button(data, guild_id=message.guild.id)

            def _db_check() -> tuple[bool, bool]:
                conn = connect_guild_db(message.guild.id)
                try:
                    in_wl = is_in_wishlist(conn, channel_id=message.channel.id, app_id=app_id)
                    in_rem = reminder_exists(conn, app_id=app_id, remind_channel_id=message.channel.id)
                    return in_wl, in_rem
                finally:
                    conn.close()

            in_wl, in_rem = await asyncio.to_thread(_db_check)

            view = GameDetailActionsView(
                client,
                guild_id=message.guild.id,
                channel_id=message.channel.id,
                app_id=app_id,
                game_name=name,
                show_reminder=show_reminder,
                in_wishlist=in_wl,
                in_reminders=in_rem,
            )
            await message.channel.send(embeds=embeds, view=view)
            return

    # --- Access request flow ---
    if resp.startswith("__ACCESS_REQUEST__:"):
        try:
            _pfx, gid_s, chid_s, uid_s, cmd_text = resp.split(":", 4)
            gid = int(gid_s)
            chid = int(chid_s)
            uid = int(uid_s)
        except Exception:
            gid = message.guild.id
            chid = message.channel.id
            uid = message.author.id
            cmd_text = content

        sent = await client.dm_admin_access_request(
            guild_id=gid,
            channel_id=chid,
            requester_id=uid,
            command_text=cmd_text,
        )
        if sent:
            await message.channel.send("🔐 Access denied. Request sent to the admin.")
        else:
            await message.channel.send("🔐 Access denied.")
        return

    # --- Admin approve/revoke/list ---
    if resp.startswith("__ADMIN_APPROVE__:"):
        _p, guild_id_s, target_id_s, admin_id_s = resp.split(":", 3)
        guild_id = int(guild_id_s)
        target_id = int(target_id_s)
        admin_id = int(admin_id_s)

        conn = connect_guild_db(guild_id)
        try:
            approve_user(conn, discord_id=str(target_id), approved_by_discord_id=str(admin_id), note=None)
            touch_plex_use(conn, str(target_id))
        finally:
            conn.close()

        await message.channel.send(f"✅ Approved <@{target_id}>")
        return

    if resp.startswith("__ADMIN_REVOKE__:"):
        _p, guild_id_s, target_id_s, admin_id_s = resp.split(":", 3)
        guild_id = int(guild_id_s)
        target_id = int(target_id_s)
        admin_id = int(admin_id_s)

        if target_id in owner_ids():
            await message.channel.send("❌ You cannot revoke the bot owner.")
            return

        conn = connect_guild_db(guild_id)
        try:
            revoke_user(
                conn,
                discord_id=str(target_id),
                revoked_by_discord_id=str(admin_id),
                note="Revoked by admin",
            )
        finally:
            conn.close()

        await message.channel.send(f"🛑 Revoked <@{target_id}>")
        return

    if resp.startswith("__ADMIN_PLEXACCESS__:"):
        _p, guild_id_s = resp.split(":", 1)
        guild_id = int(guild_id_s)

        conn = connect_guild_db(guild_id)
        try:
            rows = list_approved(conn)
        finally:
            conn.close()

        if not rows:
            await message.channel.send("No approved users.")
            return

        now = utc_now()
        window = timedelta(days=14)

        lines = ["Approved users (Plex add access):"]
        for discord_id, approved_at_utc, last_use_utc, note in rows:
            last_iso = (last_use_utc or approved_at_utc)
            try:
                last_dt = parse_iso(last_iso)
            except Exception:
                last_dt = parse_iso(approved_at_utc)

            remaining = window - (now - last_dt)
            if remaining.total_seconds() <= 0:
                remaining_str = "expired (auto-revokes on next protected command)"
            else:
                days = int(remaining.total_seconds() // 86400)
                hours = int((remaining.total_seconds() % 86400) // 3600)
                remaining_str = f"{days}d {hours}h left"

            note_str = f" — {note}" if note else ""
            lines.append(f"- <@{discord_id}> — {remaining_str}{note_str}")

        await message.channel.send("\n".join(lines))
        return
    
    # Simplified success messages for ARR adds (message-based commands)
    if content.startswith("*plexmovie "):
        if resp.startswith("Added."):
            await message.channel.send("✅ Movie added.")
            return
        if resp.startswith("Already added"):
            await message.channel.send("ℹ️ Movie already added (on Plex or in the download queue).")
            return
        if resp.startswith("Failed."):
            await message.channel.send(f"❌ Failed to add movie. ({resp})")
            return

    if content.startswith("*plexshow "):
        if resp.startswith("Added."):
            await message.channel.send("✅ Show added.")
            return
        if resp.startswith("Already added"):
            await message.channel.send("ℹ️ Show already added (on Plex or in the download queue).")
            return
        if resp.startswith("Failed."):
            await message.channel.send(f"❌ Failed to add show. ({resp})")
            return


    # default: plain text response
    await message.channel.send(resp)



def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    load_env()
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise SystemExit("DISCORD_TOKEN not found in environment variables (.env).")

    client = create_client()

    @client.event
    async def on_guild_join(guild: discord.Guild) -> None:
        # Create DB immediately
        try:
            conn = connect_guild_db(guild.id)
            conn.close()
            log.info("Initialized guild db for guild_id=%s", guild.id)
        except Exception:
            log.exception("Failed to init db for new guild=%s", guild.id)

        # Optional: try to message system channel (won't always work)
        try:
            ch = guild.system_channel
            if ch:
                await ch.send(
                    "👋 Thanks for adding me!\n"
                    "1) Set my channel: `*setchannel #channel`\n"
                    "2) Set timezone: `*settimezone America/Denver`"
                )
        except Exception:
            # ignore: permissions vary wildly
            pass


    @client.event
    async def on_ready() -> None:
        await client.ensure_http_session()
        log.info("Bot connected as %s", client.user)

        # Start scheduler (it will only run for guilds with timezone configured)
        scheduler.start(client)

        # Startup message to each guild's allowed channel, if configured
        for g in client.guilds:
            try:
                allowed = _get_allowed_channel_id(g.id)
                if not allowed:
                    continue
                ch = client.get_channel(int(allowed)) or await client.fetch_channel(int(allowed))
                await ch.send("I am back online.")
            except Exception:
                log.exception("Startup message failed for guild=%s", g.id)

    @client.event
    async def on_message(message) -> None:
        if message.author == client.user:
            return
        if message.guild is None:
            return

        content = message.content or ""

        # Centralized channel gating
        if not await _should_process_message(client, message, content):
            return

        try:
            http = await client.ensure_http_session()
            ctx = CommandContext(
                guild_id=message.guild.id,
                channel_id=message.channel.id,
                author_id=message.author.id,
                content=content,
                http=http,
            )

            resp = await dispatch_command(ctx)
            if not resp:
                return

            await _handle_dispatch_output(client, message, content=content, resp=resp)

        except Exception:
            log.exception("Command execution failed")
            await message.channel.send("⚠️ Command failed. Check logs for details.")


    client.run(token)
