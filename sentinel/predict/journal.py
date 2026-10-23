"""Calls logged from chat (plan 3.4): checked, stored with the market they were made in,
and shown back.

``log`` reads the coin's daily candles and BTC's daily and hourly candles (exchange only,
no CMC or NewsAPI credits) for the live price the entry is checked against and for a
compact snapshot: the price, the coin's daily RSI, and BTC's regime and 24 h change, the
same regime ``snapshot`` and ``market scan`` give. ``model`` names the chat model, so
calls from different models can be compared later. The first score check is due an
hour after the call.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from pydantic import ValidationError
from ulid import ULID

from sentinel.data import exchange
from sentinel.predict.validator import PredictionOut, check
from sentinel.signals import indicators, snapshot
from sentinel.signals.snapshot import DAILY_LIMIT, HOURLY_LIMIT, iso, rounded, sig
from sentinel.store.dynamo import Prediction, PredictionRepo

FIRST_CHECK = timedelta(hours=1)
SYMBOL = re.compile(r"[A-Z0-9]{1,15}")


class PredictError(RuntimeError):
    """A call that cannot be logged or found (bad JSON, unknown id)."""


def _now() -> datetime:
    return datetime.now(UTC)


def _dec(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def log(symbol: str, raw: str, model: str, source: str = "chat") -> Prediction:
    symbol = symbol.upper()
    if not SYMBOL.fullmatch(symbol):
        raise PredictError(f"bad symbol {symbol!r}")
    try:
        pred = PredictionOut.model_validate_json(raw)
    except ValidationError as exc:
        error = exc.errors()[0]
        where = ".".join(map(str, error["loc"])) or "json"
        raise PredictError(f"bad prediction: {where}: {error['msg']}") from exc
    now = _now()
    daily = exchange.candles(symbol, "1d", DAILY_LIMIT)
    btc_daily = exchange.candles("BTC", "1d", DAILY_LIMIT)
    btc_hourly = exchange.candles("BTC", "1h", HOURLY_LIMIT)
    btc = snapshot.btc_context(btc_hourly, snapshot.technicals(btc_daily, btc_hourly), None)
    price = daily.price
    errors, warnings = check(pred, price)
    prediction = Prediction(
        pred_id=str(ULID.from_datetime(now)),
        symbol=symbol,
        created_at=f"{now:%Y-%m-%dT%H:%M:%S}.{now.microsecond // 1000:03d}Z",
        model=model,
        action=pred.action,
        direction=pred.direction,
        confidence=Decimal(str(pred.confidence)),
        horizon_h=pred.horizon_h,
        entry=Decimal(str(pred.entry)),
        target=_dec(pred.target),
        stop=_dec(pred.stop),
        btc_context=pred.btc_context,
        reasons=pred.reasons,
        risk_note=pred.risk_note,
        snapshot={
            "price": _dec(sig(price)),
            "rsi14": _dec(rounded(indicators.rsi([c.close for c in daily.candles]), 1)),
            "btc_regime": btc.regime,
            "btc_chg_24h": _dec(btc.chg_24h),
        },
        valid=not errors,
        validator_errors=errors,
        warnings=warnings,
        due_at=iso(now + FIRST_CHECK),
        source=source,
    )
    if not PredictionRepo().add(prediction):
        raise PredictError(f"a call for {symbol} was logged at the same moment, log it again")
    return prediction


def show(pred_id: str) -> Prediction:
    pred_id = pred_id.upper()
    try:
        logged = ULID.from_str(pred_id).datetime
    except ValueError as exc:
        raise PredictError(f"bad id {pred_id!r}") from exc
    found = PredictionRepo().get(pred_id, f"{logged:%Y-%m-%d}")
    if found is None:
        raise PredictError(f"no prediction {pred_id}")
    return found
