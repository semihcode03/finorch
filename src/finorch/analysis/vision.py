"""Cok-modlu gorsel okuma (trading grafikleri).

Bir gorseli (yerel dosya veya url) gpt-4o-mini'ye gonderir ve grafikten okunabilen
bilgiyi metne cevirir: enstruman, zaman dilimi, gorunur fiyat seviyeleri, desenler
(FVG, order block, trend, likidite), ve varsa cizim/anotasyonlar.
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

from finorch.analysis.client import get_client, is_enabled
from finorch.config import settings

logger = logging.getLogger(__name__)

_PROMPT = """Bu bir finansal grafik/gorsel olabilir. Gorselde OKUNABILEN bilgiyi kisa ve
yapilandirilmis sekilde ozetle (yorum katma, sadece gorulen):
- enstruman/sembol (varsa)
- zaman dilimi (varsa)
- gorunur onemli fiyat seviyeleri / bolgeler
- teknik desenler veya isaretlemeler (FVG, order block, trend cizgisi, likidite, destek/direnc)
- metin/anotasyon (varsa)
Finansal grafik degilse kisaca ne oldugunu yaz. Turkce yanit ver."""


def _encode_image(path: str) -> str | None:
    try:
        data = Path(path).read_bytes()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception as e:
        logger.error("Gorsel okunamadi (%s): %s", path, e)
        return None


def describe_image(path_or_url: str) -> str:
    """Gorseli okuyup metin ozeti dondurur. Basarisizsa bos string."""
    if not (settings.vision_enabled and is_enabled()):
        return ""

    if path_or_url.startswith(("http://", "https://")):
        image_url = path_or_url
    else:
        image_url = _encode_image(path_or_url)
        if not image_url:
            return ""

    try:
        client = get_client()
        resp = client.chat.completions.create(
            model=settings.vision_model,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": _PROMPT},
                        {"type": "image_url", "image_url": {"url": image_url, "detail": "low"}},
                    ],
                }
            ],
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.error("Vision cagrisi basarisiz (%s): %s", path_or_url[:80], e)
        return ""
