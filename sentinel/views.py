"""Command results in the two output forms: compact JSON for the agent, 5 lines or fewer
for Telegram.

Code does the fetching and arithmetic; the agent only reads the result. Market-wide
context comes first (the agent weighs BTC and the market before a coin), and a source
that fails is reported in ``missing`` instead of failing the whole command.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any

import requests

from sentinel.alerts import watch as alerts_watch
from sentinel.data import SourceError, cmc, exchange, feargreed, newsapi
from sentinel.eval.rules import is_scalp_candidate, rules_signal
from sentinel.portfolio import service
from sentinel.predict.runner import RunResult
from sentinel.predict.scorer import ScoreResult
from sentinel.signals import scan as signals_scan
from sentinel.signals import snapshot as signals_snapshot
from sentinel.signals.snapshot import rounded, sig
from sentinel.store.sim import Prediction, Watch

# Legacy whale_monitor.py: a 1 h pump above this many percent is worth an alert.
WHALE_PUMP_1H_PCT = 1.5
TELEGRAM_MAX_LINES = 5
NO_NEWS = "no relevant headlines"
NO_REPLY = "NO_REPLY"  # OpenClaw's silent token: an automation run that prints it sends nothing

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
    """The coin's most read headlines of 14 days; the agent judges their sentiment."""
    items = newsapi.headlines(symbol, limit)
    label = f"{symbol.upper()} news, {newsapi.COIN_DAYS} days"
    return _headlines({"symbol": symbol.upper(), "days": newsapi.COIN_DAYS}, label, items)


def world_news(limit: int) -> View:
    """The most read world news of 3 days that moves markets beyond crypto."""
    items = newsapi.world(limit)
    label = f"World news, {newsapi.WORLD_DAYS} days"
    return _headlines({"days": newsapi.WORLD_DAYS}, label, items)


def _headlines(data: dict[str, Any], label: str, items: list[newsapi.Headline]) -> View:
    head = f"{label}, most read first (about 24 h delayed)"
    data = {
        **data,
        "delayed_24h": True,
        "headlines": [{"title": h.title, "source": h.source, "url": h.url} for h in items],
    }
    if not items:
        data["note"] = NO_NEWS
        return View(data, f"{head}: {NO_NEWS}")
    shown = items[: TELEGRAM_MAX_LINES - 1]
    more = f", {len(shown)} shown" if len(shown) < len(items) else ""
    lines = [f"{head}: {len(items)}{more}"]
    lines += [f"- {_short(h.title)} ({h.source})" for h in shown]
    return View(data, _lines(lines))


def scan(limit: int, wanted: list[str]) -> View:
    """One row of computed signals per top coin; the text names the stand-outs."""
    result = signals_scan.build(limit, wanted)
    rows, btc = result.rows, result.btc
    head = f"Top {limit} scan" + (f" + {', '.join(wanted)}" if wanted else "")
    head += f", {len(rows)} coins"
    if btc:
        head += (
            f": BTC {_usd(btc.price)} {btc.regime} "
            f"({_pct_or(btc.chg_24h)} 24h, {_pct_or(btc.chg_7d)} 7d)"
        )
    if result.missing:
        head += f"; no data: {', '.join(result.missing)}"
    if result.skipped:
        head += f"; skipped: {', '.join(result.skipped)}"
    ranked = sorted((r for r in rows if r.rs_7d is not None), key=lambda r: r.rs_7d, reverse=True)
    near_low = sorted(
        (r for r in rows if r.to_low_7d is not None), key=lambda r: r.to_low_7d, reverse=True
    )
    hot = [f"{r.sym} {r.rsi14:.0f}" for r in rows if r.rsi14 is not None and r.rsi14 > 70]
    cold = [f"{r.sym} {r.rsi14:.0f}" for r in rows if r.rsi14 is not None and r.rsi14 < 30]
    # The weakest come from the coins not already among the strongest.
    strongest, weakest = ranked[:3], ranked[3:][::-1][:3]
    lines = [
        head,
        "Strongest vs BTC 7d: " + ", ".join(f"{r.sym} {r.rs_7d:+.1f}" for r in strongest),
        "Weakest vs BTC 7d: " + (", ".join(f"{r.sym} {r.rs_7d:+.1f}" for r in weakest) or "none"),
        "Near 7d wick low: " + ", ".join(f"{r.sym} ({r.to_low_7d:+.1f}%)" for r in near_low[:3]),
        f"RSI over 70: {_some(hot)}; under 30: {_some(cold)}",
    ]
    return View(result.data(), _lines(lines))


TIMEFRAME_WORDS = {
    "1w": "weekly",
    "1d": "daily",
    "4h": "4-hour",
    "1h": "hourly",
    "15m": "15-minute",
}


def candles(symbol: str, timeframe: exchange.Timeframe, limit: int) -> View:
    """Raw candles for history the snapshot does not cover (a year or more: weekly)."""
    series = exchange.history(symbol, timeframe, limit)
    rows = series.candles
    when = "%d %b %Y" if timeframe in ("1w", "1d") else "%d %b %H:%M"
    high = max(rows, key=lambda c: c.high)
    low = min(rows, key=lambda c: c.low)
    data: dict[str, Any] = {
        "symbol": series.symbol,
        "exchange": series.exchange,
        "timeframe": timeframe,
        "columns": ["open_time", "open", "high", "low", "close"],
        "candles": [
            [c.ts.isoformat(), sig(c.open), sig(c.high), sig(c.low), sig(c.close)] for c in rows
        ],
        "last_open": not rows[-1].closed,
        "high": {"price": sig(high.high), "open_time": high.ts.isoformat()},
        "low": {"price": sig(low.low), "open_time": low.ts.isoformat()},
    }
    first = rows[0]
    change = (series.price - first.close) / first.close * 100
    lines = [
        f"{series.symbol} {TIMEFRAME_WORDS[timeframe]}, {len(rows)} candles from {first.ts:{when}}",
        f"Close {_usd(first.close)} then, now {_usd(series.price)} ({_pct(change)})",
        f"High {_usd(high.high)} ({high.ts:{when}}), low {_usd(low.low)} ({low.ts:{when}})",
    ]
    return View(data, _lines(lines))


def _some(items: list[str], shown: int = 5) -> str:
    if not items:
        return "none"
    more = f" (+{len(items) - shown} more)" if len(items) > shown else ""
    return ", ".join(items[:shown]) + more


def snapshot(symbol: str) -> View:
    """The coin in the signal hierarchy: BTC, market, macro, news, flow, technicals."""
    snap = signals_snapshot.build(symbol)
    data = snap.model_dump(mode="json")
    tech, btc, vs = snap.technicals, snap.btc, snap.vs_btc
    head = f"{snap.symbol} {_usd(snap.price)}"
    if tech:
        rsi = "?" if tech.rsi14 is None else tech.rsi14
        head += f" ({_pct_or(tech.chg_24h)} 24h, {_pct_or(tech.chg_7d)} 7d), RSI {rsi}"
    if vs and vs.rs_7d is not None:
        head += f", vs BTC 7d {vs.rs_7d:+.1f} pts"
    lines = [head]
    if btc:
        mood = snap.market.fear_greed if snap.market else None
        lines.append(
            f"BTC {_usd(btc.price)} {btc.regime}: {_pct_or(btc.chg_24h)} 24h, "
            f"{_side(btc.above_sma50)} SMA50, {_side(btc.above_sma200)} SMA200"
            + (f"; F&G {mood}" if mood is not None else "")
        )
    week = snap.levels.d7 if snap.levels else None
    if week:
        lines.append(
            f"7d range: wicks {_usd(week.wick_low)} ({week.wick_low_date:%d %b}) to "
            f"{_usd(week.wick_high)} ({week.wick_high_date:%d %b}); "
            f"closes {_usd(week.close_low)} to {_usd(week.close_high)}"
        )
    if snap.setup:
        s = snap.setup
        setup = (
            f"4h setup: trigger close above {_usd(s.trigger)}; stop {_usd(s.stop)} "
            f"(-{s.stop_pct}%, {s.stop_atr} ATR{', in noise' if s.stop_in_noise else ''})"
        )
        if s.pullback_low is not None:
            setup += f"; pullback {_usd(s.pullback_low)} to {_usd(s.pullback_high)}"
        if s.room_pct is not None:
            setup += f"; room to 30d high {_pct_or(s.room_pct)}"
        lines.append(setup)
    extra = []
    if snap.flow:
        f = snap.flow
        extra.append(
            f"funding {f.funding_pct:+.4f}%/{f.funding_interval_h:g}h, "
            f"OI {_pct_or(f.oi_chg_7d)} 7d, L/S {f.long_short}"
        )
    if snap.macro:
        extra.append(f"FOMC {snap.macro.next_fomc:%d %b} (in {snap.macro.days_to_fomc} d)")
    if extra:
        lines.append("; ".join(extra))
    if snap.missing:
        lines.append("Missing: " + ", ".join(snap.missing))
    return View(data, _lines(lines))


def _watch(watch: Watch) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": watch.pred_id,
        "symbol": watch.symbol,
        "trigger": watch.trigger,
        "level": _num(watch.level),
        "timeframe": watch.timeframe,
        "stop": None if watch.stop is None else _num(watch.stop),
        "target": None if watch.target is None else _num(watch.target),
        "note": watch.note,
        "status": watch.status,
        "created_at": watch.created_at,
    }
    if watch.hit_at:
        data["hit_at"] = watch.hit_at
        data["hit_price"] = None if watch.hit_price is None else _num(watch.hit_price)
    return data


def _watch_line(watch: Watch) -> str:
    line = f"{watch.symbol} {alerts_watch.describe(watch)}"
    if watch.stop is not None:
        line += f", stop {service.plain(watch.stop)}"
    if watch.target is not None:
        line += f", target {service.plain(watch.target)}"
    return line


def watch_added(watch: Watch, price: float) -> View:
    data = {**_watch(watch), "price": sig(price)}
    return View(data, f"Watching {_watch_line(watch)}. Now {_usd(price)}.")


def watch_list(watches: list[Watch]) -> View:
    data = {"watches": [_watch(w) for w in watches]}
    if not watches:
        return View(data, "No watches")
    count = len(watches)
    lines = [f"{count} watch{'es' if count > 1 else ''}", *(_watch_line(w) for w in watches)]
    return View(data, "\n".join(lines))


def watch_removed(watch: Watch) -> View:
    return View({**_watch(watch), "status": "removed"}, f"Stopped watching {_watch_line(watch)}.")


def watch_checked(result: alerts_watch.CheckResult) -> View:
    """The text is what OpenClaw delivers: one line per hit, or ``NO_REPLY`` (its silent
    token) when nothing hit, so a quiet run sends nothing."""
    data = {
        "checked": result.checked,
        "hits": [_watch(w) for w in result.hits],
        "missing": result.missing,
    }
    if not result.hits:
        return View(data, NO_REPLY)
    lines = [alerts_watch.alert(w) for w in result.hits]
    return View(data, "\n".join([*lines, "Ask your AI agent for a fresh look before acting."]))


def _prediction(pred: Prediction) -> dict[str, Any]:
    data = asdict(pred)
    data["id"] = data.pop("pred_id")
    for name in ("confidence", "entry", "target", "stop", "max_adverse_pct", "cost_usd"):
        data[name] = None if data[name] is None else _num(data[name])
    data["snapshot"] = _floats(pred.snapshot)
    data["checks"] = {name: _floats(check) for name, check in pred.checks.items()}
    return data


def _floats(values: dict[str, Any]) -> dict[str, Any]:
    return {name: _num(v) if isinstance(v, Decimal) else v for name, v in values.items()}


def _levels_line(pred: Prediction) -> str:
    line = f"entry {service.plain(pred.entry)}"
    if pred.target is not None:
        line += f", target {service.plain(pred.target)}"
    if pred.stop is not None:
        line += f", stop {service.plain(pred.stop)}"
    return line


def prediction_logged(pred: Prediction) -> View:
    line = f"Logged {pred.symbol} {pred.action} {pred.horizon_h}h ({pred.pred_id}): "
    line += _levels_line(pred) + "."
    if pred.validator_errors:
        line += f" Invalid: {'; '.join(pred.validator_errors)}."
    if pred.warnings:
        line += f" Warning: {'; '.join(pred.warnings)}."
    return View(_prediction(pred), line)


def prediction(pred: Prediction) -> View:
    """A logged call in full (the "details")."""
    lines = [
        f"{pred.symbol} {pred.action} ({pred.direction}) {pred.horizon_h}h, "
        f"confidence {service.plain(pred.confidence)}, by {pred.model} at {pred.created_at}",
        _levels_line(pred).capitalize(),
        f"BTC: {pred.btc_context}",
        "Reasons: " + ("; ".join(pred.reasons) or "none"),
    ]
    if pred.validator_errors:
        lines.append(f"Invalid: {'; '.join(pred.validator_errors)}")
    elif pred.risk_note:
        lines.append(f"Risk: {pred.risk_note}")
    return View(_prediction(pred), _lines(lines))


def prediction_scored(result: ScoreResult) -> View:
    """One line for the automation's run history; nothing is sent to Telegram."""
    data = {
        "checked": result.checked,
        "graded": [p.pred_id for p in result.graded],
        "done": result.done,
        "missing": result.missing,
    }
    line = f"Due {result.checked}: {len(result.graded)} graded, {result.done} done"
    if result.missing:
        line += f"; no candles: {', '.join(result.missing)}"
    return View(data, line)


EXPORT_COLUMNS = [
    "at",
    "id",
    "sym",
    "model",
    "action",
    "h",
    "conf",
    "entry",
    "target",
    "stop",
    "valid",
    "ret",
    "hit",
    "first",
    "adverse",
    "btc",
    "reasons",
]


def predictions_exported(preds: list[Prediction], days: int) -> View:
    """Every call with its result at its own horizon, plus hit rates computed here, so a
    review never has to count."""
    rows, graded = [], []
    for p in preds:
        check = p.checks.get(f"h{p.horizon_h}")
        if check:
            graded.append((p, check["hit"]))
        rows.append(
            [
                p.created_at[:16],
                p.pred_id,
                p.symbol,
                _who(p),
                p.action,
                p.horizon_h,
                _num(p.confidence),
                _num(p.entry),
                None if p.target is None else _num(p.target),
                None if p.stop is None else _num(p.stop),
                p.valid,
                _num(check["return_pct"]) if check else None,
                check["hit"] if check else None,
                p.target_hit_first,
                None if p.max_adverse_pct is None else _num(p.max_adverse_pct),
                p.snapshot.get("btc_regime"),
                "; ".join(p.reasons),
            ]
        )
    by_horizon = _hit_rates((f"{p.horizon_h}h", hit) for p, hit in graded)
    by_model = _hit_rates((_who(p), hit) for p, hit in graded)
    summary = {
        "calls": len(preds),
        "graded": len(graded),
        "open": len(preds) - len(graded),
        "invalid": sum(not p.valid for p in preds),
        "by_horizon": by_horizon,
        "by_model": by_model,
    }
    data = {"days": days, "summary": summary, "columns": EXPORT_COLUMNS, "rows": rows}
    lines = [
        f"Calls {days}d: {len(preds)}, graded {len(graded)}, open {summary['open']}, "
        f"invalid {summary['invalid']}",
        "By horizon: " + _rates_text(by_horizon),
        "By model: " + _rates_text(by_model),
    ]
    return View(data, _lines(lines))


def _who(pred: Prediction) -> str:
    """The chat model, or the experiment arm and its model (two arms share a model)."""
    return pred.model if pred.arm == "chat" else f"{pred.arm} {pred.model}"


def experiment_ran(result: RunResult) -> View:
    """One line for the automation's run history; nothing is sent to Telegram."""
    data = asdict(result)
    data["cost_usd"] = round(result.cost_usd, 4)
    if result.ended:
        return View(data, f"Run {result.date} {result.slot}: experiment ended {result.ended}")
    arms = ", ".join(
        f"{name} {n}" + (f" ({result.invalid[name]} invalid)" if result.invalid[name] else "")
        for name, n in result.stored.items()
    )
    line = f"Run {result.date} {result.slot}: {arms or 'no calls'}; ${result.cost_usd:.4f}"
    if result.skipped:
        line += f"; {result.skipped} done before"
    for name, coins in result.failed.items():
        line += f"; {name} failed: {', '.join(coins)}"
    if result.missing:
        line += f"; no snapshot: {', '.join(result.missing)}"
    return View(data, line)


def _hit_rates(pairs: Iterable[tuple[str, bool]]) -> dict[str, dict[str, int]]:
    rates: dict[str, dict[str, int]] = {}
    for name, hit in pairs:
        rate = rates.setdefault(name, {"n": 0, "hits": 0})
        rate["n"] += 1
        rate["hits"] += hit
    for rate in rates.values():
        rate["hit_pct"] = round(rate["hits"] / rate["n"] * 100)
    return rates


def _rates_text(rates: dict[str, dict[str, int]]) -> str:
    return (
        ", ".join(f"{name} {r['hits']}/{r['n']} ({r['hit_pct']}%)" for name, r in rates.items())
        or "none graded"
    )


def trade_added(result: dict[str, Any]) -> View:
    """The journalled trade and the position it left."""
    position = result["position"]
    data: dict[str, Any] = {
        "trade_id": result["trade_id"],
        "symbol": result["symbol"],
        "side": result["side"],
        "qty": _num(result["qty"]),
        "price": _num(result["price"]),
        "fee": _num(result["fee"]),
        "position": {"qty": _num(position.qty), "avg_price": _num(position.avg_price)},
    }
    qty = service.plain(result["qty"])
    line = f"{result['side']} {qty} {result['symbol']} at {_usd(data['price'])}."
    if result["realised_pnl"] is not None:
        data["realised_pnl"] = _num(result["realised_pnl"])
        line += f" Realised {_signed_usd(data['realised_pnl'])}."
    if position.qty > 0:
        line += f" Now {service.plain(position.qty)} at avg {_usd(data['position']['avg_price'])}."
    else:
        line += " Position closed."
    return View(data, line)


def baseline_set(result: dict[str, Any]) -> View:
    data: dict[str, Any] = {
        "baseline_usdt": _num(result["baseline_usdt"]),
        "since": result["since"],
    }
    text = f"Starting cash set to {_usd(data['baseline_usdt'])}."
    if "replaced" in result:
        old = result["replaced"]
        data["replaced"] = {"baseline_usdt": _num(old["baseline_usdt"]), "since": old["since"]}
        text += f" Was {_usd(data['replaced']['baseline_usdt'])} since {old['since']}."
    return View(data, text)


def portfolio_summary() -> View:
    """Cash and open positions first, so "nothing is deployed" is never in doubt."""
    state = service.summary()
    cash = None if state.cash_usdt is None else _num(state.cash_usdt)
    data: dict[str, Any] = {
        "cash_usdt": cash,
        "invested_usdt": _num(state.invested_usdt),
        "open_positions": [
            {
                "symbol": p.symbol,
                "qty": _num(p.qty),
                "avg_price": _num(p.avg_price),
                "cost_basis": _num(p.cost_basis),
            }
            for p in state.open_positions
        ],
        "realised_pnl": _num(state.realised_pnl),
        "baseline_usdt": None if state.baseline_usdt is None else _num(state.baseline_usdt),
        "since": state.since,
    }
    lines = ["Cash: " + ("not known, no starting cash set" if cash is None else _usd(cash))]
    if state.open_positions:
        count = len(state.open_positions)
        lines.append(
            f"Deployed: {_usd(data['invested_usdt'])} in {count} "
            f"position{'s' if count > 1 else ''}, realised {_signed_usd(data['realised_pnl'])}"
        )
        rows = [
            f"{p.symbol} {service.plain(p.qty)} at avg {_usd(_num(p.avg_price))}"
            for p in state.open_positions
        ]
        if len(rows) > 3:
            rows = [*rows[:2], f"+{len(rows) - 2} more"]
        lines += rows
    else:
        lines.append(f"Nothing deployed, realised {_signed_usd(data['realised_pnl'])}")
    return View(data, _lines(lines))


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
        market["btc_dominance"] = rounded(metrics.btc_dominance, 1)
        market["total_mcap_chg_24h"] = rounded(metrics.total_mcap_chg_24h, 2)
        market["stablecoin_share"] = rounded(metrics.stablecoin_share, 1)
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
        "price": sig(coin.price),
        "chg_1h": rounded(coin.change_1h, 2),
        "chg_24h": rounded(coin.change_24h, 2),
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


def _usd(value: float | None) -> str:
    if value is None:
        return "?"
    if value >= 1000:
        return f"${value:,.0f}"
    if value >= 1:
        return f"${value:,.2f}"
    return f"${value:.4g}"


def _num(value: Decimal) -> float:
    # The journal already rounds to 10 decimals, so a float keeps every digit that matters.
    return float(value)


def _signed_usd(value: float) -> str:
    return ("-" if value < 0 else "+") + _usd(abs(value))


def _pct(value: float) -> str:
    return f"{value:+.1f}%"


def _pct_or(value: float | None) -> str:
    return "?" if value is None else _pct(value)


def _side(above: bool | None) -> str:
    return "?" if above is None else ("above" if above else "below")


def _short(text: str, width: int = 90) -> str:
    return text if len(text) <= width else text[: width - 1] + "…"


def _lines(lines: list[str]) -> str:
    return "\n".join(lines[:TELEGRAM_MAX_LINES])
