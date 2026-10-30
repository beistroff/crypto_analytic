"""RQ3 (plan 5.5): does BTC lead the altcoins?

1. P(altcoin down | BTC down more than 2 % that day) against P(altcoin down) on all days,
   for the same day and the next day, over the experiment coins' daily history, with a
   chi-square test of independence (BTC down more than 2 % or not, altcoin down or not).
2. The likelihood ratios of the stored Naive Bayes model: P(category | up) over
   P(category | down) for every feature (above 1 favours an up day).

Run from the repo root; part 2 reads the model from S3:
    aws-vault exec sentinel-deploy -- python analysis/rq3_btc_leads.py [days]
"""

from __future__ import annotations

import sys
from datetime import timedelta

from scipy.stats import chi2_contingency

from sentinel.data import SourceError
from sentinel.models import check, history
from sentinel.predict import runner
from sentinel.signals.indicators import pct

BTC_DROP_PCT = -2.0
DAY = timedelta(days=1)


def btc_leads(days: int) -> None:
    closes = {c.ts: c.close for c in history.daily("BTC", days + 2)}
    btc_ret = {d: pct(closes[d], closes[d - DAY]) for d in closes if d - DAY in closes}
    # [BTC not down 2 %, BTC down 2 %] x [altcoin not down, altcoin down]
    tables = {"same day": [[0, 0], [0, 0]], "next day": [[0, 0], [0, 0]]}
    for symbol in runner.load().coins:
        if symbol == "BTC":
            continue
        alt = {c.ts: c.close for c in history.daily(symbol, days + 2)}
        for day, ret in btc_ret.items():
            for name, when in (("same day", day), ("next day", day + DAY)):
                if when in alt and when - DAY in alt:
                    tables[name][ret < BTC_DROP_PCT][alt[when] < alt[when - DAY]] += 1
    for name, t in tables.items():
        chi2, p, _, _ = chi2_contingency(t)
        dropped = sum(t[1])
        base = (t[0][1] + t[1][1]) / (sum(t[0]) + dropped)
        print(
            f"{name}: P(altcoin down | BTC down > 2 %) {t[1][1] / dropped:.1%} over {dropped} "
            f"coin-days, against {base:.1%} on all days; chi-square {chi2:.1f}, p {p:.2g}"
        )


def likelihood_ratios() -> None:
    key, model = check.model()
    print(f"Likelihood ratios, P(category | up) / P(category | down), {key}:")
    for feature, categories in model.likelihoods.items():
        ratios = ", ".join(f"{c} {up / down:.2f}" for c, (down, up) in categories.items())
        print(f"  {feature}: {ratios}")


if __name__ == "__main__":
    btc_leads(int(sys.argv[1]) if len(sys.argv) > 1 else 1095)
    try:
        likelihood_ratios()
    except SourceError as exc:
        print(f"No likelihood ratios: {exc}")
