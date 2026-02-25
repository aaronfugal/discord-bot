# ingrid_patel/clients/plex_client.py

from __future__ import annotations

from typing import Any
import re
import xml.etree.ElementTree as ET

import aiohttp


def _norm_title(text: str) -> str:
    if not text:
        return ""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _safe_int(v: Any) -> int | None:
    try:
        return int(v)
    except Exception:
        return None


class PlexClient:
    def __init__(self, base_url: str, token: str, session: aiohttp.ClientSession) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token.strip()
        self.http = session

    async def _get_xml(self, path: str, params: dict[str, Any] | None = None) -> ET.Element:
        url = f"{self.base_url}{path}"
        query = dict(params or {})
        query["X-Plex-Token"] = self.token

        try:
            async with self.http.get(url, params=query) as r:
                body = await r.text()
                if r.status < 200 or r.status >= 300:
                    snippet = (body or "")[:600].replace("\n", " ")
                    raise RuntimeError(f"Plex GET {r.status} for {url}. Body starts: {snippet}")
        except aiohttp.ClientError as e:
            raise RuntimeError(f"Plex GET failed: {e.__class__.__name__}: {e}") from e

        try:
            return ET.fromstring(body or "")
        except Exception as e:
            raise RuntimeError(f"Plex returned invalid XML for {url}: {e}") from e

    @staticmethod
    def _item_matches(item: ET.Element, *, title: str, year: int | None) -> bool:
        target_title = _norm_title(title)
        if not target_title:
            return False

        item_title = _norm_title(item.attrib.get("title", ""))
        item_sort = _norm_title(item.attrib.get("titleSort", ""))
        if target_title not in (item_title, item_sort):
            return False

        if year is None:
            return True

        item_year = _safe_int(item.attrib.get("year"))
        if item_year is None:
            return True

        return item_year == int(year)

    async def _has_match(self, *, media_type: str, title: str, year: int | None = None) -> bool:
        if not title:
            return False

        root = await self._get_xml("/library/search", params={"query": title})
        for item in root.iter():
            if item.attrib.get("type") != media_type:
                continue
            if self._item_matches(item, title=title, year=year):
                return True
        return False

    async def has_movie(self, *, title: str, year: int | None = None) -> bool:
        return await self._has_match(media_type="movie", title=title, year=year)

    async def has_show(self, *, title: str, year: int | None = None) -> bool:
        return await self._has_match(media_type="show", title=title, year=year)
