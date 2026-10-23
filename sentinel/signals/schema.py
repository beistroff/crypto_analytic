"""Pydantic models for what the agent reads. Field order is the reading order."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from sentinel.signals.btc_regime import Label

SNAPSHOT_SCHEMA = 1


class BtcContext(BaseModel):
    price: float
    chg_24h: float | None
    chg_7d: float | None
    sma50: float | None
    sma200: float | None
    above_sma50: bool | None
    above_sma200: bool | None
    dominance: float | None
    regime: Label
    regime_points: int


class Headline(BaseModel):
    title: str
    source: str


class Market(BaseModel):
    fear_greed: int | None
    total_mcap_chg_24h: float | None
    stablecoin_share: float | None
    headlines: list[Headline] | None  # BTC's, from RSS, last 24 h, newest first


class Macro(BaseModel):
    next_fomc: date
    days_to_fomc: int


class Flow(BaseModel):
    funding_pct: float
    funding_interval_h: float
    oi_usd: float
    oi_chg_7d: float | None
    long_short: float


class Technicals(BaseModel):
    rsi14: float | None
    rsi14_4h: float | None
    rsi14_1h: float | None
    sma20: float | None
    sma50: float | None
    sma200: float | None
    above_sma50: bool | None
    above_sma200: bool | None
    atr14_pct: float | None
    vol_z30: float | None
    chg_1h: float | None
    chg_24h: float | None
    chg_7d: float | None


class Range(BaseModel):
    """Wick edges are candle lows and highs (today's included); close edges are closes
    of finished days. The two are different levels and are never mixed."""

    wick_low: float
    wick_low_date: date
    wick_high: float
    wick_high_date: date
    close_low: float
    close_high: float


class Levels(BaseModel):
    d7: Range | None
    d30: Range | None


class Setup(BaseModel):
    """A trade of 12 h to 7 days, on 4h candles. Trigger: a 4h close above the highest
    4h close of the last 48 h. Stop: 0.25 ATR (4h) under the 48 h wick low; its distance
    from the price in % and in ATR, flagged ``stop_in_noise`` under 1 ATR. Pullback zone:
    4h SMA50 to the 48 h close low, only while the price is above the SMA50. Room: from
    the price to the 30-day wick high, in %."""

    trigger: float
    stop: float
    stop_pct: float
    stop_atr: float
    stop_in_noise: bool
    pullback_low: float | None
    pullback_high: float | None
    room_pct: float | None


class VsBtc(BaseModel):
    """Return difference against BTC in percentage points (positive: stronger than BTC),
    and beta of daily returns to BTC's over 90 days."""

    rs_7d: float | None
    rs_14d: float | None
    rs_30d: float | None
    beta_90d: float | None


class Snapshot(BaseModel):
    schema_version: int = SNAPSHOT_SCHEMA
    as_of: str
    symbol: str
    price: float | None
    prices_at: str | None
    exchange: str | None
    btc: BtcContext | None
    market: Market | None
    macro: Macro | None
    coin_news_fresh: list[Headline] | None  # RSS, last 24 h
    coin_news: list[Headline] | None  # NewsAPI, about a day old
    news_delayed_24h: bool = True
    flow: Flow | None
    technicals: Technicals | None
    levels: Levels | None
    setup: Setup | None
    vs_btc: VsBtc | None
    missing: list[str]
