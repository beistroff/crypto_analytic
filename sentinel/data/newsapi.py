"""NewsAPI.org headlines.

The free developer plan delivers articles about 24 h late, so this is for longer-range
research, not for what happened today.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sentinel import aws, net
from sentinel.data import SourceError

URL = "https://newsapi.org/v2/everything"


@dataclass(frozen=True)
class Headline:
    title: str
    source: str
    url: str


def headlines(query: str, limit: int = 5) -> list[Headline]:
    """Newest articles about ``query`` from the last day available on the plan."""
    since = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    response = net.session("newsapi").get(
        URL,
        params={"q": query, "sortBy": "publishedAt", "from": since, "pageSize": limit},
        headers={"X-Api-Key": aws.get_secret("newsapi_key")},
    )
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code != 200 or not isinstance(body, dict) or body.get("status") != "ok":
        code = body.get("code") if isinstance(body, dict) else None
        raise SourceError(f"NewsAPI: HTTP {response.status_code}, error {code}")
    return [_headline(article) for article in body.get("articles", [])[:limit]]


def _headline(article: dict) -> Headline:
    return Headline(
        title=article.get("title") or "",
        source=(article.get("source") or {}).get("name") or "",
        url=article.get("url") or "",
    )
