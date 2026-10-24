import json
from dataclasses import replace
from decimal import Decimal

import pytest
from click.testing import CliRunner

from sentinel.cli import cli
from sentinel.portfolio import service
from sentinel.portfolio.service import JournalError
from sentinel.store.real import PositionRepo, TradeRepo, VersionConflict

D = Decimal


def _trades(tables, symbol):
    page = tables.query(
        TableName="sentinel-real",
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues={":pk": {"S": f"TRADE#{symbol}"}},
    )
    return page["Items"]


def test_buys_average_the_cost_fee_included(tables):
    first = service.record_trade("buy", "sol", D(2), D(100), D(1))
    result = service.record_trade("buy", "SOL", D(2), D(120), D(1))
    position = PositionRepo().get("SOL")
    assert result["position"] == position
    assert (position.qty, position.cost_basis, position.avg_price) == (D(4), D(442), D("110.5"))
    assert position.version == 2
    assert position.created_at == first["position"].created_at
    trades = _trades(tables, "SOL")
    assert [t["side"]["S"] for t in trades] == ["BUY", "BUY"]
    assert D(trades[0]["quote_amount"]["N"]) == D(200)
    assert trades[0]["GSI1PK"]["S"] == "SYM#SOL"


def test_sells_realise_pnl_and_close_the_position(tables):
    service.record_trade("buy", "SOL", D(4), D(100))
    service.set_baseline(D(1000))
    part = service.record_trade("sell", "SOL", D(1), D(130), D(2))
    assert part["realised_pnl"] == D(28)
    held = PositionRepo().get("SOL")
    assert (held.qty, held.avg_price, held.cost_basis, held.realised_pnl) == (
        D(3),
        D(100),
        D(300),
        D(28),
    )
    assert service.summary().cash_usdt == D(1000) - 300 + 28

    service.record_trade("sell", "SOL", D(3), D(90))
    closed = PositionRepo().get("SOL")
    assert (closed.qty, closed.cost_basis, closed.realised_pnl) == (D(0), D(0), D(-2))
    state = service.summary()
    assert state.open_positions == []
    assert state.cash_usdt == D(998)


def test_bad_trades_write_nothing(tables):
    service.record_trade("buy", "SOL", D(1), D(100))
    with pytest.raises(JournalError, match=r"holding 1$"):
        service.record_trade("sell", "SOL", D(2), D(100))
    with pytest.raises(JournalError, match=r"holding 0$"):
        service.record_trade("sell", "ETH", D(1), D(100))
    with pytest.raises(JournalError, match="positive"):
        service.record_trade("buy", "ETH", D("0.00000000001"), D(100))
    assert len(_trades(tables, "SOL")) == 1
    assert PositionRepo().get("ETH") is None


def test_inputs_round_to_ten_decimals(tables):
    result = service.record_trade("buy", "BTC", D("0.000138888888888888"), D("72000.123456789012"))
    assert result["qty"] == D("0.0001388889")
    assert result["position"].avg_price == D("72000.1234567890")


def test_stale_version_fails_the_whole_transaction(tables):
    service.record_trade("buy", "SOL", D(1), D(100))
    stale = replace(PositionRepo().get("SOL"), version=1)
    with pytest.raises(VersionConflict):
        TradeRepo().add({"PK": "TRADE#SOL", "SK": "late"}, stale, expected_version=0)
    with pytest.raises(VersionConflict):
        TradeRepo().add({"PK": "TRADE#NEW", "SK": "late"}, stale, expected_version=None)
    assert len(_trades(tables, "SOL")) == 1
    assert _trades(tables, "NEW") == []


def test_baseline_is_set_once_unless_replaced(tables):
    service.set_baseline(D(1000))
    with pytest.raises(JournalError, match="already 1000 USDT"):
        service.set_baseline(D(500))
    result = service.set_baseline(D(500), replace=True)
    assert result["replaced"]["baseline_usdt"] == D(1000)
    assert service.summary().baseline_usdt == D(500)


def test_cli_journals_a_trade_and_summarises(tables):
    run = CliRunner()
    empty = run.invoke(cli, ["portfolio", "summary", "--format", "telegram"])
    assert empty.output.splitlines() == [
        "Cash: not known, no starting cash set",
        "Nothing deployed, realised +$0",
    ]

    assert run.invoke(cli, ["portfolio", "baseline", "--usdt", "1000"]).exit_code == 0
    add = ["trade", "add", "--symbol", "xrp", "--qty", "100", "--price", "1.2"]
    added = run.invoke(cli, [*add, "--side", "buy"])
    assert json.loads(added.output)["position"] == {"qty": 100.0, "avg_price": 1.2}

    summary = json.loads(run.invoke(cli, ["portfolio", "summary"]).output)
    assert summary["cash_usdt"] == 880.0
    assert summary["open_positions"][0]["symbol"] == "XRP"
    text = run.invoke(cli, ["portfolio", "summary", "--format", "telegram"]).output
    assert text.splitlines() == [
        "Cash: $880.00",
        "Deployed: $120.00 in 1 position, realised +$0",
        "XRP 100 at avg $1.20",
    ]

    oversell = run.invoke(
        cli, ["trade", "add", "--side", "sell", "--symbol", "XRP", "--qty", "500", "--price", "1"]
    )
    assert oversell.exit_code == 1
    assert json.loads(oversell.output)["error"] == "cannot sell 500 XRP, holding 100"
    zero = run.invoke(
        cli, ["trade", "add", "--side", "buy", "--symbol", "XRP", "--qty", "0", "--price", "1"]
    )
    assert zero.exit_code == 2
