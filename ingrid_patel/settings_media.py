# ingrid_patel/settings_media.py
from __future__ import annotations

import os

DEFAULT_RADARR_ROOT = r"\\cobalt\media\Movies"
DEFAULT_SONARR_ROOT = r"\\cobalt\media\Shows"


def _normalize_root_folder(raw: str | None, default: str) -> str:
    """
    Normalize root folder values from env vars so UNC paths are stable.
    Handles over-escaped leading backslashes and mixed slash styles.
    """
    s = (raw or default or "").strip().strip('"').strip("'")
    if not s:
        s = default

    looks_windowsish = ("\\" in s) or (len(s) >= 2 and s[1] == ":") or s.startswith("\\")
    if not looks_windowsish:
        return s

    s = s.replace("/", "\\")

    # Keep at most a standard UNC prefix (\\server\share...)
    if s.startswith("\\"):
        lead = len(s) - len(s.lstrip("\\"))
        if lead >= 2:
            rest = s.lstrip("\\")
            while "\\\\" in rest:
                rest = rest.replace("\\\\", "\\")
            return "\\\\" + rest
        if lead == 1 and ":" not in s:
            return "\\" + s

    while "\\\\" in s:
        s = s.replace("\\\\", "\\")
    return s


def get_radarr_config() -> tuple[str, str, str] | None:
    base = (os.getenv("RADARR_BASE_URL") or "").strip()
    key = (os.getenv("RADARR_API_KEY") or "").strip()
    root = _normalize_root_folder(os.getenv("RADARR_ROOT_FOLDER"), DEFAULT_RADARR_ROOT)
    if not base or not key:
        return None
    return base, key, root


def get_sonarr_config() -> tuple[str, str, str] | None:
    base = (os.getenv("SONARR_BASE_URL") or "").strip()
    key = (os.getenv("SONARR_API_KEY") or "").strip()
    root = _normalize_root_folder(os.getenv("SONARR_ROOT_FOLDER"), DEFAULT_SONARR_ROOT)
    if not base or not key:
        return None
    return base, key, root


def get_plex_config() -> tuple[str, str] | None:
    base = (os.getenv("PLEX_BASE_URL") or "").strip()
    token = (os.getenv("PLEX_TOKEN") or "").strip()
    if not base or not token:
        return None
    return base, token

