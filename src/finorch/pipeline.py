"""Boru hatti orkestrasyonu: kaynak senkronu, toplama, transkripsiyon, analiz, uyari.

Faz 1'de tum adimlar tek surecte sirayla calisir. Her adim idempotent'tir
(tekrar calistirmak yeni is olmadikca zarar vermez).
"""

from __future__ import annotations

import logging

from sqlalchemy import select

from finorch.analysis import extract_macro, extract_setups
from finorch.conditions import (
    evaluate_macro_rule,
    evaluate_projection,
    evaluate_trade_setup,
)
from finorch.analysis.vision import describe_image
from finorch.config import settings
from finorch.db import Analyst, ContentMedia, RawContent, Source, get_session
from finorch.db.models import Alert, MacroRule, Projection, TradeSetup, TranscriptSegment
from finorch.media import extract_scene_frames
from finorch.notify import send_message
from finorch.ingestion import get_ingestor
from finorch.sources import load_analysts_config
from finorch.transcription import transcribe_url

_VIDEO_SOURCES = {"youtube", "web"}
_TECHNICAL_TYPES = {"technical", "mixed"}

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
            text = describe_image(murl or mpath)
            if text:
                with get_session() as session:
                    m = session.get(ContentMedia, media_id)
                    if m:
                        m.vision_text = text

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

    vision_bits = [m.vision_text for m in (c.media or []) if m.vision_text]
    if vision_bits:
        parts.append("[Gorsellerden okunan]\n" + "\n".join(vision_bits))
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


def _analyze_technical(session, content_id: int, text: str, focus: str) -> None:
    extraction = extract_setups(text, focus=focus)
    for s in extraction.setups:
        obj = TradeSetup(content_id=content_id, **_with_analyst(session, content_id, s))
        session.add(obj)
        session.flush()
        evaluate_trade_setup(session, obj)


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
                if profile_type in ("technical", "mixed"):
                    _analyze_technical(session, content_id, text, focus)
            c.analyzed = True
            analyzed += 1
    logger.info("Analiz tamam: %d icerik islendi.", analyzed)
    return analyzed


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
        "alerts_sent": send_pending_alerts(),
    }
    logger.info("Dongu tamamlandi: %s", result)
    return result
