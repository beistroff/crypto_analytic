import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from click.testing import CliRunner

from sentinel.cli import cli
from sentinel.data import exchange
from sentinel.data.exchange import Candle, Candles
from sentinel.predict import journal, scorer
from sentinel.store.sim import Prediction, PredictionRepo

NOW = datetime(2026, 10, 17, 12, 20, tzinfo=UTC)  # the `trending` clock: XRP at 100
D = Decimal


@pytest.fixture
def market(trending, tables, monkeypatch):
    monkeypatch.setattr(journal, "_now", lambda: NOW)
    return tables


def _call(**changes):
    call = {
        "btc_context": "BTC +2.5% in 24 h, above both averages",
        "action": "BUY",
        "direction": "UP",
        "confidence": 0.6,
        "horizon_h": 24,
        "entry": 100.2,
        "target": 103,
        "stop": 98,
        "reasons": ["uptrend", "RSI has room"],
    }
    return json.dumps({**call, **changes})


def _log(raw, *extra):
    args = ["predict", "log", "--json", raw, "--symbol", "xrp", "--model", "haiku", *extra]
    return CliRunner().invoke(cli, args)


def _open(dynamodb):
    return dynamodb.query(
        TableName="sentinel-sim",
        IndexName="GSI2",
        KeyConditionExpression="GSI2PK = :pk",
        ExpressionAttributeValues={":pk": {"S": "OPEN"}},
    )["Items"]


def test_log_stores_the_call_with_its_snapshot_and_show_reads_it(market):
    logged = json.loads(_log(_call()).output)
    assert logged["valid"] is True and logged["validator_errors"] == []
    assert logged["snapshot"] == {
        "price": 100.0,
        "rsi14": 100.0,
        "btc_regime": "risk_on",
        "btc_chg_24h": 2.53,
    }
    [item] = _open(market)
    assert item["GSI2SK"]["S"] == logged["due_at"] == "2026-10-17T13:20:00Z"

    shown = CliRunner().invoke(cli, ["predict", "show", logged["id"].lower()])
    assert json.loads(shown.output) == logged
    text = CliRunner().invoke(cli, ["predict", "show", logged["id"], "--format", "telegram"])
    assert text.output.splitlines()[:2] == [
        "XRP BUY (UP) 24h, confidence 0.6, by haiku at 2026-10-17T12:20:00.000Z",
        "Entry 100.2, target 103, stop 98",
    ]


def test_invalid_call_is_stored_but_bad_json_is_not(market):
    out = _log(_call(entry=103, target=105, stop=104), "--format", "telegram").output
    assert out.endswith(
        ": entry 103, target 105, stop 104. Invalid: entry 103 is 3.0% from the price 100; "
        "BUY needs target > entry > stop.\n"
    )
    bad = _log('{"action": "BUY"}')
    assert bad.exit_code == 1
    assert json.loads(bad.output) == {"error": "bad prediction: btc_context: Field required"}
    assert len(_open(market)) == 1


def _pred(symbol, action, horizon_h, target=None, stop=None, **extra):
    """A call logged at NOW, first check due an hour later."""
    return Prediction(
        pred_id=f"ID-{symbol}",
        symbol=symbol,
        created_at="2026-10-17T12:20:00.000Z",
        model="haiku",
        action=action,
        direction={"BUY": "UP", "HOLD": "FLAT"}[action],
        confidence=D("0.6"),
        horizon_h=horizon_h,
        entry=D(100),
        target=target,
        stop=stop,
        btc_context="BTC neutral",
        reasons=["test"],
        risk_note=None,
        snapshot={"price": D(100), "btc_regime": "neutral"},
        valid=True,
        validator_errors=[],
        warnings=[],
        due_at="2026-10-17T13:20:00Z",
        **extra,
    )


def test_score_checks_each_horizon_up_to_the_calls_own(tables, monkeypatch):
    """XRP climbs 0.5 a quarter-hour from 100 (lows 1.5 under the close); ADA stays at 100.3."""
    clock = {"now": NOW}

    def candles(symbol, timeframe, limit=200):
        start, period = datetime(2026, 10, 17, 12, 15, tzinfo=UTC), exchange.PERIOD[timeframe]
        items = []
        for k in range(int((clock["now"] - start) / period) + 1):
            close = 100 + 0.5 * k if symbol == "XRP" else 100.3
            ts = start + period * k
            closed = ts + period <= clock["now"]
            items.append(Candle(ts, close, close + 0.5, close - 1.5, close, 1.0, closed))
        return Candles(symbol, "okx", f"{symbol}-USDT", timeframe, items, clock["now"])

    monkeypatch.setattr(exchange, "candles", candles)
    monkeypatch.setattr(scorer, "_now", lambda: clock["now"])
    repo = PredictionRepo()
    repo.add(_pred("XRP", "BUY", 4, target=D(103), stop=D(98)))
    repo.add(_pred("ADA", "HOLD", 1))

    clock["now"] = NOW + timedelta(minutes=65)
    run = CliRunner().invoke(cli, ["predict", "score", "--format", "telegram"])
    assert run.output == "Due 2: 2 graded, 1 done\n"
    buy, hold = repo.get("ID-XRP", "2026-10-17"), repo.get("ID-ADA", "2026-10-17")
    # The 13:15 close is nearest 13:20; the 13:30 candle is still open.
    assert buy.checks == {"h1": {"price": D("101.5"), "return_pct": D("1.5"), "hit": True}}
    assert (buy.status, buy.due_at) == ("OPEN", "2026-10-17T16:20:00Z")
    assert hold.checks["h1"]["hit"] is True  # +0.3%, within the 1% band
    assert (hold.status, hold.target_hit_first, hold.max_adverse_pct) == ("DONE", None, D("-1.2"))

    clock["now"] = NOW + timedelta(minutes=255)
    scorer.score()
    buy = repo.get("ID-XRP", "2026-10-17")
    assert buy.checks["h4"] == {"price": D("107.5"), "return_pct": D("7.5"), "hit": True}
    assert (buy.status, buy.target_hit_first, buy.max_adverse_pct) == ("DONE", "target", D("-1.5"))
    assert repo.due("2026-10-18T00:00:00Z") == []


def test_export_lists_calls_with_hit_rates(tables, monkeypatch):
    monkeypatch.setattr(journal, "_now", lambda: NOW + timedelta(hours=5))
    repo = PredictionRepo()
    hit = {"h4": {"price": D(102), "return_pct": D(2), "hit": True}}
    repo.add(_pred("XRP", "BUY", 4, D(103), D(98), checks=hit, status="DONE"))
    repo.add(_pred("ADA", "HOLD", 24))  # still open
    data = json.loads(CliRunner().invoke(cli, ["predict", "export", "--days", "1"]).output)
    assert data["summary"] == {
        "calls": 2,
        "graded": 1,
        "open": 1,
        "invalid": 0,
        "by_horizon": {"4h": {"n": 1, "hits": 1, "hit_pct": 100}},
        "by_model": {"haiku": {"n": 1, "hits": 1, "hit_pct": 100}},
    }
    row = dict(zip(data["columns"], data["rows"][1], strict=True))
    assert (row["sym"], row["ret"], row["hit"], row["btc"]) == ("XRP", 2.0, True, "neutral")
    text = CliRunner().invoke(cli, ["predict", "export", "--days", "1", "--format", "telegram"])
    assert text.output.splitlines() == [
        "Calls 1d: 2, graded 1, open 1, invalid 0",
        "By horizon: 4h 1/1 (100%)",
        "By model: haiku 1/1 (100%)",
    ]
