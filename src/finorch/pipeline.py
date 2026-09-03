"""Boru hatti orkestrasyonu: kaynak senkronu, toplama, transkripsiyon, analiz, uyari.

Faz 1'de tum adimlar tek surecte sirayla calisir. Her adim idempotent'tir
(tekrar calistirmak yeni is olmadikca zarar vermez).
"""

from __future__ import annotations

import logging

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from finorch.analysis import build_profile, extract_macro, extract_setups, extract_watches
from finorch.conditions import (
    evaluate_macro_rule,
    evaluate_projection,
    evaluate_trade_setup,
)
from finorch.conditions.watch import evaluate_all as evaluate_all_watches
from finorch.conditions.watch import expire_stale
from finorch.analysis.vision import describe_image
from finorch.config import settings
from finorch.db import Analyst, AnalystProfile, ContentMedia, RawContent, Source, get_session
from finorch.db.models import (
    Alert,
    MacroRule,
    PriceWatch,
    Projection,
    TradeSetup,
    TranscriptSegment,
)
from finorch.market import get_history, refresh_quotes, resolve_symbol
from finorch.media import extract_scene_frames
from finorch.notify import send_message
from finorch.ingestion import get_ingestor
from finorch.sources import load_analysts_config
from finorch.transcription import transcribe_url

_VIDEO_SOURCES = {"youtube", "web"}
_TECHNICAL_TYPES = {"technical", "mixed"}

# Profil cikarimi icin okunacak en fazla icerik sayisi (maliyet siniri)
_PROFILE_SAMPLE_SIZE = 12

logger = logging.getLogger(__name__)


def sync_config() -> None:
    """analysts.yaml'daki analist ve kaynaklari DB'ye yazar (upsert)."""
    cfg = load_analysts_config(settings.analysts_config)
    with get_session() as session:
        for a in cfg.analysts:
            analyst = session.scalar(select(Analyst).where(Analyst.name == a.name))
            if not analyst:
                analyst = Analyst(
                    name=a.name,
                    language=a.language,
                    focus=a.focus,
                    profile_type=a.profile_type,
                )
                session.add(analyst)
                session.flush()
            else:
                analyst.language = a.language
                analyst.focus = a.focus
                analyst.profile_type = a.profile_type

            for s in a.sources:
                src = session.scalar(
                    select(Source).where(Source.type == s.type, Source.ref == s.ref)
                )
                if not src:
                    session.add(
                        Source(analyst_id=analyst.id, type=s.type, ref=s.ref, active=True)
                    )
                else:
                    src.analyst_id = analyst.id
                    src.active = True
    logger.info("Kaynak yapilandirmasi senkronlandi (%d analist).", len(cfg.analysts))


def run_ingestion(limit_per_source: int = 5, whisper_for_missing: bool = True) -> int:
    """Aktif kaynaklari tarar, yeni icerikleri DB'ye ekler. Yeni icerik sayisini doner.

    whisper_for_missing=False iken (backfill) altyazisi olmayan videolar Whisper
    kuyruguna alinmaz; sadece hazir altyazi/metin kullanilir.
    """
    new_count = 0
    with get_session() as session:
        sources = session.scalars(select(Source).where(Source.active.is_(True))).all()
        analyst_types = {a.id: a.profile_type for a in session.scalars(select(Analyst)).all()}
        source_meta = [(s.id, s.analyst_id, s.type, s.ref) for s in sources]

    for source_id, analyst_id, stype, ref in source_meta:
        try:
            ingestor = get_ingestor(stype)
            items = ingestor.fetch(ref, limit=limit_per_source)
        except Exception as e:
            logger.error("Kaynak taranamadi (%s:%s): %s", stype, ref, e)
            continue

        is_technical = analyst_types.get(analyst_id) in _TECHNICAL_TYPES

        with get_session() as session:
            for it in items:
                exists = session.scalar(
                    select(RawContent).where(
                        RawContent.source_type == it.source_type,
                        RawContent.external_id == it.external_id,
                    )
                )
                if exists:
                    continue

                needs_tr = it.needs_transcription and whisper_for_missing
                # Teknik hesaplarin videolarinda grafik onemli -> kare cikarilacak.
                # X gorselleri de medya sayilir.
                video_media = is_technical and it.source_type in _VIDEO_SOURCES and bool(it.url)
                has_media = bool(it.media_urls) or video_media

                content = RawContent(
                    source_id=source_id,
                    analyst_id=analyst_id,
                    source_type=it.source_type,
                    external_id=it.external_id,
                    url=it.url,
                    title=it.title,
                    text=it.text,
                    transcript=it.transcript,
                    published_at=it.published_at,
                    needs_transcription=needs_tr,
                    transcribed=bool(it.transcript),
                    analyzed=False,
                    has_media=has_media,
                    vision_processed=not has_media,
                    post_kind=it.post_kind,
                    author_handle=it.author_handle,
                    quoted_text=it.quoted_text,
                    conversation_id=it.conversation_id,
                    like_count=it.like_count,
                    repost_count=it.repost_count,
                    reply_count=it.reply_count,
                    view_count=it.view_count,
                )
                session.add(content)
                session.flush()

                for murl in it.media_urls:
                    session.add(
                        ContentMedia(content_id=content.id, kind="image", url=murl)
                    )
                _store_segments(session, content.id, it.segments)
                new_count += 1
    logger.info("Toplama tamam: %d yeni icerik.", new_count)
    return new_count


def run_transcription(max_items: int = 10) -> int:
    """Transkript bekleyen videolari isler."""
    done = 0
    with get_session() as session:
        pending = session.scalars(
            select(RawContent)
            .where(
                RawContent.needs_transcription.is_(True),
                RawContent.transcribed.is_(False),
            )
            .limit(max_items)
        ).all()
        targets = [(c.id, c.url, c.analyst_id) for c in pending]

    for content_id, url, analyst_id in targets:
        lang = "tr"
        with get_session() as session:
            if analyst_id:
                a = session.get(Analyst, analyst_id)
                if a:
                    lang = a.language or "tr"
        segments = transcribe_url(url, language=lang)
        with get_session() as session:
            c = session.get(RawContent, content_id)
            if not c:
                continue
            if segments:
                _store_segments(session, content_id, segments)
                c.transcript = " ".join(s["text"] for s in segments).strip()
                c.transcribed = True
                done += 1
            else:
                # Basarisiz: tekrar denememek icin transcribed=True ama transcript bos
                c.transcribed = True
    logger.info("Transkripsiyon tamam: %d icerik.", done)
    return done


def _store_segments(session, content_id: int, segments: list[dict]) -> None:
    """Zaman damgali transkript segmentlerini kaydeder."""
    for i, s in enumerate(segments or []):
        session.add(
            TranscriptSegment(
                content_id=content_id,
                idx=i,
                start_sec=float(s.get("start", 0.0) or 0.0),
                end_sec=s.get("end"),
                text=str(s.get("text", "")).strip(),
            )
        )


def run_vision(max_items: int = 10) -> int:
    """Gorselli icerikleri isler: X gorsellerini ve teknik video karelerini okur.

    Teknik hesaplarin videolarindan sahne degisimiyle kareler cikarilir; her gorsel
    cok-modlu LLM ile ozetlenir ve content_media.vision_text'e yazilir.
    """
    if not settings.vision_enabled:
        return 0

    processed = 0
    with get_session() as session:
        pending = session.scalars(
            select(RawContent)
            .where(RawContent.has_media.is_(True), RawContent.vision_processed.is_(False))
            .limit(max_items)
        ).all()
        targets = [(c.id, c.source_type, c.external_id, c.url, c.analyst_id) for c in pending]

    for content_id, stype, ext_id, url, analyst_id in targets:
        # 1) Teknik video ise kareleri cikar ve medya olarak ekle
        is_technical = False
        with get_session() as session:
            if analyst_id:
                a = session.get(Analyst, analyst_id)
                is_technical = bool(a and a.profile_type in _TECHNICAL_TYPES)

        if is_technical and stype in _VIDEO_SOURCES and url:
            frames = extract_scene_frames(url, ext_id)
            with get_session() as session:
                for path, ts in frames:
                    session.add(
                        ContentMedia(
                            content_id=content_id, kind="frame", local_path=path, timestamp_sec=ts
                        )
                    )

        # 2) Bu icerige ait, henuz okunmamis tum gorselleri isle
        with get_session() as session:
            media = session.scalars(
                select(ContentMedia).where(
                    ContentMedia.content_id == content_id, ContentMedia.vision_text == ""
                )
            ).all()
            media_targets = [(m.id, m.url, m.local_path) for m in media]

        for media_id, murl, mpath in media_targets:
            reading = describe_image(murl or mpath)
            summary = reading.as_text()
            if not summary:
                continue
            with get_session() as session:
                m = session.get(ContentMedia, media_id)
                if m:
                    m.vision_text = summary
                    m.is_chart = reading.is_chart
                    m.chart_symbol = reading.symbol
                    m.chart_timeframe = reading.timeframe

        with get_session() as session:
            c = session.get(RawContent, content_id)
            if c:
                c.vision_processed = True
        processed += 1

    if processed:
        logger.info("Vision tamam: %d icerik islendi.", processed)
    return processed


def _fmt_ts(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m:02d}:{s:02d}"


def _content_text(session, c: RawContent) -> str:
    """Analiz icin metni olusturur. Transkript, segment varsa [saniye] etiketli verilir
    ki LLM cikarimlara zaman damgasi/dakika referansi ekleyebilsin."""
    parts = [c.title or ""]

    segments = session.scalars(
        select(TranscriptSegment)
        .where(TranscriptSegment.content_id == c.id)
        .order_by(TranscriptSegment.idx)
    ).all()
    if segments:
        parts.append(
            "\n".join(f"[{int(s.start_sec)}] {s.text}" for s in segments if s.text)
        )
    elif c.transcript:
        parts.append(c.transcript)

    if c.text:
        parts.append(c.text)

    # Alintilanan gonderi olmadan analistin yorumu baglamsiz kalir
    # ("bu tam da bekledigim seydi" -> neyi bekledigi alintida yaziyor)
    if c.quoted_text:
        parts.append(f"[Alintilanan gonderi]\n{c.quoted_text}")

    # Sadece gercek grafikler analize girer; mem/selfie aciklamasi LLM'i yaniltir
    vision_bits = [m.vision_text for m in (c.media or []) if m.vision_text and m.is_chart]
    if vision_bits:
        parts.append("[Grafiklerden okunan]\n" + "\n".join(vision_bits))
    return "\n".join(p for p in parts if p).strip()


def _analyze_macro(session, content_id: int, text: str, focus: str) -> None:
    extraction = extract_macro(text, focus=focus)
    for r in extraction.rules:
        obj = MacroRule(content_id=content_id, **_with_analyst(session, content_id, r))
        session.add(obj)
        session.flush()
        evaluate_macro_rule(session, obj)
    for p in extraction.projections:
        obj = Projection(content_id=content_id, **_with_analyst(session, content_id, p))
        session.add(obj)
        session.flush()
        evaluate_projection(session, obj)
        _watch_from_projection(session, content_id, obj)


def _analyze_technical(session, content_id: int, text: str, focus: str) -> None:
    extraction = extract_setups(text, focus=focus)
    for s in extraction.setups:
        obj = TradeSetup(content_id=content_id, **_with_analyst(session, content_id, s))
        session.add(obj)
        session.flush()
        evaluate_trade_setup(session, obj)


def _analyze_watches(session, content_id: int, text: str, focus: str) -> None:
    """Takip edilebilir fiyat kosullarini cikarip izlemeye alir."""
    extraction = extract_watches(text, focus=focus)
    for w in extraction.watches:
        payload = _with_analyst(session, content_id, w)
        _add_watch(session, content_id, symbol=resolve_symbol(w["instrument"]), **payload)


def _watch_from_projection(session, content_id: int, proj: Projection) -> None:
    """Fiyat hedefi tasiyan makro projeksiyonu izlenebilir bir hedefe cevirir.

    Makro analistler de somut hedef verir ("dolar yil sonu 45"). Bu hedefler ayri bir
    LLM cagrisi yapilmadan, zaten cikarilmis projeksiyondan izlemeye alinir.
    """
    if proj.price_target is None:
        return
    instrument = proj.asset or proj.tickers.split(",")[0].strip()
    symbol = resolve_symbol(instrument)
    if not symbol:
        return

    _add_watch(
        session,
        content_id,
        analyst_id=proj.analyst_id,
        instrument=instrument,
        symbol=symbol,
        direction={"up": "long", "down": "short"}.get(proj.direction, "neutral"),
        trigger_type="target",
        trigger_price=proj.price_target,
        structure=proj.conditions,
        action=proj.scenario,
        rationale=proj.horizon,
        confidence=proj.confidence,
        quote=proj.quote,
        source_timestamp_sec=proj.source_timestamp_sec,
    )


def _add_watch(session, content_id: int, **fields) -> PriceWatch | None:
    """Izleme kaydi ekler; ayni icerikte ayni tetik zaten varsa atlar."""
    symbol = fields.get("symbol") or ""
    trigger_price = fields.get("trigger_price")
    duplicate = session.scalar(
        select(PriceWatch).where(
            PriceWatch.content_id == content_id,
            PriceWatch.symbol == symbol,
            PriceWatch.trigger_type == fields.get("trigger_type", ""),
            PriceWatch.trigger_price.is_(None)
            if trigger_price is None
            else PriceWatch.trigger_price == trigger_price,
        )
    )
    if duplicate:
        return None

    watch = PriceWatch(
        content_id=content_id,
        status="watching" if symbol else "unresolved",
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.watch_expire_days),
        **fields,
    )
    session.add(watch)
    session.flush()
    return watch


def _with_analyst(session, content_id: int, payload: dict) -> dict:
    """content_id'ye bagli analyst_id'yi payload'a ekler."""
    c = session.get(RawContent, content_id)
    return {**payload, "analyst_id": c.analyst_id if c else None}


def run_analysis(max_items: int = 20) -> int:
    """Analiz bekleyen icerikleri profil tipine gore isler."""
    analyzed = 0

    with get_session() as session:
        # Gorselli icerikte once vision tamamlanmali (vision_text analize dahil edilir)
        pending = session.scalars(
            select(RawContent)
            .where(RawContent.analyzed.is_(False), RawContent.vision_processed.is_(True))
            .limit(max_items)
        ).all()
        targets = [c.id for c in pending]

    for content_id in targets:
        with get_session() as session:
            c = session.get(RawContent, content_id)
            if not c:
                continue
            text = _content_text(session, c)
            profile_type = "macro"
            focus = ""
            if c.analyst_id:
                a = session.get(Analyst, c.analyst_id)
                if a:
                    profile_type = a.profile_type or "macro"
                    focus = a.focus

        with get_session() as session:
            c = session.get(RawContent, content_id)
            if not c:
                continue
            if text:
                if profile_type in ("macro", "mixed"):
                    _analyze_macro(session, content_id, text, focus)
                if profile_type in _TECHNICAL_TYPES:
                    _analyze_technical(session, content_id, text, focus)
                    # Makro hesaplarda fiyat hedefleri zaten projeksiyondan turetiliyor;
                    # ayri bir LLM cagrisi sadece teknik hesaplar icin yapilir.
                    _analyze_watches(session, content_id, text, focus)
            c.analyzed = True
            analyzed += 1
    logger.info("Analiz tamam: %d icerik islendi.", analyzed)
    return analyzed


def run_watches() -> int:
    """Takipteki fiyat kosullarini guncel piyasa verisiyle degerlendirir.

    Tetiklenen kosullar icin uyari uretilir; gonderim `send_pending_alerts` ile olur.
    """
    if not settings.market_enabled:
        return 0

    with get_session() as session:
        expired = expire_stale(session)
        alerts = evaluate_all_watches(session)
        triggered = len(alerts)
        symbols = {
            w.symbol
            for w in session.scalars(
                select(PriceWatch).where(PriceWatch.status == "watching")
            ).all()
            if w.symbol
        }

    # Grafik verisini burada tazeleriz ki dashboard bir web istegi sirasinda
    # yfinance'i beklemek zorunda kalmasin.
    for symbol in symbols:
        get_history(symbol)

    if triggered or expired:
        logger.info("Izleme tamam: %d tetiklendi, %d suresi doldu.", triggered, expired)
    return triggered


def run_ticker() -> int:
    """Dashboard ustundeki piyasa seridini tazeler.

    Boru hattinin geri kalanindan bagimsizdir ve cok daha sik calisir; scheduler
    bunu ayri bir is olarak zamanlar.
    """
    try:
        return refresh_quotes()
    except Exception as e:
        logger.error("Piyasa seridi guncellenemedi: %s", e)
        return 0


def run_profiles(force: bool = False, min_new_contents: int = 3) -> int:
    """Analistlerin yontem profillerini (yeniden) uretir.

    Her calistirmada tum analistleri LLM'e sokmak pahali oldugu icin, profil
    yalnizca hic yoksa veya son uretimden bu yana yeterince yeni icerik geldiyse
    yenilenir. `force=True` bu kontrolu atlar.
    """
    built = 0
    with get_session() as session:
        analyst_ids = [a.id for a in session.scalars(select(Analyst)).all()]

    for analyst_id in analyst_ids:
        with get_session() as session:
            analyst = session.get(Analyst, analyst_id)
            if not analyst:
                continue
            profile = session.scalar(
                select(AnalystProfile).where(AnalystProfile.analyst_id == analyst_id)
            )
            total = session.scalar(
                select(func.count())
                .select_from(RawContent)
                .where(RawContent.analyst_id == analyst_id, RawContent.analyzed.is_(True))
            ) or 0
            if not total:
                continue
            if profile and not force and (total - profile.sample_size) < min_new_contents:
                continue

            contents = session.scalars(
                select(RawContent)
                .where(RawContent.analyst_id == analyst_id, RawContent.analyzed.is_(True))
                .order_by(
                    RawContent.published_at.desc().nulls_last(),
                    RawContent.fetched_at.desc(),
                )
                .limit(_PROFILE_SAMPLE_SIZE)
            ).all()
            samples = [_content_text(session, c) for c in contents]
            name, focus = analyst.name, analyst.focus

        result = build_profile(samples, analyst_name=name, focus=focus)
        if result.is_empty:
            continue

        with get_session() as session:
            profile = session.scalar(
                select(AnalystProfile).where(AnalystProfile.analyst_id == analyst_id)
            )
            if not profile:
                profile = AnalystProfile(analyst_id=analyst_id)
                session.add(profile)
            for key, value in result.as_dict().items():
                setattr(profile, key, value)
            profile.sample_size = total
            profile.updated_at = datetime.now(timezone.utc)
        built += 1

    if built:
        logger.info("Profil tamam: %d analist guncellendi.", built)
    return built


def send_pending_alerts() -> int:
    """Gonderilmemis uyarilari Telegram'a yollar."""
    sent = 0
    with get_session() as session:
        pending = session.scalars(select(Alert).where(Alert.sent.is_(False))).all()
        alert_ids = [(a.id, a.message) for a in pending]

    for alert_id, message in alert_ids:
        ok = send_message(message)
        if ok:
            with get_session() as session:
                a = session.get(Alert, alert_id)
                if a:
                    a.sent = True
            sent += 1
    if sent:
        logger.info("%d uyari Telegram'a gonderildi.", sent)
    return sent


def run_once() -> dict:
    """Tam bir dongu: toplama -> transkripsiyon -> analiz -> uyari gonderimi."""
    settings.ensure_dirs()
    result = {
        "ingested": run_ingestion(),
        "transcribed": run_transcription(),
        "vision": run_vision(),
        "analyzed": run_analysis(),
        "triggered": run_watches(),
        "profiles": run_profiles(),
        "alerts_sent": send_pending_alerts(),
    }
    logger.info("Dongu tamamlandi: %s", result)
    return result
