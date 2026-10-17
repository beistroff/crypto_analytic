"""Market scan: one short row of computed signals per top coin, BTC's regime first.

Replaces the agent's own top-50 scan (about 33 ``web_fetch`` calls, levels read off raw
candles) with one command: a CMC listings call (1 credit), then per coin its daily
candles and its OKX funding rate, fetched in parallel. BTC comes from the same list.

- 24 h and 7 d changes are CMC's rolling changes from the listing (no extra request).
- RSI, SMA50/200, strength against BTC and the 7-day wick range come from the daily
  candles (``sentinel.signals.indicators``); ``to_low_7d`` and ``to_high_7d`` are the
  distance in percent from the price to the 7-day wick low and high.
- Stablecoins and wrapped or staked copies of BTC and ETH are skipped. Coins without
  candles on any exchange are listed in ``missing``; coins without an OKX swap have no
  funding rate (``null``).

Rows are arrays under ``columns`` to keep the output small for the agent's context.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import astuple, dataclass
from datetime import UTC, datetime
from typing import Any

import requests

from sentinel.data import SourceError, cmc, exchange, flow
from sentinel.eval.rules import STABLECOINS
from sentinel.signals import btc_regime, indicators
from sentinel.signals.snapshot import DAILY_LIMIT, iso, rounded, sig

# Copies of BTC and ETH that only repeat their signals.
WRAPPED = frozenset({"WBTC", "CBBTC", "BTCB", "WETH", "STETH", "WSTETH", "WEETH", "RETH"})
WORKERS = 8

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Row:
    sym: str
    price: float | None
    chg_24h: float | None
    chg_7d: float | None
    rsi14: float | None
    above_sma50: bool | None
    above_sma200: bool | None
    rs_7d: float | None  # percentage points against BTC
    to_low_7d: float | None
    to_high_7d: float | None
    funding_pct: float | None


COLUMNS = list(Row.__dataclass_fields__)


@dataclass(frozen=True)
class Scan:
    as_of: str
    btc: dict[str, Any] | None
    rows: list[Row]
    missing: list[str]

    def data(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "btc": self.btc,
            "columns": COLUMNS,
            "rows": [list(astuple(r)) for r in self.rows],
            "missing": self.missing,
        }


def build(limit: int) -> Scan:
    now = _now()
    coins = [c for c in cmc.listings(limit) if c.symbol not in STABLECOINS | WRAPPED]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        daily_jobs = {c.symbol: pool.submit(_daily, c.symbol) for c in coins}
        funding_jobs = {c.symbol: pool.submit(_funding, c.symbol) for c in coins}
    daily = {sym: job.result() for sym, job in daily_jobs.items()}
    btc_daily = daily.get("BTC") or _daily("BTC")

    rows, missing = [], []
    for coin in coins:
        candles = daily[coin.symbol]
        if candles is None:
            missing.append(coin.symbol)
            continue
        rows.append(_row(coin, candles, btc_daily, funding_jobs[coin.symbol].result()))
    btc_coin = next((c for c in coins if c.symbol == "BTC"), None)
    btc = _btc(btc_coin, btc_daily) if btc_coin and btc_daily else None
    if btc is None:
        missing.insert(0, "btc")
    return Scan(as_of=iso(now), btc=btc, rows=rows, missing=missing)


def _now() -> datetime:
    return datetime.now(UTC)


def _daily(symbol: str) -> exchange.Candles | None:
    try:
        return exchange.candles(symbol, "1d", DAILY_LIMIT)
    except (SourceError, requests.RequestException) as exc:
        log.info("no candles", extra={"symbol": symbol, "error": type(exc).__name__})
        return None


def _funding(symbol: str) -> float | None:
    try:
        return flow.funding(symbol)[0]
    except (SourceError, requests.RequestException):
        return None  # no OKX swap for this coin


def _row(
    coin: cmc.Coin,
    daily: exchange.Candles,
    btc_daily: exchange.Candles | None,
    funding_pct: float | None,
) -> Row:
    closes = [c.close for c in daily.candles]
    price = daily.price
    sma50, sma200 = indicators.sma(closes, 50), indicators.sma(closes, 200)
    week = indicators.range_edges(daily.candles, 7)
    rs = None
    if btc_daily is not None and coin.symbol != "BTC":
        rs = indicators.relative_strength(daily.candles, btc_daily.candles, 7)
    return Row(
        sym=coin.symbol,
        price=sig(price),
        chg_24h=rounded(coin.change_24h),
        chg_7d=rounded(coin.change_7d),
        rsi14=rounded(indicators.rsi(closes), 1),
        above_sma50=None if sma50 is None else price > sma50,
        above_sma200=None if sma200 is None else price > sma200,
        rs_7d=rounded(rs),
        to_low_7d=rounded(indicators.pct(week["wick_low"], price)) if week else None,
        to_high_7d=rounded(indicators.pct(week["wick_high"], price)) if week else None,
        funding_pct=None if funding_pct is None else round(funding_pct, 4),
    )


def _btc(coin: cmc.Coin, daily: exchange.Candles) -> dict[str, Any]:
    closes = [c.close for c in daily.candles]
    sma50, sma200 = indicators.sma(closes, 50), indicators.sma(closes, 200)
    regime = btc_regime.classify(daily.price, coin.change_24h, coin.change_7d, sma50, sma200)
    return {
        "price": sig(daily.price),
        "chg_24h": rounded(coin.change_24h),
        "chg_7d": rounded(coin.change_7d),
        "regime": regime.regime,
        "regime_points": regime.points,
    }
