"""Command results in the two output forms: compact JSON for the agent, 5 lines or fewer
for Telegram.

Code does the fetching and arithmetic; the agent only reads the result. Market-wide
context comes first (the agent weighs BTC and the market before a coin), and a source
that fails is reported in ``missing`` instead of failing the whole command.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests

from sentinel.data import SourceError, cmc, feargreed, newsapi
from sentinel.eval.rules import is_scalp_candidate, rules_signal

# Legacy whale_monitor.py: a 1 h pump above this many percent is worth an alert.
WHALE_PUMP_1H_PCT = 1.5
TELEGRAM_MAX_LINES = 5

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class View:
    data: dict[str, Any]
    text: str


def overview(symbols: list[str]) -> View:
    """Market context plus the latest quote for each symbol."""
    market, missing = _market_context()
    coins = cmc.quotes(symbols)
    unknown = [s.upper() for s in symbols if s.upper() not in coins]
    data: dict[str, Any] = {"market": market, "coins": [_coin(c) for c in coins.values()]}
    if missing:
        data["missing"] = missing
    if unknown:
        data["unknown_symbols"] = unknown
    lines = [_market_line(market)]
    lines += [f"{c.symbol} {_usd(c.price)} ({_pct(c.change_24h)} 24h)" for c in coins.values()]
    return View(data, _lines(lines))


def top(limit: int) -> View:
    """Top coins by market cap with the legacy rule signal (the RULES baseline)."""
    fear_greed = _fear_greed_value()
    coins = cmc.listings(limit)
    rows = [{**_coin(c), "signal": rules_signal(fear_greed, c.change_24h, c.vol_mc)} for c in coins]
    flagged = [r for r in rows if r["signal"] != "HOLD"]
    lines = [f"Top {len(rows)} by market cap, Fear & Greed {fear_greed}"]
    lines += [f"{r['symbol']}: {r['signal']} ({_pct(r['chg_24h'])} 24h)" for r in flagged]
    if not flagged:
        lines.append("All HOLD")
    return View({"fear_greed": fear_greed, "coins": rows}, _lines(lines))


def scalp(limit: int) -> View:
    """Up to 5 actively traded coins that have not pumped yet (legacy scalp rule)."""
    coins = [c for c in cmc.listings(limit) if is_scalp_candidate(c.symbol, c.change_24h, c.vol_mc)]
    best = sorted(coins, key=lambda c: c.vol_mc, reverse=True)[:5]
    lines = [f"Scalp watch, top {limit}: {len(best)} candidates"]
    lines += [f"{c.symbol} {_usd(c.price)}, vol/mcap {c.vol_mc:.2f}" for c in best]
    return View({"candidates": [_coin(c) for c in best]}, _lines(lines))


def whales(symbol: str) -> View:
    """Rough whale proxy until task 2.5: a sharp 1 h pump."""
    coin = _quote(symbol)
    change = coin.change_1h or 0.0
    alert = change > WHALE_PUMP_1H_PCT
    data = {**_coin(coin), "alert": alert}
    state = "possible whale buying" if alert else "quiet"
    return View(data, f"{coin.symbol} {_usd(coin.price)}: {state}, {_pct(change)} in 1 h")


def news(symbol: str, limit: int) -> View:
    """Recent headlines; the agent judges their sentiment."""
    items = newsapi.headlines(symbol, limit)
    data = {
        "symbol": symbol.upper(),
        "delayed_24h": True,
        "headlines": [{"title": h.title, "source": h.source, "url": h.url} for h in items],
    }
    lines = [f"{symbol.upper()} news (about 24 h delayed): {len(items)}"]
    lines += [f"- {_short(h.title)} ({h.source})" for h in items]
    return View(data, _lines(lines))


def watch_levels(symbol: str, below: float | None, above: float | None) -> View:
    """Has the price reached a buy level (at or under ``below``) or a sell level?"""
    coin = _quote(symbol)
    zone = None
    if below is not None and coin.price <= below:
        zone = "buy"
    elif above is not None and coin.price >= above:
        zone = "sell"
    data = {
        "symbol": coin.symbol,
        "price": _round(coin.price),
        "below": below,
        "above": above,
        "zone": zone,
    }
    if zone == "buy":
        text = f"{coin.symbol} {_usd(coin.price)}: in buy zone (at or under {_usd(below)})"
    elif zone == "sell":
        text = f"{coin.symbol} {_usd(coin.price)}: in sell zone (at or over {_usd(above)})"
    else:
        text = f"{coin.symbol} {_usd(coin.price)}: between levels"
    return View(data, text)


def watch_move(symbol: str, entry: float, min_pct: float) -> View:
    """Move since an entry price; ``alert`` when it is at least ``min_pct`` either way."""
    coin = _quote(symbol)
    change = (coin.price - entry) / entry * 100
    alert = abs(change) >= min_pct
    data = {
        "symbol": coin.symbol,
        "price": _round(coin.price),
        "entry": entry,
        "chg_pct": round(change, 2),
        "alert": alert,
    }
    flag = "move alert, " if alert else ""
    return View(data, f"{coin.symbol} {_usd(coin.price)}: {flag}{_pct(change)} from {_usd(entry)}")


def _market_context() -> tuple[dict[str, Any], list[str]]:
    missing: list[str] = []
    market: dict[str, Any] = {
        "fear_greed": None,
        "btc_dominance": None,
        "total_mcap_chg_24h": None,
        "stablecoin_share": None,
    }
    try:
        mood = feargreed.latest()
        market["fear_greed"] = mood.value
    except (SourceError, requests.RequestException) as exc:
        _skip("feargreed", exc, missing)
    try:
        metrics = cmc.global_metrics()
        market["btc_dominance"] = _round(metrics.btc_dominance, 1)
        market["total_mcap_chg_24h"] = _round(metrics.total_mcap_chg_24h, 2)
        market["stablecoin_share"] = _round(metrics.stablecoin_share, 1)
    except (SourceError, requests.RequestException) as exc:
        _skip("cmc_global", exc, missing)
    return market, missing


def _fear_greed_value() -> int | None:
    try:
        return feargreed.latest().value
    except (SourceError, requests.RequestException) as exc:
        _skip("feargreed", exc, [])
        return None


def _skip(source: str, exc: Exception, missing: list[str]) -> None:
    log.warning("source unavailable", extra={"source": source, "error": type(exc).__name__})
    missing.append(source)


def _quote(symbol: str) -> cmc.Coin:
    coin = cmc.quotes([symbol]).get(symbol.upper())
    if coin is None:
        raise SourceError(f"CMC has no quote for {symbol.upper()}")
    return coin


def _coin(coin: cmc.Coin) -> dict[str, Any]:
    return {
        "symbol": coin.symbol,
        "price": _round(coin.price),
        "chg_1h": _round(coin.change_1h, 2),
        "chg_24h": _round(coin.change_24h, 2),
        "vol_mc": round(coin.vol_mc, 3),
    }


def _market_line(market: dict[str, Any]) -> str:
    parts = []
    if market["fear_greed"] is not None:
        parts.append(f"F&G {market['fear_greed']}")
    if market["btc_dominance"] is not None:
        parts.append(f"BTC dom {market['btc_dominance']}%")
    if market["total_mcap_chg_24h"] is not None:
        parts.append(f"mcap {_pct(market['total_mcap_chg_24h'])} 24h")
    if market["stablecoin_share"] is not None:
        parts.append(f"stables {market['stablecoin_share']}%")
    return "Market: " + (", ".join(parts) if parts else "no data")


def _round(value: float | None, digits: int | None = None) -> float | None:
    """Prices to 6 significant digits (works for BTC and for tiny coins alike)."""
    if value is None:
        return None
    return round(value, digits) if digits is not None else float(f"{value:.6g}")


def _usd(value: float | None) -> str:
    if value is None:
        return "?"
    if value >= 1000:
        return f"${value:,.0f}"
    if value >= 1:
        return f"${value:,.2f}"
    return f"${value:.4g}"


def _pct(value: float) -> str:
    return f"{value:+.1f}%"


def _short(text: str, width: int = 90) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _lines(lines: list[str]) -> str:
    return "\n".join(lines[:TELEGRAM_MAX_LINES])
