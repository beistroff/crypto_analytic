"""Settings shared by the CLI, the Lambda handlers and the EC2 services.

Defaults match the Terraform envs. A few values can be overridden through environment
variables (see ``ENV_VARS``). Secrets never live here; they come from ``sentinel.secrets``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date
from functools import cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
Exchange = Literal["okx", "kraken"]


class MinIntervals(BaseModel):
    """Minimum seconds between two requests to one source, from each free plan's limit.

    Every source that ``sentinel.net`` may call needs a field here.
    """

    model_config = ConfigDict(frozen=True)

    cmc: float = 2.0  # CoinMarketCap Basic: 30 requests per minute
    feargreed: float = 1.0  # alternative.me: 60 requests per minute
    newsapi: float = 1.0  # NewsAPI.org developer plan: 100 requests per day
    gemini: float = 0.0  # readiness check only; model calls go through the SDK
    okx: float = 0.05  # OKX public market data: 40 candle requests per 2 s per IP
    kraken: float = 1.0  # Kraken public API: about 1 request per second
    rss: float = 0.0  # news feeds on different sites, each read once per call


class HttpSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    timeout_s: float = 10.0
    retries: int = 3
    # Wait before retries 1, 2 and 3: 1x, 2x and 4x this, at least the source's interval.
    backoff_s: float = 1.0
    # A longer Retry-After (e.g. a used-up daily quota) returns the response at once.
    retry_after_max_s: float = 30.0
    min_interval_s: MinIntervals = Field(default_factory=MinIntervals)


# Names a coin goes by in headlines besides its ticker and its CMC name (top 100, from
# ``cmc.names``). A ticker alone matches unrelated words ("SOL" in Spanish, "ONE", "LINK"),
# so news queries search for both. Bitcoin and Ethereum are kept for when CMC is down.
COIN_NAMES: dict[str, tuple[str, ...]] = {
    "BTC": ("Bitcoin",),
    "ETH": ("Ethereum", "Ether"),
    "XRP": ("Ripple",),
    "BNB": ("Binance Coin",),
}

# Free crypto news feeds (no key, minutes old, unlike NewsAPI's free plan), by the name
# shown as a headline's source. All four answered with valid RSS 2.0 on 2026-10-17.
NEWS_FEEDS: dict[str, str] = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "The Block": "https://www.theblock.co/rss.xml",
    "Decrypt": "https://decrypt.co/feed",
}


# FOMC rate decisions (the second day of each meeting), from the Federal Reserve's
# calendar (federalreserve.gov/monetarypolicy/fomccalendars.htm, checked 2026-10-17).
# Dates are tentative until the meeting before; add the next year when the Fed publishes it.
FOMC_DECISIONS: tuple[date, ...] = (
    date(2026, 10, 28),
    date(2026, 12, 9),
    date(2027, 1, 27),
    date(2027, 3, 17),
    date(2027, 4, 28),
    date(2027, 6, 9),
    date(2027, 7, 28),
    date(2027, 9, 15),
    date(2027, 10, 27),
    date(2027, 12, 8),
)


# USD per million tokens in and out for the paid models (Anthropic list prices, checked
# 2026-10-25). Gemini runs on the free tier and costs nothing.
LLM_PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
}


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    region: str = "us-east-1"
    real_table: str = "sentinel-real"
    sim_table: str = "sentinel-sim"
    backup_bucket: str = "openclaw-files"
    # WARNING keeps CLI calls quiet; services set INFO.
    log_level: LogLevel = "WARNING"
    http: HttpSettings = Field(default_factory=HttpSettings)
    coin_names: dict[str, tuple[str, ...]] = Field(default_factory=lambda: dict(COIN_NAMES))
    news_feeds: dict[str, str] = Field(default_factory=lambda: dict(NEWS_FEEDS))
    # Candle sources in the order tried. Binance answers HTTP 451 from AWS, so it is not one.
    exchanges: tuple[Exchange, ...] = ("okx", "kraken")
    candle_cache_s: float = 300.0
    cache_dir: Path = Path("~/.cache/sentinel").expanduser()
    fomc_decisions: tuple[date, ...] = FOMC_DECISIONS
    llm_prices: dict[str, tuple[float, float]] = Field(default_factory=lambda: dict(LLM_PRICES))

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


# Environment variable for each overridable field. bootstrap.sh exports AWS_REGION and
# OPENCLAW_S3_BUCKET on the instance; the Lambda runtime sets AWS_REGION.
ENV_VARS = {
    "region": "AWS_REGION",
    "real_table": "SENTINEL_REAL_TABLE",
    "sim_table": "SENTINEL_SIM_TABLE",
    "backup_bucket": "OPENCLAW_S3_BUCKET",
    "log_level": "SENTINEL_LOG_LEVEL",
    "cache_dir": "SENTINEL_CACHE_DIR",
}


def load(env: Mapping[str, str] | None = None) -> Settings:
    """Defaults plus the overrides set in ``env`` (``os.environ`` when omitted)."""
    env = os.environ if env is None else env
    return Settings(**{field: env[var] for field, var in ENV_VARS.items() if env.get(var)})


@cache
def get_settings() -> Settings:
    """Settings for this process, read from the environment once."""
    return load()
