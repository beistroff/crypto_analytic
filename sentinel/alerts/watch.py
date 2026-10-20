"""Watches: price levels the user wants to hear about, checked by code with no LLM.

``check()`` runs from the instance's crontab every 15 minutes. A quiet run costs no tokens.
On a hit it marks the watch, then posts one message to OpenClaw's local hook; the agent
re-checks the coin and pings the user. A watch stays in GSI2 until the post succeeds, so a
failed post is retried on the next run, and the ``Idempotency-Key`` (the watch id) keeps
OpenClaw from acting on the same hit twice.

Triggers:

- ``touch_below``: an hourly low, or the latest price, at or under the level.
- ``close_below`` / ``close_above``: a closed UTC candle (``1d`` by default, or ``4h``)
  closing under / over the level.

Only candles from after the watch was set count: hourly candles that open after it, and
close candles that close after it. Each run looks back about two days (48 hourly, 10
daily or 12 four-hour candles), which covers a crontab that missed a few runs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

import requests
from ulid import ULID

from sentinel import aws, net
from sentinel.data import SourceError, exchange
from sentinel.data.exchange import PERIOD, Timeframe
from sentinel.portfolio.service import plain
from sentinel.store.dynamo import Watch, WatchRepo

TRIGGERS = ("touch_below", "close_below", "close_above")
CLOSE_TIMEFRAMES = ("1d", "4h")
LOOKBACK: dict[Timeframe, int] = {"1h": 48, "1d": 10, "4h": 12}
# The `watch` mapping in OpenClaw's hooks config (README, onboarding); the gateway listens
# on loopback only.
HOOK_URL = "http://127.0.0.1:18789/hooks/watch"
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
    alerted: list[Watch] = field(default_factory=list)
    failed: list[Watch] = field(default_factory=list)  # hit, post failed, retried next run
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
        if series.price <= level:
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
    """Look at every pending watch once; post one alert per hit."""
    repo = WatchRepo()
    result = CheckResult()
    for watch in repo.pending():
        result.checked += 1
        if watch.status == "active":
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
            if marked is None:  # removed while this run was looking
                continue
            watch = marked
        try:
            _post(watch)
        except (SourceError, requests.RequestException) as exc:
            log.warning("hook post failed", extra={"pred_id": watch.pred_id, "error": str(exc)})
            result.failed.append(watch)
            continue
        repo.mark_alerted(watch, _iso(_now()))
        result.alerted.append(watch)
    return result


def describe(watch: Watch) -> str:
    """``close below 140 (1d)``: the trigger in words."""
    words = watch.trigger.replace("_", " ")
    timeframe = f" ({watch.timeframe})" if watch.timeframe else ""
    return f"{words} {plain(watch.level)}{timeframe}"


def message(watch: Watch) -> str:
    """The hook message: a prompt for the agent, which then writes to the user."""
    parts = [
        f"Watch hit: {watch.symbol} {describe(watch)}, "
        f"price {plain(watch.hit_price)} at {watch.hit_at}."
    ]
    if watch.stop is not None:
        parts.append(f"Stop {plain(watch.stop)}.")
    if watch.target is not None:
        parts.append(f"Target {plain(watch.target)}.")
    if watch.note:
        parts.append(f"Note: {watch.note}.")
    parts.append(f"Watch id {watch.pred_id}, set {watch.created_at}.")
    parts.append(
        f"Run `sentinel snapshot {watch.symbol}`, apply the BTC gate and send your human one "
        "short message: is the setup still valid, and what would you do? Your human decides."
    )
    return " ".join(parts)


def _post(watch: Watch) -> None:
    headers = {
        "Authorization": f"Bearer {aws.get_secret('openclaw_hook_token')}",
        "Idempotency-Key": watch.pred_id,
    }
    response = net.session("openclaw").post(
        HOOK_URL, json={"message": message(watch)}, headers=headers
    )
    if not 200 <= response.status_code < 300:
        raise SourceError(f"OpenClaw hook: HTTP {response.status_code}")
