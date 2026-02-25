# ingrid_patel/clients/steam_client.py

from __future__ import annotations

import html
import os
import re
from dataclasses import dataclass
from typing import Any

import aiohttp

STEAM_STORE_BASE = "https://store.steampowered.com/app"
STEAM_LOCALE_PARAMS = {"l": "english", "cc": "US"}


@dataclass(frozen=True)
class SteamSearchResult:
    app_id: int
    name: str


@dataclass(frozen=True)
class SteamAppDetails:
    # Keep this minimal one for reminders / existing callers
    app_id: int
    name: str
    store_url: str
    release_date_text: str | None
    coming_soon: bool | None


class SteamClient:
    """
    Async Steam Store client (not Steam Web API).
    Uses the shared aiohttp.ClientSession from your app.
    """

    def __init__(self, session: aiohttp.ClientSession, api_key: str | None = None) -> None:
        self.api_key = api_key  # currently unused; keep for future
        self.http = session

    @staticmethod
    def from_env(session: aiohttp.ClientSession) -> "SteamClient":
        return SteamClient(session=session, api_key=(os.getenv("STEAM_KEY") or "").strip() or None)
    

    async def get_price_snapshot(self, app_id: int) -> dict[str, Any] | None:
        """
        Lightweight pricing fetch for sale checks.
        Returns:
            {
            "app_id": int,
            "name": str,
            "store_url": str,
            "header_image": str,
            "discount_percent": int,
            "final": str|None,      # formatted
            "initial": str|None,    # formatted
            "is_free": bool,
            }
        """
        if not isinstance(app_id, int) or app_id <= 0:
            return None

        url = "https://store.steampowered.com/api/appdetails"
        payload = await self._get_json(url, params={"appids": app_id, **STEAM_LOCALE_PARAMS})

        entry = payload.get(str(app_id))
        if not entry or not entry.get("success"):
            return None

        d = entry.get("data") or {}
        if not isinstance(d, dict) or not d:
            return None

        name = (d.get("name") or "").strip()
        if not name:
            return None

        store_url = self._store_url(app_id)
        header_img = (d.get("header_image") or "").strip() or self._steam_header_img(app_id)

        is_free = bool(d.get("is_free"))

        discount_percent = 0
        final = None
        initial = None

        po = d.get("price_overview")
        if isinstance(po, dict) and po:
            discount_percent = po.get("discount_percent") if isinstance(po.get("discount_percent"), int) else 0
            currency = (po.get("currency") or "").strip() or None
            final = self._money_from_cents(po.get("final"), currency)
            initial = self._money_from_cents(po.get("initial"), currency)

        return {
            "app_id": app_id,
            "name": name,
            "store_url": store_url,
            "header_image": header_img,
            "discount_percent": discount_percent,
            "final": final,
            "initial": initial,
            "is_free": is_free,
        }


    async def _get_json(self, url: str, *, params: dict[str, Any] | None = None) -> Any:
        try:
            async with self.http.get(url, params=params) as resp:
                body_text: str | None = None

                if resp.status < 200 or resp.status >= 300:
                    body_text = await resp.text()
                    snippet = (body_text or "")[:400].replace("\n", " ")
                    raise RuntimeError(f"Steam HTTP {resp.status} from {url}. Body starts: {snippet!r}")

                try:
                    return await resp.json()
                except Exception:
                    ct = (resp.headers.get("Content-Type") or "").lower()
                    if body_text is None:
                        body_text = await resp.text()
                    snippet = (body_text or "")[:400].replace("\n", " ")
                    raise RuntimeError(
                        f"Steam returned non-JSON from {url}. Content-Type={ct!r}. Body starts: {snippet!r}"
                    )

        except aiohttp.ClientError as e:
            raise RuntimeError(f"Steam request failed: {e.__class__.__name__}: {e}") from e

    @staticmethod
    def _store_url(app_id: int) -> str:
        return f"{STEAM_STORE_BASE}/{app_id}"

    @staticmethod
    def _steam_header_img(app_id: int) -> str:
        return f"https://cdn.cloudflare.steamstatic.com/steam/apps/{app_id}/header.jpg"

    @staticmethod
    def _strip_html(s: str) -> str:
        if not s:
            return ""
        s = s.replace("<br>", "\n").replace("<br/>", "\n").replace("<br />", "\n")
        s = re.sub(r"</p\s*>", "\n", s, flags=re.IGNORECASE)
        s = re.sub(r"<[^>]+>", "", s)
        s = html.unescape(s)
        s = re.sub(r"\n{3,}", "\n\n", s)
        return s.strip()

    @staticmethod
    def _money_from_cents(cents: int | None, currency: str | None) -> str | None:
        if cents is None or not isinstance(cents, int):
            return None
        cur = (currency or "").strip().upper() or None
        amount = cents / 100.0
        if cur:
            return f"{amount:,.2f} {cur}"
        return f"{amount:,.2f}"

    async def search_apps_top10(self, query: str) -> list[SteamSearchResult]:
        query = (query or "").strip()
        if not query:
            return []

        url = "https://store.steampowered.com/api/storesearch"
        params = {"term": query, "l": "english", "cc": "US"}
        data = await self._get_json(url, params=params)

        items = data.get("items", []) or []
        out: list[SteamSearchResult] = []
        for it in items[:10]:
            app_id = it.get("id")
            name = (it.get("name") or "").strip()
            if isinstance(app_id, int) and name:
                out.append(SteamSearchResult(app_id=app_id, name=name))
        return out

    async def get_app_details(self, app_id: int) -> SteamAppDetails | None:
        if not isinstance(app_id, int) or app_id <= 0:
            return None

        url = "https://store.steampowered.com/api/appdetails"
        payload = await self._get_json(url, params={"appids": app_id, **STEAM_LOCALE_PARAMS})

        entry = payload.get(str(app_id))
        if not entry or not entry.get("success"):
            return None

        data = entry.get("data") or {}
        name = (data.get("name") or "").strip()
        rd = data.get("release_date") or {}
        release_text = (rd.get("date") or "").strip() or None
        coming_soon = rd.get("coming_soon")
        store_url = self._store_url(app_id)

        if not name:
            return None

        return SteamAppDetails(
            app_id=app_id,
            name=name,
            store_url=store_url,
            release_date_text=release_text,
            coming_soon=coming_soon if isinstance(coming_soon, bool) else None,
        )

    async def get_review_summary(self, app_id: int) -> dict[str, Any] | None:
        if not isinstance(app_id, int) or app_id <= 0:
            return None

        url = f"https://store.steampowered.com/appreviews/{app_id}"
        params = {
            "json": 1,
            "language": "all",
            "purchase_type": "all",
            "num_per_page": 0,
        }
        data = await self._get_json(url, params=params)
        qs = data.get("query_summary") or {}
        if not isinstance(qs, dict) or not qs:
            return None

        total = qs.get("total_reviews")
        pos = qs.get("total_positive")
        neg = qs.get("total_negative")
        desc = (qs.get("review_score_desc") or "").strip() or None

        percent = None
        if isinstance(total, int) and total > 0 and isinstance(pos, int):
            percent = int(round((pos / total) * 100))

        return {
            "review_score_desc": desc,
            "total_reviews": total if isinstance(total, int) else None,
            "total_positive": pos if isinstance(pos, int) else None,
            "total_negative": neg if isinstance(neg, int) else None,
            "percent_positive": percent,
        }

    async def get_app_details_rich(self, app_id: int) -> dict[str, Any] | None:
        """
        Rich details for *searchgame <appid> UI detail view.
        Returns a dict safe to serialize into __UI__ payload.
        """
        if not isinstance(app_id, int) or app_id <= 0:
            return None

        url = "https://store.steampowered.com/api/appdetails"
        payload = await self._get_json(url, params={"appids": app_id, **STEAM_LOCALE_PARAMS})

        entry = payload.get(str(app_id))
        if not entry or not entry.get("success"):
            return None

        d = entry.get("data") or {}
        if not isinstance(d, dict) or not d:
            return None

        name = (d.get("name") or "").strip()
        if not name:
            return None

        store_url = self._store_url(app_id)
        header_img = (d.get("header_image") or "").strip() or self._steam_header_img(app_id)

        rd = d.get("release_date") or {}
        release_text = (rd.get("date") or "").strip() or None
        coming_soon = rd.get("coming_soon") if isinstance(rd.get("coming_soon"), bool) else None

        developers = d.get("developers") if isinstance(d.get("developers"), list) else []
        publishers = d.get("publishers") if isinstance(d.get("publishers"), list) else []
        developers = [str(x).strip() for x in developers if str(x).strip()]
        publishers = [str(x).strip() for x in publishers if str(x).strip()]

        plats = d.get("platforms") if isinstance(d.get("platforms"), dict) else {}
        platforms = {
            "windows": bool(plats.get("windows")),
            "mac": bool(plats.get("mac")),
            "linux": bool(plats.get("linux")),
        }

        genres = d.get("genres") if isinstance(d.get("genres"), list) else []
        genres_out: list[str] = []
        for g in genres:
            if isinstance(g, dict):
                desc = (g.get("description") or "").strip()
                if desc:
                    genres_out.append(desc)

        cats = d.get("categories") if isinstance(d.get("categories"), list) else []
        cats_out: list[str] = []
        for c in cats:
            if isinstance(c, dict):
                desc = (c.get("description") or "").strip()
                if desc:
                    cats_out.append(desc)

        short_desc = self._strip_html((d.get("short_description") or "").strip())
        about = self._strip_html((d.get("about_the_game") or "").strip())
        supported_lang = self._strip_html((d.get("supported_languages") or "").strip())

        pc_req = d.get("pc_requirements") if isinstance(d.get("pc_requirements"), dict) else {}
        min_req = self._strip_html((pc_req.get("minimum") or "").strip())
        rec_req = self._strip_html((pc_req.get("recommended") or "").strip())

        dlc_list = d.get("dlc") if isinstance(d.get("dlc"), list) else []
        dlc_count = len([x for x in dlc_list if isinstance(x, int)])

        is_free = bool(d.get("is_free"))
        price = None
        po = d.get("price_overview") if isinstance(d.get("price_overview"), dict) else {}
        if is_free:
            price = {"type": "free"}
        elif po:
            currency = (po.get("currency") or "").strip() or None
            initial = self._money_from_cents(po.get("initial"), currency)
            final = self._money_from_cents(po.get("final"), currency)
            disc = po.get("discount_percent")
            price = {
                "type": "paid",
                "currency": currency,
                "initial": initial,
                "final": final,
                "discount_percent": disc if isinstance(disc, int) else None,
            }

        meta = d.get("metacritic") if isinstance(d.get("metacritic"), dict) else {}
        metacritic_score = meta.get("score") if isinstance(meta.get("score"), int) else None

        review_summary = await self.get_review_summary(app_id)

        return {
            "app_id": app_id,
            "name": name,
            "store_url": store_url,
            "header_image": header_img,
            "release_date_text": release_text,
            "coming_soon": coming_soon,
            "developers": developers,
            "publishers": publishers,
            "platforms": platforms,
            "genres": genres_out,
            "categories": cats_out,
            "dlc_count": dlc_count,
            "price": price,
            "metacritic_score": metacritic_score,
            "short_description": short_desc,
            "about_the_game": about,
            "supported_languages": supported_lang,
            "pc_minimum": min_req,
            "pc_recommended": rec_req,
            "reviews": review_summary,
        }

    async def get_app_details_full(self, app_id: int) -> dict[str, Any] | None:
        """
        Backwards-compatible alias for rich UI details.
        """
        return await self.get_app_details_rich(app_id)
