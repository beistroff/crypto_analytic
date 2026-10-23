"""Technical indicators on exchange candles (``sentinel.data.exchange``).

Conventions:

- Candles are oldest first. The last daily candle is today's (UTC), still open: its close
  is the latest price. Moving averages and RSI include it, as charts do.
- RSI and ATR use Wilder's smoothing: the first average is the plain mean of the first
  ``n`` values, then ``avg = (avg * (n - 1) + value) / n``.
- Rolling returns (1 h, 24 h, 7 d) come from hourly candles: the latest price against
  the hourly close nearest to that many hours ago.
- Day returns (relative strength) come from daily closes: the latest price against the
  close of the UTC day ``n`` days before today, so a 1-day return is "today so far".
- Range edges: the wick low and high (candle lows and highs, including the open one) and
  the close low and high (closes of finished candles only) over the last ``count`` candles
  (days on daily candles). A level is either a wick or a close level; the two are never
  mixed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from itertools import pairwise
from statistics import fmean, pstdev

from sentinel.data.exchange import Candle

# Fewer paired daily returns than this make beta meaningless.
MIN_BETA_POINTS = 20


def sma(values: list[float], n: int) -> float | None:
    """Mean of the last ``n`` values; None when there are fewer."""
    return fmean(values[-n:]) if len(values) >= n else None


def rsi(closes: list[float], n: int = 14) -> float | None:
    """Wilder's RSI over ``n`` periods; None with fewer than ``n + 1`` closes."""
    if len(closes) <= n:
        return None
    changes = [b - a for a, b in pairwise(closes)]
    gain = fmean(max(c, 0.0) for c in changes[:n])
    loss = fmean(max(-c, 0.0) for c in changes[:n])
    for change in changes[n:]:
        gain = (gain * (n - 1) + max(change, 0.0)) / n
        loss = (loss * (n - 1) + max(-change, 0.0)) / n
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100 - 100 / (1 + gain / loss)


def atr(candles: list[Candle], n: int = 14) -> float | None:
    """Wilder's average true range; None with fewer than ``n + 1`` candles."""
    if len(candles) <= n:
        return None
    ranges = [
        max(c.high - c.low, abs(c.high - prev.close), abs(c.low - prev.close))
        for prev, c in pairwise(candles)
    ]
    value = fmean(ranges[:n])
    for tr in ranges[n:]:
        value = (value * (n - 1) + tr) / n
    return value


def pct(new: float, old: float) -> float:
    return (new / old - 1) * 100


def change_over_hours(hourly: list[Candle], hours: int, now: datetime) -> float | None:
    """Percent change from the hourly close nearest to ``hours`` ago to the latest price."""
    target = now - timedelta(hours=hours)
    closes = [(c.ts + timedelta(hours=1), c.close) for c in hourly if c.closed]
    if not closes or closes[0][0] - target > timedelta(minutes=30):
        return None  # the candles do not reach back far enough
    _, reference = min(closes, key=lambda item: abs(item[0] - target))
    return pct(hourly[-1].close, reference)


def change_over_days(daily: list[Candle], days: int) -> float | None:
    """Percent change from the close of the UTC day ``days`` before today to the latest price."""
    closes = {c.ts: c.close for c in daily}
    reference = closes.get(daily[-1].ts - timedelta(days=days))
    return pct(daily[-1].close, reference) if reference else None


def volume_z(daily: list[Candle], days: int = 30) -> float | None:
    """The last finished day's volume in standard deviations from the ``days`` before it."""
    finished = [c.volume for c in daily if c.closed]
    if len(finished) <= days:
        return None
    before = finished[-days - 1 : -1]
    spread = pstdev(before)
    return (finished[-1] - fmean(before)) / spread if spread else None


def range_edges(candles: list[Candle], count: int) -> dict[str, float | str] | None:
    """Wick and close range of the last ``count`` candles, with the UTC dates."""
    window = candles[-count:]
    finished = [c for c in window if c.closed]
    if len(window) < count or not finished:
        return None
    low = min(window, key=lambda c: c.low)
    high = max(window, key=lambda c: c.high)
    return {
        "wick_low": low.low,
        "wick_low_date": low.ts.date().isoformat(),
        "wick_high": high.high,
        "wick_high_date": high.ts.date().isoformat(),
        "close_low": min(c.close for c in finished),
        "close_high": max(c.close for c in finished),
    }


def relative_strength(coin: list[Candle], btc: list[Candle], days: int) -> float | None:
    """Coin's day return minus BTC's over ``days``, in percentage points (positive: stronger)."""
    mine, theirs = change_over_days(coin, days), change_over_days(btc, days)
    return None if mine is None or theirs is None else mine - theirs


def beta(coin: list[Candle], btc: list[Candle], days: int = 90) -> float | None:
    """Beta of the coin's daily returns to BTC's over the last ``days`` finished days."""
    coin_closes = {c.ts: c.close for c in coin if c.closed}
    btc_closes = {c.ts: c.close for c in btc if c.closed}
    dates = sorted(coin_closes.keys() & btc_closes.keys())[-days - 1 :]
    pairs = [
        (pct(coin_closes[b], coin_closes[a]), pct(btc_closes[b], btc_closes[a]))
        for a, b in pairwise(dates)
        if b - a == timedelta(days=1)
    ]
    if len(pairs) < MIN_BETA_POINTS:
        return None
    mean_coin = fmean(p[0] for p in pairs)
    mean_btc = fmean(p[1] for p in pairs)
    variance = fmean((p[1] - mean_btc) ** 2 for p in pairs)
    covariance = fmean((p[0] - mean_coin) * (p[1] - mean_btc) for p in pairs)
    return covariance / variance if variance else None
