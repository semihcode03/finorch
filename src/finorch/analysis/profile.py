"""Analistin "nasil dusundugunu" cikaran profil analizi.

Tek tek cikarimlar (kural, projeksiyon, kurulum) analistin ne DEDIGINI kaydeder.
Bu modul bir ust katmandir: bircok icerigi birlikte okuyup hesabin YONTEMINI
modeller. Hangi ekolu kullaniyor, hangi enstrumanlarda calisiyor, seviye mi
veriyor yoksa yon mu soyluyor, riski nasil yonetiyor?

Cikti `analyst_profiles` tablosuna yazilir ve dashboard'da analistin ust kartinda
gosterilir. Yeni icerik geldikce yenilenir.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from finorch.analysis.client import chat_json, is_enabled

logger = logging.getLogger(__name__)

_SYSTEM = """Sen bir finans analistinin paylasimlarini okuyup ONUN YONTEMINI cikaran bir
sistemsin. Sana ayni hesaba ait birden fazla gonderi/transkript ozeti verilecek.

Tek tek tahminleri degil, hesabin GENEL MANTIGINI tarif et. Soru sudur:
"Bu kisi piyasaya nasil bakiyor ve karar verirken neye dayaniyor?"

Alanlar:
- summary: 2-3 cumlede hesabin genel mantigi. Bu kisi neye bakar, nasil karar verir?
- methodology: kullandigi yontem/ekol. Ornekler: "SMC/ICT (likidite, FVG, order block)",
  "klasik teknik analiz (destek/direnc, trend)", "Elliott dalga", "temel analiz/bilanco",
  "makro-ekonomik anlati", "on-chain veri". Birden fazlaysa virgulle ayir.
- instruments: sik islem yaptigi/yorumladigi enstrumanlar, virgulle (orn. "BTC, ETH, XU100")
- timeframes: kullandigi zaman dilimleri, virgulle (orn. "4h, 1D") veya bos
- typical_setups: tekrar eden tipik kurulumlari kisa madde madde tek satirda
- risk_style: riski nasil yonetiyor? (stop kullaniyor mu, kademeli mi giriyor,
  kaldirac kullaniyor mu, pozisyon boyutundan bahsediyor mu)
- signal_style: SADECE su ucunden biri:
    "hedefli"  = net fiyat hedefi/seviye verir
    "kosullu"  = "su seviye kirilirsa girerim" der, kosula baglar
    "yorumcu"  = yon/gorus belirtir ama somut seviye vermez
- strengths: bu hesabin takip edilmeye deger yani, tek cumle
- cautions: dikkat edilmesi gerekenler (belirsiz ifadeler, seviye vermemesi,
  asiri iddiali dil, reklam/promosyon icerigi), tek cumle

KURALLAR:
- Sadece verilen metinlerden cikar; hesap hakkinda disaridan bilgi ekleme.
- Emin olmadigin alani BOS STRING birak. Uydurma.
- Turkce yaz, kisa ve net ol. Ovgu/elestiri degil, tarif yaz.

Yaniti SADECE su JSON'da ver:
{"summary":"","methodology":"","instruments":"","timeframes":"","typical_setups":"",
 "risk_style":"","signal_style":"","strengths":"","cautions":""}"""

_SIGNAL_STYLES = {"hedefli", "kosullu", "yorumcu"}

# Sema sinirlari (db.models.AnalystProfile)
_INSTRUMENTS_MAX = 400
_TIMEFRAMES_MAX = 200
_SIGNAL_STYLE_MAX = 40


@dataclass
class ProfileResult:
    summary: str = ""
    methodology: str = ""
    instruments: str = ""
    timeframes: str = ""
    typical_setups: str = ""
    risk_style: str = ""
    signal_style: str = ""
    strengths: str = ""
    cautions: str = ""

    @property
    def is_empty(self) -> bool:
        return not (self.summary or self.methodology)

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def build_profile(samples: list[str], analyst_name: str = "", focus: str = "") -> ProfileResult:
    """Analistin icerik orneklerinden yontem profilini cikarir.

    `samples` her biri bir icerige ait metin/ozet olan liste. Tek tek cok uzun
    olabilecekleri icin her ornek kirpilir; amac uslup ve yontemi gormek, tum
    icerigi okumak degil.
    """
    usable = [s.strip() for s in samples if s and s.strip()]
    if not usable or not is_enabled():
        return ProfileResult()

    header = f"Analist: {analyst_name}\n" if analyst_name else ""
    if focus:
        header += f"Bildirilen odagi: {focus}\n"

    blocks = [f"--- Icerik {i} ---\n{s[:1500]}" for i, s in enumerate(usable, 1)]
    user = f"{header}\n" + "\n\n".join(blocks)

    try:
        data = chat_json(_SYSTEM, user, max_chars=24000)
    except Exception as e:
        logger.error("Profil LLM cagrisi basarisiz: %s", e)
        return ProfileResult()

    signal_style = str(data.get("signal_style", "")).strip().lower()
    if signal_style not in _SIGNAL_STYLES:
        signal_style = ""

    return ProfileResult(
        summary=str(data.get("summary", "")).strip(),
        methodology=str(data.get("methodology", "")).strip(),
        instruments=str(data.get("instruments", "")).strip()[:_INSTRUMENTS_MAX],
        timeframes=str(data.get("timeframes", "")).strip()[:_TIMEFRAMES_MAX],
        typical_setups=str(data.get("typical_setups", "")).strip(),
        risk_style=str(data.get("risk_style", "")).strip(),
        signal_style=signal_style[:_SIGNAL_STYLE_MAX],
        strengths=str(data.get("strengths", "")).strip(),
        cautions=str(data.get("cautions", "")).strip(),
    )
