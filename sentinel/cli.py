"""``sentinel`` command line.

Command groups are added here as their tasks land (docs/IMPLEMENTATION_PLAN.md).
Results go to stdout as compact JSON; logs go to stderr.
"""

from __future__ import annotations

import click

from sentinel import __version__, log
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
