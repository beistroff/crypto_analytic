"""Naive Bayes features and label (plan 5.2), the same for training and for a live check.

A row describes one coin on one finished UTC day ``d``, from that day's and earlier daily
candles only, and asks about the next day:

- Label: up when the close of day ``d + 1`` is above the close of day ``d`` (above 0 %,
  decided 27 Oct, like the scorer's BUY hit).
- Features: only data that exists in history (no news), so training and live use match.
  Each is computed from the last ``WINDOW`` finished days, so a live check sees exactly
  what the training rows saw (Wilder's ATR depends on how far back it starts).
- Decided 30 Oct after tests on 3 years of data: the weekday asked about, the coin's
  ATR in % of its price, and its 7-day return against BTC's. BTC's own trend, Fear &
  Greed, RSI, SMA50 and volume did not beat the base rate and are left out.

``raw`` gives the numbers; ``bucket`` turns them into categories with ``FEATURES``' edges.
A value on an edge goes to the higher bucket.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import timedelta

from sentinel.data.exchange import Candle
from sentinel.signals.indicators import atr, relative_strength

WINDOW = 100  # finished days behind each row
LABEL_PCT = 0.0  # next day's return above this is "up"

# feature: (raw column, edges, categories)
FEATURES: dict[str, tuple[str, tuple[float, ...], tuple[str, ...]]] = {
    "weekday": ("dow", (1, 2, 3, 4, 5, 6), ("mon", "tue", "wed", "thu", "fri", "sat", "sun")),
    "volatility": ("atr_pct", (5.0, 7.0), ("calm", "normal", "wild")),
    "vs_btc_7d": ("rel_btc_7d", (-3.0, 1.0), ("weaker", "even", "stronger")),
}


def raw(coin: list[Candle], btc: list[Candle]) -> dict[str, float] | None:
    """The features of the coin's last candle's day, or None when a value is missing.

    ``coin`` and ``btc`` are finished daily candles, oldest first, ending on the same day.
    """
    coin, btc = coin[-WINDOW:], btc[-WINDOW:]
    if len(coin) < WINDOW or len(btc) < WINDOW or coin[-1].ts != btc[-1].ts:
        return None
    values = {
        "dow": float((coin[-1].ts + timedelta(days=1)).weekday()),  # the day asked about
        "atr_pct": atr(coin) / coin[-1].close * 100,
        "rel_btc_7d": relative_strength(coin, btc, 7),
    }
    return None if any(v is None for v in values.values()) else values


def bucket(values: dict[str, float]) -> tuple[str, ...]:
    """The category of each feature, in ``FEATURES`` order."""
    return tuple(
        categories[bisect_right(edges, values[column])]
        for column, edges, categories in FEATURES.values()
    )


def label(ret_next: float) -> int:
    return int(ret_next > LABEL_PCT)
