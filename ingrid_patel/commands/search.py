# ingrid_patel/commands/search.py

from __future__ import annotations

import json
import re
from typing import Any

from ingrid_patel.clients.steam_client import SteamClient



def _usage() -> str:
    return (
        "Usage:\n"
        "- `*searchgame <game name>`\n"
        "- `*searchgame <appid>`\n\n"
        "Examples:\n"
        "- `*searchgame portal`\n"
        "- `*searchgame 620`"
    )


def _ui(kind: str, payload: dict[str, Any]) -> str:
    # Must match app.py _parse_ui: "__UI__:<KIND>:<JSON>"
    return "__UI__:" + kind + ":" + json.dumps(payload, ensure_ascii=False)


async def handle_searchgame(http, author_id: int, content: str) -> str:
    """
    Accepts either:
      - "*searchgame <query/appid>" (normal)
      - "<query/appid>"            (some button/router paths)
    """
    text = (content or "").strip()

    # Robust arg parsing:
    # If we got the full command, strip the prefix.
    # If we got just the argument (e.g., "620"), use it directly.
    lower = text.lower()
    if lower.startswith("*searchgame"):
        parts = text.split(maxsplit=1)
        arg = parts[1].strip() if len(parts) > 1 else ""
    else:
        arg = text

    if not arg:
        return _usage()

    client = SteamClient.from_env(session=http)

    # If numeric -> details view
    if re.fullmatch(r"\d+", arg):
        app_id = int(arg)

        details = await client.get_app_details_rich(app_id)

        # Fallback to minimal dataclass if rich fails
        if not isinstance(details, dict) or not details:
            minimal = await client.get_app_details(app_id)
            if not minimal:
                return f"No Steam game found for App ID {app_id}."
            details = {
                "app_id": minimal.app_id,
                "name": minimal.name,
                "store_url": minimal.store_url,
                "header_image": f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg",
                "release_date_text": minimal.release_date_text,
                "coming_soon": minimal.coming_soon,
            }

        return _ui("GAME_DETAIL", {"author_id": int(author_id), "data": details})

    # Otherwise -> search list view
    query = arg
    results = await client.search_apps_top10(query)
    rows = [{"id": r.app_id, "name": r.name} for r in results]

    return _ui("GAME_SEARCH", {"author_id": int(author_id), "query": query, "results": rows})
