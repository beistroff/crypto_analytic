"""Crypto Fear & Greed Index from alternative.me (no key; full history is free)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sentinel import net
from sentinel.data import SourceError

URL = "https://api.alternative.me/fng/"


@dataclass(frozen=True)
class Mood:
    value: int  # 0 extreme fear ... 100 extreme greed
    label: str


def latest() -> Mood:
    entry = _entries(1)[0]
    return Mood(value=int(entry["value"]), label=entry["value_classification"])


def history() -> dict[date, int]:
    """Every day's value since February 2018, by UTC day (the Naive Bayes dataset)."""
    return {
        datetime.fromtimestamp(int(e["timestamp"]), UTC).date(): int(e["value"])
        for e in _entries(0)  # 0: all of them
    }


def _entries(limit: int) -> list[dict[str, str]]:
    response = net.session("feargreed").get(URL, params={"limit": limit})
    if response.status_code != 200:
        raise SourceError(f"Fear & Greed: HTTP {response.status_code}")
    return response.json()["data"]
