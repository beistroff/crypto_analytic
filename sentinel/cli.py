"""``sentinel`` command line.

Command groups are added here as their tasks land (docs/IMPLEMENTATION_PLAN.md).
Results go to stdout as compact JSON (or 5 lines or fewer with ``--format telegram``);
logs go to stderr. A failing source prints ``{"error": ...}`` and exits 1.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any

import click
import requests
from botocore.exceptions import BotoCoreError, ClientError

from sentinel import __version__, aws, health, log, views
from sentinel.alerts import news as alerts_news
from sentinel.alerts import watch as alerts_watch
from sentinel.alerts.watch import WatchError
from sentinel.config import get_settings
from sentinel.data import SourceError
from sentinel.models import check, history, train
from sentinel.portfolio import service
from sentinel.portfolio.service import JournalError
from sentinel.predict import journal, runner, scorer
from sentinel.predict.journal import PredictError
from sentinel.store.real import VersionConflict

FORMAT = click.option("--format", "fmt", type=click.Choice(["json", "telegram"]), default="json")


class _Amount(click.ParamType):
    """A decimal number, kept exact; money and quantities never pass through a float."""

    name = "number"

    def __init__(self, *, allow_zero: bool = False) -> None:
        self.allow_zero = allow_zero

    def convert(self, value: Any, param: click.Parameter | None, ctx: click.Context | None) -> Any:
        if isinstance(value, Decimal):
            return value
        try:
            amount = Decimal(value)
        except InvalidOperation:
            self.fail(f"{value!r} is not a number", param, ctx)
        if not amount.is_finite() or amount < 0 or (amount == 0 and not self.allow_zero):
            self.fail(
                f"{value!r} must be {'zero or ' if self.allow_zero else ''}positive", param, ctx
            )
        return amount


def _emit(view: views.View, fmt: str) -> None:
    click.echo(view.text if fmt == "telegram" else json.dumps(view.data, separators=(",", ":")))


def _source_errors(command: Callable[..., Any]) -> Callable[..., Any]:
    """Report API and key errors as one JSON line (codes only, never key values)."""

    @functools.wraps(command)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return command(*args, **kwargs)
        except (
            SourceError,
            aws.SecretError,
            JournalError,
            VersionConflict,
            WatchError,
            PredictError,
        ) as exc:
            error = str(exc)
        except (requests.RequestException, BotoCoreError, ClientError) as exc:
            error = aws.error_code(exc)
        click.echo(json.dumps({"error": error}, separators=(",", ":")))
        raise SystemExit(1)

    return wrapper


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="sentinel")
def cli() -> None:
    """Crypto Sentinel: market data, trade journal and predictions."""
    log.setup()


@cli.group()
def config() -> None:
    """Inspect the settings."""


@config.command("show")
def config_show() -> None:
    """Print the resolved settings as JSON (no secrets)."""
    click.echo(get_settings().model_dump_json())


@cli.command("health")
@click.option(
    "--wait",
    "wait_s",
    type=click.FloatRange(min=0),
    default=0,
    help="Keep retrying transient failures for up to this many seconds.",
)
@click.option("--format", "fmt", type=click.Choice(["json", "telegram"]), default="json")
@click.pass_context
def health_cmd(ctx: click.Context, wait_s: float, fmt: str) -> None:
    """Check keys, DynamoDB, S3 and the market and model APIs; exit 1 if not ready."""
    results = health.run(wait_s)
    if fmt == "json":
        click.echo(json.dumps(health.summary(results), separators=(",", ":")))
    else:
        click.echo(health.telegram(results))
    if not all(r.ok for r in results):
        ctx.exit(1)


@cli.group()
def market() -> None:
    """Market data and computed signals (CoinMarketCap, Fear & Greed, exchanges)."""


@market.command("overview")
@click.option("--symbol", "symbols", default="BTC", help="Comma-separated, e.g. BTC,SOL.")
@FORMAT
@_source_errors
def market_overview(symbols: str, fmt: str) -> None:
    """Market context (Fear & Greed, BTC dominance, market cap, stablecoins) and quotes."""
    _emit(views.overview([s for s in symbols.split(",") if s.strip()]), fmt)


@market.command("top")
@click.option("--limit", type=click.IntRange(1, 100), default=15)
@FORMAT
@_source_errors
def market_top(limit: int, fmt: str) -> None:
    """Top coins by market cap with the legacy rule signal."""
    _emit(views.top(limit), fmt)


@market.command("scalp")
@click.option("--limit", type=click.IntRange(1, 200), default=50)
@FORMAT
@_source_errors
def market_scalp(limit: int, fmt: str) -> None:
    """Scalp candidates: actively traded, not pumped yet."""
    _emit(views.scalp(limit), fmt)


@market.command("scan")
@click.option("--limit", type=click.IntRange(1, 100), default=50)
@click.option("--symbol", "symbols", default="", help="Extra coins, e.g. DOT,ADA.")
@FORMAT
@_source_errors
def market_scan(limit: int, symbols: str, fmt: str) -> None:
    """One row of computed signals per top coin (RSI, averages, strength against BTC,
    7-day range, funding), BTC's regime first; --symbol adds coins outside the top N."""
    _emit(views.scan(limit, [s.strip().upper() for s in symbols.split(",") if s.strip()]), fmt)


@market.command("candles")
@click.argument("symbol")
@click.option("--tf", "timeframe", type=click.Choice(["1w", "1d", "4h", "1h", "15m"]), default="1w")
@click.option("--limit", type=click.IntRange(2, 300), default=104, help="Candles, newest last.")
@FORMAT
@_source_errors
def market_candles(symbol: str, timeframe: str, limit: int, fmt: str) -> None:
    """UTC candles for any span, 15m for a scalp to 1w for years (the default: 104 weeks).
    From OKX, or the exchange with the longer history."""
    _emit(views.candles(symbol, timeframe, limit), fmt)


@market.command("whales")
@click.argument("symbol")
@FORMAT
@_source_errors
def market_whales(symbol: str, fmt: str) -> None:
    """Rough whale check for one coin (a sharp 1 h pump)."""
    _emit(views.whales(symbol), fmt)


@cli.command("snapshot")
@click.argument("symbol")
@FORMAT
@_source_errors
def snapshot_cmd(symbol: str, fmt: str) -> None:
    """Computed signals for one coin, BTC first: regime, market, macro, news, flow,
    technicals, range levels and strength against BTC."""
    _emit(views.snapshot(symbol), fmt)


@cli.group()
def news() -> None:
    """Headlines for the agent to judge."""


@news.command("long")
@click.argument("symbol")
@click.option("--limit", type=click.IntRange(1, 10), default=3)
@FORMAT
@_source_errors
def news_long(symbol: str, limit: int, fmt: str) -> None:
    """The coin's most read NewsAPI headlines of 14 days (about 24 h delayed)."""
    _emit(views.news(symbol, limit), fmt)


@news.command("world")
@click.option("--limit", type=click.IntRange(1, 10), default=5)
@FORMAT
@_source_errors
def news_world(limit: int, fmt: str) -> None:
    """World news of 3 days that moves markets (rates, policy, bans, war, AI), most read first."""
    _emit(views.world_news(limit), fmt)


@news.command("alert")
@FORMAT
def news_alert(fmt: str) -> None:
    """Major market-moving headlines from the crypto feeds, each once, or NO_REPLY (an
    OpenClaw automation runs this every 30 minutes and delivers what it prints)."""
    _emit(views.news_alerted(alerts_news.check()), fmt)


@cli.group()
def watch() -> None:
    """Price levels to be alerted about (checked every 15 minutes, no LLM)."""


@watch.command("add")
@click.argument("symbol")
@click.option("--trigger", type=click.Choice(alerts_watch.TRIGGERS), required=True)
@click.option("--level", type=_Amount(), required=True, help="Price in USDT.")
@click.option(
    "--tf",
    "timeframe",
    type=click.Choice(alerts_watch.CLOSE_TIMEFRAMES),
    help="Candle for close triggers (default 1d, a UTC day).",
)
@click.option("--stop", type=_Amount(), help="Where the idea is wrong.")
@click.option("--target", type=_Amount())
@click.option("--note", help="Why, in a few words.")
@FORMAT
@_source_errors
def watch_add(
    symbol: str,
    trigger: str,
    level: Decimal,
    timeframe: str | None,
    stop: Decimal | None,
    target: Decimal | None,
    note: str | None,
    fmt: str,
) -> None:
    """Watch a level; your Telegram gets one alert when it is reached."""
    added, price = alerts_watch.add(
        symbol, trigger, level, timeframe, stop=stop, target=target, note=note
    )
    _emit(views.watch_added(added, price), fmt)


@watch.command("list")
@FORMAT
@_source_errors
def watch_list(fmt: str) -> None:
    """Active watches."""
    _emit(views.watch_list(alerts_watch.pending()), fmt)


@watch.command("remove")
@click.argument("watch_id")
@FORMAT
@_source_errors
def watch_remove(watch_id: str, fmt: str) -> None:
    """Stop an active watch."""
    _emit(views.watch_removed(alerts_watch.remove(watch_id)), fmt)


@watch.command("check")
@FORMAT
@_source_errors
def watch_check(fmt: str) -> None:
    """Check every watch once; print one alert line per hit, or NO_REPLY (an OpenClaw
    automation runs this every 15 minutes)."""
    _emit(views.watch_checked(alerts_watch.check()), fmt)


@cli.group()
def predict() -> None:
    """Calls logged from chat, checked by code and scored later."""


@predict.command("log")
@click.option("--json", "raw", required=True, help="The call as PredictionOut JSON.")
@click.option("--symbol", required=True)
@click.option("--model", required=True, help="The chat model that made the call.")
@click.option("--source", type=click.Choice(["chat"]), default="chat")
@FORMAT
@_source_errors
def predict_log(raw: str, symbol: str, model: str, source: str, fmt: str) -> None:
    """Check a call and store it with the market it was made in."""
    _emit(views.prediction_logged(journal.log(symbol, raw, model, source)), fmt)


@predict.command("show")
@click.argument("pred_id")
@FORMAT
@_source_errors
def predict_show(pred_id: str, fmt: str) -> None:
    """A logged call in full: reasons, BTC context, snapshot, validator result."""
    _emit(views.prediction(journal.show(pred_id)), fmt)


@predict.command("score")
@FORMAT
@_source_errors
def predict_score(fmt: str) -> None:
    """Check every due call once against the market (an OpenClaw automation runs this
    every hour, sending nothing)."""
    _emit(views.prediction_scored(scorer.score()), fmt)


@predict.command("export")
@click.option("--days", type=click.IntRange(1, 90), default=14)
@FORMAT
@_source_errors
def predict_export(days: int, fmt: str) -> None:
    """The calls of the last days with their results and hit rates, for a review."""
    _emit(views.predictions_exported(journal.export(days), days), fmt)


@cli.group()
def experiment() -> None:
    """The model comparison: every arm calls the same snapshots (experiment.yaml)."""


@experiment.command("run")
@click.option("--slot", type=click.Choice(runner.SLOTS), help="Default: the current UTC slot.")
@FORMAT
@_source_errors
def experiment_run(slot: str | None, fmt: str) -> None:
    """One run: a snapshot per coin, a call per arm (an OpenClaw automation runs this at
    00:05, 08:05 and 16:05 UTC, sending nothing)."""
    _emit(views.experiment_ran(runner.run(slot)), fmt)


@cli.group()
def nb() -> None:
    """Naive Bayes: a second opinion from market history, never the source of truth."""


@nb.command("build-dataset")
@click.option("--days", type=click.IntRange(400, 1500), default=1095)
@FORMAT
@_source_errors
def nb_build_dataset(days: int, fmt: str) -> None:
    """Daily features and next-day returns of the experiment coins, stored in S3."""
    _emit(views.dataset_built(history.build(days, runner.load().coins)), fmt)


@nb.command("train")
@click.option("--dataset", "key", help="S3 key of a dataset (default: the newest).")
@FORMAT
@_source_errors
def nb_train(key: str | None, fmt: str) -> None:
    """Walk-forward report, then the model on every day of the dataset, stored in S3."""
    _emit(views.model_trained(train.train(key)), fmt)


@nb.command("check")
@click.argument("symbol")
@FORMAT
@_source_errors
def nb_check(symbol: str, fmt: str) -> None:
    """P(next day up) for a coin from the stored model, and the features behind it."""
    _emit(views.nb_checked(check.check(symbol)), fmt)


@cli.group()
def trade() -> None:
    """The trade journal."""


@trade.command("add")
@click.option("--side", type=click.Choice(["buy", "sell"], case_sensitive=False), required=True)
@click.option("--symbol", required=True, help="Ticker, e.g. SOL.")
@click.option("--qty", type=_Amount(), required=True)
@click.option("--price", type=_Amount(), required=True, help="Price per coin in USDT.")
@click.option("--fee", type=_Amount(allow_zero=True), default=Decimal(0), help="Fee in USDT.")
@click.option("--venue", help="Where it was traded.")
@click.option("--note", help="Why, in a few words.")
@FORMAT
@_source_errors
def trade_add(
    side: str,
    symbol: str,
    qty: Decimal,
    price: Decimal,
    fee: Decimal,
    venue: str | None,
    note: str | None,
    fmt: str,
) -> None:
    """Journal a buy or sell and update the position."""
    result = service.record_trade(side, symbol, qty, price, fee, venue=venue, note=note)
    _emit(views.trade_added(result), fmt)


@cli.group()
def portfolio() -> None:
    """Cash and positions from the trade journal."""


@portfolio.command("summary")
@FORMAT
@_source_errors
def portfolio_summary(fmt: str) -> None:
    """Cash and open positions first, then what is deployed and realised."""
    _emit(views.portfolio_summary(), fmt)


@portfolio.command("baseline")
@click.option("--usdt", type=_Amount(allow_zero=True), required=True, help="Starting cash.")
@click.option("--replace", is_flag=True, help="Overwrite a starting cash already set.")
@FORMAT
@_source_errors
def portfolio_baseline(usdt: Decimal, replace: bool, fmt: str) -> None:
    """Set the starting cash (USDT) that the cash balance is counted from."""
    _emit(views.baseline_set(service.set_baseline(usdt, replace=replace)), fmt)
