import json

import pytest
from click.testing import CliRunner

from sentinel.cli import cli

LISTINGS = "/v1/cryptocurrency/listings/latest"
# About 4 characters per token: 1,500 tokens for 50 coins.
MAX_CHARS = 6000


def _listing(symbol, change_24h=1.2, change_7d=-3.4):
    usd = {
        "price": 100.0,
        "volume_24h": 1e9,
        "percent_change_1h": 0.1,
        "percent_change_24h": change_24h,
        "percent_change_7d": change_7d,
        "market_cap": 1e10,
    }
    return {"symbol": symbol, "quote": {"USD": usd}}


@pytest.fixture
def top50(trending):
    """CMC's top 50: BTC, a stablecoin, wrapped BTC, a coin no exchange has, 46 others."""
    coins = [_listing("BTC", 2.5, 4.0), _listing("USDT"), _listing("WBTC"), _listing("NOPE")]
    coins += [_listing(f"C{i:02}") for i in range(46)]
    body = {"status": {"error_code": 0}, "data": coins}
    trending.cmc.routes[LISTINGS] = (200, {}, body)
    return trending


def _run(*args):
    result = CliRunner().invoke(cli, ["market", "scan", *args])
    assert result.exit_code == 0, result.output
    return result.stdout


def test_scan_one_row_per_coin_within_budget(top50):
    out = _run()
    data = json.loads(out)
    assert len(out) < MAX_CHARS
    assert data["btc"] == {
        "price": 80000.0,
        "chg_24h": 2.5,
        "chg_7d": 4.0,
        "regime": "risk_on",
        "regime_points": 4,
    }
    assert data["missing"] == ["NOPE"]
    rows = [dict(zip(data["columns"], row, strict=True)) for row in data["rows"]]
    assert [r["sym"] for r in rows[:2]] == ["BTC", "C00"]  # no USDT, no WBTC
    assert len(rows) == 47
    assert rows[0]["rs_7d"] is None
    # Uptrend of 0.1% a day: the 7-day wick low is 6 days back, 0.99 x its close.
    assert rows[1] == {
        "sym": "C00",
        "price": 100.0,
        "chg_24h": 1.2,
        "chg_7d": -3.4,
        "rsi14": 100.0,
        "above_sma50": True,
        "above_sma200": True,
        "rs_7d": 0.0,
        "to_low_7d": round((1.001**-6 * 0.99 - 1) * 100, 2),
        "to_high_7d": 1.0,
        "funding_pct": -0.0011,
    }
    lines = _run("--format", "telegram").strip().splitlines()
    assert lines[0] == (
        "Top 50 scan, 47 coins: BTC $80,000 risk_on (+2.5% 24h, +4.0% 7d); no data: NOPE"
    )
    assert (
        lines[-1]
        == "RSI over 70: BTC 100, C00 100, C01 100, C02 100, C03 100 (+42 more); under 30: none"
    )
    assert len(lines) == 5
