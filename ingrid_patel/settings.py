# ingrid_patel/settings.py 

from __future__ import annotations
from pathlib import Path

import os

BOT_OWNER_ID = {
    555261159452966928,  # Aaron's ID
    # List more here if needed
}

# Local testing override (single guild + single channel)
# Toggle this before starting the bot.
TESTING_MODE = False
TEST_GUILD_ID = 1154925436703342604
TEST_CHANNEL_ID = 1268026496027459715
TEST_TIMEZONE = "America/Denver"

# If True, testing mode reads/writes from a separate DB directory to keep prod data untouched.
TESTING_USE_SEPARATE_DB = True

REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DATA_DIR = REPO_ROOT / "data" / "guilds"
_DEFAULT_TEST_DATA_DIR = REPO_ROOT / "data" / "guilds_testing"

if TESTING_MODE and TESTING_USE_SEPARATE_DB:
    DATA_DIR = Path(os.getenv("INGRID_TEST_DATA_DIR", str(_DEFAULT_TEST_DATA_DIR)))
else:
    DATA_DIR = Path(os.getenv("INGRID_DATA_DIR", str(_DEFAULT_DATA_DIR)))


TIMEZONE = os.getenv("TIMEZONE", "America/Denver")  # fallback ONLY
# --- Bot behavior ---
APPROVAL_TIMEOUT_MINUTES = 20
INACTIVITY_DAYS = 14

# Used when the system auto-revokes inactive users
SYSTEM_ACTOR_ID = "system"

# HTTP client defaults (aiohttp)
HTTP_TIMEOUT_SECONDS = 30

# Temporary lifetime for search-heavy bot messages (0 disables auto-delete)
SEARCH_RESULTS_TTL_SECONDS = 120

# If True, only the search author can click numbered result buttons.
RESTRICT_SEARCH_BUTTONS_TO_AUTHOR = False

# Generic user-facing failure message
USER_ERROR_MESSAGE = "An error occured and the bot admin was notified. There should be a fix shortly."


def is_owner(user_id: int) -> bool:
    return user_id in BOT_OWNER_ID


def owner_ids() -> set[int]:
    # convenience if you ever expand to multiple owners
    return set(BOT_OWNER_ID)
