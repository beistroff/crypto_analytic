"""Naive Bayes features and label (plan 5.2), the same for training and for a live check.

A row describes one coin on one finished UTC day ``d``, from that day's and earlier daily
candles only, and asks about the next day:

- Label: up when the close of day ``d + 1`` is above the close of day ``d`` (above 0 %,
  decided 27 Oct, like the scorer's BUY hit).
- Features: only data that exists in history (no news), so training and live use match.
  Each is computed from the last ``WINDOW`` finished days, so a live check sees exactly
  what the training rows saw (Wilder's RSI depends on how far back it starts).

``raw`` gives the numbers; ``bucket`` turns them into categories with ``FEATURES``' edges.
A value on an edge goes to the higher bucket.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import timedelta

from sentinel.data.exchange import Candle
from sentinel.signals.indicators import pct, rsi, sma, volume_z

WINDOW = 100  # finished days behind each row
LABEL_PCT = 0.0  # next day's return above this is "up"

# feature: (raw column, edges, categories)
FEATURES: dict[str, tuple[str, tuple[float, ...], tuple[str, ...]]] = {
    "btc_24h": ("btc_ret", (-1.0, 1.0), ("down", "flat", "up")),
    "btc_sma50": ("btc_vs_sma50", (0.0,), ("below", "above")),
    "rsi": ("rsi14", (30.0, 70.0), ("low", "mid", "high")),
    "sma50": ("vs_sma50", (0.0,), ("below", "above")),
    "fng": (
        "fng",
        (25, 45, 56, 76),
        ("extreme_fear", "fear", "neutral", "greed", "extreme_greed"),
    ),
    "weekend": ("weekend", (1,), ("no", "yes")),
    "vol_z": ("vol_z", (-1.0, 1.0), ("low", "normal", "high")),
}


def raw(coin: list[Candle], btc: list[Candle], fng: int | None) -> dict[str, float] | None:
    """The features of the coin's last candle's day, or None when a value is missing.

    ``coin`` and ``btc`` are finished daily candles, oldest first, ending on the same day;
    ``fng`` is that day's Fear & Greed value.
    """
    coin, btc = coin[-WINDOW:], btc[-WINDOW:]
    if len(coin) < WINDOW or len(btc) < WINDOW or fng is None or coin[-1].ts != btc[-1].ts:
        return None
    closes = [c.close for c in coin]
    btc_closes = [c.close for c in btc]
    values = {
        "btc_ret": pct(btc_closes[-1], btc_closes[-2]),
        "btc_vs_sma50": pct(btc_closes[-1], sma(btc_closes, 50)),
        "rsi14": rsi(closes),
        "vs_sma50": pct(closes[-1], sma(closes, 50)),
        "fng": float(fng),
        "weekend": float((coin[-1].ts + timedelta(days=1)).weekday() >= 5),  # the day asked about
        "vol_z": volume_z(coin),
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
