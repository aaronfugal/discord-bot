# ingrid_patel/commands/help.py
from __future__ import annotations


HELP_TEXT = (
    "## 🤖 Ingrid Patel (6.0.1) Help\n"
    "\n"
    "### 🔎 Search\n"
    "- `*searchgame <game name>` — Search Steam games. Results show clickable store links + buttons to view details.\n"
    "- `*searchmovie <movie name>` — Search movies. **Approved users** can add movies to Plex by clicking the button that corresponds with the movie entry in search results.\n"
    "- `*searchshow <show name>` — Search shows. **Approved users** can add shows to Plex by clicking the button that corresponds with the movie entry in search results.\n"
    "\n"
    "### ⏰ Reminders & Channel Wishlist \n"
    "Use this to have the channel notified when a game is about to release or to be notified of sales. Notifications are sent around 6 PM in this server's configured timezone. \n"
    "- To schedule upcoming games for reminders, search a game → open its details → click:\n"
    "  - `🔔 Remind this channel`\n"
    "  - `🗑 Remove reminder`\n"
    "  - `*reminders` — List all scheduled reminders (soonest → latest).\n"
    "- To add a game to the wishlist to notify the channel of sales, search a game → open its details → click:\n"
    "  - `⭐ Add to channel wishlist`\n"
    "  - `🗑 Remove from channel wishlist`\n"
    "  - `*wishlist` — List all games on this channel’s wishlist.\n"
    "\n"
)

ADMIN_TEXT = (
    "\n"
    "## 🛠 Admin (Bot Owner Only)\n"
    "- `*approve @user` — Grant Plex add access.\n"
    "- `*revoke @user` — Remove Plex add access.\n"
    "- `*plexaccess` — Show who currently has Plex add access.\n"
    "- `*setchannel <channel ID>` — Set the channel where the bot listens and posts. \n"
    "- `*settimezone <IANA timezone>` — Set this servers timezone (example: `America/Denver`). \n" 
)

def handle_help(*, is_admin: bool) -> str:
    return HELP_TEXT + (ADMIN_TEXT if is_admin else "")
