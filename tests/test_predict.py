import json
from datetime import UTC, datetime

import pytest
from click.testing import CliRunner

from sentinel.cli import cli
from sentinel.predict import journal

NOW = datetime(2026, 10, 17, 12, 20, tzinfo=UTC)  # the `trending` clock: XRP at 100


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
