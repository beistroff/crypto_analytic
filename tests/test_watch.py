import json
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from click.testing import CliRunner

from sentinel.alerts import watch
from sentinel.cli import cli
from sentinel.data import SourceError, exchange
from sentinel.data.exchange import Candle, Candles
from sentinel.store.dynamo import Watch

D = Decimal
SET_AT = datetime(2026, 10, 20, 9, 30, tzinfo=UTC)
NOW = datetime(2026, 10, 20, 12, 20, tzinfo=UTC)


def _series(timeframe, lows, closes, end):
    """Candles oldest first; the last one opens at ``end`` and is still open at NOW."""
    period = exchange.PERIOD[timeframe]
    items = []
    for i, (low, close) in enumerate(zip(lows, closes, strict=True)):
        ts = end - period * (len(closes) - 1 - i)
        items.append(Candle(ts, close, close + 1, low, close, 1000.0, ts + period <= NOW))
    return Candles("SOL", "okx", "SOL-USDT", timeframe, items, NOW)


# Hourly: opens 07:00 to 12:00 on 20 Oct. Daily: 16 to 20 Oct, 20 Oct still open.
SERIES = {
    "1h": _series(
        "1h", [90, 99, 98, 97.5, 96, 99], [100] * 6, datetime(2026, 10, 20, 12, tzinfo=UTC)
    ),
    "1d": _series("1d", [80] * 5, [100, 90, 95, 105, 80], datetime(2026, 10, 20, tzinfo=UTC)),
}


def _candles(symbol, timeframe, limit=200):
    if symbol == "NOPE":
        raise SourceError("no candles for NOPE")
    return SERIES[timeframe]


@pytest.fixture
def clock(tables, monkeypatch):
    """Mocked tables, the fixture candles and the clock at SET_AT; move it with
    ``clock(NOW)``."""
    monkeypatch.setattr(exchange, "candles", _candles)

    def at(moment):
        monkeypatch.setattr(watch, "_now", lambda: moment)

    at(SET_AT)
    return at


def _watch(trigger, level, created_at, timeframe=None):
    return Watch("ID", "SOL", created_at, trigger, D(level), timeframe)


def test_triggers_on_a_fixture_series(monkeypatch):
    monkeypatch.setattr(exchange, "candles", _candles)
    # The 07:00 low of 90 is before the watch; 10:00 is the first candle after it.
    touch = watch.find_hit(_watch("touch_below", 97, "2026-10-20T09:30:00Z"))
    assert touch == watch.Hit(datetime(2026, 10, 20, 11, tzinfo=UTC), 96)
    assert watch.find_hit(_watch("touch_below", 95, "2026-10-20T09:30:00Z")) is None
    # The latest price (100) was fetched at NOW, before this watch: no hit yet.
    assert watch.find_hit(_watch("touch_below", 101, "2026-10-20T12:30:00Z")) is None
    # The 17 Oct candle closes after the watch was set; the open 20 Oct candle never counts.
    below = watch.find_hit(_watch("close_below", 92, "2026-10-17T10:00:00Z", "1d"))
    assert below == watch.Hit(datetime(2026, 10, 18, tzinfo=UTC), 90)
    assert watch.find_hit(_watch("close_below", 92, "2026-10-18T01:00:00Z", "1d")) is None
    above = watch.find_hit(_watch("close_above", 100, "2026-10-18T01:00:00Z", "1d"))
    assert above == watch.Hit(datetime(2026, 10, 20, tzinfo=UTC), 105)


def test_a_watch_with_no_candles_waits(clock):
    watch.WatchRepo().add(Watch("ID", "NOPE", "2026-10-20T09:30:00Z", "touch_below", D(1)))
    clock(NOW)
    result = watch.check()
    assert (result.checked, result.missing, result.hits) == (1, ["NOPE"], [])
    assert watch.pending()[0].status == "active"


def test_a_hit_is_reported_once(clock):
    run = CliRunner()
    _, price = watch.add("sol", "touch_below", D(97), stop=D(90), note="retest")
    assert price == 100
    clock(NOW)
    first = run.invoke(cli, ["watch", "check", "--format", "telegram"]).output
    assert first.splitlines() == [
        "Watch hit: SOL touch below 97: 96 at 2026-10-20T11:00:00Z. Stop 90. Note: retest.",
        "Ask your AI agent for a fresh look before acting.",
    ]
    assert watch.pending() == []
    second = json.loads(run.invoke(cli, ["watch", "check"]).output)
    assert (second["checked"], second["hits"]) == (0, [])
    assert run.invoke(cli, ["watch", "check", "--format", "telegram"]).output == "NO_REPLY\n"


def test_cli_adds_lists_and_removes(clock):
    run = CliRunner()
    add = ["watch", "add", "SOL", "--trigger", "close_below", "--level", "92", "--stop", "85"]
    added = json.loads(run.invoke(cli, add).output)
    assert (added["timeframe"], added["status"], added["price"]) == ("1d", "active", 100)

    listed = run.invoke(cli, ["watch", "list", "--format", "telegram"]).output
    assert listed.splitlines() == ["1 watch", "SOL close below 92 (1d), stop 85"]

    bad_tf = ["watch", "add", "SOL", "--trigger", "touch_below", "--level", "1", "--tf", "4h"]
    assert json.loads(run.invoke(cli, bad_tf).output) == {
        "error": "--tf is for close triggers only"
    }
    removed = run.invoke(cli, ["watch", "remove", added["id"]])
    assert json.loads(removed.output)["status"] == "removed"
    assert run.invoke(cli, ["watch", "list", "--format", "telegram"]).output == "No watches\n"
    assert run.invoke(cli, ["watch", "remove", added["id"]]).exit_code == 1
