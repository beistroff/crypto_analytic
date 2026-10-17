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


def test_snapshot_in_hierarchy_order_and_within_budget(trending):
    long_title = {"source": {"name": "Example Wire"}, "title": "Solana " + "x" * 300, "url": "u"}
    trending.news.routes["/v2/everything"] = (
        200,
        {},
        {"status": "ok", "articles": [long_title] * 3},
    )
    out = _run("SOL")
    data = json.loads(out)
    assert list(data) == HIERARCHY
    assert len(out) < MAX_CHARS
    assert data["missing"] == []
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
    data = json.loads(_run("BTC"))
    assert data["vs_btc"] is None
    assert data["technicals"]["rsi14"] == 100.0
    assert data["missing"] == []


def test_missing_sources_become_null(trending):
    trending.okx.routes[flow.FUNDING] = (200, {}, {"code": "51001", "data": [], "msg": ""})
    trending.fng.routes["/fng/"] = (200, {}, {"data": []})  # malformed reply
    trending.news.routes["/v2/everything"] = (401, {}, {"status": "error", "code": "apiKeyInvalid"})
    data = json.loads(_run("NOPE"))
    assert data["missing"] == ["candles", "feargreed", "news", "flow"]
    assert [data[k] for k in ("price", "flow", "technicals", "levels", "vs_btc")] == [None] * 5
    assert data["market"]["fear_greed"] is None
    assert data["btc"]["regime"] == "risk_on"
    text = _run("NOPE", "--format", "telegram")
    assert text.strip().splitlines()[-1] == "Missing: candles, feargreed, news, flow"
