"""CoinMarketCap Pro API (Basic plan): listings, quotes and global metrics.

Credits: listings cost 1 per 100 coins, a quotes call 1 per 100 symbols, global metrics 1.
Coin names (for matching headlines) come from the top 100 listing, cached on disk for a
day: 1 credit a day.
"""

from __future__ import annotations

import functools
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import requests

from sentinel import aws, net
from sentinel.config import get_settings
from sentinel.data import SourceError

BASE_URL = "https://pro-api.coinmarketcap.com"
NAMES_LIMIT = 100
NAMES_MAX_AGE = timedelta(days=1)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Coin:
    symbol: str
    name: str
    price: float
    change_1h: float | None
    change_24h: float
    volume_24h: float
    market_cap: float
    change_7d: float | None = None
    is_stablecoin: bool = False  # CMC's "stablecoin" tag

    @property
    def vol_mc(self) -> float:
        """24 h volume over market cap: how actively the coin trades."""
        return self.volume_24h / self.market_cap if self.market_cap > 0 else 0.0


@dataclass(frozen=True)
class Market:
    btc_dominance: float | None
    total_mcap_chg_24h: float | None
    stablecoin_share: float | None
    vol_chg_24h: float | None = None  # all crypto volume against yesterday's, percent
    alt_vol_share: float | None = None  # percent of the volume outside BTC


def listings(limit: int) -> list[Coin]:
    """Top ``limit`` coins by market cap."""
    data = _get(
        "/v1/cryptocurrency/listings/latest",
        {"start": 1, "limit": limit, "convert": "USD", "sort": "market_cap"},
    )
    return [_coin(raw) for raw in data]


def quotes(symbols: list[str]) -> dict[str, Coin]:
    """Latest quotes for ``symbols`` (one call). Unknown symbols are left out."""
    wanted = [s.upper() for s in symbols]
    data = _get("/v1/cryptocurrency/quotes/latest", {"symbol": ",".join(wanted), "convert": "USD"})
    return {s: _coin(data[s]) for s in wanted if isinstance(data.get(s), dict)}


@functools.cache
def names() -> dict[str, str]:
    """Coin names by ticker for the top 100 (``{"SOL": "Solana"}``), read once per process
    from a file cached for a day. Empty when CMC cannot be reached: headlines are then
    matched by ticker and the aliases in config."""
    path = get_settings().cache_dir / "cmc_names.json"
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if datetime.now(UTC) - datetime.fromisoformat(cached["fetched_at"]) < NAMES_MAX_AGE:
            return cached["names"]
    except (OSError, ValueError, KeyError, TypeError):
        pass  # no cache yet, or an unreadable one
    try:
        found = {c.symbol: c.name for c in listings(NAMES_LIMIT)}
    except (SourceError, aws.SecretError, requests.RequestException, KeyError) as exc:
        log.warning("coin names unavailable", extra={"error": type(exc).__name__})
        return {}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        cached = {"fetched_at": datetime.now(UTC).isoformat(), "names": found}
        path.write_text(json.dumps(cached), encoding="utf-8")
    except OSError as exc:
        log.warning("coin names not cached", extra={"error": type(exc).__name__})
    return found


def global_metrics() -> Market:
    """Market-wide context: BTC dominance, total market cap 24 h change, stablecoin share,
    and where the money trades: the volume's change against yesterday and the share of it
    outside BTC (field names from CMC's API reference, checked 26 Oct 2026)."""
    data = _get("/v1/global-metrics/quotes/latest", {"convert": "USD"})
    usd = data.get("quote", {}).get("USD", {})
    total = usd.get("total_market_cap")
    stable = usd.get("stablecoin_market_cap")
    share = stable / total * 100 if stable is not None and total else None
    volume, alt_volume = usd.get("total_volume_24h"), usd.get("altcoin_volume_24h")
    return Market(
        btc_dominance=data.get("btc_dominance"),
        total_mcap_chg_24h=usd.get("total_market_cap_yesterday_percentage_change"),
        stablecoin_share=share,
        vol_chg_24h=usd.get("total_volume_24h_yesterday_percentage_change"),
        alt_vol_share=alt_volume / volume * 100 if alt_volume is not None and volume else None,
    )


def _get(path: str, params: dict[str, Any]) -> Any:
    key = aws.get_secret("cmc_api_key")
    response = net.session("cmc").get(
        BASE_URL + path, params=params, headers={"X-CMC_PRO_API_KEY": key}
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    code = body.get("status", {}).get("error_code") if isinstance(body, dict) else None
    if response.status_code != 200 or code:
        raise SourceError(f"CMC {path}: HTTP {response.status_code}, error {code}")
    return body["data"]


def _coin(raw: dict[str, Any]) -> Coin:
    usd = raw["quote"]["USD"]
    return Coin(
        symbol=raw["symbol"],
        name=raw["name"],
        price=usd["price"],
        change_1h=usd.get("percent_change_1h"),
        change_24h=usd["percent_change_24h"],
        volume_24h=usd.get("volume_24h") or 0.0,
        market_cap=usd.get("market_cap") or 0.0,
        change_7d=usd.get("percent_change_7d"),
        is_stablecoin="stablecoin" in (raw.get("tags") or []),
    )
