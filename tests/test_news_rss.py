from datetime import UTC, datetime

import pytest

from sentinel.data import news_rss

# The recorded feed's newest item is from 17 Oct 2026, 12:58 UTC.
NOW = datetime(2026, 10, 17, 14, 0, tzinfo=UTC)


def test_feeds_merge_each_link_once_from_the_last_day(apis):
    # `apis` serves the same feed as "Cointelegraph" and "Mirror".
    feeds = news_rss.recent(NOW)
    titles = [item.headline.title for item in feeds.items]
    # Two items are over 24 h old, among them an older Solana headline.
    assert len(titles) == 4
    assert titles[0].startswith("Solana shows resilience")
    assert {item.headline.source for item in feeds.items} == {"Cointelegraph"}
    assert feeds.failed == []
    assert [h.title for h in feeds.coin("SOL")] == [titles[0]]
    assert [h.title for h in feeds.market(2)] == titles[:2]


@pytest.mark.live
def test_live_rss():
    feeds = news_rss.recent()
    assert feeds.failed == []
    assert feeds.market()
