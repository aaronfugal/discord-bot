# ingrid_patel/commands/wishlist.py

from __future__ import annotations

import json
import asyncio

from ingrid_patel.clients.steam_client import SteamClient
from ingrid_patel.db.connect import connect_guild_db
from ingrid_patel.db.repos.wishlist_repo import list_wishlist


async def handle_wishlist(ctx) -> str:
    """
    Lists this channel's wishlist with cover art + current price (from Steam store API).
    Returns __UI__ payload for app.py to render embeds.
    """
    if not ctx.guild_id or not ctx.channel_id:
        return "⚠️ This command only works in a server channel."

    # Load wishlist rows for THIS channel
    def _db_read() -> list[tuple[int, int, str]]:
        conn = connect_guild_db(int(ctx.guild_id))
        try:
            rows = list_wishlist(conn)  # (channel_id, app_id, name)
        finally:
            conn.close()
        return [r for r in rows if int(r[0]) == int(ctx.channel_id)]

    rows = await asyncio.to_thread(_db_read)

    if not rows:
        payload = {"channel_id": int(ctx.channel_id), "items": []}
        return "__UI__:WISHLIST:" + json.dumps(payload)

    steam = SteamClient.from_env(session=ctx.http)

    items = []
    for (_channel_id, app_id, name) in rows:
        try:
            snap = await steam.get_price_snapshot(int(app_id))
        except Exception:
            snap = None

        # Fallback if Steam doesn't return pricing for some reason
        if not snap:
            snap = {
                "app_id": int(app_id),
                "name": str(name),
                "store_url": f"https://store.steampowered.com/app/{int(app_id)}",
                "header_image": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{int(app_id)}/header.jpg",
                "discount_percent": 0,
                "final": None,
                "initial": None,
                "is_free": False,
            }

        items.append(snap)

    # Sort: biggest discount first, then name
    items.sort(key=lambda x: (-(int(x.get("discount_percent") or 0)), (x.get("name") or "").lower()))

    payload = {"channel_id": int(ctx.channel_id), "items": items}
    return "__UI__:WISHLIST:" + json.dumps(payload)
