"""Outcome scorer (plan 3.6): what the market did after each logged call, by code, with no
model tokens.

``sentinel predict score`` runs every hour as an OpenClaw command automation that sends
nothing; the results show through ``predict export``. A call is checked at each standard
horizon up to its own (1, 4, 12, 24, 72 or 168 h). The price then is the close of the
candle that closes nearest that time: 15-minute candles up to 12 h, hourly ones above. A
check whose candle is still open waits for the next run; one whose time the candles no
longer reach (300 of them: 75 h of 15-minute candles, 12.5 days of hourly ones, so only
after a long outage) is never graded with a later price: the coin is reported in
``missing`` instead.

- Hit: BUY when the price is above the entry, SELL when below. HOLD means "wait, do not
  buy now" (decided 26 Oct): a hit when buying would not have paid, i.e. the price is
  not more than 1 % above the entry; a drop counts as a hit, since waiting was better.
- After its own horizon the call is DONE, with ``target_hit_first`` (target, stop or
  neither; both touched in one candle counts as stop) and ``max_adverse_pct``, the worst
  move against the call in percent of the entry (0 or less). Both read the candles that
  open after the call, so a wick from before it never counts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import requests

from sentinel.data import SourceError, exchange
from sentinel.data.exchange import Candle, Timeframe
from sentinel.predict.validator import HORIZONS
from sentinel.signals.snapshot import iso, sig
from sentinel.store.sim import Prediction, PredictionRepo

MIN_GAIN_PCT = 1.0  # a rise of 1 % or less after a HOLD did not make buying worth it

log = logging.getLogger(__name__)


@dataclass
class ScoreResult:
    checked: int = 0  # calls that were due
    graded: list[Prediction] = field(default_factory=list)  # got a new check this run
    done: int = 0
    missing: list[str] = field(default_factory=list)  # symbols with no candles this run


def _now() -> datetime:
    return datetime.now(UTC)


def score() -> ScoreResult:
    """Check every due call once and save what is new."""
    now = _now()
    repo = PredictionRepo()
    result = ScoreResult()
    for pred in repo.due(iso(now)):
        result.checked += 1
        created = datetime.fromisoformat(pred.created_at)
        timeframe: Timeframe = "15m" if pred.horizon_h <= 12 else "1h"
        period = exchange.PERIOD[timeframe]
        try:
            # One fixed limit, so calls on the same coin share one cached fetch.
            candles = exchange.candles(pred.symbol, timeframe, exchange.OKX_MAX_LIMIT).candles
        except (SourceError, requests.RequestException) as exc:
            log.warning("no candles", extra={"symbol": pred.symbol, "error": str(exc)})
            if pred.symbol not in result.missing:
                result.missing.append(pred.symbol)
            continue
        horizons = [h for h in HORIZONS if h <= pred.horizon_h]
        checks = dict(pred.checks)
        for h in horizons:
            if f"h{h}" in checks:
                continue
            at = created + timedelta(hours=h)
            if at > now:
                break
            candle = min(candles, key=lambda c: abs(c.ts + period - at))
            if not candle.closed:
                break
            if abs(candle.ts + period - at) > period / 2:  # the candles no longer reach it
                if pred.symbol not in result.missing:
                    result.missing.append(pred.symbol)
                break
            checks[f"h{h}"] = _check(pred, candle.close)
        if len(checks) == len(pred.checks):
            continue  # its candle is still open
        result.graded.append(pred)
        pending = [h for h in horizons if f"h{h}" not in checks]
        if pending:
            repo.record(pred, checks, iso(created + timedelta(hours=pending[0])))
            continue
        window = [c for c in candles if created <= c.ts < created + timedelta(hours=pred.horizon_h)]
        if repo.record(pred, checks, None, _first(pred, window), _adverse(pred, window)):
            result.done += 1
    return result


def _check(pred: Prediction, price: float) -> dict[str, object]:
    ret = (price / float(pred.entry) - 1) * 100
    if pred.action == "BUY":
        hit = ret > 0
    elif pred.action == "SELL":
        hit = ret < 0
    else:
        hit = ret <= MIN_GAIN_PCT
    return {
        "price": Decimal(str(sig(price))),
        "return_pct": Decimal(str(round(ret, 2))),
        "hit": hit,
    }


def _first(pred: Prediction, window: list[Candle]) -> str | None:
    """Which level the price touched first: target, stop or neither."""
    if pred.action == "HOLD" or pred.target is None or pred.stop is None:
        return None
    target, stop = float(pred.target), float(pred.stop)
    for c in window:
        if pred.action == "BUY":
            to_target, to_stop = c.high >= target, c.low <= stop
        else:
            to_target, to_stop = c.low <= target, c.high >= stop
        if to_stop:
            return "stop"
        if to_target:
            return "target"
    return "neither"


def _adverse(pred: Prediction, window: list[Candle]) -> Decimal | None:
    if not window:
        return None
    entry = float(pred.entry)
    low = (min(c.low for c in window) / entry - 1) * 100
    high = (max(c.high for c in window) / entry - 1) * 100
    if pred.action == "BUY":
        worst = min(low, 0.0)
    elif pred.action == "SELL":
        worst = -max(high, 0.0)
    else:
        worst = -max(abs(low), abs(high))
    return Decimal(str(round(worst, 2)))
