"""Ingestion katmani ortak arayuzu ve backend yonlendirmesi.

Her kaynak turu (youtube/x/web) icin bir Ingestor implementasyonu vardir.
"Birincil + yedek" felsefesi: bir Ingestor birden fazla backend deneyebilir;
ilki basarisiz olursa digerine duser (Agent-Reach'ten ilham).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FetchedItem:
    """Bir kaynaktan cekilen tek bir icerik parcasi (video/tweet/yazi)."""

    source_type: str  # youtube | x | web
    external_id: str  # video id / tweet id / url hash
    url: str = ""
    title: str = ""
    text: str = ""  # dogrudan metin (tweet/yazi)
    transcript: str = ""  # varsa hazir altyazi transkripti
    published_at: datetime | None = None
    needs_transcription: bool = False  # video var, transkript sonradan cikarilacak mi
    audio_path: str = ""
    media_urls: list[str] = field(default_factory=list)  # tweet gorselleri vb.
    # Zaman damgali transkript segmentleri: [{"start": float, "end": float|None, "text": str}]
    segments: list[dict] = field(default_factory=list)
    extra: dict = field(default_factory=dict)


class Ingestor(ABC):
    """Belirli bir kaynak turunu tarayan soyut sinif."""

    source_type: str = ""

    @abstractmethod
    def fetch(self, ref: str, limit: int = 5) -> list[FetchedItem]:
        """`ref` (kanal/handle/feed) icin en son `limit` icerigi getirir."""
        raise NotImplementedError

    def healthcheck(self) -> tuple[bool, str]:
        """Backend'in kullanilabilir olup olmadigini dondurur (ok, mesaj)."""
        return True, "ok"


def get_ingestor(source_type: str) -> Ingestor:
    """Kaynak turune gore uygun Ingestor'u dondurur (lazy import)."""
    source_type = source_type.lower().strip()
    if source_type == "youtube":
        from finorch.ingestion.youtube import YouTubeIngestor

        return YouTubeIngestor()
    if source_type == "x":
        from finorch.ingestion.x import XIngestor

        return XIngestor()
    if source_type == "web":
        from finorch.ingestion.web import WebIngestor

        return WebIngestor()
    raise ValueError(f"Bilinmeyen kaynak turu: {source_type}")
