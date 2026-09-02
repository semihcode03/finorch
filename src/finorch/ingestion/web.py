"""Web ingestor.

Iki mod:
  - RSS/Atom feed  -> feedparser ile son yazilar/basliklar
  - Video sayfasi  -> yt-dlp'ye devredilir (altyazi yoksa transkripsiyon isaretlenir)

`ref` bir feed url'si mi yoksa video sayfasi mi oldugunu icerige gore ayirt eder.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from time import mktime

from finorch.ingestion.base import FetchedItem, Ingestor

logger = logging.getLogger(__name__)


def _url_hash(url: str) -> str:
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:20]


class WebIngestor(Ingestor):
    source_type = "web"

    def healthcheck(self) -> tuple[bool, str]:
        try:
            import feedparser  # noqa: F401

            return True, "feedparser yuklu"
        except Exception as e:  # pragma: no cover
            return False, f"feedparser bulunamadi: {e}"

    def _fetch_rss(self, ref: str, limit: int) -> list[FetchedItem]:
        import feedparser

        feed = feedparser.parse(ref)
        items: list[FetchedItem] = []
        for entry in feed.entries[:limit]:
            link = entry.get("link", ref)
            published_at = None
            if entry.get("published_parsed"):
                published_at = datetime.fromtimestamp(mktime(entry["published_parsed"]))
            summary = entry.get("summary", "") or entry.get("description", "")
            items.append(
                FetchedItem(
                    source_type="web",
                    external_id=entry.get("id") or _url_hash(link),
                    url=link,
                    title=entry.get("title", ""),
                    text=summary,
                    published_at=published_at,
                    needs_transcription=False,
                )
            )
        return items

    def _fetch_video_page(self, ref: str) -> list[FetchedItem]:
        import yt_dlp

        opts = {"quiet": True, "no_warnings": True, "skip_download": True}
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(ref, download=False)
        except Exception as e:
            logger.error("Web videosu cozumlenemedi (%s): %s", ref, e)
            return []

        return [
            FetchedItem(
                source_type="web",
                external_id=info.get("id") or _url_hash(ref),
                url=ref,
                title=info.get("title", ""),
                needs_transcription=True,
                extra={"duration": info.get("duration")},
            )
        ]

    def fetch(self, ref: str, limit: int = 5) -> list[FetchedItem]:
        lower = ref.lower()
        if lower.endswith((".xml", ".rss", ".atom")) or "/rss" in lower or "/feed" in lower:
            return self._fetch_rss(ref, limit)
        # Once RSS dene, bos donerse video sayfasi olarak dene
        rss_items = self._fetch_rss(ref, limit)
        if rss_items:
            return rss_items
        return self._fetch_video_page(ref)
