# ingrid_patel/settings.py 

from __future__ import annotations
from pathlib import Path # import Path for handling filesystem paths which is nicer than writing raw strings like "C:/some/folder"

import os

REPO_ROOT = Path(__file__).resolve().parent.parent # file is this file, and absoltue path is made and goes up two directories to set the root file path
DATA_DIR = Path(os.getenv("INGRID_DATA_DIR", str(REPO_ROOT / "data" / "guilds")))

BOT_OWNER_ID = { # set admin ID's
    555261159452966928, # Aaron's ID
    # List more here if needed
}


TIMEZONE = os.getenv("TIMEZONE", "America/Denver")  # fallback ONLY


# --- Bot behavior ---
APPROVAL_TIMEOUT_MINUTES = 20
INACTIVITY_DAYS = 14

# Used when the system auto-revokes inactive users
SYSTEM_ACTOR_ID = "system"

# HTTP client defaults (aiohttp)
HTTP_TIMEOUT_SECONDS = 30



def is_owner(user_id: int) -> bool:
    return user_id in BOT_OWNER_ID


def owner_ids() -> set[int]:
    # convenience if you ever expand to multiple owners
    return set(BOT_OWNER_ID)
