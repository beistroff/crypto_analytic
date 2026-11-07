"""US stock indexes' latest daily move, from Yahoo Finance's public chart API (no key).

For the daily brief only: a stock sell-off (an AI or rate scare) often reaches crypto.
"""

from __future__ import annotations

from urllib.parse import quote

from sentinel import net
from sentinel.data import SourceError

URL = "https://query1.finance.yahoo.com/v8/finance/chart/"
INDEXES = {"S&P 500": "^GSPC", "Nasdaq": "^IXIC"}


def moves() -> dict[str, float]:
    """Each index's change in % against the close before its latest session (live while
    the US market is open)."""
    out = {}
    for name, ticker in INDEXES.items():
        response = net.session("yahoo").get(
            URL + quote(ticker), params={"range": "5d", "interval": "1d"}
        )
        if response.status_code != 200:
            raise SourceError(f"Yahoo {ticker}: HTTP {response.status_code}")
        try:
            quote_ = response.json()["chart"]["result"][0]["indicators"]["quote"][0]
            closes = [c for c in quote_["close"] if c is not None]
            out[name] = round((closes[-1] / closes[-2] - 1) * 100, 2)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise SourceError(f"Yahoo {ticker}: unexpected reply") from exc
    return out
