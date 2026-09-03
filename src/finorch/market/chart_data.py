"""Interactive chart data and indicators.

The chart consumes a provider-neutral payload. Yahoo Finance is the free test
provider for now; another adapter can replace it without changing the browser.
"""

from __future__ import annotations

import math
import re
import time
from datetime import timezone
from typing import Any

SUPPORTED_INTERVALS: dict[str, str] = {
    "15m": "60d",
    "30m": "60d",
    "60m": "2y",
}

_SYMBOL_RE = re.compile(r"^[A-Z0-9.^=\-]{1,40}$")
_CACHE_TTL_SECONDS = 300
_payload_cache: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


class ChartDataError(RuntimeError):
    """Raised when chart data cannot be fetched or validated."""


def normalize_chart_symbol(raw: str) -> str:
    symbol = (raw or "").strip().upper()
    if not _SYMBOL_RE.fullmatch(symbol):
        raise ChartDataError("Gecersiz sembol")
    return symbol


def get_chart_payload(symbol: str, interval: str) -> dict[str, Any]:
    """Fetch the longest free test range supported for the interval."""
    symbol = normalize_chart_symbol(symbol)
    if interval not in SUPPORTED_INTERVALS:
        raise ChartDataError("Desteklenmeyen periyot")

    key = (symbol, interval)
    cached = _payload_cache.get(key)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    payload = _fetch_yahoo(symbol, interval, SUPPORTED_INTERVALS[interval])
    _payload_cache[key] = (time.monotonic(), payload)
    return payload


def _fetch_yahoo(symbol: str, interval: str, period: str) -> dict[str, Any]:
    try:
        import yfinance as yf

        frame = yf.Ticker(symbol).history(
            period=period,
            interval=interval,
            auto_adjust=False,
            actions=False,
        )
    except Exception as exc:
        raise ChartDataError(f"Piyasa verisi alinamadi: {exc}") from exc

    if frame.empty:
        raise ChartDataError("Bu sembol ve periyot icin veri bulunamadi")

    candles: list[dict[str, float | int]] = []
    volumes: list[dict[str, float | int | str]] = []
    for timestamp, row in frame.iterrows():
        values = [_number(row.get(name)) for name in ("Open", "High", "Low", "Close")]
        if any(value is None for value in values):
            continue
        open_, high, low, close = values
        ts = timestamp.to_pydatetime()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        unix_time = int(ts.timestamp())
        candles.append(
            {
                "time": unix_time,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
            }
        )
        volume = _number(row.get("Volume")) or 0.0
        volumes.append(
            {
                "time": unix_time,
                "value": volume,
                "color": "rgba(5, 113, 63, .42)" if close >= open_ else "rgba(168, 38, 26, .38)",
            }
        )

    if len(candles) < 2:
        raise ChartDataError("Grafik icin yeterli mum bulunamadi")

    closes = [float(candle["close"]) for candle in candles]
    times = [int(candle["time"]) for candle in candles]
    indicators = {
        "sma20": _line_series(times, _sma(closes, 20)),
        "ema50": _line_series(times, _ema(closes, 50)),
        "rsi14": _line_series(times, _rsi(closes, 14)),
    }
    first = frame.index[0].to_pydatetime()
    last = frame.index[-1].to_pydatetime()
    return {
        "meta": {
            "symbol": symbol,
            "interval": interval,
            "requested_period": period,
            "provider": "Yahoo Finance",
            "bar_count": len(candles),
            "first_bar": first.isoformat(),
            "last_bar": last.isoformat(),
            "cached_for_seconds": _CACHE_TTL_SECONDS,
        },
        "candles": candles,
        "volume": volumes,
        "indicators": indicators,
        "price_lines": [],
        "trades": [],
    }


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _line_series(times: list[int], values: list[float | None]) -> list[dict[str, float | int]]:
    return [
        {"time": timestamp, "value": value}
        for timestamp, value in zip(times, values, strict=True)
        if value is not None
    ]


def _sma(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    window_sum = 0.0
    for index, value in enumerate(values):
        window_sum += value
        if index >= period:
            window_sum -= values[index - period]
        if index >= period - 1:
            result[index] = window_sum / period
    return result


def _ema(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) < period:
        return result
    current = sum(values[:period]) / period
    result[period - 1] = current
    multiplier = 2.0 / (period + 1)
    for index in range(period, len(values)):
        current = (values[index] - current) * multiplier + current
        result[index] = current
    return result


def _rsi(values: list[float], period: int) -> list[float | None]:
    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result

    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    average_gain = sum(max(change, 0.0) for change in changes[:period]) / period
    average_loss = sum(max(-change, 0.0) for change in changes[:period]) / period
    result[period] = _rsi_value(average_gain, average_loss)

    for index in range(period + 1, len(values)):
        change = changes[index - 1]
        average_gain = (average_gain * (period - 1) + max(change, 0.0)) / period
        average_loss = (average_loss * (period - 1) + max(-change, 0.0)) / period
        result[index] = _rsi_value(average_gain, average_loss)
    return result


def _rsi_value(average_gain: float, average_loss: float) -> float:
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + strength))
