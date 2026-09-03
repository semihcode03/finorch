"""Canli fiyat ve gecmis OHLC verisi (Yahoo Finance / yfinance).

Iki katmanli onbellek kullanilir:
  - surec ici TTL onbellegi: ayni dongude ayni sembol tekrar cekilmez
  - market_snapshots tablosu: gecmis mumlar kalici saklanir (grafik cizimi icin)

Ag erisimi yoksa veya sembol gecersizse fonksiyonlar None/bos liste doner;
cagiran taraf bunu "fiyat bilinmiyor" olarak ele almalidir.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from finorch.config import settings
from finorch.db import MarketSnapshot, get_session
from finorch.market.symbols import DERIVED, is_derived

logger = logging.getLogger(__name__)

# {sembol: (zaman_damgasi, fiyat)}
_price_cache: dict[str, tuple[float, float | None]] = {}


def _cache_get(symbol: str) -> float | None | object:
    """Onbellekteki fiyati doner. Kayit yoksa `_MISS` sentinel'i doner."""
    hit = _price_cache.get(symbol)
    if hit and (time.monotonic() - hit[0]) < settings.market_cache_ttl_sec:
        return hit[1]
    return _MISS


_MISS = object()


def clear_cache() -> None:
    _price_cache.clear()


def get_last_price(symbol: str) -> float | None:
    """Sembolun son fiyatini doner. Turev semboller formulle hesaplanir."""
    if not symbol or not settings.market_enabled:
        return None

    cached = _cache_get(symbol)
    if cached is not _MISS:
        return cached  # type: ignore[return-value]

    price = _compute_derived(symbol) if is_derived(symbol) else _fetch_last(symbol)
    _price_cache[symbol] = (time.monotonic(), price)
    return price


def _compute_derived(symbol: str) -> float | None:
    """Turev sembolu (orn. gram altin) baz fiyat x kur x carpan ile hesaplar."""
    base_sym, fx_sym, factor = DERIVED[symbol]
    base = get_last_price(base_sym)
    if base is None:
        return None
    fx = 1.0
    if fx_sym:
        rate = get_last_price(fx_sym)
        if rate is None:
            return None
        fx = rate
    return base * fx * factor


def _fetch_last(symbol: str) -> float | None:
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        # fast_info agir "info" cagrisini yapmadan son fiyati verir
        price = getattr(ticker.fast_info, "last_price", None)
        if price:
            return float(price)

        # fast_info bos donduyse son kapanisa dus
        hist = ticker.history(period="5d", interval="1d")
        if not hist.empty:
            return float(hist["Close"].dropna().iloc[-1])
    except Exception as e:
        logger.warning("Fiyat alinamadi (%s): %s", symbol, e)
    return None


def get_history(
    symbol: str,
    period: str = "6mo",
    interval: str = "1d",
    store: bool = True,
    cached_only: bool = False,
) -> list[dict]:
    """Gecmis mumlari doner: [{ts, open, high, low, close, volume}, ...].

    Once market_snapshots'a bakilir; yeterince guncel veri varsa ag'a cikilmaz.
    `cached_only=True` iken hic ag cagrisi yapilmaz ve onbellek bossa bos liste
    doner. Dashboard bunu kullanir: bir web istegi asla yfinance'i beklemesin;
    veriyi `finorch watch` onceden doldurur.
    """
    if not symbol or not settings.market_enabled:
        return []

    cached = _history_from_db(symbol, period)
    # Dashboard elindekiyle yetinir: eldeki veri bayat olsa bile grafik cizmek
    # hic cizmemekten iyidir, tazelemeyi `finorch watch` yapar.
    if cached_only:
        return cached
    if cached and _is_fresh(symbol):
        return cached

    rows = _fetch_history(symbol, period, interval)
    if rows and store:
        _store_history(symbol, rows)
    return rows or cached


def _is_fresh(symbol: str) -> bool:
    """Veri yeterince yakin zamanda cekildi mi?

    Tazelik SON MUMUN tarihine gore olculemez: borsalar hafta sonu ve tatilde
    kapalidir, BIST'te 3 gun once kapanmis bir mum tamamen normaldir. Olcut
    bizim en son ne zaman cektigimizdir.
    """
    with get_session() as session:
        last_fetch = session.scalar(
            select(func.max(MarketSnapshot.created_at)).where(MarketSnapshot.symbol == symbol)
        )
    if not last_fetch:
        return False
    age = datetime.now(timezone.utc) - _as_utc(last_fetch)
    return age < timedelta(hours=settings.market_history_ttl_hours)


def _fetch_history(symbol: str, period: str, interval: str) -> list[dict]:
    if is_derived(symbol):
        return _derived_history(symbol, period, interval)
    try:
        import yfinance as yf

        hist = yf.Ticker(symbol).history(period=period, interval=interval)
        if hist.empty:
            return []
        rows: list[dict] = []
        for ts, row in hist.iterrows():
            rows.append(
                {
                    "ts": _as_utc(ts.to_pydatetime()),
                    "open": _num(row.get("Open")),
                    "high": _num(row.get("High")),
                    "low": _num(row.get("Low")),
                    "close": _num(row.get("Close")),
                    "volume": _num(row.get("Volume")),
                }
            )
        return [r for r in rows if r["close"] is not None]
    except Exception as e:
        logger.warning("Gecmis veri alinamadi (%s): %s", symbol, e)
        return []


def _derived_history(symbol: str, period: str, interval: str) -> list[dict]:
    """Turev sembolun gecmisini baz ve kur serilerini tarihe gore carparak uretir."""
    base_sym, fx_sym, factor = DERIVED[symbol]
    base = {r["ts"].date(): r for r in _fetch_history(base_sym, period, interval)}
    if not base:
        return []

    fx: dict = {}
    if fx_sym:
        fx = {r["ts"].date(): r for r in _fetch_history(fx_sym, period, interval)}
        if not fx:
            return []

    rows: list[dict] = []
    last_rate: float | None = None
    for day in sorted(base):
        b = base[day]
        if fx_sym:
            # Iki serinin tatil takvimi birebir ortusmez. Kur o gun yoksa
            # bilinen son kur tasinir; 1.0'a dusulemez, cunku bu cevrimi
            # tamamen atlayip fiyati yanlis para biriminde birakir.
            rate = fx.get(day, {}).get("close") or last_rate
            if rate is None:
                continue
            last_rate = rate
        else:
            rate = 1.0
        rows.append(
            {
                "ts": b["ts"],
                "open": _scale(b["open"], rate, factor),
                "high": _scale(b["high"], rate, factor),
                "low": _scale(b["low"], rate, factor),
                "close": _scale(b["close"], rate, factor),
                "volume": None,
            }
        )
    return [r for r in rows if r["close"] is not None]


def _scale(value: float | None, rate: float, factor: float) -> float | None:
    return None if value is None else value * rate * factor


def _period_days(period: str) -> int:
    return {
        "5d": 5, "1mo": 31, "3mo": 92, "6mo": 183,
        "1y": 365, "2y": 730, "5y": 1825,
    }.get(period, 183)


def _history_from_db(symbol: str, period: str) -> list[dict]:
    """Istenen donemdeki kayitli mumlari doner."""
    since = datetime.now(timezone.utc) - timedelta(days=_period_days(period))
    with get_session() as session:
        rows = session.scalars(
            select(MarketSnapshot)
            .where(MarketSnapshot.symbol == symbol, MarketSnapshot.ts >= since)
            .order_by(MarketSnapshot.ts)
        ).all()
        return [
            {
                "ts": _as_utc(r.ts),
                "open": r.open,
                "high": r.high,
                "low": r.low,
                "close": r.close,
                "volume": r.volume,
            }
            for r in rows
        ]


def _store_history(symbol: str, rows: list[dict]) -> None:
    """Mumlari kaydeder; ayni (sembol, zaman) varsa gunceller."""
    payload = [
        {
            "symbol": symbol,
            "ts": r["ts"],
            "open": r["open"],
            "high": r["high"],
            "low": r["low"],
            "close": r["close"],
            "volume": r["volume"],
        }
        for r in rows
    ]
    if not payload:
        return
    try:
        with get_session() as session:
            stmt = pg_insert(MarketSnapshot).values(payload)
            session.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_snapshot_symbol_ts",
                    set_={
                        "open": stmt.excluded.open,
                        "high": stmt.excluded.high,
                        "low": stmt.excluded.low,
                        "close": stmt.excluded.close,
                        "volume": stmt.excluded.volume,
                    },
                )
            )
    except Exception as e:
        logger.warning("Piyasa verisi kaydedilemedi (%s): %s", symbol, e)


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _num(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return None if result != result else result  # NaN elenir
