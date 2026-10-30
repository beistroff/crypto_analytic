"""Naive Bayes gate (plan 5.4): a second opinion, never the source of truth.

A BUY or SELL with at least ``gate.confidence`` that Naive Bayes contradicts (P(up
tomorrow) at most ``gate.buy_max_p_up`` for a BUY, at least ``gate.sell_min_p_up`` for a
SELL) goes back to the model once with ``gate_recheck.md``: its call, NB's P(up) and the
features behind it. The model keeps or revises the call and says why; the gate never
changes a call by itself.
"""

from __future__ import annotations

from sentinel.config import get_settings
from sentinel.models.check import Check
from sentinel.predict.validator import PredictionOut


def triggered(pred: PredictionOut, p_up: float) -> bool:
    gate = get_settings().gate
    if pred.confidence < gate.confidence:
        return False
    if pred.action == "BUY":
        return p_up <= gate.buy_max_p_up
    if pred.action == "SELL":
        return p_up >= gate.sell_min_p_up
    return False


def recheck_prompt(
    template: str, symbol: str, horizon_h: int, pred: PredictionOut, nb: Check, snapshot: str
) -> str:
    because = ", ".join(
        f"{feature} {category} (x{ratio:.2f})" for feature, category, ratio in nb.top
    )
    return (
        template.replace("{symbol}", symbol)
        .replace("{horizon_h}", str(horizon_h))
        .replace("{call}", pred.model_dump_json())
        .replace("{p_up}", f"{nb.p_up:.2f}")
        .replace("{because}", because)
        .replace("{snapshot}", snapshot)
    )
