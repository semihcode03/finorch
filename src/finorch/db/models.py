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
from sqlalchemy import text as sa_text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# `text` olarak import EDILMEZ: RawContent ve TranscriptSegment'te `text` adinda
# bir kolon var ve sinif govdesinde fonksiyonu golgeleyip
# "MappedColumn object is not callable" hatasi veriyor.


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

    # --- X (Twitter) ozel alanlari; diger kaynaklarda bos kalir ---
    # original = analistin kendi gonderisi, repost = baskasindan alinti/retweet,
    # quote = alintilayip yorum katmis, reply = birine cevap
    post_kind: Mapped[str] = mapped_column(String(20), default="", server_default=sa_text("''"))
    # Gonderiyi gercekte yazan hesap (repost'ta orijinal yazar)
    author_handle: Mapped[str] = mapped_column(String(100), default="", server_default=sa_text("''"))
    # Alintilanan gonderinin metni (quote/repost'ta analiz baglami icin gerekir)
    quoted_text: Mapped[str] = mapped_column(Text, default="", server_default=sa_text("''"))
    # Ayni thread'deki gonderiler ayni conversation_id'yi paylasir
    conversation_id: Mapped[str] = mapped_column(String(100), default="", server_default=sa_text("''"))
    like_count: Mapped[int] = mapped_column(Integer, default=0, server_default=sa_text("0"))
    repost_count: Mapped[int] = mapped_column(Integer, default=0, server_default=sa_text("0"))
    reply_count: Mapped[int] = mapped_column(Integer, default=0, server_default=sa_text("0"))
    view_count: Mapped[int] = mapped_column(Integer, default=0, server_default=sa_text("0"))

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

    # Gorsel gercekten bir finansal grafik mi, yoksa selfie/mem/ekran goruntusu mu?
    # Vision cikti okunurken belirlenir; sadece grafikler analiz metnine dahil edilir.
    is_chart: Mapped[bool] = mapped_column(Boolean, default=False, server_default=sa_text("false"))
    # Grafikte okunan enstruman ve zaman dilimi (varsa)
    chart_symbol: Mapped[str] = mapped_column(String(60), default="", server_default=sa_text("''"))
    chart_timeframe: Mapped[str] = mapped_column(String(30), default="", server_default=sa_text("''"))

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
    # Etkilenen alan ve somut enstrumanlar: "Bankacilik" / "GARAN, AKBNK"
    effect_sector: Mapped[str] = mapped_column(String(150), default="", server_default=sa_text("''"))
    effect_tickers: Mapped[str] = mapped_column(
        String(300), default="", server_default=sa_text("''")
    )  # virgulle ayrilmis
    # key  = kalici/yapisal mekanizma ("faiz duserse bankacilik yukselir")
    # live = guncel, tarihli gorus ("bu ceyrek faiz inecek")
    # bos  = eski kayit; dashboard yayin tarihine gore geriye donuk siniflar
    rule_class: Mapped[str] = mapped_column(String(10), default="", server_default=sa_text("''"))
    rationale: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source_timestamp_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- Faz 2 (Progress Score) icin ayrilmis; henuz doldurulmuyor ---
    progress_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..1
    # pending | forming | met | invalid
    progress_status: Mapped[str] = mapped_column(String(20), default="", server_default=sa_text("''"))
    progress_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


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
    # scenario = "SU OLUR" tarafi (sonuc), conditions = "BU OLURSA" tarafi (tetikleyici).
    # Ikisi birlikte tek satirlik kesin bir kosul cumlesi olusturur.
    scenario: Mapped[str] = mapped_column(Text)
    direction: Mapped[str] = mapped_column(String(20), default="")  # up | down | neutral
    price_target: Mapped[float | None] = mapped_column(Float, nullable=True)
    conditions: Mapped[str] = mapped_column(Text, default="")
    # Etkilenen alan ve somut enstrumanlar
    sector: Mapped[str] = mapped_column(String(150), default="", server_default=sa_text("''"))
    tickers: Mapped[str] = mapped_column(
        String(300), default="", server_default=sa_text("''")
    )  # virgulle ayrilmis
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source_timestamp_sec: Mapped[float | None] = mapped_column(Float, nullable=True)
    quote: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # --- Faz 2 (Progress Score) icin ayrilmis; henuz doldurulmuyor ---
    progress_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..1
    progress_status: Mapped[str] = mapped_column(String(20), default="", server_default=sa_text("''"))
    progress_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


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


class StrategySignal(Base):
    """Mum verisinden deterministik olarak uretilen ve yasam dongusu izlenen sinyal."""

    __tablename__ = "strategy_signals"
    __table_args__ = (UniqueConstraint("dedup_key", name="uq_strategy_signal_dedup"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedup_key: Mapped[str] = mapped_column(String(160), nullable=False)
    strategy: Mapped[str] = mapped_column(String(80), index=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    timeframe: Mapped[str] = mapped_column(String(20), index=True)
    direction: Mapped[str] = mapped_column(String(10))
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(24), index=True)
    bias: Mapped[str] = mapped_column(String(40), default="")
    entry: Mapped[float] = mapped_column(Float)
    stop_loss: Mapped[float] = mapped_column(Float)
    take_profit: Mapped[float] = mapped_column(Float)
    rr: Mapped[float] = mapped_column(Float, default=1.0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    rationale: Mapped[str] = mapped_column(Text, default="")
    evidence_json: Mapped[str] = mapped_column(Text, default="{}")
    source_url: Mapped[str] = mapped_column(Text, default="")
    candle_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    target_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PriceWatch(Base):
    """Fiyata bagli, izlenebilir bir kosul: "X seviyesi asilirsa islem acacagim".

    TradeSetup'tan farki: TradeSetup analistin ZATEN acmis oldugu/tarif ettigi kurulumu
    kaydeder. PriceWatch ise HENUZ gerceklesmemis, canli fiyatla surekli kontrol edilen
    bir tetikleyicidir. Fiyat kosulu sagladiginda status "triggered" olur ve uyari uretilir.

    Fiyat hedefleri de (analistin "hedefim 120 TL" demesi) trigger_type="target" ile
    buraya yazilir; boylece hedefe yaklasma da ayni cubukla izlenir.
    """

    __tablename__ = "price_watches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("raw_content.id", ondelete="CASCADE"))
    analyst_id: Mapped[int | None] = mapped_column(
        ForeignKey("analysts.id", ondelete="SET NULL"), nullable=True
    )

    # Analistin soyledigi ham ad ("gram altin", "THYAO", "bitcoin")
    instrument: Mapped[str] = mapped_column(String(100), index=True)
    # Piyasa saglayicisinda gecerli sembol ("THYAO.IS", "BTC-USD"); cozumlenemezse bos
    symbol: Mapped[str] = mapped_column(String(40), default="", server_default=sa_text("''"))
    direction: Mapped[str] = mapped_column(String(10), default="")  # long | short | neutral

    # break_above  = seviyenin uzerine cikis      break_below = altina inis
    # reclaim      = kaybedilen seviyeyi geri alma  retest    = seviyeye geri donus
    # range        = iki fiyat arasinda bant        target    = fiyat hedefi
    # structure    = saf formasyon kosulu (fiyatsiz; elle/gorsel dogrulama gerekir)
    trigger_type: Mapped[str] = mapped_column(String(20), default="")
    trigger_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    trigger_price_2: Mapped[float | None] = mapped_column(Float, nullable=True)  # bant ust ucu
    timeframe: Mapped[str] = mapped_column(String(30), default="")
    # Fiyat disi kosul: "FVG doldurulur", "haftalik kapanis ustunde", "MSB olusur"
    structure: Mapped[str] = mapped_column(Text, default="")
    # Analistin kosul saglanirsa yapacagini soyledigi sey: "kademeli alim yapacagim"
    action: Mapped[str] = mapped_column(Text, default="")

    entry: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    take_profit: Mapped[str] = mapped_column(String(200), default="")
    rr: Mapped[float | None] = mapped_column(Float, nullable=True)

    rationale: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    quote: Mapped[str] = mapped_column(Text, default="")
    source_timestamp_sec: Mapped[float | None] = mapped_column(Float, nullable=True)

    # watching = canli takipte, triggered = kosul saglandi, invalid = gecersizlesti,
    # expired  = suresi doldu, unresolved = sembol cozumlenemedi (takip edilemiyor)
    status: Mapped[str] = mapped_column(String(20), default="watching", server_default=sa_text("'watching'"))
    last_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Tetik fiyatina yuzde uzaklik; negatif = fiyat tetigin uzerinde
    distance_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    progress_score: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..1
    last_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalystProfile(Base):
    """Bir hesabin "nasil dusundugu": metodoloji, enstrumanlar, sinyal uslubu.

    Analistin son N icerigi toplu okunarak LLM ile uretilir ve icerik geldikce
    yenilenir. Amac: tek tek cikarimlarin otesinde hesabin mantigini modellemek.
    """

    __tablename__ = "analyst_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    analyst_id: Mapped[int] = mapped_column(
        ForeignKey("analysts.id", ondelete="CASCADE"), unique=True
    )

    summary: Mapped[str] = mapped_column(Text, default="")  # hesabin genel mantigi
    methodology: Mapped[str] = mapped_column(Text, default="")  # SMC/ICT, Elliott, temel...
    instruments: Mapped[str] = mapped_column(String(400), default="")  # sik isledigi enstrumanlar
    timeframes: Mapped[str] = mapped_column(String(200), default="")
    typical_setups: Mapped[str] = mapped_column(Text, default="")
    risk_style: Mapped[str] = mapped_column(Text, default="")
    # "hedefli" = net fiyat hedefi verir, "kosullu" = "su olursa girerim" der,
    # "yorumcu" = yon belirtir ama seviye vermez
    signal_style: Mapped[str] = mapped_column(String(40), default="")
    strengths: Mapped[str] = mapped_column(Text, default="")
    cautions: Mapped[str] = mapped_column(Text, default="")  # dikkat edilmesi gerekenler
    sample_size: Mapped[int] = mapped_column(Integer, default=0)  # kac icerikten uretildi
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class MarketSnapshot(Base):
    """Piyasa verisi onbellegi: sembol basina gunluk/anlik OHLC kaydi.

    Ayni sembolu her kosul kontrolunde tekrar tekrar cekmemek ve dashboard'da
    grafik cizebilmek icin saklanir.
    """

    __tablename__ = "market_snapshots"
    __table_args__ = (UniqueConstraint("symbol", "ts", name="uq_snapshot_symbol_ts"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    open: Mapped[float | None] = mapped_column(Float, nullable=True)
    high: Mapped[float | None] = mapped_column(Float, nullable=True)
    low: Mapped[float | None] = mapped_column(Float, nullable=True)
    close: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MarketQuote(Base):
    """Dashboard ustundeki kayan piyasa seridi icin hazir kotasyon.

    Serit her sayfa yuklenisinde gorunur; oradaki bir web istegi asla yfinance'i
    beklememeli. Bu yuzden veriler arka planda (`finorch ticker` / scheduler)
    toplanip burada hazir tutulur, dashboard yalnizca okur.

    `spark` alani mini grafik icin virgulle ayrilmis kapanis serisidir. Normalde
    boyle bir seri `market_snapshots`'tan sorgulanirdi; ancak serit her sembol icin
    tek satirda ve tek sorguda cizilmeli, bu yuzden burada denormalize saklanir.
    """

    __tablename__ = "market_quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    label: Mapped[str] = mapped_column(String(60), default="")  # "BIST 100", "USD/TRY"
    # Seritteki sira; yapilandirmadaki siralamayi korur
    position: Mapped[int] = mapped_column(Integer, default=0)

    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    previous_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    change: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    spark: Mapped[str] = mapped_column(Text, default="", server_default=sa_text("''"))

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule: Mapped[str] = mapped_column(String(50))  # new_price_target | stance_change | consensus
    asset: Mapped[str] = mapped_column(String(100), index=True)
    message: Mapped[str] = mapped_column(Text)
    dedup_key: Mapped[str] = mapped_column(String(300), unique=True)  # ayni uyariyi tekrar gondermemek
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent: Mapped[bool] = mapped_column(Boolean, default=False)
