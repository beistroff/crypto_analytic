"""Crypto Fear & Greed Index from alternative.me (no key; full history is free)."""

from __future__ import annotations

from dataclasses import dataclass

from sentinel import net
from sentinel.data import SourceError

URL = "https://api.alternative.me/fng/"


@dataclass(frozen=True)
class Mood:
    value: int  # 0 extreme fear ... 100 extreme greed
    label: str


def latest() -> Mood:
    response = net.session("feargreed").get(URL, params={"limit": 1})
    if response.status_code != 200:
        raise SourceError(f"Fear & Greed: HTTP {response.status_code}")
    entry = response.json()["data"][0]
    return Mood(value=int(entry["value"]), label=entry["value_classification"])
