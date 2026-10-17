import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import boto3
import pytest
from click.testing import CliRunner
from moto import mock_aws

from sentinel import net
from sentinel.cli import cli
from sentinel.config import HttpSettings
from sentinel.data import cmc, feargreed, newsapi
from sentinel.eval.rules import rules_signal

FIXTURES = Path(__file__).parent / "fixtures"
CMC_KEY = "cmc-test-value"
NEWS_KEY = "news-test-value"
LISTINGS = "/v1/cryptocurrency/listings/latest"
QUOTES = "/v1/cryptocurrency/quotes/latest"
GLOBAL = "/v1/global-metrics/quotes/latest"
CMC_INVALID_KEY = (401, {}, {"status": {"error_code": 1001, "error_message": "API key invalid"}})


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def apis(make_server, monkeypatch):
    """Keys in a mocked SSM, and local CMC, Fear & Greed and NewsAPI serving the fixtures."""
    with mock_aws():
        ssm = boto3.client("ssm", region_name="us-east-1")
        ssm.put_parameter(Name="/sentinel/cmc_api_key", Value=CMC_KEY, Type="SecureString")
        ssm.put_parameter(Name="/sentinel/newsapi_key", Value=NEWS_KEY, Type="SecureString")
        servers = SimpleNamespace(cmc=make_server(), fng=make_server(), news=make_server())
        servers.cmc.routes.update(
            {
                LISTINGS: (200, {}, _fixture("cmc_listings.json")),
                QUOTES: (200, {}, _fixture("cmc_quotes.json")),
                GLOBAL: (200, {}, _fixture("cmc_global.json")),
            }
        )
        servers.fng.routes["/fng/"] = (200, {}, _fixture("feargreed.json"))
        servers.news.routes["/v2/everything"] = (200, {}, _fixture("newsapi.json"))
        monkeypatch.setattr(cmc, "BASE_URL", servers.cmc.base)
        monkeypatch.setattr(feargreed, "URL", f"{servers.fng.base}/fng/")
        monkeypatch.setattr(newsapi, "URL", f"{servers.news.base}/v2/everything")
        fast = HttpSettings(backoff_s=0, min_interval_s={"cmc": 0, "feargreed": 0, "newsapi": 0})
        sessions = {name: net.Session(name, fast) for name in ("cmc", "feargreed", "newsapi")}
        monkeypatch.setattr(net, "_sessions", sessions)
        yield servers


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
    assert request.headers["X-CMC_PRO_API_KEY"] == CMC_KEY
    assert CMC_KEY not in request.path


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
    terms = '("SOL" OR "Solana") AND (crypto OR cryptocurrency OR blockchain OR token)'
    assert (query["q"], query["language"]) == ([terms], ["en"])
    assert request.headers["X-Api-Key"] == NEWS_KEY
    assert NEWS_KEY not in request.path


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


@pytest.mark.parametrize(("symbol", "alert"), [("SOL", True), ("BTC", False)])
def test_whales(apis, symbol, alert):
    assert _json(_run("market", "whales", symbol))["alert"] is alert


@pytest.mark.parametrize(
    ("levels", "zone"),
    [
        (["--below", "75"], "buy"),
        (["--above", "70"], "sell"),
        (["--below", "60", "--above", "80"], None),
    ],
)
def test_watch_levels(apis, levels, zone):
    assert _json(_run("watch", "levels", "SOL", *levels))["zone"] == zone


def test_watch_levels_needs_a_level(apis):
    assert _run("watch", "levels", "SOL").exit_code == 2


def test_watch_move(apis):
    data = _json(_run("watch", "move", "SOL", "--entry", "70"))
    assert (data["chg_pct"], data["alert"]) == (3.71, True)
    assert _json(_run("watch", "move", "SOL", "--entry", "70", "--min-pct", "5"))["alert"] is False


def test_news_telegram(apis):
    result = _run("news", "long", "SOL", "--format", "telegram")
    lines = result.stdout.strip().splitlines()
    assert lines[0] == "SOL news (about 24 h delayed): 2"
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
    assert CMC_KEY not in everything
    assert NEWS_KEY not in everything


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
