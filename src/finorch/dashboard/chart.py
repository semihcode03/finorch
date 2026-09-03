"""Sunucu tarafinda SVG fiyat grafigi cizimi.

Neden JavaScript grafik kutuphanesi degil: kurumsal ag CDN'leri engelleyebiliyor
(api.telegram.org ornegi) ve dashboard'un "ekstra kurulum gerekmez" ilkesi var.
SVG dogrudan HTML'e gomulur; tarayici disinda hicbir sey gerekmez.

Cizilen sey: kapanis fiyati cizgisi + altinda dolgu, uzerine analistin verdigi
tetik seviyeleri kesikli cizgi olarak islenir. Boylece "fiyat tetige ne kadar
yakin" sorusu tek bakista goruluyor.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

# Cizim alani ve kenar bosluklari
_PAD_L = 4
_PAD_R = 54  # sag tarafta fiyat etiketlerine yer
_PAD_Y = 10


@dataclass
class Level:
    """Grafige cizilecek yatay seviye (tetik fiyati, hedef vb.)."""

    value: float
    label: str = ""
    color: str = "#1f5fd0"


def render_price_svg(
    rows: list[dict],
    levels: list[Level] | None = None,
    width: int = 520,
    height: int = 140,
) -> str:
    """Kapanis serisini SVG olarak cizer. Veri yoksa bos string doner.

    `rows` `market.get_history()` ciktisidir: [{ts, open, high, low, close, ...}].
    """
    closes = [r["close"] for r in rows if r.get("close") is not None]
    if len(closes) < 2:
        return ""

    levels = levels or []
    # Seviyeler grafik disinda kalmasin diye olcege dahil edilir
    span_values = closes + [lv.value for lv in levels]
    low, high = min(span_values), max(span_values)
    if high == low:
        high = low + 1

    plot_w = width - _PAD_L - _PAD_R
    plot_h = height - 2 * _PAD_Y

    def x_at(i: int) -> float:
        return _PAD_L + (i / (len(closes) - 1)) * plot_w

    def y_at(value: float) -> float:
        return _PAD_Y + (high - value) / (high - low) * plot_h

    points = [(x_at(i), y_at(v)) for i, v in enumerate(closes)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    area = f"{_PAD_L},{height - _PAD_Y} {line} {points[-1][0]:.1f},{height - _PAD_Y}"

    # Seri yukseliyorsa yesil, dusuyorsa kirmizi
    rising = closes[-1] >= closes[0]
    stroke = "#05713f" if rising else "#a8261a"
    fill = "#e9f9f0" if rising else "#fdeeec"

    parts = [
        f'<svg class="spark" viewBox="0 0 {width} {height}" width="100%" height="{height}" '
        f'preserveAspectRatio="none" role="img">',
        f'<polygon points="{area}" fill="{fill}" />',
        f'<polyline points="{line}" fill="none" stroke="{stroke}" stroke-width="1.6" '
        f'stroke-linejoin="round" stroke-linecap="round" />',
    ]

    for lv in levels:
        y = y_at(lv.value)
        parts.append(
            f'<line x1="{_PAD_L}" y1="{y:.1f}" x2="{_PAD_L + plot_w:.1f}" y2="{y:.1f}" '
            f'stroke="{lv.color}" stroke-width="1" stroke-dasharray="4 3" opacity=".85" />'
        )
        parts.append(
            f'<text x="{_PAD_L + plot_w + 5:.1f}" y="{y + 3.5:.1f}" font-size="10" '
            f'fill="{lv.color}" font-family="monospace">{escape(lv.label or _fmt(lv.value))}</text>'
        )

    # Son fiyat noktasi ve etiketi
    last_x, last_y = points[-1]
    parts.append(f'<circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="2.8" fill="{stroke}" />')
    parts.append(
        f'<text x="{_PAD_L + plot_w + 5:.1f}" y="{last_y + 3.5:.1f}" font-size="10.5" '
        f'font-weight="600" fill="{stroke}" font-family="monospace">{_fmt(closes[-1])}</text>'
    )
    parts.append("</svg>")
    return "".join(parts)


def render_sparkline(
    values: list[float],
    up: bool | None = None,
    width: int = 58,
    height: int = 20,
) -> str:
    """Piyasa seridi icin eksensiz, etiketsiz mini cizgi. Veri yetersizse bos string.

    `render_price_svg`'den ayri durur cunku serit farkli bir sey ister: fiyat
    etiketi, dolgu ve seviye cizgisi yok; sadece hareketin silueti.

    `up` verilirse renk ondan alinir. Serit gunluk degisimi gosterirken cizgi bir
    aylik egimi cizer; ikisi ters yone bakabilir ve ayni satirda iki farkli renk
    kafa karistirir. Bu yuzden cagiran taraf rengi gunluk degisime sabitler.
    """
    series = [v for v in values if v is not None]
    if len(series) < 2:
        return ""

    low, high = min(series), max(series)
    span = (high - low) or 1.0
    # Cizgi kalinligi kenarlarda kirpilmasin diye her yonde ~1.5px pay birakilir
    inset = 1.5
    step = (width - 2 * inset) / (len(series) - 1)
    inner = height - 2 * inset

    points = " ".join(
        f"{(inset + i * step):.1f},{(inset + (high - v) / span * inner):.1f}"
        for i, v in enumerate(series)
    )
    rising = up if up is not None else series[-1] >= series[0]
    stroke = "#05713f" if rising else "#a8261a"

    return (
        f'<svg class="mini" viewBox="0 0 {width} {height}" width="{width}" height="{height}" '
        f'preserveAspectRatio="none" aria-hidden="true">'
        f'<polyline points="{points}" fill="none" stroke="{stroke}" stroke-width="1.3" '
        f'stroke-linejoin="round" stroke-linecap="round" /></svg>'
    )


def _fmt(value: float) -> str:
    """Fiyati buyuklugune gore uygun ondalikla yazar."""
    if abs(value) >= 1000:
        return f"{value:,.0f}".replace(",", ".")
    if abs(value) >= 10:
        return f"{value:.2f}"
    return f"{value:.4g}"
