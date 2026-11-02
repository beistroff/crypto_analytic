"""Categorical Naive Bayes with Laplace smoothing (plan 5.3), in plain Python.

``P(up | x)`` is proportional to ``P(up)`` times the product of ``P(x_f | up)`` over the
features, and the same for down. Priors are the class shares of the training rows. Each
likelihood is ``(count + alpha) / (class rows + alpha * categories of f)``, so a category
never seen with a class gets a small probability instead of zero. The products are sums
of logs. scikit-learn's ``CategoricalNB`` gives the same numbers (tests/test_nb.py).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

Row = tuple[str, ...]  # one category per feature, in the model's feature order


@dataclass(frozen=True)
class Model:
    priors: tuple[float, float]  # down, up
    # feature -> category -> (P(category | down), P(category | up))
    likelihoods: dict[str, dict[str, tuple[float, float]]]

    def p_up(self, x: Row) -> float:
        down, up = (math.log(p) for p in self.priors)
        for categories, category in zip(self.likelihoods.values(), x, strict=True):
            down += math.log(categories[category][0])
            up += math.log(categories[category][1])
        return 1 / (1 + math.exp(down - up))


def fit(
    xs: Sequence[Row], ys: Sequence[int], categories: dict[str, tuple[str, ...]], alpha: float = 1.0
) -> Model:
    """Train on rows ``xs`` with labels ``ys`` (1 up, 0 down); ``categories`` names every
    feature's possible values, in row order, including ones the rows lack."""
    rows = [ys.count(0), ys.count(1)]
    counts = {f: {c: [0, 0] for c in values} for f, values in categories.items()}
    for x, y in zip(xs, ys, strict=True):
        for feature, category in zip(categories, x, strict=True):
            counts[feature][category][y] += 1
    likelihoods = {
        feature: {
            category: (
                (n[0] + alpha) / (rows[0] + alpha * len(by_category)),
                (n[1] + alpha) / (rows[1] + alpha * len(by_category)),
            )
            for category, n in by_category.items()
        }
        for feature, by_category in counts.items()
    }
    return Model(priors=(rows[0] / len(ys), rows[1] / len(ys)), likelihoods=likelihoods)
