"""Headlines from free crypto news feeds (RSS, no key).

Unlike NewsAPI's free plan these are minutes old, not a day. Feeds are read in parallel
and merged: newest first, each link once, the last 24 h only. A feed that fails is
skipped and named in ``Feeds.failed``; only when every feed fails is it an error.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import requests

from sentinel import net
from sentinel.config import get_settings
from sentinel.data import SourceError
from sentinel.data.newsapi import Headline, names_coin

WINDOW = timedelta(hours=24)
# Feeds are optional extras: give up sooner than the 10 s default so one slow feed does
# not hold up the whole snapshot.
TIMEOUT_S = 5

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Item:
    headline: Headline
    published: datetime


@dataclass(frozen=True)
class Feeds:
    items: list[Item]  # newest first
    failed: list[str]

    def market(self, limit: int = 5, skip: frozenset[str] = frozenset()) -> list[Headline]:
        """The newest headlines across all feeds, leaving out the links in ``skip``
        (as ``plain_link`` gives them)."""
        found = [i.headline for i in self.items if plain_link(i.headline.url) not in skip]
        return found[:limit]

    def coin(self, symbol: str, limit: int = 5) -> list[Headline]:
        """The newest headlines that name the coin (its ticker in capitals, or its name)."""
        ticker = symbol.upper()
        names = get_settings().coin_names.get(ticker, ())
        found = [i.headline for i in self.items if names_coin(i.headline.title, ticker, names)]
        return found[:limit]


def recent(now: datetime | None = None) -> Feeds:
    """Every configured feed's items from the 24 h before ``now``."""
    now = now or datetime.now(UTC)
    feeds = get_settings().news_feeds
    if not feeds:
        return Feeds([], [])
    with ThreadPoolExecutor(max_workers=len(feeds)) as pool:
        futures = {name: pool.submit(_read, name, url) for name, url in feeds.items()}
    items, failed = [], []
    for name, future in futures.items():
        try:
            items += future.result()
        except (SourceError, requests.RequestException) as exc:
            log.warning("feed unavailable", extra={"source": name, "error": type(exc).__name__})
            failed.append(name)
    if feeds and len(failed) == len(feeds):
        raise SourceError("RSS: every feed failed")
    seen, merged = set(), []
    for item in sorted(items, key=lambda i: i.published, reverse=True):
        link = plain_link(item.headline.url)
        if now - WINDOW <= item.published <= now and link not in seen:
            seen.add(link)
            merged.append(item)
    return Feeds(merged, failed)


def _read(name: str, url: str) -> list[Item]:
    # Imported here: it takes about 0.4 s, which commands that read no feed should not pay.
    import feedparser

    response = net.session("rss").get(url, timeout=TIMEOUT_S)
    if response.status_code != 200:
        raise SourceError(f"RSS {name}: HTTP {response.status_code}")
    parsed = feedparser.parse(response.content)
    # No version: no RSS or Atom found (e.g. a maintenance page).
    if not parsed.version:
        raise SourceError(f"RSS {name}: not a feed")
    items = []
    for entry in parsed.entries:
        stamp = entry.get("published_parsed") or entry.get("updated_parsed")
        title, link = (entry.get("title") or "").strip(), entry.get("link") or ""
        # Without a date there is no telling whether it is from the last 24 h.
        if stamp and title and link:
            published = datetime(*stamp[:6], tzinfo=UTC)
            items.append(Item(Headline(title=title, source=name, url=link), published))
    return items


def plain_link(url: str) -> str:
    """The link without query, fragment or trailing slash (feeds add tracking tags)."""
    parts = urlsplit(url)
    return f"{parts.netloc.lower()}{parts.path.rstrip('/')}"
