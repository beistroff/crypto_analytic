"""Watches: price levels the user wants to hear about, checked by code with no LLM.

``sentinel watch check`` runs every 15 minutes as an OpenClaw command automation, which
calls no model. On a hit it marks the watch (it then leaves GSI2) and prints a short alert,
which OpenClaw delivers to Telegram; a quiet run prints ``NO_REPLY`` and delivers nothing.
One alert per hit: if that delivery fails, the alert is lost and OpenClaw records the run
as failed.

Triggers:

- ``touch_below``: an hourly low, or the latest price, at or under the level.
- ``close_below`` / ``close_above``: a closed UTC candle (``1d`` by default, or ``4h``)
  closing under / over the level.

Only candles from after the watch was set count: hourly candles that open after it, and
close candles that close after it. Each run looks back about two days (48 hourly, 10
daily or 12 four-hour candles), which covers a few missed runs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import requests
from ulid import ULID

from sentinel.data import SourceError, exchange
from sentinel.data.exchange import PERIOD, Timeframe
from sentinel.portfolio.service import plain
from sentinel.store.dynamo import Watch, WatchRepo

TRIGGERS = ("touch_below", "close_below", "close_above")
CLOSE_TIMEFRAMES = ("1d", "4h")
LOOKBACK: dict[Timeframe, int] = {"1h": 48, "1d": 10, "4h": 12}
SYMBOL = re.compile(r"[A-Z0-9]{1,15}")

log = logging.getLogger(__name__)


class WatchError(RuntimeError):
    """A watch that cannot be added or removed (bad trigger, unknown id)."""


@dataclass(frozen=True)
class Hit:
    at: datetime
    price: float


@dataclass
class CheckResult:
    checked: int = 0
    hits: list[Watch] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # symbols with no candles this run


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def add(
    symbol: str,
    trigger: str,
    level: Decimal,
    timeframe: str | None = None,
    *,
    stop: Decimal | None = None,
    target: Decimal | None = None,
    note: str | None = None,
) -> tuple[Watch, float]:
    """Store a new watch; returns it with the coin's latest price.

    The price comes from the same candles ``check`` reads, so a ticker no exchange lists
    is refused here instead of never firing.
    """
    symbol = symbol.upper()
    if not SYMBOL.fullmatch(symbol):
        raise WatchError(f"bad symbol {symbol!r}")
    if trigger not in TRIGGERS:
        raise WatchError(f"bad trigger {trigger!r}, expected one of: {', '.join(TRIGGERS)}")
    if trigger == "touch_below":
        if timeframe:
            raise WatchError("--tf is for close triggers only")
    else:
        timeframe = timeframe or "1d"
        if timeframe not in CLOSE_TIMEFRAMES:
            raise WatchError(f"bad timeframe {timeframe!r}, expected 1d or 4h")
    price = exchange.candles(symbol, "1h", LOOKBACK["1h"]).price
    watch = Watch(
        pred_id=str(ULID()),
        symbol=symbol,
        created_at=_iso(_now()),
        trigger=trigger,
        level=level,
        timeframe=timeframe,
        stop=stop,
        target=target,
        note=note,
    )
    WatchRepo().add(watch)
    return watch, price


def pending() -> list[Watch]:
    return WatchRepo().pending()


def remove(pred_id: str) -> Watch:
    """Stop an active watch by its id."""
    repo = WatchRepo()
    watch = next((w for w in repo.pending() if w.pred_id == pred_id.upper()), None)
    if watch is None:
        raise WatchError(f"no active watch {pred_id}")
    if watch.status != "active" or not repo.remove(watch, _iso(_now())):
        raise WatchError(f"watch {pred_id} is no longer active (hit or removed)")
    return watch


def find_hit(watch: Watch) -> Hit | None:
    """The first time the watch's level was reached since it was set, if it was."""
    since = datetime.fromisoformat(watch.created_at)
    level = float(watch.level)
    if watch.trigger == "touch_below":
        series = exchange.candles(watch.symbol, "1h", LOOKBACK["1h"])
        for candle in series.candles:
            if candle.ts >= since and candle.low <= level:
                return Hit(candle.ts, candle.low)
        # Cached candles can predate the watch; their latest price then does not count.
        if series.fetched_at >= since and series.price <= level:
            return Hit(series.fetched_at, series.price)
        return None
    timeframe: Timeframe = "4h" if watch.timeframe == "4h" else "1d"
    period = PERIOD[timeframe]
    for candle in exchange.candles(watch.symbol, timeframe, LOOKBACK[timeframe]).candles:
        if not candle.closed or candle.ts + period <= since:
            continue
        crossed = candle.close < level if watch.trigger == "close_below" else candle.close > level
        if crossed:
            return Hit(candle.ts + period, candle.close)
    return None


def check() -> CheckResult:
    """Look at every active watch once and mark the ones that hit."""
    repo = WatchRepo()
    result = CheckResult()
    for watch in repo.pending():
        result.checked += 1
        try:
            hit = find_hit(watch)
        except (SourceError, requests.RequestException) as exc:
            log.warning("no candles", extra={"symbol": watch.symbol, "error": str(exc)})
            if watch.symbol not in result.missing:
                result.missing.append(watch.symbol)
            continue
        if hit is None:
            continue
        marked = repo.mark_hit(watch, _iso(hit.at), Decimal(str(hit.price)))
        if marked is not None:  # None: removed while this run was looking
            result.hits.append(marked)
    return result


def describe(watch: Watch) -> str:
    """``close below 140 (1d)``: the trigger in words."""
    words = watch.trigger.replace("_", " ")
    timeframe = f" ({watch.timeframe})" if watch.timeframe else ""
    return f"{words} {plain(watch.level)}{timeframe}"


def alert(watch: Watch) -> str:
    """One line for the user: ``Watch hit: SOL close below 140 (1d): 138.2 at ...``."""
    parts = [
        f"Watch hit: {watch.symbol} {describe(watch)}: {plain(watch.hit_price)} at {watch.hit_at}."
    ]
    if watch.stop is not None:
        parts.append(f"Stop {plain(watch.stop)}.")
    if watch.target is not None:
        parts.append(f"Target {plain(watch.target)}.")
    if watch.note:
        parts.append(f"Note: {watch.note}.")
    return " ".join(parts)
