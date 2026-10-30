"""Major-news alerts: headlines that can move the whole market, flagged by code with no LLM.

``sentinel news alert`` runs every 30 minutes as an OpenClaw command automation, which
calls no model. It reads the free crypto news feeds (``sentinel.data.news_rss``, minutes
old) and keeps the new headlines of the last ``LOOKBACK`` that name a market-moving event
(an exchange hack or exploit, frozen or halted withdrawals, an insolvency, a delisting or
a ban, a rate decision, a stablecoin losing its peg).

One alert is one line: the newest such headline with its source, and how many more there
are. After an alert, ``QUIET`` passes before the next one: outlets keep posting follow-ups
on a big event, and those are skipped, not saved for later. Every headline found is
remembered for two days in ``news_alerts.json`` in the cache folder, so none is alerted
twice. A quiet run, and a run where every feed fails (a news outage is not news), prints
``NO_REPLY`` and delivers nothing.
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
QUIET = timedelta(hours=3)
KEEP = timedelta(days=2)
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
    headline: Headline | None = None  # the one alerted, newest first
    more: int = 0  # further new major headlines in the same run
    skipped: int = 0  # new major headlines inside the quiet period
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
    last_alert, seen = _load(now)
    found = []
    for item in feeds.items:  # newest first
        link = news_rss.plain_link(item.headline.url)
        if (
            item.published >= now - LOOKBACK
            and link not in seen
            and EVENT.search(item.headline.title)
        ):
            found.append(item.headline)
            seen[link] = now.isoformat()
    if not found:
        return result
    if last_alert is not None and now - last_alert < QUIET:
        result.skipped = len(found)
    else:
        result.headline, result.more, last_alert = found[0], len(found) - 1, now
    _save(last_alert, seen)
    return result


def _path() -> Path:
    return get_settings().cache_dir / "news_alerts.json"


def _load(now: datetime) -> tuple[datetime | None, dict[str, str]]:
    """When the last alert went out, and the headline links seen in the last ``KEEP``."""
    try:
        state = json.loads(_path().read_text(encoding="utf-8"))
        last = datetime.fromisoformat(state["last_alert"]) if state.get("last_alert") else None
        seen = {k: v for k, v in state["seen"].items() if now - datetime.fromisoformat(v) < KEEP}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None, {}  # no file yet, or an unreadable one
    return last, seen


def _save(last_alert: datetime | None, seen: dict[str, str]) -> None:
    path = _path()
    state = {"last_alert": last_alert.isoformat() if last_alert else None, "seen": seen}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError as exc:
        log.warning("news alert state not saved", extra={"error": type(exc).__name__})
