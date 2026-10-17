"""``sentinel`` command line.

Command groups are added here as their tasks land (docs/IMPLEMENTATION_PLAN.md).
Results go to stdout as compact JSON (or 5 lines or fewer with ``--format telegram``);
logs go to stderr. A failing source prints ``{"error": ...}`` and exits 1.
"""

from __future__ import annotations

import functools
import json
from collections.abc import Callable
from typing import Any

import click
import requests

from sentinel import __version__, aws, health, log, views
from sentinel.config import get_settings
from sentinel.data import SourceError

FORMAT = click.option("--format", "fmt", type=click.Choice(["json", "telegram"]), default="json")


def _emit(view: views.View, fmt: str) -> None:
    click.echo(view.text if fmt == "telegram" else json.dumps(view.data, separators=(",", ":")))


def _source_errors(command: Callable[..., Any]) -> Callable[..., Any]:
    """Report API and key errors as one JSON line (codes only, never key values)."""

    @functools.wraps(command)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return command(*args, **kwargs)
        except (SourceError, aws.SecretError) as exc:
            error = str(exc)
        except requests.RequestException as exc:
            error = type(exc).__name__
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
    """Market data from CoinMarketCap and Fear & Greed."""


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
    """NewsAPI headlines (about 24 h delayed): longer-range research."""
    _emit(views.news(symbol, limit), fmt)


@cli.group()
def watch() -> None:
    """Price checks for monitoring."""


@watch.command("levels")
@click.argument("symbol")
@click.option("--below", type=float, help="Buy level: alert at or under this price.")
@click.option("--above", type=float, help="Sell level: alert at or over this price.")
@FORMAT
@_source_errors
def watch_levels(symbol: str, below: float | None, above: float | None, fmt: str) -> None:
    """Has the price reached a buy or sell level?"""
    if below is None and above is None:
        raise click.UsageError("give --below, --above or both")
    _emit(views.watch_levels(symbol, below, above), fmt)


@watch.command("move")
@click.argument("symbol")
@click.option("--entry", type=click.FloatRange(min=0, min_open=True), required=True)
@click.option("--min-pct", type=click.FloatRange(min=0), default=1.0, show_default=True)
@FORMAT
@_source_errors
def watch_move(symbol: str, entry: float, min_pct: float, fmt: str) -> None:
    """Move since an entry price; alert when it reaches --min-pct either way."""
    _emit(views.watch_move(symbol, entry, min_pct), fmt)
