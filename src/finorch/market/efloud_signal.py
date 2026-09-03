"""Explainable BTC 15m watcher inspired by Efloud's published workflow.

This is deliberately narrower than a discretionary price-action model: a known
HTF level must be swept/reclaimed, then a closed 15m candle must break the prior
three-bar high. Only closed candles are evaluated, so a live wick cannot repaint
an interface signal.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from finorch.config import settings
from finorch.db import StrategySignal, get_session
from finorch.market.chart_data import get_chart_payload

STRATEGY = "efloud-btc-confirmation-v1"
SOURCE_URL = "https://tr.okx.com/en/learn/haftalik-arastirma-raporu-44"
INTERVAL_SECONDS = 15 * 60
REFERENCE_CHARTS = [
    {
        "label": "Efloud BTCUSDT Gunluk",
        "timeframe": "1D",
        "role": "HTF bias ve ana seviyeler",
        "url": "https://www.tradingview.com/x/8Ils0OQV/",
    },
    {
        "label": "Efloud BTCUSDT 4 Saat",
        "timeframe": "4H",
        "role": "HTF bolge ve senaryo dogrulamasi",
        "url": "https://www.tradingview.com/x/XWfkXLPy/",
    },
    {
        "label": "BTC canli teyit grafigi",
        "timeframe": "15m",
        "role": "Sweep, reclaim ve yapi kirilimi",
        "url": "/charts?symbol=BTC-USD&interval=15m",
    },
]


@dataclass
class Signal:
    dedup_key: str
    direction: str
    kind: str
    status: str
    bias: str
    entry: float
    stop_loss: float
    take_profit: float
    rr: float
    confidence: float
    rationale: str
    candle_time: int
    sweep_time: int
    sweep_low: float
    target_hit_time: int | None = None
    invalidated_time: int | None = None


def closed_candles(candles: list[dict[str, Any]], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    cutoff = int(now.timestamp())
    return [c for c in candles if int(c["time"]) + INTERVAL_SECONDS <= cutoff]


def detect_support_reclaims(candles: list[dict[str, Any]]) -> list[Signal]:
    """Find sweep/reclaim + 3-bar structure-break confirmations."""
    support = settings.efloud_btc_support
    zone_top = support * (1 + settings.efloud_zone_pct / 100)
    source_start = int(datetime(2026, 8, 27, tzinfo=timezone.utc).timestamp())
    bars = [c for c in candles if int(c["time"]) >= source_start]
    results: list[Signal] = []
    consumed_until = -1

    for sweep_index, sweep in enumerate(bars):
        if sweep_index <= consumed_until:
            continue
        if float(sweep["low"]) > support or float(sweep["high"]) < support:
            continue
        if float(sweep["close"]) < support:
            continue

        # A deeper sweep in the next two bars belongs to the same test.
        episode_end = min(len(bars), sweep_index + 3)
        candidates = [
            (idx, bars[idx])
            for idx in range(sweep_index, episode_end)
            if float(bars[idx]["low"]) <= zone_top and float(bars[idx]["close"]) >= support
        ]
        if candidates:
            sweep_index, sweep = min(candidates, key=lambda pair: float(pair[1]["low"]))

        confirm_index = None
        for idx in range(max(sweep_index + 1, 3), min(len(bars), sweep_index + 13)):
            bar = bars[idx]
            prior_high = max(float(x["high"]) for x in bars[idx - 3 : idx])
            if float(bar["close"]) > prior_high and float(bar["close"]) > float(bar["open"]):
                confirm_index = idx
                break
        if confirm_index is None:
            continue

        confirm = bars[confirm_index]
        entry = float(confirm["close"])
        sweep_low = min(float(x["low"]) for x in bars[sweep_index : confirm_index + 1])
        stop = min(settings.efloud_btc_invalidation, sweep_low * 0.999)
        risk = entry - stop
        if risk <= 0:
            continue
        target = entry + risk
        status = "active"
        target_time = None
        invalid_time = None
        runner_stop = entry
        for later in bars[confirm_index + 1 :]:
            # Both touched in one candle: conservative ordering, stop first.
            if status == "active" and float(later["low"]) <= stop:
                status = "invalidated"
                invalid_time = int(later["time"])
                break
            if status == "active" and float(later["high"]) >= target:
                status = "managed"
                target_time = int(later["time"])
                continue
            if status == "managed" and float(later["low"]) <= runner_stop:
                status = "closed_be"
                invalid_time = int(later["time"])
                break

        candle_time = int(confirm["time"])
        results.append(
            Signal(
                dedup_key=f"{STRATEGY}:support-reclaim:{candle_time}",
                direction="long",
                kind="support_reclaim",
                status=status,
                bias="bullish_confirmation",
                entry=entry,
                stop_loss=stop,
                take_profit=target,
                rr=1.0,
                confidence=0.78,
                rationale=(
                    f"{support:,.0f} bolgesi sweep/reclaim sonrasi kapali 15dk mum, "
                    "onceki 3 mumun tepesini kirdi. 1R sonrasi kalan pozisyon girise tasinir."
                ),
                candle_time=candle_time,
                sweep_time=int(sweep["time"]),
                sweep_low=sweep_low,
                target_hit_time=target_time,
                invalidated_time=invalid_time,
            )
        )
        consumed_until = confirm_index + 8
    return results


def monitor_snapshot(candles: list[dict[str, Any]]) -> dict[str, Any]:
    bars = closed_candles(candles)
    if not bars:
        return {"enabled": True, "bias": "unknown", "signals": []}
    last = float(bars[-1]["close"])
    if last >= settings.efloud_btc_reclaim:
        bias = "bullish_breakout"
        note = "82.300 uzeri; kirilim teyidi izleniyor."
    elif last < settings.efloud_btc_invalidation:
        bias = "bearish_warning"
        note = "76.000 alti LTF uyari; HTF kapanis teyidi gerekir."
    elif last >= settings.efloud_btc_support:
        bias = "constructive"
        note = "76.400 destegi korunuyor; 82.300 geri alimi ana yukari tetik."
    else:
        bias = "neutral_warning"
        note = "76.400 kayip, 76.000 kapanis destegi kritik."
    signals = detect_support_reclaims(bars)
    return {
        "enabled": settings.efloud_signal_enabled,
        "strategy": STRATEGY,
        "bias": bias,
        "note": note,
        "last_closed_price": last,
        "last_closed_time": int(bars[-1]["time"]),
        "levels": {
            "support": settings.efloud_btc_support,
            "invalidation": settings.efloud_btc_invalidation,
            "downside_target": settings.efloud_btc_downside_target,
            "reclaim": settings.efloud_btc_reclaim,
        },
        "signals": [asdict(signal) for signal in signals[-5:]],
        "reference_charts": REFERENCE_CHARTS,
        "disclaimer": "Kapali 15dk mumlara dayali kural motoru; yatirim tavsiyesi degildir.",
    }


def refresh_efloud_signals() -> dict[str, Any]:
    payload = get_chart_payload("BTC-USD", "15m")
    snapshot = monitor_snapshot(payload["candles"])
    with get_session() as session:
        for item in snapshot["signals"]:
            row = session.scalar(
                select(StrategySignal).where(StrategySignal.dedup_key == item["dedup_key"])
            )
            values = {
                "status": item["status"],
                "bias": item["bias"],
                "entry": item["entry"],
                "stop_loss": item["stop_loss"],
                "take_profit": item["take_profit"],
                "rr": item["rr"],
                "confidence": item["confidence"],
                "rationale": item["rationale"],
                "evidence_json": json.dumps(
                    {
                        "sweep_time": item["sweep_time"],
                        "sweep_low": item["sweep_low"],
                        "reference_charts": REFERENCE_CHARTS,
                    }
                ),
                "target_hit_at": _dt(item["target_hit_time"]),
                "invalidated_at": _dt(item["invalidated_time"]),
            }
            if row is None:
                row = StrategySignal(
                    dedup_key=item["dedup_key"], strategy=STRATEGY, symbol="BTC-USD",
                    timeframe="15m", direction=item["direction"], kind=item["kind"],
                    source_url=SOURCE_URL, candle_time=_dt(item["candle_time"]), **values,
                )
                session.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
    return snapshot


def _dt(timestamp: int | None) -> datetime | None:
    return datetime.fromtimestamp(timestamp, timezone.utc) if timestamp is not None else None
