import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from click.testing import CliRunner

from sentinel.cli import cli
from sentinel.data import cmc, feargreed, newsapi
from sentinel.eval.rules import rules_signal

# The `apis` fixture (conftest.py) serves these fixtures from local servers.
FIXTURES = Path(__file__).parent / "fixtures"
LISTINGS = "/v1/cryptocurrency/listings/latest"
QUOTES = "/v1/cryptocurrency/quotes/latest"
GLOBAL = "/v1/global-metrics/quotes/latest"
CMC_INVALID_KEY = (401, {}, {"status": {"error_code": 1001, "error_message": "API key invalid"}})


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _run(*args):
    return CliRunner().invoke(cli, list(args))


def _json(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


# --- clients ---------------------------------------------------------------------------


def test_listings_parse_and_send_the_key_in_a_header(apis):
    coins = cmc.listings(5)
    assert [c.symbol for c in coins] == ["BTC", "ETH", "USDT", "SOL", "XRP"]
    assert coins[0].vol_mc == pytest.approx(30e9 / 1.6e12)
    request = apis.cmc.seen[0]
    assert request.headers["X-CMC_PRO_API_KEY"] == apis.keys.cmc
    assert apis.keys.cmc not in request.path


def test_global_metrics_tolerate_missing_fields(apis):
    # Field names are not confirmed by CMC's docs yet (test_live_cmc checks them).
    apis.cmc.routes[GLOBAL] = (200, {}, {"status": {"error_code": 0}, "data": {}})
    assert cmc.global_metrics() == cmc.Market(None, None, None)


def test_news_asks_for_ticker_and_name_and_drops_unrelated_titles(apis):
    items = newsapi.headlines("SOL", limit=3)
    # "Puerta del Sol" is dropped: the ticker counts only in capitals.
    assert [h.source for h in items] == ["Example Wire", "Example Markets"]
    request = apis.news.seen[0]
    query = parse_qs(urlsplit(request.path).query)
    # "Solana" is CMC's name for SOL (the listing fixture).
    terms = '("SOL" OR "Solana") AND (crypto OR cryptocurrency OR blockchain OR token)'
    assert (query["q"], query["language"], query["sortBy"]) == ([terms], ["en"], ["popularity"])
    assert request.headers["X-Api-Key"] == apis.keys.news
    assert apis.keys.news not in request.path


def test_coin_names_without_cmc_fall_back_to_config(apis):
    apis.cmc.routes["/v1/cryptocurrency/listings/latest"] = (500, {})
    assert (newsapi.coin_names("SOL"), newsapi.coin_names("BTC")) == ((), ("Bitcoin",))


def test_world_news_once_per_title_without_removed_articles(apis):
    story = {"source": {"name": "Example Wire"}, "title": "Fed holds rates", "url": "u1"}
    copy = {**story, "source": {"name": "Example Copy"}, "url": "u2"}
    removed = {"source": {"name": "[Removed]"}, "title": "[Removed]", "url": "u3"}
    others = [{**story, "title": f"Story {i}", "url": f"s{i}"} for i in range(5)]
    apis.news.routes["/v2/everything"] = (
        200,
        {},
        {"status": "ok", "articles": [story, copy, removed, *others]},
    )
    lines = _run("news", "world", "--format", "telegram").stdout.strip().splitlines()
    # 5 of 6 distinct stories (the default limit); Telegram has room for 4 under the head.
    assert lines == [
        "World news, 3 days, most read first (about 24 h delayed): 5, 4 shown",
        "- Fed holds rates (Example Wire)",
        *[f"- Story {i} (Example Wire)" for i in range(3)],
    ]
    query = parse_qs(urlsplit(apis.news.seen[0].path).query)
    assert (query["q"], query["searchIn"]) == ([newsapi.WORLD_QUERY], ["title"])


# --- legacy rules (RULES baseline) -----------------------------------------------------


@pytest.mark.parametrize(
    ("fear_greed", "change_24h", "vol_mc", "signal"),
    [
        (25, -6.0, 0.01, "DCA BUY"),
        (25, -4.0, 0.01, "HOLD"),
        (80, 3.0, 0.01, "REDUCE/TP"),
        (50, 0.0, 0.2, "VOLATILITY ALERT"),
        (None, -9.0, 0.5, "HOLD"),
    ],
)
def test_rules_signal(fear_greed, change_24h, vol_mc, signal):
    assert rules_signal(fear_greed, change_24h, vol_mc) == signal


# --- commands --------------------------------------------------------------------------


def test_overview_json(apis):
    result = _run("market", "overview", "--symbol", "BTC,SOL")
    data = _json(result)
    assert data["market"] == {
        "fear_greed": 41,
        "btc_dominance": 58.1,
        "total_mcap_chg_24h": 1.23,
        "stablecoin_share": 7.9,
    }
    assert [c["symbol"] for c in data["coins"]] == ["BTC", "SOL"]
    assert "missing" not in data
    assert len(result.stdout) < 500  # lands in the agent's context


def test_overview_telegram(apis):
    result = _run("market", "overview", "--symbol", "BTC,SOL", "--format", "telegram")
    lines = result.stdout.strip().splitlines()
    assert lines == [
        "Market: F&G 41, BTC dom 58.1%, mcap +1.2% 24h, stables 7.9%",
        "BTC $81,250 (+1.2% 24h)",
        "SOL $72.60 (-1.5% 24h)",
    ]


def test_overview_survives_a_missing_source(apis):
    apis.fng.routes["/fng/"] = (404, {})
    data = _json(_run("market", "overview", "--symbol", "BTC,NOPE"))
    assert data["market"]["fear_greed"] is None
    assert data["missing"] == ["feargreed"]
    assert data["unknown_symbols"] == ["NOPE"]


def test_top_uses_the_legacy_rules(apis):
    data = _json(_run("market", "top", "--limit", "5"))
    signals = {c["symbol"]: c["signal"] for c in data["coins"]}
    assert signals == {
        "BTC": "HOLD",
        "ETH": "HOLD",
        "USDT": "VOLATILITY ALERT",
        "SOL": "HOLD",
        "XRP": "HOLD",
    }
    fear = _fixture("feargreed.json")
    fear["data"][0]["value"] = "25"
    apis.fng.routes["/fng/"] = (200, {}, fear)
    text = _run("market", "top", "--limit", "5", "--format", "telegram").stdout
    assert "ETH: DCA BUY (-6.3% 24h)" in text


def test_scalp_skips_stablecoins_and_pumped_coins(apis):
    data = _json(_run("market", "scalp", "--limit", "5"))
    assert [c["symbol"] for c in data["candidates"]] == ["SOL", "XRP"]  # not USDT, not ETH


def test_weekly_candles_cover_two_years(trending):
    text = _run("market", "candles", "SOL", "--format", "telegram").stdout
    assert text.splitlines() == [
        "SOL weekly, 104 candles from 26 Oct 2024",
        "Close $90.22 then, now $100.00 (+10.8%)",
        "High $101.00 (17 Oct 2026), low $89.32 (26 Oct 2024)",
    ]
    data = _json(_run("market", "candles", "SOL"))
    assert (len(data["candles"]), data["last_open"], data["high"]["price"]) == (104, True, 101.0)


@pytest.mark.parametrize(("symbol", "alert"), [("SOL", True), ("BTC", False)])
def test_whales(apis, symbol, alert):
    assert _json(_run("market", "whales", symbol))["alert"] is alert


def test_news_telegram(apis):
    result = _run("news", "long", "SOL", "--format", "telegram")
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "SOL news, 14 days, most read first (about 24 h delayed): 2"
    assert len(lines) <= 5


def test_news_says_when_nothing_is_relevant(apis):
    apis.news.routes["/v2/everything"] = (200, {}, {"status": "ok", "articles": []})
    data = _json(_run("news", "long", "SOL"))
    assert (data["headlines"], data["note"]) == ([], "no relevant headlines")


def test_source_error_is_one_json_line_and_exit_1(apis):
    apis.cmc.routes[LISTINGS] = CMC_INVALID_KEY
    result = _run("market", "top")
    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error == f"CMC {LISTINGS}: HTTP 401, error 1001"


# One command per keyed source; JSON and telegram share the same error and log paths.
@pytest.mark.parametrize("failing", [False, True])
@pytest.mark.parametrize(
    "command", [["market", "overview", "--symbol", "BTC,SOL"], ["news", "long", "SOL"]]
)
def test_keys_never_leak(apis, monkeypatch, command, failing):
    monkeypatch.setenv("SENTINEL_LOG_LEVEL", "DEBUG")
    if failing:
        for path in (QUOTES, GLOBAL):
            apis.cmc.routes[path] = CMC_INVALID_KEY
        apis.news.routes["/v2/everything"] = (401, {}, {"status": "error", "code": "apiKeyInvalid"})
    result = _run(*command)
    everything = result.stdout + result.stderr
    assert result.stdout.strip()
    assert apis.keys.cmc not in everything
    assert apis.keys.news not in everything


# --- live smoke tests (opt-in: pytest -m live, under aws-vault) ------------------------


@pytest.mark.live
def test_live_cmc():
    assert len(cmc.listings(3)) == 3
    assert "BTC" in cmc.quotes(["BTC"])
    market = cmc.global_metrics()  # confirms the global-metrics field names
    assert market.btc_dominance and market.stablecoin_share
    assert market.total_mcap_chg_24h is not None


@pytest.mark.live
def test_live_fear_and_greed():
    assert 0 <= feargreed.latest().value <= 100


@pytest.mark.live
def test_live_newsapi():
    assert newsapi.headlines("BTC", limit=1)
