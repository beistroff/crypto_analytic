"""Major-news alerts: headlines that can move the whole market, flagged by code with no LLM.

``sentinel news alert`` runs every 30 minutes as an OpenClaw command automation, which
calls no model. It reads the free crypto news feeds (``sentinel.data.news_rss``, minutes
old), keeps the headlines of the last ``LOOKBACK`` that name a market-moving event (an
exchange hack or exploit, frozen or halted withdrawals, an insolvency, a delisting or a
ban, a rate decision, a stablecoin losing its peg), and prints at most ``MAX_ALERTS`` of
them. A quiet run prints ``NO_REPLY`` and delivers nothing.

Each link is alerted once: sent links are kept for two days in ``news_alerts.json`` in
the cache folder. When every feed fails the run stays silent (a news outage is not
news); the failure is logged.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sentinel.config import get_settings
from sentinel.data import SourceError, news_rss
from sentinel.data.newsapi import Headline

LOOKBACK = timedelta(hours=2)  # a few missed runs, and feeds that post late
KEEP = timedelta(days=2)
MAX_ALERTS = 3
EVENT = re.compile(
    r"\b(hack(s|ed|er|ers)?|exploit(s|ed)?|drain(s|ed)?|breach(es|ed)?|stolen"
    r"|insolven\w*|bankrupt\w*|delist\w*|bans?|banned|unauthori[sz]ed|freez\w*|froze|frozen"
    r"|(halts?|pauses?|suspends?)\b.{0,20}\bwithdrawals?"
    r"|withdrawals?\b.{0,20}\b(halted|paused|suspended)"
    r"|rate (cut|hike)s?|(cuts|raises|hikes) rates|depeg\w*)\b",
    re.IGNORECASE,
)

log = logging.getLogger(__name__)


@dataclass
class AlertResult:
    alerts: list[Headline] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # feeds that could not be read


def _now() -> datetime:
    return datetime.now(UTC)


def check() -> AlertResult:
    now = _now()
    result = AlertResult()
    try:
        feeds = news_rss.recent(now)
    except SourceError:
        log.warning("news feeds unavailable")
        result.missing.append("rss")
        return result
    result.missing += [f"rss:{name}" for name in feeds.failed]
    sent = _sent(now)
    for item in feeds.items:  # newest first
        link = news_rss.plain_link(item.headline.url)
        if item.published < now - LOOKBACK or link in sent:
            continue
        if EVENT.search(item.headline.title):
            result.alerts.append(item.headline)
            sent[link] = now.isoformat()
        if len(result.alerts) == MAX_ALERTS:
            break
    if result.alerts:
        _save(sent)
    return result


def _path() -> Path:
    return get_settings().cache_dir / "news_alerts.json"


def _sent(now: datetime) -> dict[str, str]:
    """Links alerted in the last ``KEEP``, with when."""
    try:
        sent = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}  # no file yet, or an unreadable one
    return {k: v for k, v in sent.items() if now - datetime.fromisoformat(v) < KEEP}


def _save(sent: dict[str, str]) -> None:
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sent), encoding="utf-8")
    except OSError as exc:
        log.warning("alerted links not saved", extra={"error": type(exc).__name__})
