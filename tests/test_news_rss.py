from datetime import UTC, datetime, timedelta

import pytest
from click.testing import CliRunner

from sentinel import config
from sentinel.alerts import news as alerts_news
from sentinel.cli import cli
from sentinel.data import SourceError, news_rss
from sentinel.data.newsapi import Headline

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
    assert [h.title for h in feeds.market()] == [titles[3]]  # the one Bitcoin headline


def test_items_dated_after_now_are_dropped(apis):
    # An hour before the newest item, so that item counts as dated in the future.
    early = datetime(2026, 10, 17, 11, 58, tzinfo=UTC)
    assert len(news_rss.recent(early).items) == 3


def test_no_feeds_configured(apis, monkeypatch):
    monkeypatch.setattr(config, "NEWS_FEEDS", {})
    config.get_settings.cache_clear()
    assert news_rss.recent(NOW) == news_rss.Feeds([], [])


def test_news_alert_names_each_major_headline_once(monkeypatch):
    def item(title, minutes_ago, url):
        published = NOW - timedelta(minutes=minutes_ago)
        return news_rss.Item(Headline(title=title, source="CoinDesk", url=url), published)

    feeds = news_rss.Feeds(
        [
            item("Binance hacked: $2.5B drained from a hot wallet", 20, "https://a/hack"),
            item("Exchange halts withdrawals after the breach", 40, "https://a/halt"),
            item("Bitcoin ETF inflows rise for a third day", 30, "https://a/etf"),
            item("Protocol exploit drains $40M", 180, "https://a/old"),  # before the lookback
        ],
        [],
    )
    monkeypatch.setattr(news_rss, "recent", lambda now: feeds)
    monkeypatch.setattr(alerts_news, "_now", lambda: NOW)
    run = CliRunner()
    first = run.invoke(cli, ["news", "alert", "--format", "telegram"]).output
    assert first.splitlines() == [
        "⚠️ Binance hacked: $2.5B drained from a hot wallet (CoinDesk)",
        "⚠️ Exchange halts withdrawals after the breach (CoinDesk)",
        "Ask your AI agent what it means for your coins.",
    ]
    # The next run sends nothing new; a news outage stays silent too.
    assert run.invoke(cli, ["news", "alert", "--format", "telegram"]).output == "NO_REPLY\n"

    def down(now):
        raise SourceError("RSS: every feed failed")

    monkeypatch.setattr(news_rss, "recent", down)
    assert run.invoke(cli, ["news", "alert", "--format", "telegram"]).stdout == "NO_REPLY\n"


@pytest.mark.live
def test_live_rss():
    feeds = news_rss.recent()
    assert feeds.failed == []
    assert feeds.items
