"""The old fixed trading rules, kept unchanged as the RULES baseline of the experiment.

Ported from the legacy market scripts. They lean on Fear & Greed far more than the agent
should; that is the point of a baseline: the agent has to beat it.
- Fear & Greed below 30 and a 24 h drop of more than 5%: DCA BUY.
- Fear & Greed above 75: REDUCE/TP.
- Otherwise 24 h volume above 15% of market cap: VOLATILITY ALERT.
- Else HOLD (also when Fear & Greed is unknown).
"""

from __future__ import annotations

from typing import Literal

Signal = Literal["DCA BUY", "REDUCE/TP", "VOLATILITY ALERT", "HOLD"]

# Scalp candidates (legacy top_50_scalp.py): actively traded, not pumped yet.
SCALP_MIN_VOL_MC = 0.05
SCALP_CHANGE_RANGE = (-4.0, 2.0)
STABLECOINS = frozenset({"USDT", "USDC", "DAI", "FDUSD", "USDe", "USD1", "RLUSD", "USDD"})


def rules_signal(fear_greed: int | None, change_24h: float, vol_mc: float) -> Signal:
    if fear_greed is None:
        return "HOLD"
    if fear_greed < 30 and change_24h < -5:
        return "DCA BUY"
    if fear_greed > 75:
        return "REDUCE/TP"
    if vol_mc > 0.15:
        return "VOLATILITY ALERT"
    return "HOLD"


def is_scalp_candidate(symbol: str, change_24h: float, vol_mc: float) -> bool:
    low, high = SCALP_CHANGE_RANGE
    return symbol not in STABLECOINS and vol_mc > SCALP_MIN_VOL_MC and low <= change_24h <= high
