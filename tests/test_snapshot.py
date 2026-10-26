import json
from dataclasses import replace

import pytest
from click.testing import CliRunner

from sentinel.cli import cli
from sentinel.data import exchange, flow
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
    "setup",
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
    """An RSS feed of ``count`` long headlines naming Solana and Bitcoin, from the last
    hour (they fill both the coin's and the market's list)."""
    items = "".join(
        f"<item><title>Solana and Bitcoin {i} {'x' * 300}</title>"
        f"<link>https://example.com/{i}</link>"
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
    # Money flow: volume against yesterday, the share outside BTC, and spot takers (a
    # live OKX reply: 36,612 bought at the ask against 29,295 sold).
    assert (data["market"]["vol_chg_24h"], data["market"]["alt_vol_share"]) == (-12.3, 60.0)
    assert data["flow"]["taker_buy_pct"] == 55.6
    assert len(data["coin_news"][0]["title"]) == snapshot.TITLE_WIDTH
    # 7-day wick low: the oldest of the last 7 days (an uptrend), 6 days before today.
    assert data["levels"]["d7"]["wick_low"] == pytest.approx(100 * 1.001**-6 * 0.99, rel=1e-5)
    assert data["levels"]["d7"]["wick_low_date"] == "2026-10-11"
    assert data["vs_btc"]["rs_7d"] == 0.0  # the same trend as BTC
    assert data["technicals"]["rsi14_4h"] == data["technicals"]["rsi14_1h"] == 100.0
    # 4h candles: the price is 100 and each finished close 0.1% below the next one. Of the
    # last 12 (48 h) the highest finished close is one candle back, the wick low 11 back;
    # every true range is 2% of its close, so the 4h ATR is 1.974 (2% of the recent closes).
    setup = data["setup"]
    assert setup["trigger"] == pytest.approx(100 * 1.001**-1, rel=1e-5)
    assert setup["stop"] == pytest.approx(100 * 1.001**-11 * 0.99 - 0.25 * 1.974, abs=1e-3)
    # 100 - 97.424 = 2.576: 2.58% and 1.3 ATR away, so outside the noise.
    assert (setup["stop_pct"], setup["stop_atr"], setup["stop_in_noise"]) == (2.58, 1.3, False)
    # Pullback: 4h SMA50 (the mean of the last 50 closes) up to the 48 h close low.
    sma50 = sum(100 * 1.001**-k for k in range(50)) / 50
    assert setup["pullback_low"] == pytest.approx(sma50, rel=1e-5)
    assert setup["pullback_high"] == pytest.approx(100 * 1.001**-11, rel=1e-5)
    assert setup["room_pct"] == 1.0  # today's daily wick high is 1% above the price
    assert len(_run("SOL", "--format", "telegram").strip().splitlines()) == 5  # nothing missing


def test_stop_inside_half_a_day_is_noise(trending):
    # Daily candles 10% wide: the daily ATR is about 10, so a stop 2.58 away (1.3 ATR on
    # 4h) is inside half a day's swing.
    h4 = exchange.candles("SOL", "4h", snapshot.H4_LIMIT)
    daily = exchange.candles("SOL", "1d", snapshot.DAILY_LIMIT)
    wide = [replace(c, high=c.close * 1.05, low=c.close * 0.95) for c in daily.candles]
    setup = snapshot._setup(h4, replace(daily, candles=wide), 100.0, None)
    assert (setup.stop_atr, setup.stop_in_noise) == (1.3, True)


def test_btc_snapshot_has_no_comparison_with_itself(trending):
    trending.rss.routes["/mirror"] = (404, {})
    data = json.loads(_run("BTC"))
    assert data["vs_btc"] is None
    assert data["technicals"]["rsi14"] == 100.0
    # The other feed still answers. Of its two Bitcoin headlines one is over 24 h old; the
    # other is shown as coin news, so the market headlines (BTC's) have none left.
    assert data["missing"] == ["rss:Mirror"]
    assert [h["title"][:20] for h in data["coin_news_fresh"]] == ["Bitcoin price steadi"]
    assert data["market"]["headlines"] == []


def test_coin_without_a_swap_has_no_flow_and_nothing_missing(trending):
    trending.okx.routes[flow.FUNDING] = (200, {}, {"code": "51001", "data": [], "msg": ""})
    data = json.loads(_run("XMR"))
    assert (data["flow"], data["missing"]) == (None, [])


def test_missing_sources_become_null(trending):
    trending.okx.routes[flow.FUNDING] = (500, {})
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
