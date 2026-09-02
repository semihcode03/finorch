"""SQLAlchemy modelleri.

Faz 1 semasi:
  analysts     -> takip edilen analistler
  sources      -> her analistin youtube/x/web kaynaklari
  raw_content  -> toplanan ham icerik (video/tweet/yazi + transkript)
  opinions     -> LLM'in ham icerikten cikardigi yapilandirilmis gorusler
  alerts       -> uretilen uyarilar
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Analyst(Base):
    __tablename__ = "analysts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    language: Mapped[str] = mapped_column(String(10), default="tr")
    focus: Mapped[str] = mapped_column(Text, default="")
    # macro | technical | mixed  -> icerik cikarim/degerlendirme yolunu belirler
    profile_type: Mapped[str] = mapped_column(String(20), default="macro")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    sources: Mapped[list["Source"]] = relationship(
        back_populates="analyst", cascade="all, delete-orphan"
    )
    opinions: Mapped[list["Opinion"]] = relationship(back_populates="analyst")


class Source(Base):
    __tablename__ = "sources"
    __table_args__ = (UniqueConstraint("type", "ref", name="uq_source_type_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analyst_id: Mapped[int] = mapped_column(ForeignKey("analysts.id", ondelete="CASCADE"))
    type: Mapped[str] = mapped_column(String(20))  # youtube | x | web
    ref: Mapped[str] = mapped_column(String(500))  # url / handle / feed
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    analyst: Mapped["Analyst"] = relationship(back_populates="sources")


class RawContent(Base):
    __tablename__ = "raw_content"
    __table_args__ = (
        UniqueConstraint("source_type", "external_id", name="uq_content_source_extid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int | None] = mapped_column(
        ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    analyst_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysts.id", ondelete="SET NULL"), nullable=True
    )
    source_type: Mapped[str] = mapped_column(String(20))  # youtube | x | web
    external_id: Mapped[str] = mapped_column(String(300))  # video id / tweet id / url hash
    url: Mapped[str] = mapped_column(String(800), default="")
    title: Mapped[str] = mapped_column(Text, default="")
    text: Mapped[str] = mapped_column(Text, default="")  # tweet metni / yazi (varsa)
    transcript: Mapped[str] = mapped_column(Text, default="")  # video transkripti (varsa)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Boru hatti durumu
    needs_transcription: Mapped[bool] = mapped_column(Boolean, default=False)
    transcribed: Mapped[bool] = mapped_column(Boolean, default=False)
    analyzed: Mapped[bool] = mapped_column(Boolean, default=False)
    audio_path: Mapped[str] = mapped_column(String(800), default="")

    # Gorsel isleme durumu (video kareleri / tweet gorselleri)
    has_media: Mapped[bool] = mapped_column(Boolean, default=False)
    vision_processed: Mapped[bool] = mapped_column(Boolean, default=False)

    media: Mapped[list["ContentMedia"]] = relationship(
        back_populates="content", cascade="all, delete-orphan"
    )


class ContentMedia(Base):
    """Bir icerige ait gorseller: tweet gorselleri veya videodan cikarilan kareler.

    vision_text: gorseli okuyan cok-modlu LLM'in ciktisi (grafik/seviye/desen ozeti).
    """

    __tablename__ = "content_media"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("raw_content.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(20))  # image | frame
    url: Mapped[str] = mapped_column(String(800), default="")
    local_path: Mapped[str] = mapped_column(String(800), default="")
    timestamp_sec: Mapped[float | None] = mapped_column(Float, nullable=True)  # videoda saniye
    vision_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    content: Mapped["RawContent"] = relationship(back_populates="media")


class TranscriptSegment(Base):
    """Zaman damgali transkript parcasi (VTT altyazi veya Whisper segmenti).

    start_sec sayesinde her cikarim videonun hangi dakikasinda soylendigine
    referans verebilir (dashboard'da tiklanabilir &t= linki icin).
    """

    __tablename__ = "transcript_segments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("raw_content.id", ondelete="CASCADE"))
    idx: Mapped[int] = mapped_column(Integer, default=0)
    start_sec: Mapped[float] = mapped_column(Float, default=0.0)
    end_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")


class Opinion(Base):
    __tablename__ = "opinions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("raw_content.id", ondelete="CASCADE"))
    analyst_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysts.id", ondelete="SET NULL"), nullable=True
    )

    asset: Mapped[str] = mapped_column(String(100), index=True)  # BTC, XU100, XAUUSD, ...
    stance: Mapped[str] = mapped_column(String(20))  # bullish | bearish | neutral
    timeframe: Mapped[str] = mapped_column(String(50), default="")  # kisa/orta/uzun vade
    price_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    analyst: Mapped["Analyst"] = relationship(back_populates="opinions")


class MacroRule(Base):
    """Makro/anlati hesaplarindan cikarilan nedensel kurallar.

    Ornek: condition="savas/jeopolitik gerilim", effect_asset="XAUUSD",
    effect_direction="up", rationale="guvenli liman talebi".
    Bu kurallar hafizada birikir; ileride gercek olaylar/fiyatlarla eslesince tetiklenir.
    """

    __tablename__ = "macro_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("raw_content.id", ondelete="CASCADE"))
    analyst_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysts.id", ondelete="SET NULL"), nullable=True
    )
    condition: Mapped[str] = mapped_column(Text)  # tetikleyici olay/kosul
    effect_asset: Mapped[str] = mapped_column(String(100), index=True)
    effect_direction: Mapped[str] = mapped_column(String(20))  # up | down | neutral
    rationale: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source_timestamp_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Projection(Base):
    """Makro/anlati hesaplarindan cikarilan gelecek projeksiyonlari/senaryolari."""

    __tablename__ = "projections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("raw_content.id", ondelete="CASCADE"))
    analyst_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysts.id", ondelete="SET NULL"), nullable=True
    )
    asset: Mapped[str] = mapped_column(String(100), index=True)
    horizon: Mapped[str] = mapped_column(String(50), default="")  # 1 hafta / 3 ay / 2026 sonu
    scenario: Mapped[str] = mapped_column(Text)  # senaryonun ozeti
    direction: Mapped[str] = mapped_column(String(20), default="")  # up | down | neutral
    price_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    conditions: Mapped[str] = mapped_column(Text, default="")  # varsa on kosullar
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source_timestamp_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TradeSetup(Base):
    """Teknik analiz hesaplarindan cikarilan islem kurulumlari (kendi icinde degerlendirilir)."""

    __tablename__ = "trade_setups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("raw_content.id", ondelete="CASCADE"))
    analyst_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysts.id", ondelete="SET NULL"), nullable=True
    )
    instrument: Mapped[str] = mapped_column(String(100), index=True)  # BTCUSDT, XU100, ...
    direction: Mapped[str] = mapped_column(String(10))  # long | short
    timeframe: Mapped[str] = mapped_column(String(30), default="")  # 15m, 4h, 1D
    setup_conditions: Mapped[str] = mapped_column(Text, default="")  # "FVG + MSB" gibi
    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[str] = mapped_column(String(200), default="")  # tek/coklu TP
    rr: Mapped[float | None] = mapped_column(Float, nullable=True)  # risk/reward
    rationale: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source_timestamp_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="new")  # new | triggered | invalid
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule: Mapped[str] = mapped_column(String(50))  # new_price_target | stance_change | consensus
    asset: Mapped[str] = mapped_column(String(100), index=True)
    message: Mapped[str] = mapped_column(Text)
    dedup_key: Mapped[str] = mapped_column(String(300), unique=True)  # ayni uyariyi tekrar gondermemek
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
