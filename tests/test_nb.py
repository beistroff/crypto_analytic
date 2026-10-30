import json
import random
from datetime import date, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import boto3
import pytest
from click.testing import CliRunner
from moto import mock_aws
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import CategoricalNB

from sentinel.cli import cli
from sentinel.models import check, history, train
from sentinel.models import naive_bayes as nb
from sentinel.predict import runner

BUCKET = "openclaw-files"


def _s3():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    return s3


def test_build_dataset_stores_a_row_per_coin_and_day(trending, monkeypatch):
    monkeypatch.setattr(runner, "load", lambda: SimpleNamespace(coins=["BTC", "SOL", "NOPE"]))
    _s3()

    result = CliRunner().invoke(cli, ["nb", "build-dataset", "--days", "400"])

    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    # The trend's last candle (17 Oct) is open, so the 15th is the last day with a known next.
    assert out["key"] == "datasets/nb/2026-10-15.csv.gz"
    assert (out["rows"], out["missing"]) == ({"BTC": 400, "SOL": 400}, ["NOPE"])
    key, rows = history.load()
    row = rows[-1]
    assert (key, row["date"], row["symbol"]) == (out["key"], "2026-10-15", "SOL")
    assert row["dow"] == 4.0  # 16 Oct 2026, the day asked about, is a Friday
    assert row["atr_pct"] == pytest.approx(2.0, abs=0.05)  # every candle spans 2 %
    assert row["rel_btc_7d"] == pytest.approx(0.0)  # both rise 0.1 % a day
    assert row["ret_next"] == pytest.approx(0.1)


def test_okx_days_page_back_past_300(apis):
    day_ms = 86_400_000
    newest = 1792195200000  # 17 Oct 2026

    def page(first, count):  # newest first, as OKX sends them
        days = range(first, first + count)
        rows = [
            [str(newest - d * day_ms), "1", "2", "0.5", "1.5", "0", "0", "9", "1"] for d in days
        ]
        return (200, {}, {"code": "0", "data": rows})

    apis.okx.replies.extend([page(0, 300), page(300, 5)])  # older candles run out
    candles = history._okx_days("BTC", 310)
    second = parse_qs(urlsplit(apis.okx.seen[1].path).query)
    assert (second["limit"], second["after"]) == (["10"], [str(newest - 299 * day_ms)])
    assert len(candles) == 305
    assert candles[0].ts < candles[-1].ts


def _row(day, symbol, weaker):
    """A day whose next return follows the coin against BTC: up after weaker, down after
    stronger."""
    return {
        "date": f"{day}",
        "symbol": symbol,
        "dow": 0.0,
        "atr_pct": 6.0,
        "rel_btc_7d": -5.0 if weaker else 5.0,
        "ret_next": 2.0 if weaker else -2.0,
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
        history._put("datasets/nb/2026-03-26.csv.gz", rows)

        result = CliRunner().invoke(cli, ["nb", "train"])

        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        report = out["report"]
        # 450 days: at least 365 to train, then months from day 366 (the last one partial).
        assert (report["folds"], report["test_rows"]) == (3, 170)
        assert report["nb"]["accuracy"] == 1.0
        assert report["logreg"]["accuracy"] == 1.0
        assert report["base"]["brier"] == pytest.approx(0.25)
        latest = json.loads(s3.get_object(Bucket=BUCKET, Key=train.LATEST)["Body"].read())
        assert latest == {"key": "models/nb/2026-03-26.json", "trained_until": "2026-03-26"}
        model = json.loads(s3.get_object(Bucket=BUCKET, Key=latest["key"])["Body"].read())
        assert (model["train_rows"], model["label_pct"]) == (900, 0.0)  # every row
        assert model["features"]["vs_btc_7d"]["edges"] == [-3.0, 1.0]
        assert model["likelihoods"]["vs_btc_7d"]["weaker"][1] > 0.99  # P(weaker | up)


def test_nb_check_reads_the_stored_model(trending):
    _s3()
    start = date(2025, 1, 1)
    # Every training day looks like the trend's last one (a Saturday asked about, calm,
    # even with BTC), and one in four went up.
    rows = [
        {
            "date": f"{start + timedelta(days=i)}",
            "symbol": symbol,
            "dow": 5.0,
            "atr_pct": 2.0,
            "rel_btc_7d": 0.0,
            "ret_next": 1.0 if i % 4 == 0 else -1.0,
        }
        for i in range(450)
        for symbol in ("BTC", "SOL")
    ]
    history._put("datasets/nb/2026-03-26.csv.gz", rows)
    train.train()
    check.model.cache_clear()

    result = CliRunner().invoke(cli, ["nb", "check", "sol"])

    assert result.exit_code == 0, result.output
    out = json.loads(result.output)
    assert (out["symbol"], out["day"], out["model"]) == (
        "SOL",
        "2026-10-16",
        "models/nb/2026-03-26.json",
    )
    assert out["p_up"] == pytest.approx(0.25, abs=0.01)
    assert [(t["feature"], t["category"]) for t in out["top"]] == [
        ("weekday", "sat"),
        ("volatility", "calm"),
        ("vs_btc_7d", "even"),
    ]


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
