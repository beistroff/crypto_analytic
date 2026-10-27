"""Exchange candles from public, keyless endpoints: OKX first, Kraken as the fallback.

Plain ``requests`` through ``sentinel.net`` rather than ``ccxt``: two endpoints only, the
same timeouts, retries, rate limits and logging as every other source, and no large
library to import on each CLI call. Binance is not used: it answers HTTP 451 from AWS.

- Daily candles are UTC days. OKX's ``1D`` bar runs on Hong Kong time (16:00 to 16:00
  UTC), so daily candles always ask for ``1Dutc``; Kraken's days are UTC already.
- Pairs come from the CMC ticker: ``SOL`` is ``SOL-USDT`` on OKX and ``SOLUSD`` on Kraken.
  A coin not listed on one exchange (OKX has no XMR) is fetched from the next one in
  ``settings.exchanges``; the order there decides which exchange is used.
- Every result carries its candles' UTC open times; the last candle is usually still
  open, so its close is the latest price. Volume is in the quote currency (USD or USDT).
- Results are cached in files for ``settings.candle_cache_s`` (5 minutes), so a scan of
  several coins fetches BTC once.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import requests

from sentinel import net
from sentinel.config import Exchange, get_settings
from sentinel.data import SourceError

Timeframe = Literal["1w", "1d", "4h", "1h", "15m"]
PERIOD = {
    "1w": timedelta(weeks=1),
    "1d": timedelta(days=1),
    "4h": timedelta(hours=4),
    "1h": timedelta(hours=1),
    "15m": timedelta(minutes=15),
}

OKX_URL = "https://www.okx.com/api/v5/market/candles"
# 4H, 1H and 15m bars start at the same times in UTC and in Hong Kong time; 1D and 1W
# differ. 1Wutc weeks start on Monday 00:00 UTC; Kraken's weekly candles start on another
# weekday.
OKX_BARS = {"1w": "1Wutc", "1d": "1Dutc", "4h": "4H", "1h": "1H", "15m": "15m"}
OKX_MAX_LIMIT = 300
OKX_NOT_LISTED = "51001"

KRAKEN_URL = "https://api.kraken.com/0/public/OHLC"
KRAKEN_INTERVALS = {"1w": 10080, "1d": 1440, "4h": 240, "1h": 60, "15m": 15}
KRAKEN_NOT_LISTED = "EQuery:Unknown asset pair"

SYMBOL = re.compile(r"[A-Z0-9]{1,20}")

log = logging.getLogger(__name__)


class NotListed(SourceError):
    """The exchange has no such pair."""


@dataclass(frozen=True)
class Candle:
    ts: datetime  # open time, UTC
    open: float
    high: float
    low: float
    close: float
    volume: float  # quote currency
    closed: bool


@dataclass(frozen=True)
class Candles:
    symbol: str
    exchange: Exchange
    pair: str
    timeframe: Timeframe
    candles: list[Candle]  # oldest first
    fetched_at: datetime

    @property
    def price(self) -> float:
        return self.candles[-1].close


def pair(exchange: Exchange, symbol: str) -> str:
    """Exchange pair for a CMC ticker."""
    symbol = symbol.upper()
    return f"{symbol}-USDT" if exchange == "okx" else f"{symbol}USD"


def candles(symbol: str, timeframe: Timeframe, limit: int = 200) -> Candles:
    """The newest ``limit`` candles from the first exchange in ``settings.exchanges`` that
    lists the coin. Another exchange is tried when one fails or does not list it."""
    symbol = symbol.upper()
    # The ticker becomes part of a cache file name, so only plain tickers pass.
    if not SYMBOL.fullmatch(symbol):
        raise SourceError(f"not a ticker: {symbol!r}")
    errors = []
    for exchange in get_settings().exchanges:
        try:
            return _cached(exchange, symbol, timeframe, limit)
        except NotListed:
            errors.append(f"{exchange}: not listed")
        except (SourceError, requests.RequestException) as exc:
            log.warning("exchange failed", extra={"exchange": exchange, "error": str(exc)})
            errors.append(f"{exchange}: {exc}")
        except (ValueError, KeyError, IndexError, TypeError) as exc:  # not the expected JSON
            log.warning(
                "exchange reply malformed",
                extra={"exchange": exchange, "error": type(exc).__name__},
            )
            errors.append(f"{exchange}: malformed reply")
    raise SourceError(f"no candles for {symbol} ({'; '.join(errors)})")


def history(symbol: str, timeframe: Timeframe, limit: int) -> Candles:
    """Like ``candles``, but when the first exchange has fewer candles than asked (a coin
    it listed recently: OKX has ZEC only since November 2025), the exchange with the most
    candles wins. Costs one more request, and only for such coins."""
    best = candles(symbol, timeframe, limit)
    for exchange in get_settings().exchanges:
        if len(best.candles) >= limit:
            break
        if exchange == best.exchange:
            continue
        try:
            other = _cached(exchange, best.symbol, timeframe, limit)
        except (
            SourceError,
            requests.RequestException,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
        ):
            continue  # the first exchange's shorter history is still an answer
        if len(other.candles) > len(best.candles):
            best = other
    return best


def _cached(exchange: Exchange, symbol: str, timeframe: Timeframe, limit: int) -> Candles:
    settings = get_settings()
    path = settings.cache_dir / "candles" / f"{exchange}-{symbol}-{timeframe}-{limit}.json"
    now = _now()
    hit = _read_cache(path)
    if hit is not None and now - hit.fetched_at < timedelta(seconds=settings.candle_cache_s):
        return hit
    fetch = _okx if exchange == "okx" else _kraken
    rows = fetch(pair(exchange, symbol), timeframe, limit)
    result = _candles(symbol, exchange, timeframe, rows, now)
    _write_cache(path, result, rows)
    return result


def _okx(instrument: str, timeframe: Timeframe, limit: int) -> list[list[float]]:
    # More than 300 candles (the Naive Bayes dataset's years of days) come in pages, each
    # older than the last one's oldest candle.
    rows: list[list[Any]] = []
    while len(rows) < limit:
        params = {"instId": instrument, "bar": OKX_BARS[timeframe]}
        params["limit"] = min(limit - len(rows), OKX_MAX_LIMIT)
        if rows:
            params["after"] = rows[-1][0]
        response = net.session("okx").get(OKX_URL, params=params)
        body = _body(response)
        code = body.get("code")
        if code == OKX_NOT_LISTED:
            raise NotListed(f"OKX has no {instrument}")
        if response.status_code != 200 or code != "0":
            raise SourceError(f"OKX candles: HTTP {response.status_code}, code {code}")
        rows.extend(body["data"])
        if len(body["data"]) < params["limit"]:
            break  # no older candles
    # [ts ms, open, high, low, close, vol, volCcy, volCcyQuote, confirm], newest first
    return [[float(r[0]), *map(float, r[1:5]), float(r[7])] for r in reversed(rows)]


def _kraken(pair_name: str, timeframe: Timeframe, limit: int) -> list[list[float]]:
    params = {"pair": pair_name, "interval": KRAKEN_INTERVALS[timeframe]}
    response = net.session("kraken").get(KRAKEN_URL, params=params)
    body = _body(response)
    errors = body.get("error") or []
    if KRAKEN_NOT_LISTED in errors:
        raise NotListed(f"Kraken has no {pair_name}")
    if response.status_code != 200 or errors:
        raise SourceError(f"Kraken OHLC: HTTP {response.status_code}, {', '.join(errors)}")
    # The result key is Kraken's own pair name (XXMRZUSD), next to "last".
    rows = next((v for k, v in body["result"].items() if k != "last"), [])
    # [time s, open, high, low, close, vwap, volume, count], oldest first; vwap * volume
    # is the volume in USD, comparable with OKX's quote volume.
    return [[r[0] * 1000.0, *map(float, r[1:5]), float(r[5]) * float(r[6])] for r in rows[-limit:]]


def _now() -> datetime:
    return datetime.now(UTC)


def _body(response: requests.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        body = None
    return body if isinstance(body, dict) else {}


def _candles(
    symbol: str,
    exchange: Exchange,
    timeframe: Timeframe,
    rows: list[list[float]],
    fetched_at: datetime,
) -> Candles:
    if not rows:
        raise SourceError(f"{exchange}: no {timeframe} candles for {symbol}")
    period = PERIOD[timeframe]
    items = []
    for ts_ms, o, h, low, c, volume in rows:
        ts = datetime.fromtimestamp(ts_ms / 1000, UTC)
        items.append(Candle(ts, o, h, low, c, volume, closed=ts + period <= fetched_at))
    return Candles(symbol, exchange, pair(exchange, symbol), timeframe, items, fetched_at)


def _read_cache(path: Path) -> Candles | None:
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(cached["fetched_at"])
        rows = cached["rows"]
        return _candles(cached["symbol"], cached["exchange"], cached["timeframe"], rows, fetched_at)
    except (OSError, ValueError, KeyError, TypeError, SourceError):
        return None


def _write_cache(path: Path, result: Candles, rows: list[list[float]]) -> None:
    cached = {
        "symbol": result.symbol,
        "exchange": result.exchange,
        "timeframe": result.timeframe,
        "fetched_at": result.fetched_at.isoformat(),
        "rows": rows,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(cached), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        log.warning("candle cache not written", extra={"error": type(exc).__name__})
