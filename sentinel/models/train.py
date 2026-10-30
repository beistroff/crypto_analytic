"""Training and walk-forward validation (plan 5.3): ``sentinel nb train``.

Walk-forward: train on every day before a test month of ``TEST_DAYS``, predict that
month, move on by a month; the first test month comes after ``MIN_TRAIN_DAYS``. Every
past day, not only the last year, so the model has seen rallies, dumps and quiet months
(decided 30 Oct: better than a 365-day window in the tests). The scores pool every test
month's rows. Three predictions of P(up) are compared:

- ``nb``: Naive Bayes on the bucketed features;
- ``logreg``: logistic regression on the same buckets (one-hot, L2 penalty 1, Newton
  steps), the same inputs without Naive Bayes' independence assumption;
- ``base``: the training window's share of up days, the same for every row.

Scores: accuracy (up when P(up) > 0.5), Brier score and log-loss (lower is better).
The exported model is Naive Bayes on the whole dataset, as the walk-forward's last fold
would be. It is stored with its bucket edges and the report in the backup bucket
as ``models/nb/<last day>.json``, and ``models/nb/latest.json`` names it.
"""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta

from sentinel import aws
from sentinel.config import get_settings
from sentinel.data import SourceError
from sentinel.models import features, history
from sentinel.models import naive_bayes as nb
from sentinel.models.naive_bayes import Row

MIN_TRAIN_DAYS = 365
TEST_DAYS = 30
PREFIX = "models/nb/"
LATEST = f"{PREFIX}latest.json"
CATEGORIES = {name: categories for name, (_, _, categories) in features.FEATURES.items()}

Example = tuple[date, Row, int]
Predict = Callable[[Row], float]


@dataclass
class Trained:
    key: str
    dataset: str
    trained_until: str
    train_rows: int
    report: dict[str, object]


def train(dataset_key: str | None = None) -> Trained:
    """Validate, fit on every row and store the model; returns its key."""
    dataset_key, rows = history.load(dataset_key)
    examples = sorted(
        (
            date.fromisoformat(str(r["date"])),
            features.bucket(r),
            features.label(float(r["ret_next"])),
        )
        for r in rows
    )
    report = walk_forward(examples)
    last = examples[-1][0]
    model = nb.fit([e[1] for e in examples], [e[2] for e in examples], CATEGORIES)
    trained = Trained(
        key=f"{PREFIX}{last}.json",
        dataset=dataset_key,
        trained_until=f"{last}",
        train_rows=len(examples),
        report=report,
    )
    document = {
        **asdict(trained),
        "created_at": f"{datetime.now(UTC):%Y-%m-%dT%H:%M:%SZ}",
        "label_pct": features.LABEL_PCT,
        "window_days": features.WINDOW,
        "features": {
            name: {"column": column, "edges": edges, "categories": categories}
            for name, (column, edges, categories) in features.FEATURES.items()
        },
        "priors": model.priors,
        "likelihoods": model.likelihoods,
    }
    s3 = aws.client("s3")
    bucket = get_settings().backup_bucket
    s3.put_object(Bucket=bucket, Key=trained.key, Body=json.dumps(document).encode("utf-8"))
    pointer = json.dumps({"key": trained.key, "trained_until": trained.trained_until})
    s3.put_object(Bucket=bucket, Key=LATEST, Body=pointer.encode("utf-8"))
    return trained


def walk_forward(examples: Sequence[Example]) -> dict[str, object]:
    """Pooled test scores of every monthly fold; ``examples`` sorted by date."""
    predicted: dict[str, list[float]] = {"nb": [], "logreg": [], "base": []}
    actual: list[int] = []
    folds = 0
    start = examples[0][0] + timedelta(days=MIN_TRAIN_DAYS)
    while start <= examples[-1][0]:
        end = start + timedelta(days=TEST_DAYS)
        train = [e for e in examples if e[0] < start]
        test = [e for e in examples if start <= e[0] < end]
        start = end
        if not train or not test:
            continue
        xs, ys = [e[1] for e in train], [e[2] for e in train]
        base = sum(ys) / len(ys)
        models: dict[str, Predict] = {
            "nb": nb.fit(xs, ys, CATEGORIES).p_up,
            "logreg": logreg(xs, ys),
            "base": lambda _x, base=base: base,
        }
        for name, predict in models.items():
            predicted[name].extend(predict(e[1]) for e in test)
        actual.extend(e[2] for e in test)
        folds += 1
    if not folds:
        raise SourceError(f"the dataset spans less than {MIN_TRAIN_DAYS + 1} days")
    return {
        "folds": folds,
        "test_rows": len(actual),
        "test_up_pct": round(sum(actual) / len(actual) * 100, 1),
        **{name: scores(ps, actual) for name, ps in predicted.items()},
    }


def scores(ps: Sequence[float], ys: Sequence[int]) -> dict[str, float]:
    n = len(ys)
    clipped = [min(max(p, 1e-15), 1 - 1e-15) for p in ps]
    log_loss = -sum(math.log(p if y else 1 - p) for p, y in zip(clipped, ys, strict=True)) / n
    return {
        "accuracy": round(sum((p > 0.5) == y for p, y in zip(ps, ys, strict=True)) / n, 4),
        "brier": round(sum((p - y) ** 2 for p, y in zip(ps, ys, strict=True)) / n, 4),
        "log_loss": round(log_loss, 4),
    }


def logreg(xs: Sequence[Row], ys: Sequence[int], l2: float = 1.0, steps: int = 10) -> Predict:
    """Logistic regression on one-hot categories by Newton's method, with the L2 penalty on
    every weight but the intercept (as scikit-learn's ``LogisticRegression(C=1 / l2)``).
    Identical rows are counted once, so a step costs the distinct rows, not all of them."""
    columns: dict[tuple[int, str], int] = {}
    distinct = Counter(
        (tuple(columns.setdefault((f, c), len(columns)) for f, c in enumerate(x)), y)
        for x, y in zip(xs, ys, strict=True)
    )
    bias = len(columns)
    w = [0.0] * (bias + 1)
    for _ in range(steps):
        grad = [l2 * v for v in w[:bias]] + [0.0]
        hess = [[l2 if a == b != bias else 0.0 for b in range(bias + 1)] for a in range(bias + 1)]
        for (cols, y), n in distinct.items():
            active = (*cols, bias)
            p = _sigmoid(sum(w[c] for c in active))
            for a in active:
                grad[a] += n * (p - y)
                for b in active:
                    hess[a][b] += n * p * (1 - p)
        w = [v - d for v, d in zip(w, _solve(hess, grad), strict=True)]

    def predict(x: Row) -> float:
        cols = [columns[(f, c)] for f, c in enumerate(x) if (f, c) in columns]
        return _sigmoid(w[bias] + sum(w[c] for c in cols))

    return predict


def _sigmoid(z: float) -> float:
    return 1 / (1 + math.exp(-z)) if z >= 0 else math.exp(z) / (1 + math.exp(z))


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """``x`` with ``a x = b``, by Gaussian elimination with partial pivoting."""
    n = len(b)
    m = [[*row, rhs] for row, rhs in zip(a, b, strict=True)]
    for i in range(n):
        pivot = max(range(i, n), key=lambda r: abs(m[r][i]))
        m[i], m[pivot] = m[pivot], m[i]
        for r in range(i + 1, n):
            factor = m[r][i] / m[i][i]
            for c in range(i, n + 1):
                m[r][c] -= factor * m[i][c]
    x = [0.0] * n
    for i in reversed(range(n)):
        x[i] = (m[i][n] - sum(m[i][c] * x[c] for c in range(i + 1, n))) / m[i][i]
    return x
