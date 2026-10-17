"""Derivatives flow for a coin from OKX's public endpoints (its USDT perpetual swap).

Checked against the OKX API v5 docs and live calls (17 Oct 2026); no key needed:

- ``/api/v5/public/funding-rate``: ``fundingRate`` is the predicted rate for the
  current period (positive: longs pay shorts). The period is ``nextFundingTime -
  fundingTime``, usually 8 h but OKX can shorten it, so it is reported with the rate.
- ``/api/v5/rubik/stat/contracts/open-interest-history`` with ``period=4H`` and 43
  entries: the newest and the one exactly 7 days before it, ``[ts, oi, oiCcy, oiUsd]``.
  The change is in coins, so a price move alone does not count as new positions.
- ``/api/v5/rubik/stat/contracts/long-short-account-ratio-contract`` with
  ``period=1H``: accounts net long divided by accounts net short.

Coins without an OKX swap raise ``SourceError``; the snapshot lists them as missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sentinel import net
from sentinel.data import SourceError

BASE_URL = "https://www.okx.com"
FUNDING = "/api/v5/public/funding-rate"
OI_HISTORY = "/api/v5/rubik/stat/contracts/open-interest-history"
LONG_SHORT = "/api/v5/rubik/stat/contracts/long-short-account-ratio-contract"
OI_PERIOD = timedelta(hours=4)
OI_DAYS = 7


@dataclass(frozen=True)
class Flow:
    funding_pct: float  # per funding period
    funding_interval_h: float
    oi_usd: float
    oi_chg_7d: float | None  # percent, in coins
    long_short: float
    ts: datetime  # newest open-interest entry


def swap(symbol: str) -> str:
    return f"{symbol.upper()}-USDT-SWAP"


def flow(symbol: str) -> Flow:
    instrument = swap(symbol)
    funding = _get(FUNDING, {"instId": instrument})[0]
    span = OI_DAYS * timedelta(days=1)
    entries = _get(
        OI_HISTORY, {"instId": instrument, "period": "4H", "limit": span // OI_PERIOD + 1}
    )
    long_short = _get(LONG_SHORT, {"instId": instrument, "period": "1H", "limit": 1})[0]

    newest, oldest = entries[0], entries[-1]
    newest_ts = datetime.fromtimestamp(int(newest[0]) / 1000, UTC)
    oldest_ts = datetime.fromtimestamp(int(oldest[0]) / 1000, UTC)
    oi_chg = None
    if newest_ts - oldest_ts == span and float(oldest[2]) > 0:
        oi_chg = (float(newest[2]) / float(oldest[2]) - 1) * 100
    interval_ms = int(funding["nextFundingTime"]) - int(funding["fundingTime"])
    return Flow(
        funding_pct=float(funding["fundingRate"]) * 100,
        funding_interval_h=interval_ms / 3_600_000,
        oi_usd=float(newest[3]),
        oi_chg_7d=oi_chg,
        long_short=float(long_short[1]),
        ts=newest_ts,
    )


def _get(path: str, params: dict[str, Any]) -> list[Any]:
    response = net.session("okx").get(BASE_URL + path, params=params)
    try:
        body = response.json()
    except ValueError:
        body = {}
    code = body.get("code") if isinstance(body, dict) else None
    if response.status_code != 200 or code != "0" or not body.get("data"):
        raise SourceError(f"OKX {path}: HTTP {response.status_code}, code {code}")
    return body["data"]
