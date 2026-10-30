"""Market history for Naive Bayes (plan 5.1): ``sentinel nb build-dataset``.

One row per experiment coin (``experiment.yaml``) and finished UTC day over the last
``days`` days: the raw features of ``features.raw`` and the next day's return in percent.
Market data only (candles and Fear & Greed), no trades or journal items. Daily candles come
from the live ``exchange.history`` (OKX 300 or Kraken 720 days), paged back on OKX here
when that is too short; Fear & Greed's full history from alternative.me. BTC dominance is
left out: its history needs a paid CMC plan.

Rows hold raw numbers, not buckets, so the edges can change without a rebuild. They are
stored as gzipped CSV in the backup bucket under ``datasets/nb/<last day>.csv.gz``.
"""

from __future__ import annotations

import csv
import gzip
import io
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

import requests

from sentinel import aws, net
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
    fng = _fear_greed()
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
    best = exchange.history(symbol, "1d", limit).candles
    if len(best) < limit:
        paged = _okx_days(symbol, limit)
        best = paged if len(paged) > len(best) else best
    return [c for c in best if c.closed]


def _okx_days(symbol: str, limit: int) -> list[Candle]:
    """Up to ``limit`` daily OKX candles, oldest first, in pages of 300 going back from the
    oldest one so far; none when OKX does not list the coin."""
    rows: list[list[Any]] = []
    while len(rows) < limit:
        params = {"instId": exchange.pair("okx", symbol), "bar": exchange.OKX_BARS["1d"]}
        params["limit"] = min(limit - len(rows), exchange.OKX_MAX_LIMIT)
        if rows:
            params["after"] = rows[-1][0]
        response = net.session("okx").get(exchange.OKX_URL, params=params)
        body = response.json()
        if body.get("code") == exchange.OKX_NOT_LISTED:
            return []
        if response.status_code != 200 or body.get("code") != "0":
            raise SourceError(f"OKX candles: HTTP {response.status_code}, code {body.get('code')}")
        rows.extend(body["data"])
        if len(body["data"]) < params["limit"]:
            break  # no older candles
    now = datetime.now(UTC)
    candles = []
    # [ts ms, open, high, low, close, vol, volCcy, volCcyQuote, confirm], newest first
    for r in reversed(rows):
        ts = datetime.fromtimestamp(int(r[0]) / 1000, UTC)
        o, h, low, c = map(float, r[1:5])
        candles.append(Candle(ts, o, h, low, c, float(r[7]), closed=ts + timedelta(days=1) <= now))
    return candles


def _fear_greed() -> dict[date, int]:
    """Every day's value since February 2018, by UTC day."""
    response = net.session("feargreed").get(feargreed.URL, params={"limit": 0})  # 0: all
    if response.status_code != 200:
        raise SourceError(f"Fear & Greed: HTTP {response.status_code}")
    return {
        datetime.fromtimestamp(int(e["timestamp"]), UTC).date(): int(e["value"])
        for e in response.json()["data"]
    }


def _put(key: str, rows: list[dict[str, float | str]]) -> None:
    text = io.StringIO()
    writer = csv.DictWriter(text, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    body = gzip.compress(text.getvalue().encode("utf-8"))
    aws.client("s3").put_object(Bucket=get_settings().backup_bucket, Key=key, Body=body)
