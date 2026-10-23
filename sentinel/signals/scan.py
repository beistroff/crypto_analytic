"""Market scan: one short row of computed signals per top coin, BTC's regime first.

Replaces the agent's own top-50 scan (about 33 ``web_fetch`` calls, levels read off raw
candles) with one command: a CMC listings call (1 credit), then per coin its daily
candles and its OKX funding rate, fetched in parallel, plus BTC's hourly candles once.

- BTC's block is the snapshot's (``snapshot.btc_context``), so both commands give the
  same regime. The coins' 24 h and 7 d changes are CMC's rolling changes from the
  listing (no extra request).
- RSI, SMA50/200, strength against BTC and the 7-day wick range come from the daily
  candles (``sentinel.signals.indicators``); ``to_low_7d`` and ``to_high_7d`` are the
  distance in percent from the price to the 7-day wick low and high.
- Stablecoins (CMC's "stablecoin" tag, or the fixed list) and wrapped or staked copies
  of BTC and ETH in the listing are left out and named in ``skipped``. Coins asked for by
  ``wanted`` outside the top N come from one CMC quotes call (1 credit) and are added
  after it; symbols CMC does not know are in ``missing``. Coins without
  candles on any exchange are listed in ``missing``; coins without an OKX swap have no
  funding rate (``null``). When a rate could not be read (rate limit, outage),
  ``missing`` also names ``funding``.
- News is counted, not listed (titles for 50 coins would not fit the agent's context):
  ``news_24h`` is the coin's headlines in the RSS feeds over the last 24 h (one read of
  each feed for the whole scan). Feeds that cannot be read are ``rss`` in ``missing``.

Rows are arrays under ``columns`` to keep the output small for the agent's context.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import astuple, dataclass
from datetime import UTC, datetime
from typing import Any

import requests

from sentinel.data import SourceError, cmc, exchange, flow, news_rss
from sentinel.data.exchange import NotListed
from sentinel.eval.rules import STABLECOINS
from sentinel.signals import indicators, schema, snapshot
from sentinel.signals.snapshot import DAILY_LIMIT, HOURLY_LIMIT, iso, rounded, sig

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
    news_24h: int | None  # RSS headlines in the last 24 h


COLUMNS = list(Row.__dataclass_fields__)


@dataclass(frozen=True)
class Scan:
    as_of: str
    btc: schema.BtcContext | None
    rows: list[Row]
    missing: list[str]
    skipped: list[str]

    def data(self) -> dict[str, Any]:
        return {
            "as_of": self.as_of,
            "btc": self.btc.model_dump(mode="json") if self.btc else None,
            "columns": COLUMNS,
            "rows": [list(astuple(r)) for r in self.rows],
            "missing": self.missing,
            "skipped": self.skipped,
        }


def build(limit: int, wanted: list[str] | None = None) -> Scan:
    now = _now()
    listed = cmc.listings(limit)
    coins, skipped = [], []
    for c in listed:
        if c.is_stablecoin or c.symbol in STABLECOINS | WRAPPED:
            skipped.append(c.symbol)
        else:
            coins.append(c)
    unknown = []
    extra = [s for s in wanted or [] if s not in {c.symbol for c in listed}]
    if extra:
        found = cmc.quotes(extra)
        coins += [found[s] for s in extra if s in found]
        unknown = [s for s in extra if s not in found]
    symbols = [c.symbol for c in coins]
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        feeds_job = pool.submit(_feeds, now)
        daily_jobs = {sym: pool.submit(_candles, sym, "1d") for sym in symbols}
        funding_jobs = {sym: pool.submit(_funding, sym) for sym in symbols}
        btc_hourly_job = pool.submit(_candles, "BTC", "1h")
    daily = {sym: job.result() for sym, job in daily_jobs.items()}
    funding = {sym: job.result() for sym, job in funding_jobs.items()}
    btc_daily, btc_hourly = daily.get("BTC"), btc_hourly_job.result()
    feeds = feeds_job.result()

    rows, missing = [], unknown
    for coin in coins:
        candles = daily[coin.symbol]
        if candles is None:
            missing.append(coin.symbol)
            continue
        # Every headline counts, not just the first few a snapshot would list.
        news_24h = len(feeds.coin(coin.symbol, len(feeds.items))) if feeds else None
        rows.append(_row(coin, candles, btc_daily, funding[coin.symbol][0], news_24h))
    if not all(read for _, read in funding.values()):
        missing.append("funding")  # some rates failed; their null is not "no swap"
    if feeds is None:
        missing.append("rss")
    else:
        missing += [f"rss:{name}" for name in feeds.failed]
    btc = None
    if btc_daily and btc_hourly:
        # The snapshot's own calculation, so both commands give the same regime.
        tech = snapshot.technicals(btc_daily, btc_hourly)
        btc = snapshot.btc_context(btc_hourly, tech, None)
    elif "BTC" not in missing:
        missing.insert(0, "btc")
    return Scan(as_of=iso(now), btc=btc, rows=rows, missing=missing, skipped=skipped)


def _now() -> datetime:
    return datetime.now(UTC)


def _candles(symbol: str, timeframe: exchange.Timeframe) -> exchange.Candles | None:
    limit = DAILY_LIMIT if timeframe == "1d" else HOURLY_LIMIT
    try:
        return exchange.candles(symbol, timeframe, limit)
    except (SourceError, requests.RequestException) as exc:
        log.info("no candles", extra={"symbol": symbol, "error": type(exc).__name__})
        return None


def _funding(symbol: str) -> tuple[float | None, bool]:
    """The funding rate and whether it could be read (a coin without an OKX swap has
    none, which is not a failure)."""
    try:
        return flow.funding(symbol)[0], True
    except NotListed:
        return None, True
    except (
        SourceError,
        requests.RequestException,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
    ) as exc:
        log.warning("funding unavailable", extra={"symbol": symbol, "error": type(exc).__name__})
        return None, False


def _feeds(now: datetime) -> news_rss.Feeds | None:
    try:
        return news_rss.recent(now)
    except SourceError:
        log.warning("news feeds unavailable")
        return None


def _row(
    coin: cmc.Coin,
    daily: exchange.Candles,
    btc_daily: exchange.Candles | None,
    funding_pct: float | None,
    news_24h: int | None,
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
        news_24h=news_24h,
    )
