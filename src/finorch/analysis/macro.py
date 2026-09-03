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
gelebilir (orn. "[125] ..."). Iki tur bilgi cikar.

BICIM KURALLARI (her iki tur icin gecerli):
- Keskin ve kisa yaz. Giris cumlesi, yorum veya kendi degerlendirmeni ekleme.
- Kosul ve sonuc alanlari en fazla 12 kelime olsun ve tek bir olguyu anlatsin.
- Metinde kac tane kural/projeksiyon varsa HEPSINI cikar; sayiyi kendin kisitlama.
  Kisa olmasi gereken sey her bir maddenin ifadesi, listenin uzunlugu degil.
- Etkilenen alan belliyse sektoru doldur (orn. "Bankacilik", "Havacilik", "Perakende",
  "Sanayi"). Belli degilse bos birak.
- Metinde somut hisse/enstruman kodu geciyorsa virgulle ayirarak yaz (orn. "GARAN, AKBNK").
  Kod soylenmemisse bos birak; kod UYDURMA.
- Bir alanin degeri yoksa BOS STRING ("") kullan. "NULL", "null", "-", "yok" YAZMA.
- Somut bir kod/endeks yoksa varlik alani bos kalabilir; ama o zaman sektor dolu olmali
  (orn. "faiz duserse bankacilik hisseleri yukselir" -> sektor="Bankacilik", varlik="").

1) rules: analistin ifade ettigi NEDENSEL kurallar.
   Ornek: condition="faiz duser", effect_asset="XU100", effect_sector="Bankacilik",
   effect_direction="up"  ->  "faiz duserse bankacilik hisseleri yukselir".
   Alanlar: condition (tetikleyici olay/kosul), effect_asset (varlik/endeks kodu, orn.
   XAUUSD/BTC/DXY/XU100), effect_sector, effect_tickers, effect_direction
   ("up"|"down"|"neutral"), rule_class, rationale (tek kisa gerekce cumlesi; yoksa bos),
   confidence (0..1), timestamp_sec (bu ifadenin gectigi yaklasik saniye, [saniye]
   etiketlerinden; yoksa null), quote (metinden kisa dogrudan alinti).

   rule_class iki degerden biri olmali:
     "key"  = zamansiz/yapisal mekanizma; tarih belirtmeden her zaman gecerli sayilan
              neden-sonuc iliskisi ("faiz duserse bankacilik yukselir").
     "live" = su ana veya yakin doneme ait, tarihli guncel gorus/beklenti
              ("bu ceyrek faiz inecek").

2) projections: analistin GELECEGE yonelik projeksiyonlari.
   Her projeksiyon "BU OLURSA -> SU OLUR" seklinde tek satirlik kesin bir ifade olmali:
     conditions = tetikleyici taraf ("BU OLURSA")
     scenario   = sonuc taraf ("SU OLUR")
   Kosul soylenmemisse conditions bos kalir; scenario tek basina net bir beklenti olur.
   Alanlar: asset, sector, tickers, horizon (orn. "1 hafta"/"3 ay"/"2026 sonu"),
   conditions, scenario, direction ("up"|"down"|"neutral"), price_target (sayi veya null),
   confidence (0..1), timestamp_sec (yaklasik saniye veya null), quote (kisa alinti).

Sadece metinde ACIKCA soylenenleri cikar, yorum katma. Net bilgi yoksa ilgili listeyi bos birak.
Yaniti SADECE su JSON'da ver: {"rules": [...], "projections": [...]}"""

# Sema sinirlari (db.models): asiri uzun LLM ciktisi INSERT'i patlatmasin
_SECTOR_MAX = 150
_TICKERS_MAX = 300

# LLM bazen JSON null yerine bunlari duz metin olarak yaziyor; bos kabul edilir.
_PLACEHOLDERS = {"", "null", "none", "nil", "n/a", "na", "-", "--", "yok", "belirtilmemis"}


def _clean_text(raw: object, limit: int | None = None) -> str:
    """Metni kirpar; "null"/"yok" gibi yer tutucu degerleri bos stringe cevirir."""
    value = str(raw).strip() if raw is not None else ""
    if value.lower() in _PLACEHOLDERS:
        return ""
    return value[:limit] if limit else value


def _clean_tickers(raw: object) -> str:
    """LLM'den gelen ticker listesini "GARAN, AKBNK" formatina normalize eder."""
    if isinstance(raw, (list, tuple)):
        parts = [str(x) for x in raw]
    else:
        parts = _clean_text(raw).replace("/", ",").replace(";", ",").split(",")

    seen: list[str] = []
    for p in parts:
        code = _clean_text(p).upper().lstrip("$#")
        if code and code not in seen:
            seen.append(code)
    return ", ".join(seen)[:_TICKERS_MAX]


def _clean_sector(raw: object) -> str:
    return _clean_text(raw, _SECTOR_MAX)


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
        asset = _clean_text(r.get("effect_asset"), 100).upper()
        sector = _clean_sector(r.get("effect_sector"))
        direction = _clean_text(r.get("effect_direction")).lower()
        cond = _clean_text(r.get("condition"))
        # Etki ya somut bir varliga ya da bir sektore bagli olmali; ikisi de yoksa
        # kural hedefsiz kalir ve ise yaramaz.
        if not cond or not (asset or sector) or direction not in {"up", "down", "neutral"}:
            continue
        rule_class = _clean_text(r.get("rule_class")).lower()
        if rule_class not in {"key", "live"}:
            rule_class = ""
        rules.append(
            {
                "condition": cond,
                "effect_asset": asset,
                "effect_sector": sector,
                "effect_tickers": _clean_tickers(r.get("effect_tickers")),
                "effect_direction": direction,
                "rule_class": rule_class,
                "rationale": _clean_text(r.get("rationale")),
                "confidence": float(r.get("confidence", 0.0) or 0.0),
                "source_timestamp_sec": _to_float(r.get("timestamp_sec")),
                "quote": _clean_text(r.get("quote")),
            }
        )

    projections = []
    for p in data.get("projections", []) or []:
        asset = _clean_text(p.get("asset"), 100).upper()
        sector = _clean_sector(p.get("sector"))
        scenario = _clean_text(p.get("scenario"))
        # Sonuc cumlesi ve bir hedef (varlik veya sektor) olmadan projeksiyon anlamsiz
        if not scenario or not (asset or sector):
            continue
        direction = _clean_text(p.get("direction")).lower()
        if direction not in {"up", "down", "neutral"}:
            direction = ""
        projections.append(
            {
                "asset": asset,
                "sector": sector,
                "tickers": _clean_tickers(p.get("tickers")),
                "horizon": _clean_text(p.get("horizon"), 50),
                "scenario": scenario,
                "direction": direction,
                "price_target": _to_float(p.get("price_target")),
                "conditions": _clean_text(p.get("conditions")),
                "confidence": float(p.get("confidence", 0.0) or 0.0),
                "source_timestamp_sec": _to_float(p.get("timestamp_sec")),
                "quote": _clean_text(p.get("quote")),
            }
        )

    return MacroExtraction(rules=rules, projections=projections)
