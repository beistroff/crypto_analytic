"""Shared test setup: no network, fake AWS credentials, fresh module state per test."""

import json
import logging
import socket
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import boto3
import pytest
from moto import mock_aws

from sentinel import aws, log, net
from sentinel.config import ENV_VARS, HttpSettings, get_settings
from sentinel.data import SourceError, cmc, exchange, feargreed, flow, newsapi
from sentinel.data.exchange import Candle, Candles
from sentinel.signals import scan, snapshot

FIXTURES = Path(__file__).parent / "fixtures"
_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    """Fail on any connection beyond localhost, unless the test is marked live."""
    if request.node.get_closest_marker("live"):
        return
    connect = socket.socket.connect

    def guarded(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOCAL_HOSTS:
            raise RuntimeError(f"network access in a unit test: {address!r}")
        return connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture(autouse=True)
def _isolated_env(request, monkeypatch, tmp_path):
    """Fake AWS credentials, no AWS config files, no overrides from the developer's shell,
    and a fresh cache folder.

    Live tests keep the real environment (run them under aws-vault).
    """
    if request.node.get_closest_marker("live"):
        return
    for var in [*ENV_VARS.values(), "AWS_PROFILE", "AWS_DEFAULT_PROFILE"]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "aws-credentials"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("SENTINEL_CACHE_DIR", str(tmp_path / "cache"))


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    get_settings.cache_clear()
    aws.clear_cache()
    monkeypatch.setattr(net, "_sessions", {})
    monkeypatch.setattr(log, "_secrets", set())
    loggers = [logging.getLogger(), *map(logging.getLogger, log._QUIET_LOGGERS)]
    levels = [logger.level for logger in loggers]
    yield
    if log._handler is not None:
        logging.getLogger().removeHandler(log._handler)
        log._handler = None
    for logger, level in zip(loggers, levels, strict=True):
        logger.setLevel(level)


@pytest.fixture
def make_server():
    """Start local HTTP servers that answer scripted replies, then 200 ``{"ok": true}``.

    Append ``(status, headers)`` or ``(status, headers, json_body)`` to ``.replies``
    (used once each, in order), or set ``.routes[path]`` to answer every request for
    that path (without query string). ``.seen`` lists each request's path and headers.
    """
    servers = []

    def start():
        replies = []
        routes = {}
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(SimpleNamespace(path=self.path, headers=dict(self.headers)))
                route = routes.get(self.path.split("?")[0])
                reply = replies.pop(0) if replies else route or (200, {})
                body = json.dumps(reply[2] if len(reply) > 2 else {"ok": True}).encode()
                self.send_response(reply[0])
                for name, value in reply[1].items():
                    self.send_header(name, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        # A short poll interval keeps shutdown() quick in teardown.
        threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True).start()
        servers.append(httpd)
        base = f"http://127.0.0.1:{httpd.server_port}"
        return SimpleNamespace(
            base=base, url=f"{base}/v1/quotes", replies=replies, routes=routes, seen=seen
        )

    yield start
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def server(make_server):
    return make_server()


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def apis(make_server, monkeypatch):
    """Keys in a mocked SSM, and local CMC, Fear & Greed, NewsAPI, OKX and Kraken servers
    answering with the recorded fixtures. Sessions have no waits."""
    with mock_aws():
        ssm = boto3.client("ssm", region_name="us-east-1")
        keys = SimpleNamespace(cmc="cmc-test-value", news="news-test-value")
        ssm.put_parameter(Name="/sentinel/cmc_api_key", Value=keys.cmc, Type="SecureString")
        ssm.put_parameter(Name="/sentinel/newsapi_key", Value=keys.news, Type="SecureString")
        servers = SimpleNamespace(
            keys=keys,
            cmc=make_server(),
            fng=make_server(),
            news=make_server(),
            okx=make_server(),
            kraken=make_server(),
        )
        servers.cmc.routes.update(
            {
                "/v1/cryptocurrency/listings/latest": (200, {}, load_fixture("cmc_listings.json")),
                "/v1/cryptocurrency/quotes/latest": (200, {}, load_fixture("cmc_quotes.json")),
                "/v1/global-metrics/quotes/latest": (200, {}, load_fixture("cmc_global.json")),
            }
        )
        servers.fng.routes["/fng/"] = (200, {}, load_fixture("feargreed.json"))
        servers.news.routes["/v2/everything"] = (200, {}, load_fixture("newsapi.json"))
        servers.okx.routes.update(
            {
                "/api/v5/market/candles": (200, {}, load_fixture("okx_candles.json")),
                flow.FUNDING: (200, {}, load_fixture("okx_funding.json")),
                flow.OI_HISTORY: (200, {}, load_fixture("okx_oi_history.json")),
                flow.LONG_SHORT: (200, {}, load_fixture("okx_long_short.json")),
            }
        )
        servers.kraken.routes["/0/public/OHLC"] = (200, {}, load_fixture("kraken_ohlc.json"))
        monkeypatch.setattr(cmc, "BASE_URL", servers.cmc.base)
        monkeypatch.setattr(feargreed, "URL", f"{servers.fng.base}/fng/")
        monkeypatch.setattr(newsapi, "URL", f"{servers.news.base}/v2/everything")
        monkeypatch.setattr(exchange, "OKX_URL", f"{servers.okx.base}/api/v5/market/candles")
        monkeypatch.setattr(exchange, "KRAKEN_URL", f"{servers.kraken.base}/0/public/OHLC")
        monkeypatch.setattr(flow, "BASE_URL", servers.okx.base)
        names = ("cmc", "feargreed", "newsapi", "okx", "kraken")
        fast = HttpSettings(backoff_s=0, min_interval_s=dict.fromkeys(names, 0))
        monkeypatch.setattr(net, "_sessions", {name: net.Session(name, fast) for name in names})
        yield servers


# 17 Oct 2026, 12:20 UTC, for the `trending` fixture.
TRENDING_NOW = datetime(2026, 10, 17, 12, 20, tzinfo=UTC)


def _trend_candles(symbol, timeframe, limit=200):
    """A steady uptrend of 0.1% per candle ending at the base price, the last one open."""
    if symbol == "NOPE":
        raise SourceError("no candles for NOPE")
    period = exchange.PERIOD[timeframe]
    end = (
        datetime(2026, 10, 17, tzinfo=UTC) if timeframe == "1d" else TRENDING_NOW.replace(minute=0)
    )
    base = 80000.0 if symbol == "BTC" else 100.0
    items = []
    for i in range(limit):
        close = base * 1.001 ** (i - limit + 1)
        ts = end - period * (limit - 1 - i)
        items.append(
            Candle(ts, close, close * 1.01, close * 0.99, close, 1000.0 + i % 5, i < limit - 1)
        )
    return Candles(symbol, "okx", exchange.pair("okx", symbol), timeframe, items, TRENDING_NOW)


@pytest.fixture
def trending(apis, monkeypatch):
    """`apis`, with every coin's candles a steady uptrend (BTC at 80,000, others at 100;
    "NOPE" has none) and the clock at 17 Oct 2026, 12:20 UTC."""
    monkeypatch.setattr(exchange, "candles", _trend_candles)
    monkeypatch.setattr(snapshot, "_now", lambda: TRENDING_NOW)
    monkeypatch.setattr(scan, "_now", lambda: TRENDING_NOW)
    return apis
