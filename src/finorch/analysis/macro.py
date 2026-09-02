"""Makro/anlati hesaplari icin cikarim.

Iki tur bilgi cikarilir:
  - rules       : nedensel kurallar ("savas cikarsa altin yukselir")
  - projections : gelecek projeksiyonlari/senaryolari (varlik, ufuk, yon, hedef)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from finorch.analysis.client import _to_float, chat_json, is_enabled

logger = logging.getLogger(__name__)

_SYSTEM = """Sen makro/anlati odakli finansal icerigi analiz ediyorsun. Sana bir analistin
video transkripti, tweet'i veya yazisi verilecek. Transkript satirlari [saniye] etiketiyle
gelebilir (orn. "[125] ..."). Iki tur bilgi cikar:

1) rules: analistin ifade ettigi NEDENSEL kurallar/heuristikler.
   Ornek: "savas/jeopolitik gerilim -> altin yukselir".
   Alanlar: condition (tetikleyici olay/kosul), effect_asset (varlik, orn. XAUUSD/BTC/DXY),
   effect_direction ("up"|"down"|"neutral"), rationale (kisa gerekce), confidence (0..1),
   timestamp_sec (bu ifadenin gectigi yaklasik saniye, [saniye] etiketlerinden; yoksa null),
   quote (metinden kisa dogrudan alinti).

2) projections: analistin GELECEGE yonelik projeksiyonlari/senaryolari.
   Alanlar: asset, horizon (orn. "1 hafta"/"3 ay"/"2026 sonu"), scenario (ozet),
   direction ("up"|"down"|"neutral"), price_target (sayi veya null),
   conditions (varsa on kosullar), confidence (0..1),
   timestamp_sec (yaklasik saniye veya null), quote (kisa alinti).

Sadece metinde ACIKCA soylenenleri cikar, yorum katma. Net bilgi yoksa ilgili listeyi bos birak.
Yaniti SADECE su JSON'da ver: {"rules": [...], "projections": [...]}"""


@dataclass
class MacroExtraction:
    rules: list[dict] = field(default_factory=list)
    projections: list[dict] = field(default_factory=list)


def extract_macro(text: str, focus: str = "") -> MacroExtraction:
    text = (text or "").strip()
    if len(text) < 20 or not is_enabled():
        return MacroExtraction()

    user = f"[Analistin odagi: {focus}]\n\n{text}" if focus else text
    try:
        data = chat_json(_SYSTEM, user)
    except Exception as e:
        logger.error("Makro LLM cagrisi basarisiz: %s", e)
        return MacroExtraction()

    rules = []
    for r in data.get("rules", []) or []:
        asset = str(r.get("effect_asset", "")).strip()
        direction = str(r.get("effect_direction", "")).strip().lower()
        cond = str(r.get("condition", "")).strip()
        if not asset or not cond or direction not in {"up", "down", "neutral"}:
            continue
        rules.append(
            {
                "condition": cond,
                "effect_asset": asset.upper(),
                "effect_direction": direction,
                "rationale": str(r.get("rationale", "")).strip(),
                "confidence": float(r.get("confidence", 0.0) or 0.0),
                "source_timestamp_sec": _to_float(r.get("timestamp_sec")),
                "quote": str(r.get("quote", "")).strip(),
            }
        )

    projections = []
    for p in data.get("projections", []) or []:
        asset = str(p.get("asset", "")).strip()
        if not asset:
            continue
        direction = str(p.get("direction", "")).strip().lower()
        if direction not in {"up", "down", "neutral", ""}:
            direction = ""
        projections.append(
            {
                "asset": asset.upper(),
                "horizon": str(p.get("horizon", "")).strip(),
                "scenario": str(p.get("scenario", "")).strip(),
                "direction": direction,
                "price_target": _to_float(p.get("price_target")),
                "conditions": str(p.get("conditions", "")).strip(),
                "confidence": float(p.get("confidence", 0.0) or 0.0),
                "source_timestamp_sec": _to_float(p.get("timestamp_sec")),
                "quote": str(p.get("quote", "")).strip(),
            }
        )

    return MacroExtraction(rules=rules, projections=projections)
