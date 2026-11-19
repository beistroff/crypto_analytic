from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from scipy.stats import chi2

from analysis import experiment_stats as stats
from sentinel.predict import journal
from sentinel.predict.validator import PredictionOut


def _call(arm, symbol, **changes):
    values = {
        "day": "2026-11-09",
        "slot": "00",
        "at": "00:10",
        "symbol": symbol,
        "arm": arm,
        "action": "BUY",
        "confidence": 0.7,
        "valid": True,
        "hit": True,
        "ret": 2.0,
        "first": None,
        "regime": "neutral",
        "tokens_in": None,
        "tokens_out": None,
        "cost_usd": None,
        "latency_ms": None,
        "gate_triggered": None,
        "revised": None,
    }
    return stats.Call(**{**values, **changes})


def test_mcnemar_is_exact_for_few_pairs_and_chi_square_above():
    assert stats.mcnemar(3, 1) == pytest.approx(0.625)
    assert stats.mcnemar(30, 10) == pytest.approx(chi2.sf(19**2 / 40, 1))
    assert stats.mcnemar(0, 0) == 1.0


def test_cochran_q_of_two_arms_is_mcnemar_without_the_correction():
    rows = [[1, 0]] * 3 + [[0, 1]] + [[1, 1]] * 5 + [[0, 0]] * 2
    q, _ = stats.cochran_q(rows)
    assert q == pytest.approx((3 - 1) ** 2 / (3 + 1))
    assert stats.cochran_q([[1, 1], [0, 0]]) == (0.0, 1.0)


def test_holm_adjusts_in_the_given_order_and_never_falls():
    assert stats.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_brier_parts_add_up_when_each_bin_has_one_confidence():
    calls = [_call("L1", "A", confidence=0.75)] * 3
    calls += [_call("L1", "B", hit=False, confidence=0.75)]
    calls += [_call("L1", "C", hit=False, confidence=0.55)] * 2
    score, reliability, resolution, uncertainty, bins = stats.brier_parts(calls)
    assert score == pytest.approx(reliability - resolution + uncertainty)
    assert bins[0][0] == 2 and bins[1][0] == 4


def test_to_calls_keeps_scheduled_calls_with_the_result_at_their_horizon():
    out = PredictionOut(
        btc_context="flat",
        action="BUY",
        direction="UP",
        confidence=0.6,
        horizon_h=24,
        entry=100.0,
        target=110.0,
        stop=95.0,
    )
    now = datetime(2026, 11, 9, 0, 5, tzinfo=UTC)
    snap = {"btc_regime": "neutral"}
    run = journal.new("SOL", out, "m", 100.0, snap, now, source="scheduled", arm="L1", slot="00")
    graded = replace(run, checks={"h24": {"hit": True, "return_pct": Decimal("1.5")}})
    chat = journal.new("SOL", out, "m", 100.0, snap, now)
    [call] = stats.to_calls([graded, chat])
    assert (call.arm, call.slot, call.at, call.hit, call.ret) == ("L1", "00", "00:05", True, 1.5)


def test_report_compares_arms_on_shared_calls_only():
    calls = [
        _call("L0", "A"),
        _call("L1", "A", action="HOLD", hit=False, ret=3.0),
        _call("L0", "B", hit=False, ret=-1.0),  # L1 has no answer for B
        _call("L1", "C", hit=None, ret=None),  # not graded yet
        _call("L1", "B", at="03:15"),  # a manual re-run hours after the slot
    ]
    text = stats.report(calls)
    assert "| L0 - L1 | 1 | 0 | 1 |" in text
    assert "Left out, made outside their run: L1 B 2026-11-09 00 at 03:15." in text
    assert "| L0 | 2 | 0.30 | 1/2 (50.0%) |" in text  # BUYs net of the fee: 1.8 and -1.2
