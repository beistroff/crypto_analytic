"""NewsAPI.org headlines, most read first.

The free developer plan delivers articles about 24 h late, so this is context (the RSS
feeds in ``news_rss`` have today's news): a coin's most read stories of the last 14 days,
and the world news of the last 3 days that moves markets beyond crypto.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sentinel import aws, net
from sentinel.config import get_settings
from sentinel.data import SourceError, cmc

URL = "https://newsapi.org/v2/everything"
# An article must also mention one of these, so "Solana" the surname or "SOL" in Spanish
# do not count as coin news.
CRYPTO_WORDS = ("crypto", "cryptocurrency", "blockchain", "token")
# Ask for more articles than needed: some are dropped as unrelated.
FETCH_FACTOR = 4
MAX_PAGE_SIZE = 20
COIN_DAYS = 14
WORLD_DAYS = 3
# Titles only: rates, inflation, recession, trade, US policy, bans, war and AI, in stories
# about markets.
WORLD_QUERY = (
    '("Federal Reserve" OR Fed OR "interest rates" OR inflation OR recession OR tariffs '
    'OR SEC OR regulation OR ban OR sanctions OR war OR "artificial intelligence" OR AI) '
    'AND (crypto OR bitcoin OR markets OR stocks OR economy OR "Wall Street")'
)
# NewsAPI's placeholder for an article taken down since.
REMOVED = "[Removed]"


@dataclass(frozen=True)
class Headline:
    title: str
    source: str
    url: str


def headlines(symbol: str, limit: int = 5) -> list[Headline]:
    """The coin's most read English headlines of the last 14 days (ticker or name)."""
    ticker = symbol.upper()
    names = coin_names(ticker)
    terms = " OR ".join(f'"{term}"' for term in (ticker, *names))
    query = f"({terms}) AND ({' OR '.join(CRYPTO_WORDS)})"
    items = _search(query, "title,description", COIN_DAYS, limit * FETCH_FACTOR)
    return [h for h in items if names_coin(h.title, ticker, names)][:limit]


def world(limit: int = 5) -> list[Headline]:
    """The most read headlines of the last 3 days on what moves markets beyond crypto,
    each title once (one story is often syndicated under the same title)."""
    found: dict[str, Headline] = {}
    for item in _search(WORLD_QUERY, "title", WORLD_DAYS, limit * FETCH_FACTOR):
        found.setdefault(item.title.lower(), item)
    return list(found.values())[:limit]


def _search(query: str, search_in: str, days: int, page_size: int) -> list[Headline]:
    since = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "q": query,
        "searchIn": search_in,
        "language": "en",
        "sortBy": "popularity",
        "from": since,
        "pageSize": min(page_size, MAX_PAGE_SIZE),
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
    return [h for h in items if h.title and h.title != REMOVED]


def coin_names(ticker: str) -> tuple[str, ...]:
    """The coin's CMC name plus its extra aliases in config (``Ether``, ``Ripple``)."""
    found = (cmc.names().get(ticker), *get_settings().coin_names.get(ticker, ()))
    return tuple(dict.fromkeys(n for n in found if n and n != ticker))


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
