"""Naive Bayes gate (plan 5.4): a second opinion, never the source of truth.

A BUY or SELL with at least ``CONFIDENCE`` that Naive Bayes contradicts (P(up tomorrow) at
most ``BUY_MAX_P_UP`` for a BUY, at least ``SELL_MIN_P_UP`` for a SELL) goes back to the
model once with ``gate_recheck.md``. The model keeps or revises the call and says why; the
gate never changes a call by itself. The plan's 0.35 and 0.65 never occur: the model's
P(up) spans 0.41 to 0.58 (decided 30 Oct). Fixed at the experiment freeze (9.1).
"""

from __future__ import annotations

from sentinel.predict.validator import PredictionOut

CONFIDENCE = 0.6
BUY_MAX_P_UP = 0.45
SELL_MIN_P_UP = 0.55


def triggered(pred: PredictionOut, p_up: float) -> bool:
    if pred.confidence < CONFIDENCE:
        return False
    return (pred.action == "BUY" and p_up <= BUY_MAX_P_UP) or (
        pred.action == "SELL" and p_up >= SELL_MIN_P_UP
    )
