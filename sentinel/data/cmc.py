"""CoinMarketCap Pro API (Basic plan): listings, quotes and global metrics.

Credits: listings cost 1 per 100 coins, a quotes call 1 per 100 symbols, global metrics 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sentinel import aws, net
from sentinel.data import SourceError

BASE_URL = "https://pro-api.coinmarketcap.com"


@dataclass(frozen=True)
class Coin:
    symbol: str
    price: float
    change_1h: float | None
    change_24h: float
    volume_24h: float
    market_cap: float
    change_7d: float | None = None

    @property
    def vol_mc(self) -> float:
        """24 h volume over market cap: how actively the coin trades."""
        return self.volume_24h / self.market_cap if self.market_cap > 0 else 0.0


@dataclass(frozen=True)
class Market:
    btc_dominance: float | None
    total_mcap_chg_24h: float | None
    stablecoin_share: float | None


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


def global_metrics() -> Market:
    """Market-wide context: BTC dominance, total market cap 24 h change, stablecoin share."""
    data = _get("/v1/global-metrics/quotes/latest", {"convert": "USD"})
    usd = data.get("quote", {}).get("USD", {})
    total = usd.get("total_market_cap")
    stable = usd.get("stablecoin_market_cap")
    share = stable / total * 100 if stable is not None and total else None
    return Market(
        btc_dominance=data.get("btc_dominance"),
        total_mcap_chg_24h=usd.get("total_market_cap_yesterday_percentage_change"),
        stablecoin_share=share,
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
        price=usd["price"],
        change_1h=usd.get("percent_change_1h"),
        change_24h=usd["percent_change_24h"],
        volume_24h=usd.get("volume_24h") or 0.0,
        market_cap=usd.get("market_cap") or 0.0,
        change_7d=usd.get("percent_change_7d"),
    )
