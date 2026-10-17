"""NewsAPI.org headlines.

The free developer plan delivers articles about 24 h late, so this is for longer-range
research, not for what happened today.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sentinel import aws, net
from sentinel.config import get_settings
from sentinel.data import SourceError

URL = "https://newsapi.org/v2/everything"
# An article must also mention one of these, so "Solana" the surname or "SOL" in Spanish
# do not count as coin news.
CRYPTO_WORDS = ("crypto", "cryptocurrency", "blockchain", "token")
# Ask for more articles than needed: some are dropped as unrelated.
FETCH_FACTOR = 4
MAX_PAGE_SIZE = 20


@dataclass(frozen=True)
class Headline:
    title: str
    source: str
    url: str


def headlines(symbol: str, limit: int = 5) -> list[Headline]:
    """Newest English headlines that name the coin (its ticker or full name)."""
    ticker = symbol.upper()
    names = get_settings().coin_names.get(ticker, ())
    terms = " OR ".join(f'"{term}"' for term in (ticker, *names))
    since = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    params = {
        "q": f"({terms}) AND ({' OR '.join(CRYPTO_WORDS)})",
        "searchIn": "title,description",
        "language": "en",
        "sortBy": "publishedAt",
        "from": since,
        "pageSize": min(limit * FETCH_FACTOR, MAX_PAGE_SIZE),
    }
    response = net.session("newsapi").get(
        URL, params=params, headers={"X-Api-Key": aws.get_secret("newsapi_key")}
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code != 200 or not isinstance(body, dict) or body.get("status") != "ok":
        code = body.get("code") if isinstance(body, dict) else None
        raise SourceError(f"NewsAPI: HTTP {response.status_code}, error {code}")
    items = [_headline(article) for article in body.get("articles", [])]
    return [h for h in items if names_coin(h.title, ticker, names)][:limit]


def names_coin(title: str, ticker: str, names: tuple[str, ...]) -> bool:
    """Does the title name the coin? The ticker counts only in capitals ("SOL", not "sol")."""
    if re.search(rf"\b{re.escape(ticker)}\b", title):
        return True
    return any(re.search(rf"\b{re.escape(name)}\b", title, re.IGNORECASE) for name in names)


def _headline(article: dict) -> Headline:
    return Headline(
        title=article.get("title") or "",
        source=(article.get("source") or {}).get("name") or "",
        url=article.get("url") or "",
    )
