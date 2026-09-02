"""X (Twitter) ingestor - twscrape tabanli.

twscrape bir burner hesabin cookie'lerini (auth_token + ct0) kullanir.
Cookie'ler .env icinde X_AUTH_TOKEN / X_CT0 / X_USERNAME olarak verilir.

NOT: twscrape async'tir. Burada senkron sarmalayici sunuyoruz. Bir hesap havuzu
SQLite'ta (accounts.db) tutulur; ilk calistirmada cookie hesabi otomatik eklenir.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from finorch.config import settings
from finorch.ingestion.base import FetchedItem, Ingestor

logger = logging.getLogger(__name__)

_ACCOUNTS_DB = "accounts.db"


class XIngestor(Ingestor):
    source_type = "x"

    def healthcheck(self) -> tuple[bool, str]:
        try:
            import twscrape  # noqa: F401
        except Exception as e:  # pragma: no cover
            return False, f"twscrape bulunamadi: {e}"
        if not (settings.x_auth_token and settings.x_ct0):
            return False, "X_AUTH_TOKEN / X_CT0 tanimli degil (burner hesap cookie'leri gerekli)"
        return True, "twscrape hazir"

    async def _ensure_account(self, api) -> None:
        cookies = f"auth_token={settings.x_auth_token}; ct0={settings.x_ct0}"
        username = settings.x_username or "finorch_burner"
        try:
            await api.pool.add_account(
                username, "_", "_", "_", cookies=cookies
            )
        except Exception as e:
            # Zaten ekliyse sorun degil
            logger.debug("Hesap ekleme atlandi: %s", e)

    async def _fetch_async(self, ref: str, limit: int) -> list[FetchedItem]:
        from twscrape import API

        api = API(_ACCOUNTS_DB)
        await self._ensure_account(api)

        handle = ref.lstrip("@")
        items: list[FetchedItem] = []
        try:
            user = await api.user_by_login(handle)
            if not user:
                logger.warning("X kullanicisi bulunamadi: %s", handle)
                return items
            async for tweet in api.user_tweets(user.id, limit=limit):
                media_urls = _extract_media_urls(tweet)
                items.append(
                    FetchedItem(
                        source_type="x",
                        external_id=str(tweet.id),
                        url=getattr(tweet, "url", "") or "",
                        title="",
                        text=tweet.rawContent or "",
                        published_at=_as_naive(getattr(tweet, "date", None)),
                        needs_transcription=False,
                        media_urls=media_urls,
                    )
                )
        except Exception as e:
            logger.error("X icerigi cekilemedi (%s): %s", handle, e)
        return items

    def fetch(self, ref: str, limit: int = 10) -> list[FetchedItem]:
        try:
            return asyncio.run(self._fetch_async(ref, limit))
        except RuntimeError:
            # Zaten calisan bir event loop varsa (nadir)
            loop = asyncio.new_event_loop()
            try:
                return loop.run_until_complete(self._fetch_async(ref, limit))
            finally:
                loop.close()


def _as_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _extract_media_urls(tweet) -> list[str]:
    """Tweet'e ekli foto/gorsel url'lerini toplar (video kapaklari dahil)."""
    urls: list[str] = []
    media = getattr(tweet, "media", None)
    if not media:
        return urls
    for photo in getattr(media, "photos", []) or []:
        u = getattr(photo, "url", None)
        if u:
            urls.append(u)
    # Video/animasyon kapak gorselleri de grafik icerebilir
    for vid in getattr(media, "videos", []) or []:
        u = getattr(vid, "thumbnailUrl", None)
        if u:
            urls.append(u)
    return urls
