"""``sentinel`` command line.

Command groups are added here as their tasks land (docs/IMPLEMENTATION_PLAN.md).
Results go to stdout as compact JSON; logs go to stderr.
"""

from __future__ import annotations

import json

import click

from sentinel import __version__, health, log
from sentinel.config import get_settings


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
