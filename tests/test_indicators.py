"""Indicators against values worked out by hand (the arithmetic is in the comments)."""

from datetime import UTC, datetime, timedelta

import pytest

from sentinel.data.exchange import Candle
from sentinel.signals import indicators as ind

DAY0 = datetime(2026, 9, 1, tzinfo=UTC)


def _candle(ts, close, high=None, low=None, volume=0.0, closed=True):
    high = close if high is None else high
    low = close if low is None else low
    return Candle(ts, close, high, low, close, volume, closed)


def _days(closes, last_open=True):
    """Daily candles from DAY0 on; the last one is today's, still open."""
    n = len(closes)
    return [
        _candle(DAY0 + timedelta(days=i), c, closed=not (last_open and i == n - 1))
        for i, c in enumerate(closes)
    ]


def test_sma():
    assert ind.sma([1, 2, 3, 4, 5], 3) == 4.0
    assert ind.sma([1, 2], 3) is None


def test_rsi_wilder():
    # 14 changes, 7 of +2 and 7 of -1: avg gain 1, avg loss 0.5, RS 2, RSI 66.67.
    closes = [100.0]
    for _ in range(7):
        closes += [closes[-1] + 2, closes[-1] + 1]
    assert ind.rsi(closes) == pytest.approx(66.667, abs=1e-3)
    # One more change of +3: gain (13 + 3) / 14, loss 6.5 / 14, RS 16 / 6.5, RSI 71.11.
    assert ind.rsi([*closes, closes[-1] + 3]) == pytest.approx(71.111, abs=1e-3)
    assert ind.rsi(closes[:14]) is None


def test_atr_wilder():
    rows = [(10, 8, 9), (11, 9, 10.5), (12, 10, 11), (13, 9, 12), (15, 12, 14), (20, 18, 19)]
    candles = [_candle(DAY0 + timedelta(days=i), c, h, lo) for i, (h, lo, c) in enumerate(rows)]
    # True ranges 2, 2, 4 -> first ATR 8/3; then 3 -> 25/9; then a gap up, TR 20 - 14 = 6
    # -> (25/9 * 2 + 6) / 3 = 104/27.
    assert ind.atr(candles[:4], n=3) == pytest.approx(8 / 3)
    assert ind.atr(candles, n=3) == pytest.approx(104 / 27)


def test_change_over_hours_uses_the_nearest_hourly_close():
    # Hourly closes 100..129 (finished) and 130 (current hour, 20 minutes in).
    start = DAY0
    hourly = [_candle(start + timedelta(hours=i), 100.0 + i, closed=i < 30) for i in range(31)]
    now = hourly[-1].ts + timedelta(minutes=20)
    # 24 h ago is 23 h 40 min before the current hour: nearest close is 24 h before it,
    # the close of candle 5 (105).
    assert ind.change_over_hours(hourly, 24, now) == pytest.approx((130 / 105 - 1) * 100)
    # 1 h ago: the close at the start of the previous hour (128) is 20 min off, the
    # latest close (129) 40 min.
    assert ind.change_over_hours(hourly, 1, now) == pytest.approx((130 / 128 - 1) * 100)
    assert ind.change_over_hours(hourly, 48, now) is None


def test_volume_z_of_the_last_finished_day():
    # 30 days of 9 and 11 (mean 10, standard deviation 1), then 13: z = 3.
    days = [*[9.0, 11.0] * 15, 13.0, 1.0]
    candles = [
        _candle(DAY0 + timedelta(days=i), 100, volume=v, closed=i < 31) for i, v in enumerate(days)
    ]
    assert ind.volume_z(candles) == pytest.approx(3.0)
    assert ind.volume_z(candles[:30]) is None


def test_range_edges_keep_wicks_and_closes_apart():
    # (high, low, close) for 1 to 8 Sep; 1 Sep is outside the 7-day window.
    rows = [
        (90000, 70000, 85000),
        (83000, 81000, 82000),
        (84000, 81500, 83500),
        (82900, 80809, 81600),
        (82600, 80400, 80600),  # lowest close
        (84500, 82000, 84200),  # highest close
        (85100, 83000, 83100),  # 7 Sep: highest wick
        (83500, 79775, 81700),  # 8 Sep, today, still open: lowest wick; its close does not count
    ]
    candles = [
        _candle(DAY0 + timedelta(days=i), c, h, lo, closed=i < 7)
        for i, (h, lo, c) in enumerate(rows)
    ]
    assert ind.range_edges(candles, 7) == {
        "wick_low": 79775,
        "wick_low_date": "2026-09-08",
        "wick_high": 85100,
        "wick_high_date": "2026-09-07",
        "close_low": 80600,
        "close_high": 84200,
    }
    assert ind.range_edges(candles, 30) is None


def test_relative_strength_and_beta_to_btc():
    # Two days back: BTC 100 -> 105 (+5%), the coin 100 -> 110 (+10%): 5 points stronger.
    btc, coin = _days([100, 100, 105]), _days([100, 100, 110])
    assert ind.relative_strength(coin, btc, 2) == pytest.approx(5.0)
    assert ind.relative_strength(coin, btc, 30) is None
    # Every daily move of the coin is twice BTC's: beta 2.
    btc_closes, coin_closes = [100.0], [100.0]
    for i in range(40):
        move = 0.02 if i % 2 else -0.01
        btc_closes.append(btc_closes[-1] * (1 + move))
        coin_closes.append(coin_closes[-1] * (1 + 2 * move))
    assert ind.beta(_days(coin_closes), _days(btc_closes)) == pytest.approx(2.0)
    assert ind.beta(_days(coin_closes[:10]), _days(btc_closes[:10])) is None
