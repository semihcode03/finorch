"""Fiyata bagli izleme kosullarinin cikarimi.

TradeSetup analistin tarif ettigi kurulumu kaydeder; burasi ise HENUZ
gerceklesmemis, canli fiyatla takip edilebilecek tetikleyicileri cikarir:

  "3.250 uzerinde gunluk kapanis gorursem alirim"  -> break_above @ 3250
  "48.000'e geri cekilirse kademeli girerim"       -> retest @ 48000
  "hedefim 120 TL"                                 -> target @ 120
  "4 saatlikte FVG doldurulursa islem acarim"      -> structure (fiyatsiz)

Cikarilanlar `price_watches` tablosuna yazilir ve `finorch watch` her
calistiginda guncel fiyatla karsilastirilir.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from finorch.analysis.client import _to_float, chat_json, is_enabled

logger = logging.getLogger(__name__)

_SYSTEM = """Sen bir trader'in paylasimlarini okuyup TAKIP EDILEBILIR fiyat kosullarini
cikaran bir sistemsin. Metin bir tweet, thread, video transkripti veya grafik aciklamasi
olabilir. Transkript satirlari [saniye] etiketiyle gelebilir.

Amac: analistin "su olursa su yapacagim" dedigi, ileride fiyata bakarak DOGRULANABILIR
kosullari cikarmak. Gecmis yorumu, genel piyasa sohbeti ve zaten kapanmis islemler HARIC.

Her kosul icin alanlar:
- instrument: enstrumanin metinde gectigi hali (orn. "THYAO", "gram altin", "bitcoin",
  "BIST 100"). Kisaltma UYDURMA; metinde ne yaziyorsa onu yaz.
- direction: "long" (yukari/alim) | "short" (asagi/satim) | "neutral"
- trigger_type: asagidakilerden biri
    "break_above" = seviyenin UZERINE cikarsa
    "break_below" = seviyenin ALTINA inerse
    "reclaim"     = kaybedilen seviyeyi geri alirsa
    "retest"      = seviyeye geri cekilirse / test ederse
    "range"       = iki fiyat arasindaki banda girerse (trigger_price + trigger_price_2)
    "target"      = analistin verdigi FIYAT HEDEFI (kosul degil, varis noktasi)
    "structure"   = sadece formasyon kosulu var, sayisal seviye YOK
- trigger_price: kosulun sayisal seviyesi (sayi veya null). Binlik ayraci kullanma:
  "3.250 TL" -> 3250, "48 bin" -> 48000, "1,2 milyon" -> 1200000
- trigger_price_2: sadece "range" icin bandin diger ucu, yoksa null
- timeframe: "15m" | "1h" | "4h" | "1D" | "1W" gibi, yoksa bos
- structure: fiyat disi kosul, kisa (orn. "gunluk kapanis ustunde", "FVG doldurulur",
  "MSB olusur", "hacimli kirilim"). Yoksa bos.
- action: analistin kosul saglanirsa yapacagini soyledigi sey (orn. "kademeli alim",
  "stop'u yukari cekerim", "pozisyonu kapatirim"). Yoksa bos.
- entry / stop_loss: sayi veya null
- take_profit: metin (orn. "68000 / 70000" veya "2RR"), yoksa bos
- rr: risk/odul orani (sayi veya null; "2RR" -> 2)
- rationale: tek kisa gerekce cumlesi, yoksa bos
- confidence: 0..1 (analistin ifadesi ne kadar kesin? "kesinlikle alirim" yuksek,
  "belki bakariz" dusuk)
- timestamp_sec: [saniye] etiketlerinden yaklasik saniye, yoksa null
- quote: metinden kisa dogrudan alinti

KURALLAR:
- Sadece ILERIYE donuk, henuz gerceklesmemis kosullari cikar. "Dun 50'den aldim" -> CIKARMA.
- Seviye sayisi metinde yoksa trigger_price null olsun ve trigger_type "structure" olsun.
- Ayni enstrumanda birden fazla senaryo varsa (yukari kirarsa X, asagi kirarsa Y)
  her birini AYRI kayit olarak yaz.
- Bir alanin degeri yoksa BOS STRING ("") veya null kullan. "yok"/"-"/"belirtilmemis" YAZMA.
- Net bir kosul yoksa bos liste dondur. Uydurma.

Yaniti SADECE su JSON'da ver: {"watches": [...]}"""

_TRIGGER_TYPES = {
    "break_above",
    "break_below",
    "reclaim",
    "retest",
    "range",
    "target",
    "structure",
}

# Sayisal seviye zorunlu olan turler; seviye yoksa "structure"a dusurulur
_NEEDS_PRICE = {"break_above", "break_below", "reclaim", "retest", "range", "target"}

_PLACEHOLDERS = {"", "null", "none", "nil", "n/a", "na", "-", "--", "yok", "belirtilmemis"}


def _clean(raw: object, limit: int | None = None) -> str:
    value = str(raw).strip() if raw is not None else ""
    if value.lower() in _PLACEHOLDERS:
        return ""
    return value[:limit] if limit else value


@dataclass
class WatchExtraction:
    watches: list[dict] = field(default_factory=list)


def extract_watches(text: str, focus: str = "") -> WatchExtraction:
    """Metinden takip edilebilir fiyat kosullarini cikarir."""
    text = (text or "").strip()
    if len(text) < 20 or not is_enabled():
        return WatchExtraction()

    user = f"[Analistin odagi: {focus}]\n\n{text}" if focus else text
    try:
        data = chat_json(_SYSTEM, user)
    except Exception as e:
        logger.error("Fiyat kosulu LLM cagrisi basarisiz: %s", e)
        return WatchExtraction()

    watches: list[dict] = []
    for w in data.get("watches", []) or []:
        instrument = _clean(w.get("instrument"), 100)
        if not instrument:
            continue

        direction = _clean(w.get("direction")).lower()
        if direction not in {"long", "short", "neutral"}:
            direction = "neutral"

        trigger_type = _clean(w.get("trigger_type")).lower()
        if trigger_type not in _TRIGGER_TYPES:
            trigger_type = "structure"

        trigger_price = _to_float(w.get("trigger_price"))
        trigger_price_2 = _to_float(w.get("trigger_price_2"))
        structure = _clean(w.get("structure"))

        # Seviyesiz bir "kirilim" takip edilemez; formasyon kosuluna dusur
        if trigger_type in _NEEDS_PRICE and trigger_price is None:
            trigger_type = "structure"
        if trigger_type == "range" and trigger_price_2 is None:
            trigger_type = "retest"

        # Ne sayisal seviye ne de formasyon kosulu varsa izlenecek bir sey yok
        if trigger_type == "structure" and not structure:
            continue

        watches.append(
            {
                "instrument": instrument,
                "direction": direction,
                "trigger_type": trigger_type,
                "trigger_price": trigger_price,
                "trigger_price_2": trigger_price_2,
                "timeframe": _clean(w.get("timeframe"), 30),
                "structure": structure,
                "action": _clean(w.get("action")),
                "entry": _to_float(w.get("entry")),
                "stop_loss": _to_float(w.get("stop_loss")),
                "take_profit": _clean(w.get("take_profit"), 200),
                "rr": _to_float(w.get("rr")),
                "rationale": _clean(w.get("rationale")),
                "confidence": float(w.get("confidence", 0.0) or 0.0),
                "source_timestamp_sec": _to_float(w.get("timestamp_sec")),
                "quote": _clean(w.get("quote")),
            }
        )

    return WatchExtraction(watches=watches)
