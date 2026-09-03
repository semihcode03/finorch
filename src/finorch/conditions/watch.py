"""Fiyat kosullarinin canli veriyle degerlendirilmesi.

Her `price_watches` kaydi bir tetikleyicidir: "fiyat X'in uzerine cikarsa".
Bu modul guncel fiyati alir, kosulun saglanip saglanmadigina bakar ve iki sey uretir:

  - **progress**: kosula ne kadar yaklasildigi (0..1). Dashboard'daki cubugu bu doldurur.
    Tetik fiyatina `WATCH_BAND_PCT` (varsayilan %10) uzaklikta 0, tam ustunde 1 olur.
  - **uyari**: kosul saglandiginda tek seferlik Telegram bildirimi.

Fiyatsiz (trigger_type="structure") kayitlar otomatik takip edilemez; grafik
uzerinden dogrulama gerektirdikleri icin dashboard'da ayri listelenir.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from finorch.config import settings
from finorch.db.models import Alert, Analyst, PriceWatch
from finorch.market import get_last_price, resolve_symbol
from finorch.market.symbols import display_name

logger = logging.getLogger(__name__)

# Fiyata bakarak otomatik dogrulanabilen tetik turleri
AUTOMATABLE = {"break_above", "break_below", "reclaim", "retest", "range", "target"}

# Fiyatin tetigi hangi yonden gecmesi gerektigi
_UPWARD = {"break_above", "reclaim"}
_DOWNWARD = {"break_below"}


def evaluate_price_watch(session: Session, watch: PriceWatch) -> Alert | None:
    """Tek bir izlemeyi guncel fiyatla karsilastirir; durumu ve skorunu gunceller.

    Kosul saglandiysa uyari uretip dondurur, aksi halde None.
    """
    now = datetime.now(timezone.utc)

    if not watch.symbol:
        watch.symbol = resolve_symbol(watch.instrument)
    if not watch.symbol:
        # Enstruman bir piyasa sembolune baglanamadi; elle eslestirme gerekir
        watch.status = "unresolved"
        watch.last_checked_at = now
        return None

    if watch.trigger_type not in AUTOMATABLE or watch.trigger_price is None:
        watch.last_checked_at = now
        return None

    if watch.expires_at and now > _as_utc(watch.expires_at):
        watch.status = "expired"
        watch.last_checked_at = now
        return None

    price = get_last_price(watch.symbol)
    if price is None:
        watch.last_checked_at = now
        return None

    watch.last_price = price
    watch.last_checked_at = now
    watch.distance_pct = _distance_pct(price, watch.trigger_price)
    watch.progress_score = _progress(price, watch)

    if not _is_triggered(price, watch):
        return None

    watch.status = "triggered"
    watch.triggered_at = now
    watch.progress_score = 1.0
    return _make_alert(session, watch, price)


def evaluate_all(session: Session, limit: int | None = None) -> list[Alert]:
    """Takipteki tum izlemeleri degerlendirir ve uretilen uyarilari dondurur."""
    stmt = (
        select(PriceWatch)
        .where(PriceWatch.status.in_(("watching", "unresolved")))
        .order_by(PriceWatch.created_at.desc())
    )
    if limit:
        stmt = stmt.limit(limit)

    alerts: list[Alert] = []
    for watch in session.scalars(stmt).all():
        try:
            alert = evaluate_price_watch(session, watch)
        except Exception as e:
            logger.error("Izleme degerlendirilemedi (id=%s): %s", watch.id, e)
            continue
        if alert:
            alerts.append(alert)
    return alerts


def expire_stale(session: Session) -> int:
    """Suresi dolmus izlemeleri "expired" yapar ve sayisini dondurur."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.watch_expire_days)
    stale = session.scalars(
        select(PriceWatch).where(
            PriceWatch.status == "watching", PriceWatch.created_at < cutoff
        )
    ).all()
    for watch in stale:
        watch.status = "expired"
    return len(stale)


def _is_triggered(price: float, watch: PriceWatch) -> bool:
    level = watch.trigger_price
    ttype = watch.trigger_type

    if ttype in _UPWARD:
        return price >= level
    if ttype in _DOWNWARD:
        return price <= level
    if ttype == "range":
        low, high = sorted((level, watch.trigger_price_2 or level))
        return low <= price <= high
    if ttype == "target":
        # Hedef yonu belliyse o yonden varis, degilse iki yonlu yakinlik
        if watch.direction == "long":
            return price >= level
        if watch.direction == "short":
            return price <= level
        return abs(price - level) / level <= 0.005
    if ttype == "retest":
        # Seviyeye geri donus: yonden bagimsiz, %0.5 bant icine girmesi yeterli
        return abs(price - level) / level <= 0.005
    return False


def _progress(price: float, watch: PriceWatch) -> float:
    """Kosula yakinligi 0..1 arasinda skorlar.

    Tetik fiyatina uzaklik `watch_band_pct` bandinin disindaysa 0, tam uzerindeyse 1.
    Bant araligi tetik seviyesinin yuzdesi olarak olculur ki farkli fiyat
    buyukluklerindeki enstrumanlar (BTC ~100.000 vs THYAO ~300) karsilastirilabilsin.
    """
    level = watch.trigger_price
    if not level:
        return 0.0

    # Kosul zaten saglanmissa skor tam olur. Yoksa fiyat tetigi asip uzaklastikca
    # skor geri duserdi ("100'u gecerse al" kosulunda fiyat 105 iken %50 gibi).
    if _is_triggered(price, watch):
        return 1.0

    if watch.trigger_type == "range":
        low, high = sorted((level, watch.trigger_price_2 or level))
        gap = low - price if price < low else price - high
        reference = (low + high) / 2
    else:
        gap = abs(price - level)
        reference = level

    band = abs(reference) * (settings.watch_band_pct / 100.0)
    if band <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - gap / band))


def _distance_pct(price: float, level: float) -> float | None:
    """Fiyatin tetige yuzde uzakligi. Pozitif = tetik hala yukarida."""
    if not price:
        return None
    return (level - price) / price * 100.0


def _make_alert(session: Session, watch: PriceWatch, price: float) -> Alert | None:
    key = f"watch:{watch.id}"
    if session.scalar(select(Alert).where(Alert.dedup_key == key)):
        return None

    analyst = session.get(Analyst, watch.analyst_id) if watch.analyst_id else None
    name = analyst.name if analyst else "Bilinmeyen analist"
    label = display_name(watch.symbol)

    bits = [
        f"[TETIKLENDI] {name} - {label}",
        f"{_trigger_text(watch)} (guncel {price:g})",
    ]
    if watch.action:
        bits.append(f"Plan: {watch.action}")
    if watch.entry is not None:
        bits.append(f"giris {watch.entry:g}")
    if watch.stop_loss is not None:
        bits.append(f"SL {watch.stop_loss:g}")
    if watch.take_profit:
        bits.append(f"TP {watch.take_profit}")
    if watch.rationale:
        bits.append(watch.rationale)

    alert = Alert(
        rule="price_watch",
        asset=label,
        message=" | ".join(bits),
        dedup_key=key,
    )
    session.add(alert)
    session.flush()
    return alert


def _trigger_text(watch: PriceWatch) -> str:
    """Tetik kosulunu okunabilir tek satira cevirir."""
    level = watch.trigger_price
    if level is None:
        return watch.structure or "kosul"

    phrases = {
        "break_above": f"{level:g} uzerine cikti",
        "break_below": f"{level:g} altina indi",
        "reclaim": f"{level:g} seviyesini geri aldi",
        "retest": f"{level:g} seviyesini test etti",
        "target": f"{level:g} hedefine ulasti",
    }
    if watch.trigger_type == "range":
        low, high = sorted((level, watch.trigger_price_2 or level))
        return f"{low:g} - {high:g} bandina girdi"
    text = phrases.get(watch.trigger_type, f"{level:g} kosulu saglandi")
    return f"{text} [{watch.timeframe}]" if watch.timeframe else text


def _as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
