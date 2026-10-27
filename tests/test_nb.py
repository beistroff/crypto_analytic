import json
import random
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import boto3
import pytest
from click.testing import CliRunner
from moto import mock_aws
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import CategoricalNB

from sentinel.cli import cli
from sentinel.models import dataset, train
from sentinel.models import naive_bayes as nb
from sentinel.predict import runner

BUCKET = "openclaw-files"


def _s3():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    return s3


def test_build_dataset_stores_a_row_per_coin_and_day(trending, monkeypatch):
    monkeypatch.setattr(runner, "load", lambda: SimpleNamespace(coins=["BTC", "SOL", "NOPE"]))
    midnights = [datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i) for i in range(1100)]
    history = [{"value": "50", "timestamp": f"{t.timestamp():.0f}"} for t in midnights]
    trending.fng.routes["/fng/"] = (200, {}, {"data": history})
    _s3()

    result = CliRunner().invoke(cli, ["nb", "build-dataset", "--days", "400"])

    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    # The trend's last candle (17 Oct) is open, so the 15th is the last day with a known next.
    assert out["key"] == "datasets/nb/2026-10-15.csv.gz"
    assert (out["rows"], out["missing"]) == ({"BTC": 400, "SOL": 400}, ["NOPE"])
    key, rows = dataset.load()
    row = rows[-1]
    assert (key, row["date"], row["symbol"]) == (out["key"], "2026-10-15", "SOL")
    assert row["btc_ret"] == pytest.approx(0.1)
    assert row["rsi14"] == 100.0  # only gains
    assert (row["fng"], row["weekend"]) == (50.0, 0.0)  # 16 Oct 2026 is a Friday
    assert row["ret_next"] == pytest.approx(0.1)


def _row(day, symbol, oversold):
    """A day whose next return follows the RSI: up after oversold, down after overbought."""
    return {
        "date": f"{day}",
        "symbol": symbol,
        "btc_ret": 0.0,
        "btc_vs_sma50": 1.0,
        "rsi14": 25.0 if oversold else 75.0,
        "vs_sma50": 1.0,
        "fng": 50.0,
        "weekend": 0.0,
        "vol_z": 0.0,
        "ret_next": 2.0 if oversold else -2.0,
    }


def test_train_reports_walk_forward_and_stores_the_model():
    start = date(2025, 1, 1)
    rows = [
        _row(start + timedelta(days=i), symbol, (i + n) % 2 == 0)
        for i in range(450)
        for n, symbol in enumerate(["BTC", "SOL"])
    ]
    with mock_aws():
        s3 = _s3()
        dataset._put("datasets/nb/2026-03-26.csv.gz", rows)

        result = CliRunner().invoke(cli, ["nb", "train"])

        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        report = out["report"]
        # 450 days: 365 to train, then months from day 366 (the last one partial).
        assert (report["folds"], report["test_rows"]) == (3, 170)
        assert report["nb"]["accuracy"] == 1.0
        assert report["logreg"]["accuracy"] == 1.0
        assert report["base"]["brier"] == pytest.approx(0.25)
        latest = json.loads(s3.get_object(Bucket=BUCKET, Key=train.LATEST)["Body"].read())
        assert latest == {"key": "models/nb/2026-03-26.json", "trained_until": "2026-03-26"}
        model = json.loads(s3.get_object(Bucket=BUCKET, Key=latest["key"])["Body"].read())
        assert (model["train_rows"], model["label_pct"]) == (730, 0.0)
        assert model["features"]["rsi"]["edges"] == [30.0, 70.0]
        assert model["likelihoods"]["rsi"]["low"][1] > 0.99  # P(low RSI | up)


def _random_rows(n=400, seed=7):
    rng = random.Random(seed)
    categories = {"a": ("x", "y", "z"), "b": ("p", "q"), "c": ("u", "v", "w", "never")}
    xs = [tuple(rng.choice(values[:3]) for values in categories.values()) for _ in range(n)]
    ys = [int(rng.random() < (0.7 if x[0] == "x" else 0.4)) for x in xs]
    return categories, xs, ys


def test_naive_bayes_matches_scikit_learn():
    categories, xs, ys = _random_rows()
    model = nb.fit(xs, ys, categories)
    codes = [[v.index(c) for v, c in zip(categories.values(), x, strict=True)] for x in xs]
    reference = CategoricalNB(alpha=1.0, min_categories=[len(v) for v in categories.values()])
    reference.fit(codes, ys)
    expected = reference.predict_proba(codes)[:, 1]
    assert [model.p_up(x) for x in xs] == pytest.approx(list(expected), abs=1e-9)


def test_logistic_regression_matches_scikit_learn():
    _, xs, ys = _random_rows()
    columns = sorted({(f, c) for x in xs for f, c in enumerate(x)})
    one_hot = [[float(x[f] == c) for f, c in columns] for x in xs]
    reference = LogisticRegression(C=1.0, tol=1e-10, max_iter=1000).fit(one_hot, ys)
    predict = train.logreg(xs, ys)
    expected = reference.predict_proba(one_hot)[:, 1]
    assert [predict(x) for x in xs] == pytest.approx(list(expected), abs=1e-5)
