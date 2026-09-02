"""Teknik analiz hesaplari icin cikarim.

Islem kurulumlari cikarilir: enstruman, yon, zaman dilimi, kurulum kosullari
(orn. FVG + MSB), entry, stop, take-profit, RR. Her kurulum kendi icinde degerlendirilir.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from finorch.analysis.client import _to_float, chat_json, is_enabled

logger = logging.getLogger(__name__)

_SYSTEM = """Sen teknik analiz (SMC/ICT dahil) odakli finansal icerigi analiz ediyorsun.
Sana bir analistin video transkripti, tweet'i veya yazisi verilecek. Metinde gecen NET
islem kurulumlarini cikar.

Her setup icin alanlar:
- instrument: enstruman (orn. BTCUSDT, ETHUSDT, XU100, THYAO, XAUUSD)
- direction: "long" | "short"
- timeframe: zaman dilimi (orn. 15m, 1h, 4h, 1D) veya bos
- setup_conditions: kurulum kosullari, kisa (orn. "FVG + MSB", "OB retest + likidite alimi")
- entry: giris fiyati (sayi veya null)
- stop_loss: stop fiyati (sayi veya null)
- take_profit: hedef(ler), metin (orn. "2RR" veya "68000 / 70000")
- rr: risk/reward orani (sayi veya null; "2RR" -> 2)
- rationale: kisa gerekce
- confidence: 0..1
- timestamp_sec: bu kurulumun gectigi yaklasik saniye ([saniye] etiketlerinden; yoksa null)
- quote: metinden kisa dogrudan alinti

Transkript satirlari [saniye] etiketiyle gelebilir (orn. "[212] ...").
Sadece ACIK kurulumlari cikar. Net kurulum yoksa bos liste dondur.
Yaniti SADECE su JSON'da ver: {"setups": [...]}"""


@dataclass
class TechnicalExtraction:
    setups: list[dict] = field(default_factory=list)


def extract_setups(text: str, focus: str = "") -> TechnicalExtraction:
    text = (text or "").strip()
    if len(text) < 20 or not is_enabled():
        return TechnicalExtraction()

    user = f"[Analistin odagi: {focus}]\n\n{text}" if focus else text
    try:
        data = chat_json(_SYSTEM, user)
    except Exception as e:
        logger.error("Teknik LLM cagrisi basarisiz: %s", e)
        return TechnicalExtraction()

    setups = []
    for s in data.get("setups", []) or []:
        instrument = str(s.get("instrument", "")).strip()
        direction = str(s.get("direction", "")).strip().lower()
        if not instrument or direction not in {"long", "short"}:
            continue
        setups.append(
            {
                "instrument": instrument.upper(),
                "direction": direction,
                "timeframe": str(s.get("timeframe", "")).strip(),
                "setup_conditions": str(s.get("setup_conditions", "")).strip(),
                "entry": _to_float(s.get("entry")),
                "stop_loss": _to_float(s.get("stop_loss")),
                "take_profit": str(s.get("take_profit", "")).strip(),
                "rr": _to_float(s.get("rr")),
                "rationale": str(s.get("rationale", "")).strip(),
                "confidence": float(s.get("confidence", 0.0) or 0.0),
                "source_timestamp_sec": _to_float(s.get("timestamp_sec")),
                "quote": str(s.get("quote", "")).strip(),
            }
        )
    return TechnicalExtraction(setups=setups)
