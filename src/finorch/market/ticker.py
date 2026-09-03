"""Dashboard ustundeki kayan piyasa seridi icin kotasyon toplama.

Serit her sayfada gorunur ve bir web istegi sirasinda ag'a cikilmaz. Veriler
burada toplanip `market_quotes` tablosuna yazilir; dashboard yalnizca okur.
Tazeleme `finorch ticker` komutu veya scheduler isi ile yapilir.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select

from finorch.config import settings
from finorch.db import MarketQuote, get_session
from finorch.market.prices import get_history, get_last_price
from finorch.market.symbols import DERIVED, display_name, is_derived

logger = logging.getLogger(__name__)

# Varsayilan serit: Turkiye piyasasi merkezli, ardindan kuresel gostergeler.
# `.env` icindeki TICKER_SYMBOLS ile tamamen degistirilebilir.
DEFAULT_SYMBOLS: list[tuple[str, str]] = [
    ("XU100.IS", "BIST 100"),
    ("XU030.IS", "BIST 30"),
    ("XBANK.IS", "BIST Bankacilik"),
    ("USDTRY=X", "USD/TRY"),
    ("EURTRY=X", "EUR/TRY"),
    ("GRAMALTIN", "Gram Altin"),
    ("GC=F", "Altin/Ons"),
    ("SI=F", "Gumus/Ons"),
    ("BZ=F", "Brent"),
    ("BTC-USD", "Bitcoin"),
    ("ETH-USD", "Ethereum"),
    ("^GSPC", "S&P 500"),
    ("^IXIC", "Nasdaq"),
    ("DX-Y.NYB", "Dolar Endeksi"),
    ("^VIX", "VIX"),
]

# Mini grafikte gosterilecek nokta sayisi (yaklasik son bir ay)
_SPARK_POINTS = 30


@dataclass
class Quote:
    symbol: str
    label: str
    price: float | None = None
    previous_close: float | None = None
    change: float | None = None
    change_pct: float | None = None
    spark: list[float] = field(default_factory=list)

    @property
    def is_usable(self) -> bool:
        return self.price is not None


def configured_symbols() -> list[tuple[str, str]]:
    """Serit sembollerini ayarlardan okur; tanimli degilse varsayilani kullanir.

    Bicim: "sembol|etiket" ciftleri, virgulle ayrilmis. Etiket verilmezse
    sembolden okunabilir bir ad turetilir.
    """
    raw = (settings.ticker_symbols or "").strip()
    if not raw:
        return DEFAULT_SYMBOLS

    pairs: list[tuple[str, str]] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        symbol, _, label = chunk.partition("|")
        symbol = symbol.strip()
        if symbol:
            pairs.append((symbol, label.strip() or display_name(symbol)))
    return pairs or DEFAULT_SYMBOLS


def fetch_quote(symbol: str, label: str) -> Quote:
    """Tek bir sembol icin son fiyat, gunluk degisim ve mini seriyi toplar."""
    quote = Quote(symbol=symbol, label=label)
    quote.price = get_last_price(symbol)

    history = get_history(symbol, period="3mo", interval="1d")
    closes = [row["close"] for row in history if row["close"] is not None]
    quote.spark = closes[-_SPARK_POINTS:]

    quote.previous_close = _previous_close(symbol, closes, quote.price)
    if quote.price is not None and quote.previous_close:
        quote.change = quote.price - quote.previous_close
        quote.change_pct = quote.change / quote.previous_close * 100.0

    return quote


def _previous_close(symbol: str, closes: list[float], price: float | None) -> float | None:
    """Gunluk degisimin baz alinacagi onceki kapanisi belirler.

    Turev sembollerde (gram altin) saglayicidan onceki kapanis gelmez; seriden
    okunur. Serideki son mum bugune aitse degisim ondan onceki mumla olculmeli,
    yoksa fark her zaman sifir cikar.
    """
    if not is_derived(symbol):
        provider_close = _provider_previous_close(symbol)
        if provider_close:
            return provider_close

    if not closes:
        return None
    last = closes[-1]
    # Son mum canli fiyata cok yakinsa bugunun mumudur; bir oncekini kullan
    if price is not None and last and abs(last - price) / last < 1e-6 and len(closes) > 1:
        return closes[-2]
    return last


def _provider_previous_close(symbol: str) -> float | None:
    try:
        import yfinance as yf

        value = getattr(yf.Ticker(symbol).fast_info, "previous_close", None)
        return float(value) if value else None
    except Exception as e:
        logger.debug("Onceki kapanis alinamadi (%s): %s", symbol, e)
        return None


def refresh_quotes() -> int:
    """Yapilandirilmis tum sembolleri ceker ve `market_quotes`'a yazar."""
    if not (settings.market_enabled and settings.ticker_enabled):
        return 0

    pairs = configured_symbols()
    stored = 0

    for position, (symbol, label) in enumerate(pairs):
        try:
            quote = fetch_quote(symbol, label)
        except Exception as e:
            logger.warning("Kotasyon alinamadi (%s): %s", symbol, e)
            continue
        if not quote.is_usable:
            logger.debug("Kotasyon bos, atlaniyor: %s", symbol)
            continue
        _store(quote, position)
        stored += 1

    # Yapilandirmadan cikarilan semboller seritte asili kalmasin
    _prune({symbol for symbol, _ in pairs})

    logger.info("Piyasa seridi guncellendi: %d/%d sembol.", stored, len(pairs))
    return stored


def _store(quote: Quote, position: int) -> None:
    with get_session() as session:
        row = session.scalar(select(MarketQuote).where(MarketQuote.symbol == quote.symbol))
        if not row:
            row = MarketQuote(symbol=quote.symbol)
            session.add(row)
        row.label = quote.label
        row.position = position
        row.price = quote.price
        row.previous_close = quote.previous_close
        row.change = quote.change
        row.change_pct = quote.change_pct
        row.spark = ",".join(f"{v:.6g}" for v in quote.spark)
        row.updated_at = datetime.now(timezone.utc)


def _prune(keep: set[str]) -> None:
    with get_session() as session:
        for row in session.scalars(select(MarketQuote)).all():
            if row.symbol not in keep:
                session.delete(row)


def load_quotes() -> list[dict]:
    """Dashboard icin kayitli kotasyonlari okur (ag cagrisi yapmaz)."""
    with get_session() as session:
        rows = session.scalars(select(MarketQuote).order_by(MarketQuote.position)).all()
        return [
            {
                "symbol": row.symbol,
                "label": row.label or display_name(row.symbol),
                "price": row.price,
                "change": row.change,
                "change_pct": row.change_pct,
                "spark": _parse_spark(row.spark),
                "updated_at": row.updated_at,
            }
            for row in rows
        ]


def _parse_spark(raw: str) -> list[float]:
    values: list[float] = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(float(part))
        except ValueError:
            continue
    return values


def describe_symbol(symbol: str) -> str:
    """Turev sembolun nasil hesaplandigini aciklar (ipucu metni icin)."""
    if not is_derived(symbol):
        return ""
    base, fx, _ = DERIVED[symbol]
    return f"{base} x {fx} uzerinden hesaplanir" if fx else f"{base} uzerinden hesaplanir"
