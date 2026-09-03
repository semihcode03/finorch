"""X (Twitter) ingestor - twscrape tabanli.

twscrape bir burner hesabin cookie'lerini (auth_token + ct0) kullanir.
Cookie'ler .env icinde X_AUTH_TOKEN / X_CT0 / X_USERNAME olarak verilir.

Bu ingestor ham tweet listesi dondurmenin otesinde iki is yapar:

1. **Turu ayirir.** Bir hesabin ana sayfasinda kendi analizi kadar baskasindan
   yapilmis repost da bulunur. Amac analistin KENDI mantigini ogrenmek oldugu icin
   repost'lar varsayilan olarak elenir (`X_INCLUDE_REPOSTS=true` ile acilir).
   Alintili gonderi (quote) analistin kendi yorumunu tasidigi icin tutulur.

2. **Thread'leri birlestirir.** Analistler uzun analizi tek tweet'e sigdiramaz;
   kendine cevap vererek zincir kurar. Bunlar ayri ayri islenirse her parca
   baglamsiz kalir. Ayni `conversation_id`'deki kendi gonderileri tek bir icerige
   birlestiririz (`X_STITCH_THREADS=false` ile kapatilir).

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

# Analistin kendi gorusunu tasiyan turler (repost disarida kalir)
_OWN_VOICE = {"original", "quote", "thread"}


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
            await api.pool.add_account(username, "_", "_", "_", cookies=cookies)
        except Exception as e:
            # Zaten ekliyse sorun degil
            logger.debug("Hesap ekleme atlandi: %s", e)

    async def _collect_async(self, ref: str, limit: int) -> list[FetchedItem]:
        """Ham gonderileri ceker ve siniflandirir; henuz filtrelemez."""
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
                items.append(_to_item(tweet, handle))
        except Exception as e:
            logger.error("X icerigi cekilemedi (%s): %s", handle, e)
        return items

    def collect(self, ref: str, limit: int = 20) -> list[FetchedItem]:
        """Filtrelenmemis, siniflandirilmis gonderi listesi (on inceleme icin)."""
        return _run_async(self._collect_async(ref, limit))

    def fetch(self, ref: str, limit: int = 20) -> list[FetchedItem]:
        items = self.collect(ref, limit)
        if settings.x_stitch_threads:
            items = stitch_threads(items)
        return [it for it in items if keep_item(it)]


def keep_item(item: FetchedItem) -> bool:
    """Gonderi analiz edilmeye deger mi? (repost/cevap/dusuk etkilesim filtresi)"""
    if item.post_kind == "repost" and not settings.x_include_reposts:
        return False
    if item.post_kind == "reply" and not settings.x_include_replies:
        return False
    if settings.x_min_engagement and item.engagement < settings.x_min_engagement:
        return False
    # Gorsel de metin de yoksa cikarilacak bir sey yok
    return bool(item.text.strip() or item.media_urls)


def skip_reason(item: FetchedItem) -> str:
    """`keep_item` neden elediyse insan okunur gerekcesi; tutulduysa bos string."""
    if item.post_kind == "repost" and not settings.x_include_reposts:
        return "repost (baskasinin gonderisi)"
    if item.post_kind == "reply" and not settings.x_include_replies:
        return "cevap (baska hesaba)"
    if settings.x_min_engagement and item.engagement < settings.x_min_engagement:
        return f"dusuk etkilesim ({item.engagement} < {settings.x_min_engagement})"
    if not (item.text.strip() or item.media_urls):
        return "bos icerik"
    return ""


def stitch_threads(items: list[FetchedItem]) -> list[FetchedItem]:
    """Ayni thread'deki kendi gonderilerini tek bir icerige birlestirir.

    Zincirin koku (en eski gonderi) temsilci olur: onun id'si ve url'i kullanilir,
    metinler tarih sirasiyla birlestirilir, gorseller ve etkilesimler toplanir.
    Boylece 6 parcalik bir analiz LLM'e tek ve butun bir metin olarak gider.
    """
    groups: dict[str, list[FetchedItem]] = {}
    singles: list[FetchedItem] = []

    for it in items:
        # Sadece analistin kendi sesi zincire girer; repost/cevap tek basina kalir
        if it.conversation_id and it.post_kind in _OWN_VOICE:
            groups.setdefault(it.conversation_id, []).append(it)
        else:
            singles.append(it)

    merged: list[FetchedItem] = []
    for parts in groups.values():
        if len(parts) == 1:
            merged.append(parts[0])
            continue
        parts.sort(key=lambda p: p.published_at or datetime.min)
        merged.append(_merge_thread(parts))

    return merged + singles


def _merge_thread(parts: list[FetchedItem]) -> FetchedItem:
    root = parts[0]
    media: list[str] = []
    for p in parts:
        for url in p.media_urls:
            if url not in media:
                media.append(url)

    return FetchedItem(
        source_type="x",
        external_id=root.external_id,
        url=root.url,
        title="",
        text="\n\n".join(p.text.strip() for p in parts if p.text.strip()),
        published_at=root.published_at,
        needs_transcription=False,
        media_urls=media,
        post_kind="thread",
        author_handle=root.author_handle,
        quoted_text="\n\n".join(p.quoted_text.strip() for p in parts if p.quoted_text.strip()),
        conversation_id=root.conversation_id,
        # Zincirin etkilesimi parcalarin toplamidir; kok tweet genelde en cok alir
        like_count=sum(p.like_count for p in parts),
        repost_count=sum(p.repost_count for p in parts),
        reply_count=sum(p.reply_count for p in parts),
        view_count=max((p.view_count for p in parts), default=0),
        extra={"thread_parts": len(parts)},
    )


def _to_item(tweet, handle: str) -> FetchedItem:
    """twscrape Tweet nesnesini FetchedItem'a cevirir ve turunu belirler."""
    kind, quoted_text, author = _classify(tweet, handle)

    text = getattr(tweet, "rawContent", "") or ""
    media_urls = _extract_media_urls(tweet)

    # Repost'ta gorunur metin orijinal gonderininki; onu da alalim ki
    # kullanici isterse (X_INCLUDE_REPOSTS=true) analiz edilebilsin.
    inner = getattr(tweet, "retweetedTweet", None)
    if kind == "repost" and inner is not None:
        text = getattr(inner, "rawContent", "") or text
        media_urls = media_urls or _extract_media_urls(inner)

    return FetchedItem(
        source_type="x",
        external_id=str(tweet.id),
        url=getattr(tweet, "url", "") or "",
        title="",
        text=text,
        published_at=_as_naive(getattr(tweet, "date", None)),
        needs_transcription=False,
        media_urls=media_urls,
        post_kind=kind,
        author_handle=author,
        quoted_text=quoted_text,
        conversation_id=str(getattr(tweet, "conversationId", "") or ""),
        like_count=int(getattr(tweet, "likeCount", 0) or 0),
        repost_count=int(getattr(tweet, "retweetCount", 0) or 0),
        reply_count=int(getattr(tweet, "replyCount", 0) or 0),
        view_count=int(getattr(tweet, "viewCount", 0) or 0),
    )


def _classify(tweet, handle: str) -> tuple[str, str, str]:
    """Gonderi turunu, alintilanan metni ve gercek yazari dondurur.

    Turler:
      repost   -> saf retweet; analistin kendi cumlesi yok
      quote    -> baskasini alintilayip kendi yorumunu eklemis (kendi sesi sayilir)
      thread   -> kendi gonderisine cevap; uzun analizin devami
      reply    -> baska bir hesaba cevap
      original -> bagimsiz kendi gonderisi
    """
    me = handle.lower().lstrip("@")
    author = _username(getattr(tweet, "user", None)) or me

    retweeted = getattr(tweet, "retweetedTweet", None)
    if retweeted is not None:
        original_author = _username(getattr(retweeted, "user", None))
        return "repost", "", original_author or author

    quoted = getattr(tweet, "quotedTweet", None)
    if quoted is not None:
        return "quote", getattr(quoted, "rawContent", "") or "", author

    if getattr(tweet, "inReplyToTweetId", None):
        replied_to = _username(getattr(tweet, "inReplyToUser", None))
        # Kendine cevap = thread; baskasina cevap = reply
        if replied_to and replied_to.lower() == me:
            return "thread", "", author
        return "reply", "", author

    return "original", "", author


def _username(user) -> str:
    if user is None:
        return ""
    return str(getattr(user, "username", "") or "")


def _run_async(coro):
    """Async coroutine'i senkron baglamdan calistirir."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        # Zaten calisan bir event loop varsa (nadir)
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _as_naive(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo else dt


def _full_res(url: str) -> str:
    """pbs.twimg.com gorselini tam cozunurlukte ister.

    Varsayilan url kucuk boy dondurur; grafik uzerindeki fiyat etiketleri okunmaz.
    Vision'in seviyeleri okuyabilmesi icin `name=large` sart.
    """
    if "pbs.twimg.com" not in url or "name=" in url:
        return url
    return f"{url}{'&' if '?' in url else '?'}name=large"


def _extract_media_urls(tweet) -> list[str]:
    """Tweet'e ekli foto/gorsel url'lerini toplar (video kapaklari dahil)."""
    urls: list[str] = []
    media = getattr(tweet, "media", None)
    if not media:
        return urls
    for photo in getattr(media, "photos", []) or []:
        u = getattr(photo, "url", None)
        if u:
            urls.append(_full_res(u))
    # Video/animasyon kapak gorselleri de grafik icerebilir
    for vid in getattr(media, "videos", []) or []:
        u = getattr(vid, "thumbnailUrl", None)
        if u:
            urls.append(_full_res(u))
    for gif in getattr(media, "animated", []) or []:
        u = getattr(gif, "thumbnailUrl", None)
        if u:
            urls.append(_full_res(u))
    return urls
