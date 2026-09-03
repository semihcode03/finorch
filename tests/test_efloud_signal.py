from datetime import datetime, timezone

from finorch.market.efloud_signal import closed_candles, detect_support_reclaims


def _bar(index: int, open_: float, high: float, low: float, close: float) -> dict:
    start = int(datetime(2026, 9, 2, tzinfo=timezone.utc).timestamp())
    return {"time": start + index * 900, "open": open_, "high": high, "low": low, "close": close}


def test_live_candle_is_excluded() -> None:
    bars = [_bar(0, 77000, 77100, 76900, 77050), _bar(1, 77050, 77200, 77000, 77100)]
    now = datetime.fromtimestamp(bars[1]["time"] + 300, timezone.utc)
    assert closed_candles(bars, now) == bars[:1]


def test_sweep_reclaim_requires_structure_break_and_tracks_one_r() -> None:
    bars = [
        _bar(0, 76800, 76900, 76700, 76820),
        _bar(1, 76820, 76850, 76550, 76600),
        _bar(2, 76600, 76650, 76300, 76500),
        _bar(3, 76500, 76550, 76200, 76450),  # sweep + reclaim
        _bar(4, 76450, 76600, 76400, 76550),
        _bar(5, 76550, 76700, 76500, 76650),
        _bar(6, 76650, 76800, 76600, 76750),  # prior-three high break
        _bar(7, 76750, 78600, 76700, 78000),  # reaches 1R
    ]
    signals = detect_support_reclaims(bars)
    assert len(signals) == 1
    assert signals[0].status == "managed"
    assert signals[0].target_hit_time == bars[7]["time"]


def test_touch_without_reclaim_does_not_signal() -> None:
    bars = [
        _bar(0, 76800, 76900, 76700, 76820),
        _bar(1, 76820, 76850, 76300, 76350),
        _bar(2, 76350, 76500, 76200, 76480),
        _bar(3, 76480, 76600, 76400, 76550),
    ]
    assert detect_support_reclaims(bars) == []
