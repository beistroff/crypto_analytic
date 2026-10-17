"""BTC regime: does the market leader support taking risk in altcoins?

Rule: four inputs each score -1, 0 or +1, and the sum gives the label.

- Price against SMA50: above +1, below -1.
- Price against SMA200: above +1, below -1.
- 7-day change: above +3% +1, below -3% -1, otherwise 0.
- 24-hour change: above +2% +1, below -2% -1, otherwise 0.

A sum of +3 or more is ``risk_on``, -3 or less ``risk_off``, anything between
``neutral``. A missing input scores 0, so missing data pulls towards neutral.

BTC dominance is reported with the numbers but does not change the label: the free CMC
plan has no dominance history, so a rising dominance cannot be told from a falling one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Label = Literal["risk_on", "neutral", "risk_off"]

CHG_7D_PCT = 3.0
CHG_24H_PCT = 2.0
LABEL_POINTS = 3


@dataclass(frozen=True)
class Regime:
    regime: Label
    points: int
    price: float
    chg_24h: float | None
    chg_7d: float | None
    sma50: float | None
    sma200: float | None
    dominance: float | None


def classify(
    price: float,
    chg_24h: float | None,
    chg_7d: float | None,
    sma50: float | None,
    sma200: float | None,
    dominance: float | None = None,
) -> Regime:
    points = (
        _side(price, sma50)
        + _side(price, sma200)
        + _band(chg_7d, CHG_7D_PCT)
        + _band(chg_24h, CHG_24H_PCT)
    )
    label: Label = "neutral"
    if points >= LABEL_POINTS:
        label = "risk_on"
    elif points <= -LABEL_POINTS:
        label = "risk_off"
    return Regime(label, points, price, chg_24h, chg_7d, sma50, sma200, dominance)


def _side(price: float, average: float | None) -> int:
    if average is None or price == average:
        return 0
    return 1 if price > average else -1


def _band(change: float | None, threshold: float) -> int:
    if change is None or abs(change) <= threshold:
        return 0
    return 1 if change > 0 else -1
