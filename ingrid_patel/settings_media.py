# ingrid_patel/settings_media.py
from __future__ import annotations

import os

DEFAULT_RADARR_ROOT = r"\\cobalt\media\Movies"
DEFAULT_SONARR_ROOT = r"\\cobalt\media\Shows"


def get_radarr_config() -> tuple[str, str, str] | None:
    base = (os.getenv("RADARR_BASE_URL") or "").strip()
    key = (os.getenv("RADARR_API_KEY") or "").strip()
    root = (os.getenv("RADARR_ROOT_FOLDER") or DEFAULT_RADARR_ROOT).strip()
    if not base or not key:
        return None
    return base, key, root


def get_sonarr_config() -> tuple[str, str, str] | None:
    base = (os.getenv("SONARR_BASE_URL") or "").strip()
    key = (os.getenv("SONARR_API_KEY") or "").strip()
    root = (os.getenv("SONARR_ROOT_FOLDER") or DEFAULT_SONARR_ROOT).strip()
    if not base or not key:
        return None
    return base, key, root

