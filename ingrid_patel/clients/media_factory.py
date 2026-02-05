# ingrid_patel/clients/media_factory.py
from __future__ import annotations

import aiohttp

from ingrid_patel import settings_media as sm
from ingrid_patel.clients.radarr_client import RadarrClient
from ingrid_patel.clients.sonarr_client import SonarrClient


def radarr(session: aiohttp.ClientSession) -> tuple[RadarrClient, str] | None:
    cfg = sm.get_radarr_config()
    if not cfg:
        return None
    base, key, root = cfg
    return RadarrClient(base, key, session=session), root


def sonarr(session: aiohttp.ClientSession) -> tuple[SonarrClient, str] | None:
    cfg = sm.get_sonarr_config()
    if not cfg:
        return None
    base, key, root = cfg
    return SonarrClient(base, key, session=session), root
