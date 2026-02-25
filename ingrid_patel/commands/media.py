# ingrid_patel/commands/media.py

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp

from ingrid_patel.clients.media_factory import plex, radarr, sonarr

log = logging.getLogger(__name__)

MEDIA_ADDED_TO_QUEUE = "Added to download queue. It should be available in the next few weeks."
MEDIA_ALREADY_ON_PLEX = "Already on Plex."
MEDIA_ALREADY_IN_QUEUE = "Already in download queue. It should be available in the next few weeks."


def _join_args(content: str) -> str:
    parts = (content or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


def _ui(kind: str, payload: dict[str, Any]) -> str:
    return "__UI__:" + kind + ":" + json.dumps(payload, ensure_ascii=False)


def _safe_int(v: Any) -> int | None:
    try:
        return int(v)
    except Exception:
        return None


def _pick_poster(images) -> str | None:
    if not images or not isinstance(images, list):
        return None
    posters = [im for im in images if isinstance(im, dict) and (im.get("coverType") == "poster")]
    for im in posters + [im for im in images if isinstance(im, dict)]:
        url = (im.get("remoteUrl") or im.get("url") or "").strip()
        if url.startswith("http://") or url.startswith("https://"):
            return url
    return None


async def _movie_exists_in_plex(http: aiohttp.ClientSession, *, title: str, year: int | None) -> bool:
    client = plex(http)
    if not client or not title:
        return False
    try:
        return await client.has_movie(title=title, year=year)
    except Exception:
        log.exception("Plex movie lookup failed title=%s year=%s", title, year)
        return False


async def _show_exists_in_plex(http: aiohttp.ClientSession, *, title: str, year: int | None) -> bool:
    client = plex(http)
    if not client or not title:
        return False
    try:
        return await client.has_show(title=title, year=year)
    except Exception:
        log.exception("Plex show lookup failed title=%s year=%s", title, year)
        return False


async def handle_searchmovie(http: aiohttp.ClientSession, author_id: int, content: str) -> str:
    query = _join_args(content)
    if not query:
        return "Usage: *searchmovie <movie name>"

    cfg = radarr(http)
    if not cfg:
        return "Radarr is not configured."

    client, _root = cfg

    # Radarr lookup returns list[dict]
    results = await client.lookup_movie(query)
    if not isinstance(results, list) or not results:
        return _ui("MOVIE_SEARCH", {"author_id": int(author_id), "query": query, "results": []})

    rows: list[dict[str, Any]] = []
    for r in results[:10]:
        if not isinstance(r, dict):
            continue
        tmdb = r.get("tmdbId")
        title = (r.get("title") or "").strip()
        year = r.get("year")
        poster = _pick_poster(r.get("images"))
        if isinstance(tmdb, int) and tmdb > 0 and title:
            rows.append(
                {
                    "id": tmdb,               
                    "title": title,
                    "year": year if isinstance(year, int) else "",
                    "poster": poster or "",
                }
            )

    return _ui("MOVIE_SEARCH", {"author_id": int(author_id), "query": query, "results": rows})


async def handle_searchshow(http: aiohttp.ClientSession, author_id: int, content: str) -> str:
    query = _join_args(content)
    if not query:
        return "Usage: *searchshow <show name>"

    cfg = sonarr(http)
    if not cfg:
        return "Sonarr is not configured."

    client, _root = cfg

    results = await client.lookup_series(query)
    if not isinstance(results, list) or not results:
        return _ui("SHOW_SEARCH", {"author_id": int(author_id), "query": query, "results": []})

    rows: list[dict[str, Any]] = []
    for r in results[:10]:
        if not isinstance(r, dict):
            continue
        tvdb = r.get("tvdbId")
        title = (r.get("title") or "").strip()
        year = r.get("year")
        images = r.get("images") or r.get("imageUrls")  # defensive
        poster = _pick_poster(images)
        if isinstance(tvdb, int) and tvdb > 0 and title:
            rows.append(
                {
                    "id": tvdb,                 # <-- Option A normalization
                    "title": title,
                    "year": year if isinstance(year, int) else "",
                    "poster": poster or "",
                }
            )

    return _ui("SHOW_SEARCH", {"author_id": int(author_id), "query": query, "results": rows})


async def handle_plexmovie(http: aiohttp.ClientSession, content: str) -> str:
    arg = _join_args(content)
    if not arg.isdigit():
        return "Usage: *plexmovie <tmdb_id>"

    tmdb_id = int(arg)

    cfg = radarr(http)
    if not cfg:
        return "Radarr is not configured."

    client, root = cfg

    QUALITY_PROFILE_ID = 2

    try:
        status = await client.add_movie_by_tmdb(
            tmdb_id,
            root_folder_path=root,
            quality_profile_id=QUALITY_PROFILE_ID,
            monitored=True,
            search_for_movie=False,
        )
    except Exception as e:
        return f"Failed. {type(e).__name__}: {e}"

    if status == "already_added":
        existing = await client.get_movie_by_tmdb(tmdb_id)
        title = (existing.get("title") or "").strip() if isinstance(existing, dict) else ""
        year = _safe_int(existing.get("year")) if isinstance(existing, dict) else None

        if await _movie_exists_in_plex(http, title=title, year=year):
            return MEDIA_ALREADY_ON_PLEX
        return MEDIA_ALREADY_IN_QUEUE

    return MEDIA_ADDED_TO_QUEUE


async def handle_plexshow(http: aiohttp.ClientSession, content: str) -> str:
    arg = _join_args(content)
    if not arg.isdigit():
        return "Usage: *plexshow <tvdb_id>"

    tvdb_id = int(arg)

    cfg = sonarr(http)
    if not cfg:
        return "Sonarr is not configured."

    client, root = cfg

    QUALITY_PROFILE_ID = 1
    LANGUAGE_PROFILE_ID = 1  

    try:
        status = await client.add_series_by_tvdb(
            tvdb_id,
            root_folder_path=root,
            quality_profile_id=QUALITY_PROFILE_ID,
            language_profile_id=LANGUAGE_PROFILE_ID,
            monitored=True,
            search_for_missing_episodes=False,
        )
    except Exception as e:
        return f"Failed. {type(e).__name__}: {e}"

    if status == "already_added":
        existing = await client.get_series_by_tvdb(tvdb_id)
        title = (existing.get("title") or "").strip() if isinstance(existing, dict) else ""
        year = _safe_int(existing.get("year")) if isinstance(existing, dict) else None

        if await _show_exists_in_plex(http, title=title, year=year):
            return MEDIA_ALREADY_ON_PLEX
        return MEDIA_ALREADY_IN_QUEUE

    return MEDIA_ADDED_TO_QUEUE
