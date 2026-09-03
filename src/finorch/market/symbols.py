"""Analistin agzindan cikan enstruman adini piyasa sembolune cevirir.

Analist "gram altin", "dolar", "bitcoin" veya "THYAO" der; fiyat saglayicisi
(Yahoo Finance) ise "USDTRY=X", "BTC-USD", "THYAO.IS" bekler. Bu modul aradaki
cevirmendir.

Bazi enstrumanlarin dogrudan karsiligi yoktur (gram altin gibi). Onlar TUREV
sembol olarak tanimlanir: baz fiyat x kur x carpan formuluyle hesaplanir.
"""

from __future__ import annotations

import re

from finorch.config import settings

# Dogrudan eslesme: analistin kullandigi ad -> Yahoo Finance sembolu
_DIRECT: dict[str, str] = {
    # --- BIST endeksleri ---
    "XU100": "XU100.IS",
    "BIST": "XU100.IS",
    "BIST100": "XU100.IS",
    "BIST 100": "XU100.IS",
    "ENDEKS": "XU100.IS",
    "XU030": "XU030.IS",
    "BIST30": "XU030.IS",
    "BIST 30": "XU030.IS",
    "XBANK": "XBANK.IS",
    "BANKACILIK ENDEKSI": "XBANK.IS",
    "XUSIN": "XUSIN.IS",
    # --- Doviz ---
    "DOLAR": "USDTRY=X",
    "USDTRY": "USDTRY=X",
    "USD/TRY": "USDTRY=X",
    "DOLAR/TL": "USDTRY=X",
    "EURO": "EURTRY=X",
    "EUR": "EURTRY=X",
    "EURTRY": "EURTRY=X",
    "EUR/TRY": "EURTRY=X",
    "EURUSD": "EURUSD=X",
    "EUR/USD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "DXY": "DX-Y.NYB",
    "DOLAR ENDEKSI": "DX-Y.NYB",
    # --- Kiymetli maden (ons bazli) ---
    "ALTIN": "GC=F",
    "ONS": "GC=F",
    "ONS ALTIN": "GC=F",
    "XAUUSD": "GC=F",
    "XAU": "GC=F",
    "GUMUS": "SI=F",
    "ONS GUMUS": "SI=F",
    "XAGUSD": "SI=F",
    # --- Emtia ---
    "BRENT": "BZ=F",
    "PETROL": "BZ=F",
    "WTI": "CL=F",
    "DOGALGAZ": "NG=F",
    "BAKIR": "HG=F",
    # --- Kripto ---
    "BTC": "BTC-USD",
    "BITCOIN": "BTC-USD",
    "BTCUSD": "BTC-USD",
    "BTCUSDT": "BTC-USD",
    "ETH": "ETH-USD",
    "ETHEREUM": "ETH-USD",
    "ETHUSD": "ETH-USD",
    "ETHUSDT": "ETH-USD",
    "SOL": "SOL-USD",
    "SOLUSDT": "SOL-USD",
    "XRP": "XRP-USD",
    "AVAX": "AVAX-USD",
    "BNB": "BNB-USD",
    "DOGE": "DOGE-USD",
    # --- ABD endeksleri ---
    "SP500": "^GSPC",
    "S&P500": "^GSPC",
    "SPX": "^GSPC",
    "NASDAQ": "^IXIC",
    "NDX": "^NDX",
    "DOW": "^DJI",
    "VIX": "^VIX",
}

# Turev semboller: (baz sembol, kur sembolu veya None, carpan)
# Gram altin TL = (ons altin USD / 31.1035) x USDTRY
_TROY_OUNCE_GRAMS = 31.1034768

DERIVED: dict[str, tuple[str, str | None, float]] = {
    "GRAMALTIN": ("GC=F", "USDTRY=X", 1 / _TROY_OUNCE_GRAMS),
    "GRAMGUMUS": ("SI=F", "USDTRY=X", 1 / _TROY_OUNCE_GRAMS),
}

_DERIVED_ALIASES: dict[str, str] = {
    "GRAM ALTIN": "GRAMALTIN",
    "GRAMALTIN": "GRAMALTIN",
    "GR ALTIN": "GRAMALTIN",
    "ALTIN GRAM": "GRAMALTIN",
    "GRAM GUMUS": "GRAMGUMUS",
    "GRAMGUMUS": "GRAMGUMUS",
}

# Zaten saglayici formatinda olan semboller (THYAO.IS, BTC-USD, USDTRY=X, ^GSPC)
_ALREADY_RESOLVED = re.compile(r"[.=^]|-USD$")

# BIST hisse kodu: 4-5 buyuk harf (ASELS, THYAO, GARAN, KCHOL)
_BIST_CODE = re.compile(r"^[A-Z]{4,5}$")

_TR_MAP = str.maketrans("ıİşŞğĞüÜöÖçÇ", "iisSgGuUoOcC")


def normalize(raw: str) -> str:
    """Turkce karakterleri sadelestirip buyuk harfe cevirir, fazla bosluklari atar."""
    text = (raw or "").translate(_TR_MAP).upper().strip()
    text = text.replace("$", "").replace("#", "")
    return re.sub(r"\s+", " ", text)


def resolve_symbol(raw: str) -> str:
    """Enstruman adini piyasa sembolune cevirir; cozumleyemezse bos string.

    Donen deger ya bir Yahoo Finance sembolu ("THYAO.IS") ya da `DERIVED`
    icindeki bir turev anahtardir ("GRAMALTIN"). Ikisini de `prices` modulu anlar.
    """
    name = normalize(raw)
    if not name:
        return ""

    if name in _DERIVED_ALIASES:
        return _DERIVED_ALIASES[name]
    if name in _DIRECT:
        return _DIRECT[name]

    # Bosluksuz hali de denenir: "BIST 100" -> "BIST100"
    compact = name.replace(" ", "").replace("/", "")
    if compact in _DERIVED_ALIASES:
        return _DERIVED_ALIASES[compact]
    if compact in _DIRECT:
        return _DIRECT[compact]

    # Analist zaten saglayici formatinda yazmissa dokunma
    if _ALREADY_RESOLVED.search(compact):
        return compact

    # Kalan 4-5 harfli kodlari BIST hissesi kabul et
    if _BIST_CODE.match(compact):
        return f"{compact}{settings.bist_suffix}"

    return ""


def is_derived(symbol: str) -> bool:
    return symbol in DERIVED


def display_name(symbol: str) -> str:
    """Sembolu insan okunur kisa ada cevirir (dashboard basliklari icin)."""
    if symbol in DERIVED:
        return symbol.replace("GRAM", "Gram ").title()
    return symbol.removesuffix(settings.bist_suffix).removesuffix("=X").lstrip("^")
