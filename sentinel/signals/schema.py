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


class Market(BaseModel):
    fear_greed: int | None
    total_mcap_chg_24h: float | None
    stablecoin_share: float | None


class Macro(BaseModel):
    next_fomc: date
    days_to_fomc: int


class Headline(BaseModel):
    title: str
    source: str


class Flow(BaseModel):
    funding_pct: float
    funding_interval_h: float
    oi_usd: float
    oi_chg_7d: float | None
    long_short: float


class Technicals(BaseModel):
    rsi14: float | None
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
    coin_news: list[Headline] | None
    news_delayed_24h: bool = True
    flow: Flow | None
    technicals: Technicals | None
    levels: Levels | None
    vs_btc: VsBtc | None
    missing: list[str]
