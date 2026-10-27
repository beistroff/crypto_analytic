"""Historical dataset for Naive Bayes (plan 5.1): ``sentinel nb build-dataset``.

One row per experiment coin (``experiment.yaml``) and finished UTC day over the last
``days`` days: the raw features of ``features.raw`` and the next day's return in percent.
Daily candles come from OKX (paged) or Kraken, whichever has the longer history (Kraken
keeps 720 days); Fear & Greed from alternative.me. BTC dominance is left out: its history
needs a paid CMC plan.

Rows hold raw numbers, not buckets, so the edges can change without a rebuild. They are
stored as gzipped CSV in the backup bucket under ``datasets/nb/<last day>.csv.gz``.
"""

from __future__ import annotations

import csv
import gzip
import io
from collections import Counter
from dataclasses import dataclass
from datetime import date, timedelta

import requests

from sentinel import aws
from sentinel.config import get_settings
from sentinel.data import SourceError, exchange, feargreed
from sentinel.data.exchange import Candle
from sentinel.models import features
from sentinel.predict import runner
from sentinel.signals.indicators import pct

PREFIX = "datasets/nb/"
COLUMNS = ("date", "symbol", *(column for column, _, _ in features.FEATURES.values()), "ret_next")


@dataclass
class Built:
    key: str
    first: str
    last: str
    rows: dict[str, int]  # by coin
    missing: list[str]  # coins with no candles


def build(days: int) -> Built:
    """Fetch the history, compute the rows and store them; the key is in the result."""
    limit = days + features.WINDOW + 1  # and the open candle, dropped
    btc = _finished("BTC", limit)
    fng = feargreed.history()
    rows: list[dict[str, float | str]] = []
    missing = []
    for symbol in runner.load().coins:
        try:
            coin = btc if symbol == "BTC" else _finished(symbol, limit)
        except (SourceError, requests.RequestException):
            missing.append(symbol)
            continue
        rows.extend(coin_rows(symbol, coin, btc, fng, days))
    if not rows:
        raise SourceError("no dataset rows")
    dates = [str(r["date"]) for r in rows]
    built = Built(
        key=f"{PREFIX}{max(dates)}.csv.gz",
        first=min(dates),
        last=max(dates),
        rows=dict(Counter(str(r["symbol"]) for r in rows)),
        missing=missing,
    )
    _put(built.key, rows)
    return built


def coin_rows(
    symbol: str, coin: list[Candle], btc: list[Candle], fng: dict[date, int], days: int
) -> list[dict[str, float | str]]:
    """One row per day of the last ``days`` that has a full window and a next day."""
    btc_at = {c.ts: i for i, c in enumerate(btc)}
    first = coin[-1].ts - timedelta(days=days)
    rows: list[dict[str, float | str]] = []
    for i in range(features.WINDOW - 1, len(coin) - 1):
        day, after = coin[i], coin[i + 1]
        j = btc_at.get(day.ts)
        if day.ts < first or j is None or after.ts - day.ts != timedelta(days=1):
            continue
        window = coin[i - features.WINDOW + 1 : i + 1]
        values = features.raw(window, btc[: j + 1], fng.get(day.ts.date()))
        if values is not None:
            ret_next = pct(after.close, day.close)
            rows.append(
                {"date": f"{day.ts:%Y-%m-%d}", "symbol": symbol, **values, "ret_next": ret_next}
            )
    return rows


def load(key: str | None = None) -> tuple[str, list[dict[str, float | str]]]:
    """A stored dataset (the newest when ``key`` is None) and its key."""
    s3 = aws.client("s3")
    bucket = get_settings().backup_bucket
    if key is None:
        listed = s3.list_objects_v2(Bucket=bucket, Prefix=PREFIX).get("Contents", [])
        if not listed:
            raise SourceError("no dataset yet: run sentinel nb build-dataset")
        key = max(item["Key"] for item in listed)
    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    reader = csv.DictReader(io.StringIO(gzip.decompress(body).decode("utf-8")))
    rows = [
        {k: v if k in ("date", "symbol") else float(v) for k, v in row.items()} for row in reader
    ]
    return key, rows


def _finished(symbol: str, limit: int) -> list[Candle]:
    return [c for c in exchange.history(symbol, "1d", limit).candles if c.closed]


def _put(key: str, rows: list[dict[str, float | str]]) -> None:
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    body = gzip.compress(text.getvalue().encode("utf-8"))
    aws.client("s3").put_object(Bucket=get_settings().backup_bucket, Key=key, Body=body)
