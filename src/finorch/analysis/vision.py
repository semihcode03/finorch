"""Cok-modlu gorsel okuma (trading grafikleri).

Bir gorseli (yerel dosya veya url) gpt-4o-mini'ye gonderir ve iki soruyu yanitlar:

1. Bu gercekten bir finansal grafik mi? X'te bir analistin gonderisine ekli gorsel
   cogu zaman grafik degildir (mem, ekran goruntusu, haber kupuru, selfie). Grafik
   olmayanlar analiz metnine karistirilmaz; yoksa LLM olmayan seviyeler uydurur.
2. Grafikse uzerinde ne yaziyor? Enstruman, zaman dilimi, gorunur fiyat seviyeleri,
   desenler (FVG, order block, trend, likidite) ve analistin cizdigi anotasyonlar.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from pathlib import Path

from finorch.analysis.client import get_client, is_enabled
from finorch.config import settings

logger = logging.getLogger(__name__)

_PROMPT = """Bu gorseli incele ve SADECE gordugunu bildir; yorum katma.

Once karar ver: bu bir FINANSAL GRAFIK mi (mum/cizgi grafigi, fiyat ekrani, teknik
analiz gorseli, bilanco tablosu)? Mem, selfie, haber kupuru, alakasiz ekran goruntusu
ise grafik DEGILDIR.

Alanlar:
- is_chart: true/false
- symbol: grafikteki enstruman/sembol (orn. "BTCUSDT", "THYAO", "XAUUSD"); okunmuyorsa ""
- timeframe: zaman dilimi (orn. "4h", "1D", "1W"); okunmuyorsa ""
- levels: grafikte GORUNEN onemli fiyat seviyeleri, sayi listesi (orn. [48200, 51000]).
  Okunamiyorsa bos liste. Seviye UYDURMA.
- description: gordugunun kisa Turkce ozeti. Grafikse: trend yonu, isaretlenmis
  bolgeler/desenler (FVG, order block, destek/direnc, likidite), analistin cizimleri
  ve uzerindeki yazilar. Grafik degilse tek cumlede ne oldugunu yaz.

Yaniti SADECE su JSON'da ver:
{"is_chart": false, "symbol": "", "timeframe": "", "levels": [], "description": ""}"""

# vision_text alani icin ust sinir (cok uzun cikti analiz promptunu sisirmesin)
_DESC_MAX = 1200


@dataclass
class ChartReading:
    """Bir gorselden okunanlar."""

    is_chart: bool = False
    symbol: str = ""
    timeframe: str = ""
    levels: list[float] = None  # type: ignore[assignment]
    description: str = ""

    def __post_init__(self) -> None:
        if self.levels is None:
            self.levels = []

    def as_text(self) -> str:
        """Analiz promptuna eklenecek tek parca metin."""
        if not self.description:
            return ""
        head = " ".join(p for p in (self.symbol, self.timeframe) if p)
        levels = (
            "Gorunur seviyeler: " + ", ".join(f"{v:g}" for v in self.levels)
            if self.levels
            else ""
        )
        parts = [f"[{head}]" if head else "", self.description, levels]
        return " ".join(p for p in parts if p).strip()


def describe_image(path_or_url: str) -> ChartReading:
    """Gorseli okuyup yapilandirilmis sonuc dondurur. Basarisizsa bos ChartReading."""
    if not (settings.vision_enabled and is_enabled()):
        return ChartReading()

    if path_or_url.startswith(("http://", "https://")):
        image_url = path_or_url
    else:
        encoded = _encode_image(path_or_url)
        if not encoded:
            return ChartReading()
        image_url = encoded

    try:
        client = get_client()
        resp = client.chat.completions.create(
            model=settings.vision_model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPT},
                        # detail="high" grafikteki fiyat etiketlerini okumak icin gerekli;
                        # "low" ile seviyeler bulaniklasip yanlis okunuyor.
                        {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}},
                    ],
                }
            ],
        )
        return _parse(resp.choices[0].message.content or "{}")
    except Exception as e:
        logger.error("Vision cagrisi basarisiz (%s): %s", path_or_url[:80], e)
        return ChartReading()


def _parse(raw: str) -> ChartReading:
    import json

    try:
        data = json.loads(raw)
    except ValueError:
        logger.warning("Vision yaniti JSON degil: %s", raw[:120])
        return ChartReading()

    return ChartReading(
        is_chart=bool(data.get("is_chart")),
        symbol=str(data.get("symbol", "") or "").strip()[:60],
        timeframe=str(data.get("timeframe", "") or "").strip()[:30],
        levels=_floats(data.get("levels")),
        description=str(data.get("description", "") or "").strip()[:_DESC_MAX],
    )


def _floats(raw) -> list[float]:
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[float] = []
    for v in raw:
        try:
            out.append(float(v))
        except (TypeError, ValueError):
            continue
    return out


def _encode_image(path: str) -> str | None:
    try:
        data = Path(path).read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        logger.error("Gorsel okunamadi (%s): %s", path, e)
        return None
