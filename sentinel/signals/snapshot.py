"""One coin's snapshot in the signal hierarchy (plan, Appendix C).

BTC first (its regime outweighs the coin's own signal), then market mood, macro, the
coin's news, derivatives flow and the coin's technicals, range levels and strength
against BTC. Code computes every number; the agent reads them and decides.

Sources are fetched in parallel. A source that fails becomes ``null`` and is named in
``missing``, so one bad source never fails the whole snapshot. Candles come from
``sentinel.data.exchange`` (cached for 5 minutes, so BTC is fetched once per scan).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

import requests

from sentinel import aws
from sentinel.config import get_settings
from sentinel.data import SourceError, cmc, exchange, feargreed, flow, newsapi
from sentinel.signals import btc_regime, indicators, schema

DAILY_LIMIT = 300  # SMA200 plus 90 days for beta
HOURLY_LIMIT = 200  # 7 days of hourly closes, with room to spare
NEWS_LIMIT = 3
TITLE_WIDTH = 120

log = logging.getLogger(__name__)


def build(symbol: str) -> schema.Snapshot:
    symbol = symbol.upper()
    now = _now()
    jobs: dict[str, Callable[[], Any]] = {
        "btc_daily": lambda: exchange.candles("BTC", "1d", DAILY_LIMIT),
        "btc_hourly": lambda: exchange.candles("BTC", "1h", HOURLY_LIMIT),
        "feargreed": feargreed.latest,
        "cmc_global": cmc.global_metrics,
        "news": lambda: newsapi.headlines(symbol, NEWS_LIMIT),
        "flow": lambda: flow.flow(symbol),
    }
    if symbol != "BTC":
        jobs["daily"] = lambda: exchange.candles(symbol, "1d", DAILY_LIMIT)
        jobs["hourly"] = lambda: exchange.candles(symbol, "1h", HOURLY_LIMIT)
    got = _fetch(jobs)
    if symbol == "BTC":
        got["daily"], got["hourly"] = got.get("btc_daily"), got.get("btc_hourly")

    missing = []
    btc_daily, btc_hourly = got.get("btc_daily"), got.get("btc_hourly")
    if btc_daily is None or btc_hourly is None:
        missing.append("btc_candles")
    daily, hourly = got.get("daily"), got.get("hourly")
    if symbol != "BTC" and (daily is None or hourly is None):
        missing.append("candles")
    missing += [name for name in ("feargreed", "cmc_global", "news", "flow") if name not in got]
    macro = _macro(now)
    if macro is None:
        missing.append("fomc_calendar")

    metrics = got.get("cmc_global")
    coin_technicals = technicals(daily, hourly) if daily and hourly else None
    btc_technicals = technicals(btc_daily, btc_hourly) if btc_daily and btc_hourly else None
    return schema.Snapshot(
        as_of=iso(now),
        symbol=symbol,
        price=sig(hourly.price) if hourly else None,
        prices_at=iso(hourly.fetched_at) if hourly else None,
        exchange=hourly.exchange if hourly else None,
        btc=btc_context(btc_hourly, btc_technicals, metrics) if btc_technicals else None,
        market=schema.Market(
            fear_greed=got["feargreed"].value if "feargreed" in got else None,
            total_mcap_chg_24h=rounded(metrics.total_mcap_chg_24h) if metrics else None,
            stablecoin_share=rounded(metrics.stablecoin_share, 1) if metrics else None,
        ),
        macro=macro,
        coin_news=[_headline(h) for h in got["news"]] if "news" in got else None,
        flow=_flow(got["flow"]) if "flow" in got else None,
        technicals=coin_technicals,
        levels=_levels(daily) if daily else None,
        vs_btc=_vs_btc(daily, btc_daily) if symbol != "BTC" and daily and btc_daily else None,
        missing=missing,
    )


def _fetch(jobs: dict[str, Callable[[], Any]]) -> dict[str, Any]:
    """Run every job in parallel; failed jobs are left out of the result."""
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {name: pool.submit(job) for name, job in jobs.items()}
    results = {}
    for name, future in futures.items():
        try:
            results[name] = future.result()
        # The last four: a reply that is not the expected JSON (e.g. a maintenance page).
        except (
            SourceError,
            aws.SecretError,
            requests.RequestException,
            ValueError,
            KeyError,
            IndexError,
            TypeError,
        ) as exc:
            log.warning("source unavailable", extra={"source": name, "error": type(exc).__name__})
    return results


def technicals(daily: exchange.Candles, hourly: exchange.Candles) -> schema.Technicals:
    closes = [c.close for c in daily.candles]
    price = hourly.price
    sma50, sma200 = indicators.sma(closes, 50), indicators.sma(closes, 200)
    atr = indicators.atr(daily.candles)
    hours = {
        n: indicators.change_over_hours(hourly.candles, n, hourly.fetched_at) for n in (1, 24, 168)
    }
    return schema.Technicals(
        rsi14=rounded(indicators.rsi(closes), 1),
        sma20=sig(indicators.sma(closes, 20)),
        sma50=sig(sma50),
        sma200=sig(sma200),
        above_sma50=None if sma50 is None else price > sma50,
        above_sma200=None if sma200 is None else price > sma200,
        atr14_pct=rounded(atr / price * 100) if atr is not None else None,
        vol_z30=rounded(indicators.volume_z(daily.candles)),
        chg_1h=rounded(hours[1]),
        chg_24h=rounded(hours[24]),
        chg_7d=rounded(hours[168]),
    )


def btc_context(
    hourly: exchange.Candles, tech: schema.Technicals, metrics: cmc.Market | None
) -> schema.BtcContext:
    dominance = rounded(metrics.btc_dominance, 1) if metrics else None
    regime = btc_regime.classify(
        hourly.price, tech.chg_24h, tech.chg_7d, tech.sma50, tech.sma200, dominance
    )
    return schema.BtcContext(
        price=sig(hourly.price),
        chg_24h=tech.chg_24h,
        chg_7d=tech.chg_7d,
        sma50=tech.sma50,
        sma200=tech.sma200,
        above_sma50=tech.above_sma50,
        above_sma200=tech.above_sma200,
        dominance=dominance,
        regime=regime.regime,
        regime_points=regime.points,
    )


def _macro(now: datetime) -> schema.Macro | None:
    today = now.date()
    upcoming = [d for d in get_settings().fomc_decisions if d >= today]
    if not upcoming:
        return None
    return schema.Macro(next_fomc=upcoming[0], days_to_fomc=(upcoming[0] - today).days)


def _headline(item: newsapi.Headline) -> schema.Headline:
    title = item.title if len(item.title) <= TITLE_WIDTH else item.title[: TITLE_WIDTH - 1] + "…"
    return schema.Headline(title=title, source=item.source)


def _flow(item: flow.Flow) -> schema.Flow:
    return schema.Flow(
        funding_pct=round(item.funding_pct, 4),
        funding_interval_h=item.funding_interval_h,
        oi_usd=round(item.oi_usd),
        oi_chg_7d=rounded(item.oi_chg_7d),
        long_short=round(item.long_short, 2),
    )


def _levels(daily: exchange.Candles) -> schema.Levels:
    def edges(days: int) -> schema.Range | None:
        found = indicators.range_edges(daily.candles, days)
        if found is None:
            return None
        return schema.Range(**{k: sig(v) if isinstance(v, float) else v for k, v in found.items()})

    return schema.Levels(d7=edges(7), d30=edges(30))


def _vs_btc(daily: exchange.Candles, btc_daily: exchange.Candles) -> schema.VsBtc:
    coin, btc = daily.candles, btc_daily.candles
    return schema.VsBtc(
        rs_7d=rounded(indicators.relative_strength(coin, btc, 7)),
        rs_14d=rounded(indicators.relative_strength(coin, btc, 14)),
        rs_30d=rounded(indicators.relative_strength(coin, btc, 30)),
        beta_90d=rounded(indicators.beta(coin, btc, 90)),
    )


def _now() -> datetime:
    return datetime.now(UTC)


def iso(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def rounded(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def sig(value: float | None) -> float | None:
    """Prices to 6 significant digits (works for BTC and for tiny coins alike)."""
    return None if value is None else float(f"{value:.6g}")
