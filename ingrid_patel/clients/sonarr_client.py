# ingrid_patel/clients/sonarr_client.py

from __future__ import annotations

import logging
from typing import Any
import json

import aiohttp

log = logging.getLogger(__name__)


class SonarrClient:
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
                    snippet = (body or "")[:600].replace("\n", " ")
                    log.error("Sonarr GET %s failed: %s %s", url, r.status, snippet)
                    raise RuntimeError(f"Sonarr GET {r.status} for {url}. Body starts: {snippet}")

                try:
                    return json.loads(body) if body else None
                except Exception:
                    ct = (r.headers.get("Content-Type") or "").lower()
                    raise RuntimeError(
                        f"Sonarr returned non-JSON. status={r.status} content-type={ct} body={body[:300]!r}"
                    )
        except aiohttp.ClientError as e:
            log.exception("Sonarr GET %s client error", url)
            raise RuntimeError(f"Sonarr GET failed: {e.__class__.__name__}: {e}") from e

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
                    snippet = (body or "")[:1000].replace("\n", " ")
                    log.error("Sonarr POST %s failed: %s %s", url, r.status, snippet)

                    lowered = snippet.lower()
                    if "already been added" in lowered or "already exists" in lowered:
                        raise RuntimeError("already_added")

                    # include parsed if present
                    if parsed is not None:
                        raise RuntimeError(f"Sonarr POST {r.status} for {url}: {parsed}")
                    raise RuntimeError(f"Sonarr POST {r.status} for {url}. Body starts: {snippet}")

                return parsed
        except aiohttp.ClientError as e:
            log.exception("Sonarr POST %s client error", url)
            raise RuntimeError(f"Sonarr POST failed: {e.__class__.__name__}: {e}") from e

    async def lookup_series(self, term: str) -> Any:
        return await self._get("/api/v3/series/lookup", params={"term": term})

    async def add_series(self, payload: dict[str, Any]) -> Any:
        return await self._post("/api/v3/series", payload)

    async def list_series(self) -> list[dict[str, Any]]:
        data = await self._get("/api/v3/series")
        return data if isinstance(data, list) else []

    async def get_series_by_tvdb(self, tvdb_id: int) -> dict[str, Any] | None:
        """
        Reliable approach: list Sonarr library and filter by tvdbId.
        """
        if not isinstance(tvdb_id, int) or tvdb_id <= 0:
            return None
        shows = await self.list_series()
        for s in shows:
            if isinstance(s, dict) and s.get("tvdbId") == tvdb_id:
                return s
        return None

    async def add_series_by_tvdb(
        self,
        tvdb_id: int,
        *,
        root_folder_path: str,
        quality_profile_id: int,
        language_profile_id: int | None = None,
        monitored: bool = True,
        search_for_missing_episodes: bool = False,
    ) -> str:
        """
        Returns:
          - "added"
          - "already_added"
        """
        if not isinstance(tvdb_id, int) or tvdb_id <= 0:
            raise ValueError("tvdb_id must be a positive int")

        existing = await self.get_series_by_tvdb(tvdb_id)
        if existing:
            return "already_added"

        results = await self.lookup_series(f"tvdb:{tvdb_id}")
        if not results:
            raise RuntimeError(f"No Sonarr lookup results for tvdb:{tvdb_id}")

        series = results[0]
        payload = dict(series)
        payload["qualityProfileId"] = quality_profile_id
        payload["rootFolderPath"] = root_folder_path
        payload["monitored"] = monitored
        payload["addOptions"] = {"searchForMissingEpisodes": search_for_missing_episodes}
        if language_profile_id is not None:
            payload["languageProfileId"] = language_profile_id

        try:
            await self.add_series(payload)
            return "added"
        except RuntimeError as e:
            if str(e) == "already_added":
                return "already_added"
            raise
