"""Experiment statistics (plan 9.3): the numbers of the run, from the prediction journal.

Run from the repo root; ``fetch`` reads DynamoDB once, ``report`` needs no AWS:
    aws-vault exec sentinel-deploy -- python analysis/experiment_stats.py fetch calls.json
    python analysis/experiment_stats.py report calls.json > stats.md

Only scheduled calls from the first counted day on are used, so the warm-up and chat calls
stay out, and only those made within ``RUN_MINUTES`` of their slot's start: a manual re-run
hours later saw a newer market, so its calls are listed as left out. Arms are compared on
the calls they share (same date, slot and coin), both graded.
A call that failed the validator is graded like any other and counted per arm.

Simulated return of a call, held to its horizon: for a BUY the return minus the round-trip
fee, for a SELL the opposite return minus the fee, for a HOLD 0 (no trade).
"""

from __future__ import annotations

import json
import random
import sys
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from scipy.stats import binomtest, chi2, wilcoxon

from sentinel.predict import gate, runner
from sentinel.predict.scorer import MIN_GAIN_PCT
from sentinel.store.sim import Prediction, PredictionRepo

FIRST_DAY = date(2026, 11, 9)
FEE_PCT = 0.2  # round trip, for simulated returns only: hits stay as the scorer graded them
EXACT_BELOW = 25  # discordant pairs: under this McNemar's test uses the exact binomial
BOOTSTRAP_ROUNDS = 10_000
RUN_MINUTES = 65  # a run starts at 5 past its slot's hour and takes up to an hour
COCHRAN_ARMS = ("L0", "L1", "L1G")
ACTIONS = ("BUY", "SELL", "HOLD")
ENDINGS = ("target", "stop", "neither")  # what a BUY or SELL hit first
PAIRS = (
    ("L0", "L1"),
    ("L1", "L1G"),
    ("L0", "L1G"),
    ("L1", "H1"),
    ("H1", "D1"),
    ("H1", "G1"),
    ("F1", "S1"),
    ("F1", "L1"),
    ("F1", "H1"),
)


@dataclass(frozen=True)
class Call:
    day: str
    slot: str
    at: str  # HH:MM UTC the call was made
    symbol: str
    arm: str
    action: str
    confidence: float
    valid: bool
    hit: bool | None  # None until the horizon has passed
    ret: float | None  # percent at the horizon
    first: str | None  # target, stop or neither
    regime: str | None
    tokens_in: int | None
    tokens_out: int | None
    cost_usd: float | None
    latency_ms: int | None
    gate_triggered: bool | None
    revised: bool | None

    @property
    def key(self) -> tuple[str, str, str]:
        return self.day, self.slot, self.symbol

    @property
    def on_time(self) -> bool:
        minutes = int(self.at[:2]) * 60 + int(self.at[3:]) - int(self.slot or 0) * 60
        return 0 <= minutes <= RUN_MINUTES


def to_calls(preds: Sequence[Prediction]) -> list[Call]:
    calls = []
    for p in preds:
        if p.source != "scheduled":
            continue
        check = p.checks.get(f"h{p.horizon_h}")
        calls.append(
            Call(
                p.created_at[:10],
                p.slot or "",
                p.created_at[11:16],
                p.symbol,
                p.arm,
                p.action,
                float(p.confidence),
                p.valid,
                bool(check["hit"]) if check else None,
                float(check["return_pct"]) if check else None,
                p.target_hit_first,
                p.snapshot.get("btc_regime"),
                p.tokens_in,
                p.tokens_out,
                None if p.cost_usd is None else float(p.cost_usd),
                p.latency_ms,
                p.gate_triggered,
                p.revised,
            )
        )
    return calls


def fetch(path: str) -> int:
    """One query per date, paced below sentinel-sim's 2 RCU (``terraform/env/dynamodb``):
    a bulk export otherwise throttles (seen 16 Nov on the 7-day pull)."""
    end = runner.load().end_date or FIRST_DAY
    dates = [f"{FIRST_DAY + timedelta(n):%Y-%m-%d}" for n in range((end - FIRST_DAY).days)]
    repo = PredictionRepo()
    items = []
    for i, day in enumerate(dates):
        if i:
            time.sleep(2)
        items += repo.logged([day])
    calls = to_calls(items)
    Path(path).write_text(json.dumps([asdict(c) for c in calls]), encoding="utf-8")
    return len(calls)


def load(path: str) -> list[Call]:
    return [Call(**c) for c in json.loads(Path(path).read_text(encoding="utf-8"))]


def mcnemar(b: int, c: int) -> float:
    """p of McNemar's test for ``b`` and ``c`` calls only one arm got right."""
    n = b + c
    if n == 0:
        return 1.0
    if n < EXACT_BELOW:
        return float(binomtest(b, n, 0.5).pvalue)
    return float(chi2.sf((abs(b - c) - 1) ** 2 / n, 1))


def cochran_q(rows: Sequence[Sequence[int]]) -> tuple[float, float]:
    """Cochran's Q and its p; a row is one coin's 0 or 1 per arm."""
    arms = len(rows[0])
    per_arm = [sum(column) for column in zip(*rows, strict=True)]
    per_row = [sum(row) for row in rows]
    below = arms * sum(per_row) - sum(n * n for n in per_row)
    if below == 0:
        return 0.0, 1.0
    q = (arms - 1) * (arms * sum(n * n for n in per_arm) - sum(per_arm) ** 2) / below
    return q, float(chi2.sf(q, arms - 1))


def holm(ps: Sequence[float]) -> list[float]:
    """Holm-adjusted p values, in the order given."""
    adjusted = [0.0] * len(ps)
    worst = 0.0
    for rank, i in enumerate(sorted(range(len(ps)), key=lambda n: ps[n])):
        worst = max(worst, min(1.0, (len(ps) - rank) * ps[i]))
        adjusted[i] = worst
    return adjusted


def brier_parts(
    calls: Sequence[Call],
) -> tuple[float, float, float, float, list[tuple[int, float, float]]]:
    """Brier score, Murphy's reliability, resolution and uncertainty over 0.1-wide confidence
    bins, and each bin's (calls, mean confidence, hit rate)."""
    n = len(calls)
    base = sum(bool(c.hit) for c in calls) / n
    bins: dict[int, list[Call]] = defaultdict(list)
    for c in calls:
        bins[min(int(c.confidence * 10), 9)].append(c)
    rows = []
    reliability = resolution = 0.0
    for _, group in sorted(bins.items()):
        size = len(group)
        forecast = sum(c.confidence for c in group) / size
        observed = sum(bool(c.hit) for c in group) / size
        reliability += size * (forecast - observed) ** 2
        resolution += size * (observed - base) ** 2
        rows.append((size, forecast, observed))
    score = sum((c.confidence - bool(c.hit)) ** 2 for c in calls) / n
    return score, reliability / n, resolution / n, base * (1 - base), rows


def simulated(c: Call) -> float:
    if c.action == "HOLD" or c.ret is None:
        return 0.0
    return (c.ret if c.action == "BUY" else -c.ret) - FEE_PCT


def day_block_ci(by_day: dict[str, list[float]]) -> tuple[float, float]:
    """95 % interval of the mean, resampling whole days: coins of a day move together."""
    totals = [(sum(v), len(v)) for v in by_day.values()]
    rng = random.Random(0)
    means = []
    for _ in range(BOOTSTRAP_ROUNDS):
        sample = rng.choices(totals, k=len(totals))
        means.append(sum(t for t, _ in sample) / sum(n for _, n in sample))
    means.sort()
    return means[int(0.025 * BOOTSTRAP_ROUNDS)], means[int(0.975 * BOOTSTRAP_ROUNDS)]


def paired(a: Sequence[Call], b: Sequence[Call]) -> list[tuple[Call, Call]]:
    other = {c.key: c for c in b if c.hit is not None}
    return [(c, other[c.key]) for c in a if c.hit is not None and c.key in other]


def _share(k: int, n: int) -> str:
    return f"{k}/{n} ({k / n:.1%})" if n else "-"


def _wilson(k: int, n: int) -> str:
    if not n:
        return "-"
    ci = binomtest(k, n).proportion_ci(method="wilson")
    return f"{ci.low:.1%} to {ci.high:.1%}"


def _p(value: float) -> str:
    return "<0.0001" if value < 0.0001 else f"{value:.4f}"


def _table(title: str, head: str, rows: Sequence[Sequence[object]]) -> str:
    """A markdown table; ``head`` is the column names joined by ``|``."""
    lines = [
        f"## {title}",
        "",
        f"| {head.replace('|', ' | ')} |",
        "|" + " --- |" * (head.count("|") + 1),
    ]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def _hits(calls: Sequence[Call], action: str | None = None) -> tuple[int, int]:
    chosen = [c for c in calls if action is None or c.action == action]
    return sum(bool(c.hit) for c in chosen), len(chosen)


def _mean(values: Sequence[float]) -> str:
    return f"{sum(values) / len(values):.2f}" if values else "-"


def report(all_calls: Sequence[Call]) -> str:
    experiment = runner.load()
    late = [c for c in all_calls if not c.on_time]
    calls = [c for c in all_calls if c.on_time]
    arms: dict[str, list[Call]] = {arm.name: [] for arm in experiment.arms}
    for c in calls:
        arms.setdefault(c.arm, []).append(c)
    graded = {arm: [c for c in group if c.hit is not None] for arm, group in arms.items()}
    runs = len({(c.day, c.slot) for c in calls})
    expected = {arm.name: runs * (arm.sample or len(experiment.coins)) for arm in experiment.arms}
    parts = [
        f"# Experiment statistics\n\n{runs} runs, {len(calls)} calls, "
        f"{sum(c.hit is not None for c in calls)} graded. Pairs are compared on shared graded "
        f"calls; simulated returns are net of a {FEE_PCT} % round-trip fee. Per-arm rates are "
        "not paired: an arm with failed calls (see Coverage) is compared fairly only in the "
        "pair tables."
    ]
    if late:
        made = ", ".join(f"{c.arm} {c.symbol} {c.day} {c.slot} at {c.at}" for c in late)
        parts.append(f"Left out, made outside their run: {made}.")
    coverage = []
    for arm, group in arms.items():
        want, invalid = expected.get(arm, 0), sum(not c.valid for c in group)
        coverage.append((arm, want, len(group), want - len(group), len(graded[arm]), invalid))
    parts.append(_table("Coverage", "Arm|Expected|Stored|Failed|Graded|Invalid", coverage))

    hit_rows = []
    for arm, group in graded.items():
        k, n = _hits(group)
        by_action = [_share(*_hits(group, action)) for action in ACTIONS]
        waits = sum(c.ret is not None and c.ret <= MIN_GAIN_PCT for c in group)
        hit_rows.append((arm, n, *by_action, _share(k, n), _wilson(k, n), _share(waits, n)))
    head = "Arm|N|BUY|SELL|HOLD|All|All, 95 % Wilson|Always waiting"
    parts.append(_table("Hit rates", head, hit_rows))

    direction_rows = []
    for arm, group in graded.items():
        for action in ("BUY", "SELL"):
            chosen = [c for c in group if c.action == action]
            k, n = _hits(chosen)
            if not n:
                continue
            ended = " / ".join(str(sum(c.first == s for c in chosen)) for s in ENDINGS)
            p = _p(float(binomtest(k, n, 0.5).pvalue))
            direction_rows.append((arm, action, _share(k, n), _wilson(k, n), p, ended))
    head = "Arm|Call|Hits|95 % Wilson|p (binomial)|Target / stop / neither"
    parts.append(_table("BUY and SELL against 50 %", head, direction_rows))

    shared = [(f"{a} - {b}", paired(graded.get(a, []), graded.get(b, []))) for a, b in PAIRS]
    tests = []
    for pair, matched in shared:
        only_a = sum(bool(x.hit) and not y.hit for x, y in matched)
        only_b = sum(bool(y.hit) and not x.hit for x, y in matched)
        tests.append((pair, only_a, only_b, len(matched), mcnemar(only_a, only_b)))
    adjusted = holm([t[-1] for t in tests])
    rows = [(*t[:-1], _p(t[-1]), _p(q)) for t, q in zip(tests, adjusted, strict=True)]
    head = "Pair|Only first right|Only second right|Shared N|p|p (Holm)"
    parts.append(_table("McNemar (Holm over all pairs)", head, rows))

    keyed = [{c.key: int(bool(c.hit)) for c in graded.get(arm, [])} for arm in COCHRAN_ARMS]
    common = set.intersection(*(set(k) for k in keyed))
    if common:
        q, p = cochran_q([[k[key] for k in keyed] for key in sorted(common)])
        parts.append(
            f"## Cochran's Q\n\n{', '.join(COCHRAN_ARMS)} on {len(common)} shared calls: "
            f"Q = {q:.3f}, p = {_p(p)}"
        )
    scores, bin_rows = [], []
    for arm, group in graded.items():
        if not group:
            continue
        *brier, bins = brier_parts(group)
        scores.append((arm, *(f"{x:.4f}" for x in brier)))
        bin_rows += [(arm, n, f"{f:.2f}", f"{o:.1%}") for n, f, o in bins]
    parts.append(_table("Brier score", "Arm|Brier|REL|RES|UNC", scores))
    parts.append(_table("Reliability", "Arm|Calls|Mean confidence|Hit rate", bin_rows))

    return_rows = []
    for arm, group in graded.items():
        trades = [simulated(c) for c in group if c.action != "HOLD"]
        wins = _share(sum(t > 0 for t in trades), len(trades))
        return_rows.append((arm, len(trades), _mean(trades), wins))
    head = "Arm|Trades|Mean net, %|Net winners"
    parts.append(_table("Simulated returns, BUY and SELL", head, return_rows))

    diff_rows = []
    for pair, matched in shared:
        if not matched:
            continue
        diffs = [simulated(x) - simulated(y) for x, y in matched]
        by_day: dict[str, list[float]] = defaultdict(list)
        for (x, _), d in zip(matched, diffs, strict=True):
            by_day[x.day].append(d)
        low, high = day_block_ci(by_day)
        moved = [d for d in diffs if d]
        p = _p(float(wilcoxon(moved).pvalue)) if moved else "-"
        diff_rows.append((pair, len(diffs), _mean(diffs), f"{low:.2f} to {high:.2f}", p))
    head = "Pair|Shared N|Mean difference, %|95 % day-block bootstrap|p (Wilcoxon)"
    parts.append(_table("Simulated returns, pairs (HOLD counts as 0)", head, diff_rows))

    first = {c.key: c for c in graded.get("L1", [])}
    l1, gated = arms.get("L1", []), arms.get("L1G", [])
    confident = sum(c.action != "HOLD" and c.confidence >= gate.CONFIDENCE for c in l1)
    changed = [c for c in graded.get("L1G", []) if c.revised and c.key in first]
    gate_rows = [
        (f"L1 BUY or SELL with confidence {gate.CONFIDENCE} or more", confident),
        ("Gate triggered", sum(bool(c.gate_triggered) for c in gated)),
        ("Call changed", sum(bool(c.revised) for c in gated)),
        ("Changed calls right before", _share(*_hits([first[c.key] for c in changed]))),
        ("Changed calls right after", _share(*_hits(changed))),
    ]
    parts.append(_table("Naive Bayes gate (L1G)", "Measure|Value", gate_rows))

    cost_rows = []
    for arm, group in arms.items():
        total = sum(c.cost_usd or 0.0 for c in group)
        tokens_in = _mean([c.tokens_in for c in group if c.tokens_in is not None])
        tokens_out = _mean([c.tokens_out for c in group if c.tokens_out is not None])
        latency = _mean([c.latency_ms / 1000 for c in group if c.latency_ms is not None])
        per_call = f"{total / len(group):.6f}" if group else "-"
        per_run = f"{total / runs:.4f}" if runs else "-"
        cost_rows.append((arm, tokens_in, tokens_out, per_call, latency, f"{total:.4f}", per_run))
    head = "Arm|Tokens in|Tokens out|USD a call|Latency, s|USD total|USD a run"
    parts.append(_table("Cost", head, cost_rows))

    regimes = ("risk_on", "neutral", "risk_off")
    regime_rows = []
    for arm, group in arms.items():
        cells = []
        for regime in regimes:
            made = [c.action for c in group if c.regime == regime]
            cells.append(" / ".join(str(made.count(action)) for action in ACTIONS))
        regime_rows.append((arm, *cells))
    head = "Arm|" + "|".join(regimes)
    parts.append(_table("BUY / SELL / HOLD by BTC regime", head, regime_rows))
    return "\n\n".join(parts)


if __name__ == "__main__":
    command, file = sys.argv[1:3]
    if command == "fetch":
        print(f"{fetch(file)} calls saved to {file}")
    else:
        print(report(load(file)))
