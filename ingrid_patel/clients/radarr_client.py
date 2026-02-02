# ingrid_patel/clients/radarr_client.py

from __future__ import annotations

import logging
from typing import Any
import json

import aiohttp

log = logging.getLogger(__name__)


class RadarrClient:
    def __init__(self, base_url: str, api_key: str, session: aiohttp.ClientSession) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = session
        self.headers = {"X-Api-Key": api_key}

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with self.http.get(url, headers=self.headers, params=params) as r:
                body = await r.text()

                if r.status < 200 or r.status >= 300:
                    snippet = (body or "")[:800].replace("\n", " ")
                    log.error("Radarr GET %s failed: %s %s", url, r.status, snippet)
                    raise RuntimeError(f"Radarr GET {r.status} for {url}. Body starts: {snippet}")

                try:
                    return json.loads(body) if body else None
                except Exception:
                    ct = (r.headers.get("Content-Type") or "").lower()
                    raise RuntimeError(
                        f"Radarr returned non-JSON. status={r.status} content-type={ct} body={body[:300]!r}"
                    )
        except aiohttp.ClientError as e:
            log.exception("Radarr GET %s client error", url)
            raise RuntimeError(f"Radarr GET failed: {e.__class__.__name__}: {e}") from e

    async def _post(self, path: str, payload: dict[str, Any]) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with self.http.post(url, headers=self.headers, json=payload) as r:
                body = await r.text()

                parsed = None
                try:
                    parsed = json.loads(body) if body else None
                except Exception:
                    parsed = None

                if r.status < 200 or r.status >= 300:
                    snippet = (body or "")[:1200].replace("\n", " ")
                    log.error("Radarr POST %s failed: %s %s", url, r.status, snippet)

                    lowered = snippet.lower()
                    if "already been added" in lowered or "already exists" in lowered:
                        raise RuntimeError("already_added")

                    if parsed is not None:
                        raise RuntimeError(f"radarr_http_{r.status}: {parsed}")
                    raise RuntimeError(f"radarr_http_{r.status}: {snippet}")

                return parsed if parsed is not None else body
        except aiohttp.ClientError as e:
            log.exception("Radarr POST %s client error", url)
            raise RuntimeError(f"Radarr POST failed: {e.__class__.__name__}: {e}") from e



    async def lookup_movie(self, term: str) -> Any:
        return await self._get("/api/v3/movie/lookup", params={"term": term})

    async def add_movie(self, payload: dict[str, Any]) -> Any:
        return await self._post("/api/v3/movie", payload)

    async def list_movies(self) -> list[dict[str, Any]]:
        data = await self._get("/api/v3/movie")
        return data if isinstance(data, list) else []

    async def get_movie_by_tmdb(self, tmdb_id: int) -> dict[str, Any] | None:
        """
        Most reliable approach: list your Radarr library and filter by tmdbId.
        (This avoids relying on query params that may differ by Radarr version/config.)
        """
        if not isinstance(tmdb_id, int) or tmdb_id <= 0:
            return None
        movies = await self.list_movies()
        for m in movies:
            if isinstance(m, dict) and m.get("tmdbId") == tmdb_id:
                return m
        return None

    async def add_movie_by_tmdb(
        self,
        tmdb_id: int,
        *,
        root_folder_path: str,
        quality_profile_id: int,
        monitored: bool = True,
        search_for_movie: bool = False,
    ) -> str:
        """
        Returns:
          - "added"
          - "already_added"
        """
        if not isinstance(tmdb_id, int) or tmdb_id <= 0:
            raise ValueError("tmdb_id must be a positive int")

        # If it already exists in Radarr, we’re done.
        existing = await self.get_movie_by_tmdb(tmdb_id)
        if existing:
            return "already_added"

        # Otherwise, lookup + add
        results = await self.lookup_movie(f"tmdb:{tmdb_id}")
        if not results:
            raise RuntimeError(f"No Radarr lookup results for tmdb:{tmdb_id}")

        movie = results[0]
        payload = dict(movie)

        payload["qualityProfileId"] = quality_profile_id
        payload["rootFolderPath"] = root_folder_path
        payload["monitored"] = monitored
        payload["addOptions"] = {"searchForMovie": search_for_movie}

        try:
            await self.add_movie(payload)
            return "added"
        except RuntimeError as e:
            if str(e) == "already_added":
                return "already_added"
            raise
