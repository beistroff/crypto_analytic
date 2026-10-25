"""Deterministic checks on a call before it is stored (plan 3.3).

A call that fails is still stored, with ``valid = false`` and its errors, so the results
count it. Reward-to-risk under 1 is only a warning. A horizon outside ``HORIZONS`` is
refused with the JSON errors instead, since the scorer could never grade it.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel

Horizon = Literal[1, 4, 12, 24, 72, 168]  # scalps 1 to 12 h, trades 1 to 7 days
HORIZONS: tuple[int, ...] = get_args(Horizon)
ENTRY_TOLERANCE_PCT = 1.0


class PredictionOut(BaseModel):
    """A call as the agent writes it (plan Appendix D)."""

    btc_context: str
    action: Literal["BUY", "SELL", "HOLD"]
    direction: Literal["UP", "DOWN", "FLAT"]
    confidence: float
    horizon_h: Horizon
    entry: float
    target: float | None = None
    stop: float | None = None
    reasons: list[str] = []
    risk_note: str | None = None


def check(pred: PredictionOut, price: float) -> tuple[list[str], list[str]]:
    """Errors and warnings for ``pred`` against the coin's live ``price``."""
    errors = []
    if not pred.btc_context.strip():
        errors.append("btc_context is empty")
    off = abs(pred.entry / price - 1) * 100
    if off > ENTRY_TOLERANCE_PCT:
        errors.append(f"entry {pred.entry:g} is {off:.1f}% from the price {price:g}")
    if pred.action != "HOLD":
        target, stop = pred.target, pred.stop
        if target is None or stop is None:
            errors.append(f"{pred.action} needs a target and a stop")
        elif pred.action == "BUY" and not target > pred.entry > stop:
            errors.append("BUY needs target > entry > stop")
        elif pred.action == "SELL" and not target < pred.entry < stop:
            errors.append("SELL needs target < entry < stop")
    if not 0 <= pred.confidence <= 1:
        errors.append(f"confidence {pred.confidence:g} is not between 0 and 1")
    warnings = []
    if pred.target is not None and pred.stop is not None and pred.stop != pred.entry:
        reward_risk = abs(pred.target - pred.entry) / abs(pred.entry - pred.stop)
        if reward_risk < 1:
            warnings.append(f"reward-to-risk {reward_risk:.1f} is under 1")
    return errors, warnings
