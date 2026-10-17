import json

import pytest
from click.testing import CliRunner

from sentinel.cli import cli
from sentinel.data import flow
from sentinel.signals import snapshot

HIERARCHY = [
    "schema_version",
    "as_of",
    "symbol",
    "price",
    "prices_at",
    "exchange",
    "btc",
    "market",
    "macro",
    "coin_news_fresh",
    "coin_news",
    "news_delayed_24h",
    "flow",
    "technicals",
    "levels",
    "vs_btc",
    "missing",
]
# About 4 characters per token: 1,500 tokens.
MAX_CHARS = 6000


def _run(*args):
    result = CliRunner().invoke(cli, ["snapshot", *args])
    assert result.exit_code == 0, result.output
    return result.stdout


def _long_feed(count):
    """An RSS feed of ``count`` long Solana headlines from the last hour."""
    items = "".join(
        f"<item><title>Solana {i} {'x' * 300}</title><link>https://example.com/{i}</link>"
        "<pubDate>Sat, 17 Oct 2026 12:00:00 +0000</pubDate></item>"
        for i in range(count)
    )
    return f'<rss version="2.0"><channel><title>t</title>{items}</channel></rss>'.encode()


def test_snapshot_in_hierarchy_order_and_within_budget(trending):
    long_title = {"source": {"name": "Example Wire"}, "title": "Solana " + "x" * 300, "url": "u"}
    trending.news.routes["/v2/everything"] = (
        200,
        {},
        {"status": "ok", "articles": [long_title] * 3},
    )
    trending.rss.routes["/rss"] = (200, {}, _long_feed(10))
    out = _run("SOL")
    data = json.loads(out)
    assert list(data) == HIERARCHY
    assert len(out) < MAX_CHARS
    assert data["missing"] == []
    assert len(data["market"]["headlines"]) == snapshot.MARKET_NEWS_LIMIT
    assert len(data["coin_news_fresh"]) == snapshot.NEWS_LIMIT
    assert data["as_of"] == "2026-10-17T12:20:00Z"
    assert data["btc"]["regime"] == "risk_on"  # above both averages, up 18% in 7 days
    assert data["macro"] == {"next_fomc": "2026-10-28", "days_to_fomc": 11}
    assert len(data["coin_news"][0]["title"]) == snapshot.TITLE_WIDTH
    # 7-day wick low: the oldest of the last 7 days (an uptrend), 6 days before today.
    assert data["levels"]["d7"]["wick_low"] == pytest.approx(100 * 1.001**-6 * 0.99, rel=1e-5)
    assert data["levels"]["d7"]["wick_low_date"] == "2026-10-11"
    assert data["vs_btc"]["rs_7d"] == 0.0  # the same trend as BTC
    assert len(_run("SOL", "--format", "telegram").strip().splitlines()) == 4  # nothing missing


def test_btc_snapshot_has_no_comparison_with_itself(trending):
    trending.rss.routes["/mirror"] = (404, {})
    data = json.loads(_run("BTC"))
    assert data["vs_btc"] is None
    assert data["technicals"]["rsi14"] == 100.0
    # The other feed still answers; of its two Bitcoin headlines one is over 24 h old.
    assert data["missing"] == ["rss:Mirror"]
    assert len(data["market"]["headlines"]) == 4
    assert [h["title"][:20] for h in data["coin_news_fresh"]] == ["Bitcoin price steadi"]


def test_missing_sources_become_null(trending):
    trending.okx.routes[flow.FUNDING] = (200, {}, {"code": "51001", "data": [], "msg": ""})
    trending.fng.routes["/fng/"] = (200, {}, {"data": []})  # malformed reply
    trending.news.routes["/v2/everything"] = (401, {}, {"status": "error", "code": "apiKeyInvalid"})
    trending.rss.routes["/rss"] = (200, {}, b"<html>maintenance</html>")  # not a feed
    trending.rss.routes["/mirror"] = (404, {})
    data = json.loads(_run("NOPE"))
    assert data["missing"] == ["candles", "feargreed", "rss", "news", "flow"]
    nulls = ("price", "coin_news_fresh", "flow", "technicals", "levels", "vs_btc")
    assert [data[k] for k in nulls] == [None] * 6
    assert data["market"]["fear_greed"] is data["market"]["headlines"] is None
    assert data["btc"]["regime"] == "risk_on"
    text = _run("NOPE", "--format", "telegram")
    assert text.strip().splitlines()[-1] == "Missing: candles, feargreed, rss, news, flow"
