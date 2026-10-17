import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from sentinel import net
from sentinel.config import HttpSettings
from sentinel.data import SourceError, exchange, flow

FIXTURES = Path(__file__).parent / "fixtures"
OKX_PATH = "/api/v5/market/candles"
KRAKEN_PATH = "/0/public/OHLC"
NOT_ON_OKX = (200, {}, {"code": "51001", "data": [], "msg": "Instrument ID doesn't exist."})
# 17 Oct 2026, 12:00 UTC: the fixtures' last daily candle (17 Oct) is still open.
NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def venues(make_server, monkeypatch):
    servers = SimpleNamespace(okx=make_server(), kraken=make_server())
    servers.okx.routes[OKX_PATH] = (200, {}, _fixture("okx_candles.json"))
    servers.kraken.routes[KRAKEN_PATH] = (200, {}, _fixture("kraken_ohlc.json"))
    servers.okx.routes[flow.FUNDING] = (200, {}, _fixture("okx_funding.json"))
    servers.okx.routes[flow.OI_HISTORY] = (200, {}, _fixture("okx_oi_history.json"))
    servers.okx.routes[flow.LONG_SHORT] = (200, {}, _fixture("okx_long_short.json"))
    monkeypatch.setattr(flow, "BASE_URL", servers.okx.base)
    monkeypatch.setattr(exchange, "OKX_URL", servers.okx.base + OKX_PATH)
    monkeypatch.setattr(exchange, "KRAKEN_URL", servers.kraken.base + KRAKEN_PATH)
    monkeypatch.setattr(exchange, "_now", lambda: NOW)
    fast = HttpSettings(backoff_s=0, min_interval_s={"okx": 0, "kraken": 0})
    monkeypatch.setattr(net, "_sessions", {n: net.Session(n, fast) for n in ("okx", "kraken")})
    return servers


def _query(request):
    return parse_qs(urlsplit(request.path).query)


def test_okx_daily_candles_are_utc_days_oldest_first(venues):
    result = exchange.candles("btc", "1d", limit=3)
    assert _query(venues.okx.seen[0])["bar"] == ["1Dutc"]
    assert (result.exchange, result.pair) == ("okx", "BTC-USDT")
    days = [c.ts for c in result.candles]
    assert days == [datetime(2026, 10, d, tzinfo=UTC) for d in (15, 16, 17)]
    assert [c.closed for c in result.candles] == [True, True, False]
    first = result.candles[0]
    assert (first.low, first.close) == (79775.1, 82232.4)
    assert first.volume == pytest.approx(695608615.22)
    assert result.price == 81746.9


def test_falls_back_to_kraken_for_a_coin_okx_does_not_list(venues):
    venues.okx.routes[OKX_PATH] = NOT_ON_OKX
    result = exchange.candles("XMR", "1d", limit=2)
    assert (result.exchange, result.pair) == ("kraken", "XMRUSD")
    assert _query(venues.kraken.seen[0])["interval"] == ["1440"]
    assert [c.ts.day for c in result.candles] == [16, 17]
    assert result.candles[-1].volume == pytest.approx(559.95 * 812.3)


def test_cached_for_five_minutes(venues, monkeypatch):
    exchange.candles("BTC", "1h", limit=3)
    exchange.candles("BTC", "1h", limit=3)
    assert len(venues.okx.seen) == 1
    monkeypatch.setattr(exchange, "_now", lambda: NOW.replace(minute=6))
    exchange.candles("BTC", "1h", limit=3)
    assert len(venues.okx.seen) == 2


def test_no_exchange_has_it(venues):
    venues.okx.routes[OKX_PATH] = NOT_ON_OKX
    venues.kraken.routes[KRAKEN_PATH] = (200, {}, {"error": ["EQuery:Unknown asset pair"]})
    with pytest.raises(SourceError, match="no candles for NOPE"):
        exchange.candles("NOPE", "1d")


def test_flow_from_okx_swap(venues):
    result = flow.flow("sol")
    assert result.funding_pct == pytest.approx(-0.0011007, abs=1e-7)
    assert result.funding_interval_h == 8.0
    # Newest entry against the one 7 days earlier, in coins: 2,996,045 / 3,091,933 - 1.
    assert result.oi_chg_7d == pytest.approx(-3.1012, abs=1e-4)
    assert result.oi_usd == pytest.approx(314345044.55)
    assert result.long_short == pytest.approx(2.207036)
    assert result.ts == datetime(2026, 10, 17, 8, tzinfo=UTC)
    assert _query(venues.okx.seen[1]) == {
        "instId": ["SOL-USDT-SWAP"],
        "period": ["4H"],
        "limit": ["43"],
    }


def test_flow_for_a_coin_without_a_swap(venues):
    venues.okx.routes[flow.FUNDING] = NOT_ON_OKX
    with pytest.raises(SourceError, match="code 51001"):
        flow.flow("XMR")


@pytest.mark.live
def test_live_flow():
    assert flow.flow("BTC").oi_chg_7d is not None


@pytest.mark.live
def test_live_candles():
    btc = exchange.candles("BTC", "1d", limit=3)
    assert btc.exchange == "okx"
    assert all(c.ts.hour == 0 for c in btc.candles)  # UTC days, not Hong Kong days
    assert exchange.candles("XMR", "1h", limit=3).exchange == "kraken"
