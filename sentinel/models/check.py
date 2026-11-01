"""Live Naive Bayes check (plan 5.4): ``sentinel nb check SYM`` and the gate's input.

The model is the one ``models/nb/latest.json`` names, read from the backup bucket once per
process. Its stored features must be the code's (``features.FEATURES``): a model trained
with other features or edges is refused until ``sentinel nb train`` runs again. The
features come from the coin's and BTC's last ``WINDOW`` finished daily candles, exactly
as in training, so ``p_up`` is the chance that tomorrow's close is above today's.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cache

from sentinel import aws
from sentinel.config import get_settings
from sentinel.data import SourceError, exchange
from sentinel.data.exchange import Candle
from sentinel.models import features
from sentinel.models import naive_bayes as nb
from sentinel.models.train import LATEST


@dataclass(frozen=True)
class Check:
    symbol: str
    day: str  # the finished UTC day the features describe; p_up is about the next one
    p_up: float
    # (feature, category, P(category | up) / P(category | down)), strongest first
    top: list[tuple[str, str, float]]
    model: str  # S3 key of the model


@cache
def model() -> tuple[str, nb.Model]:
    """The latest stored model and its S3 key."""
    s3 = aws.client("s3")
    bucket = get_settings().backup_bucket
    try:
        pointer = json.loads(s3.get_object(Bucket=bucket, Key=LATEST)["Body"].read())
    except s3.exceptions.NoSuchKey as exc:
        raise SourceError("no model yet: run sentinel nb train") from exc
    doc = json.loads(s3.get_object(Bucket=bucket, Key=pointer["key"])["Body"].read())
    stored = {
        name: (f["column"], tuple(f["edges"]), tuple(f["categories"]))
        for name, f in doc["features"].items()
    }
    if stored != features.FEATURES:
        raise SourceError(f"{pointer['key']} has other features: run sentinel nb train")
    # JSON lists, not tuples: the model only indexes and unpacks them.
    return pointer["key"], nb.Model(priors=doc["priors"], likelihoods=doc["likelihoods"])


def check(symbol: str) -> Check:
    key, m = model()
    coin, btc = _finished(symbol), _finished("BTC")
    values = features.raw(coin, btc)
    if values is None:
        raise SourceError(f"not {features.WINDOW} finished days for {symbol.upper()} and BTC")
    x = features.bucket(values)
    ratios = []
    for feature, category in zip(m.likelihoods, x, strict=True):
        down, up = m.likelihoods[feature][category]
        ratios.append((feature, category, up / down))
    top = sorted(ratios, key=lambda r: abs(math.log(r[2])), reverse=True)[:3]
    return Check(symbol.upper(), f"{coin[-1].ts:%Y-%m-%d}", m.p_up(x), top, key)


def _finished(symbol: str) -> list[Candle]:
    return [c for c in exchange.candles(symbol, "1d", features.WINDOW + 1).candles if c.closed]
