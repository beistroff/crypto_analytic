"""Experiment runner (plan 3.5): three runs a day in which every arm calls its model on the
same snapshot of each experiment coin.

An OpenClaw command automation runs ``sentinel experiment run`` at 00:05, 08:05 and 16:05
UTC. OpenClaw makes no model call of its own, so every arm gets the same short prompt and
its tokens are counted exactly. ``experiment.yaml`` names the coins, the horizon and the
arms. Each coin's snapshot (without NewsAPI's day-old news, which keeps the free plan's
quota for chat) is stored as a ``SNAP`` item, and each answer goes through the validator
into the prediction journal, where the hourly scorer grades it like a chat call.

An arm with ``sample`` calls only that many coins per run, picked at random from the date
and slot, so a re-run picks the same ones, and arms with the same ``sample`` share them
(Gemini Flash and Sonnet are compared on the same coins). A re-run skips the calls already
stored for the date, slot, coin and arm, so it only retries the calls that failed (each is
logged and named in the result, and a later slot does not make it up).

An arm with ``gate`` (L1G) makes no call of its own: it takes the named arm's answer for
the coin and stores it again with Naive Bayes' P(up). Only when the gate fires does it ask
its model to re-check the call (``gate_recheck.md``), and stores the answer it gets. It is
listed after the arm it gates.
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel

from sentinel.data import SourceError
from sentinel.llm import LLMError, Usage, anthropic_, gemini
from sentinel.models import check as nb_check
from sentinel.predict import gate, journal
from sentinel.predict.validator import Horizon, PredictionOut
from sentinel.signals import snapshot
from sentinel.store.sim import Prediction, PredictionRepo, SnapshotRepo

EXPERIMENT = Path(__file__).resolve().parents[2] / "experiment.yaml"
PROMPTS = Path(__file__).resolve().parents[1] / "llm" / "prompts"
SLOTS = ("00", "08", "16")

Caller = Callable[[str, str, str, type[PredictionOut], int], tuple[PredictionOut, Usage]]
CALLERS: dict[str, Caller] = {"gemini": gemini.call, "anthropic": anthropic_.call}

log = logging.getLogger(__name__)


class Arm(BaseModel):
    name: str
    provider: Literal["gemini", "anthropic"]
    model: str
    prompt: Literal["freeform", "structured"]
    sample: int | None = None  # coins per run; all of them when not set
    min_interval_s: float = 0.0  # between two calls to the same model
    attempts: int = 3  # tries per call; each counts against a free daily quota
    gate: str | None = None  # the arm whose answer this one re-checks with Naive Bayes


class Experiment(BaseModel):
    horizon_h: Horizon
    coins: list[str]
    arms: list[Arm]
    end_date: date | None = None  # no calls from this UTC day on: a forgotten automation costs 0


@dataclass
class RunResult:
    date: str
    slot: str
    stored: dict[str, int] = field(default_factory=dict)  # calls stored, by arm
    invalid: dict[str, int] = field(default_factory=dict)  # of those, failed the validator
    failed: dict[str, list[str]] = field(default_factory=dict)  # coins with no answer, by arm
    skipped: int = 0  # stored by an earlier run of the slot
    missing: list[str] = field(default_factory=list)  # coins with no snapshot price
    cost_usd: float = 0.0
    ended: str | None = None  # the experiment's end date, once it has passed


def _now() -> datetime:
    return datetime.now(UTC)


def load(path: Path = EXPERIMENT) -> Experiment:
    return Experiment.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def prompt_hash(template: str) -> str:
    """sha256 of the system prompt and the arm's template, before the data goes in."""
    system = (PROMPTS / "system.md").read_text(encoding="utf-8")
    return hashlib.sha256(f"{system}\n{template}".encode()).hexdigest()


def run(slot: str | None = None, path: Path = EXPERIMENT) -> RunResult:
    experiment = load(path)
    now = _now()
    result = RunResult(date=f"{now:%Y-%m-%d}", slot=slot or SLOTS[now.hour // 8])
    if experiment.end_date and now.date() >= experiment.end_date:
        result.ended = f"{experiment.end_date}"
        return result
    system = (PROMPTS / "system.md").read_text(encoding="utf-8")
    templates = {
        name: (PROMPTS / f"{name}.md").read_text(encoding="utf-8")
        for name in ("freeform", "structured", "gate_recheck")
    }
    repo = PredictionRepo()
    done = {(p.slot, p.symbol, p.arm): p for p in repo.logged([result.date])}
    picks = {arm.name: _coins(experiment, arm, result) for arm in experiment.arms}
    last_call: dict[str, float] = {}  # by model
    for symbol in experiment.coins:
        arms = [arm for arm in experiment.arms if symbol in picks[arm.name]]
        todo = [arm for arm in arms if (result.slot, symbol, arm.name) not in done]
        result.skipped += len(arms) - len(todo)
        if not todo:
            continue
        snap = snapshot.build(symbol, popular_news=False)
        if snap.price is None:
            result.missing.append(symbol)
            continue
        SnapshotRepo().add(snap)
        data = snap.model_dump_json()
        compact = {
            "price": snap.price,
            "rsi14": snap.technicals.rsi14 if snap.technicals else None,
            "btc_regime": snap.btc.regime if snap.btc else None,
            "btc_chg_24h": snap.btc.chg_24h if snap.btc else None,
        }
        answers: dict[str, PredictionOut] = {}  # this coin's answers in this run, by arm
        for arm in todo:
            template = templates["gate_recheck" if arm.gate else arm.prompt]
            gated: dict[str, Any] = {}
            try:
                if arm.gate:
                    stored = done.get((result.slot, symbol, arm.gate))
                    source = answers.get(arm.gate) or (stored and _answer(stored))
                    if source is None:
                        raise SourceError(f"no {arm.gate} answer to re-check")
                    out, usage, gated = _gated(
                        arm, system, template, symbol, experiment.horizon_h, source, data, last_call
                    )
                else:
                    user = (
                        template.replace("{symbol}", symbol)
                        .replace("{horizon_h}", str(experiment.horizon_h))
                        .replace("{snapshot}", data)
                    )
                    out, usage = _ask(arm, system, user, last_call)
                if out.horizon_h != experiment.horizon_h:  # refused like bad JSON (plan 3.3)
                    raise LLMError(f"horizon {out.horizon_h} h, not {experiment.horizon_h} h")
            except (LLMError, SourceError) as exc:
                log.warning(
                    "no answer", extra={"arm": arm.name, "symbol": symbol, "error": str(exc)}
                )
                result.failed.setdefault(arm.name, []).append(symbol)
                continue
            answers[arm.name] = out
            pred = journal.new(
                symbol,
                out,
                arm.model,
                snap.price,
                compact,
                _now(),
                source="scheduled",
                arm=arm.name,
                slot=result.slot,
                model_version=usage.model_version,
                prompt_hash=prompt_hash(template),
                snapshot_ref=snap.as_of,
                tokens_in=usage.tokens_in,
                tokens_out=usage.tokens_out,
                cost_usd=Decimal(f"{usage.cost_usd:.6f}"),
                latency_ms=usage.latency_ms,
                **gated,
            )
            repo.add(pred)
            result.stored[arm.name] = result.stored.get(arm.name, 0) + 1
            result.invalid[arm.name] = result.invalid.get(arm.name, 0) + (not pred.valid)
            result.cost_usd += usage.cost_usd
    return result


def _ask(
    arm: Arm, system: str, user: str, last_call: dict[str, float]
) -> tuple[PredictionOut, Usage]:
    _pace(arm, last_call)
    try:
        return CALLERS[arm.provider](arm.model, system, user, PredictionOut, arm.attempts)
    finally:
        last_call[arm.model] = time.monotonic()


def _gated(
    arm: Arm,
    system: str,
    template: str,
    symbol: str,
    horizon_h: int,
    source: PredictionOut,
    data: str,
    last_call: dict[str, float],
) -> tuple[PredictionOut, Usage, dict[str, Any]]:
    """The source arm's call, re-asked when the gate fires, and the gate's fields. A call
    the gate lets through costs nothing."""
    nb = nb_check.check(symbol)
    fields: dict[str, Any] = {
        "nb_p_up": Decimal(f"{nb.p_up:.4f}"),
        "original_action": source.action,
        "gate_triggered": gate.triggered(source, nb.p_up),
    }
    if not fields["gate_triggered"]:
        return source, Usage(arm.model, 0, 0, 0, 0.0), {**fields, "revised": False}
    user = gate.recheck_prompt(template, symbol, horizon_h, source, nb, data)
    out, usage = _ask(arm, system, user, last_call)
    return out, usage, {**fields, "revised": out.action != source.action}


def _answer(pred: Prediction) -> PredictionOut:
    """A stored call as the model wrote it (for a gated arm on a re-run)."""
    return PredictionOut.model_validate(
        {name: getattr(pred, name) for name in PredictionOut.model_fields}
    )


def _coins(experiment: Experiment, arm: Arm, result: RunResult) -> set[str]:
    if arm.sample is None:
        return set(experiment.coins)
    rng = random.Random(f"{result.date}/{result.slot}")
    return set(rng.sample(experiment.coins, arm.sample))


def _pace(arm: Arm, last_call: dict[str, float]) -> None:
    """Wait until the model's minimum interval since its last call has passed."""
    if arm.model in last_call:
        wait = arm.min_interval_s - (time.monotonic() - last_call[arm.model])
        if wait > 0:
            time.sleep(wait)
