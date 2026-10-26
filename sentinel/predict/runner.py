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
from typing import Literal

import yaml
from pydantic import BaseModel

from sentinel.llm import LLMError, Usage, anthropic_, gemini
from sentinel.predict import journal
from sentinel.predict.validator import Horizon, PredictionOut
from sentinel.signals import snapshot
from sentinel.store.sim import PredictionRepo, SnapshotRepo

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
        for name in ("freeform", "structured")
    }
    repo = PredictionRepo()
    done = {(p.slot, p.symbol, p.arm) for p in repo.logged([result.date])}
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
        for arm in todo:
            template = templates[arm.prompt]
            user = (
                template.replace("{symbol}", symbol)
                .replace("{horizon_h}", str(experiment.horizon_h))
                .replace("{snapshot}", data)
            )
            _pace(arm, last_call)
            try:
                out, usage = CALLERS[arm.provider](
                    arm.model, system, user, PredictionOut, arm.attempts
                )
                if out.horizon_h != experiment.horizon_h:  # refused like bad JSON (plan 3.3)
                    raise LLMError(f"horizon {out.horizon_h} h, not {experiment.horizon_h} h")
            except LLMError as exc:
                log.warning(
                    "no answer", extra={"arm": arm.name, "symbol": symbol, "error": str(exc)}
                )
                result.failed.setdefault(arm.name, []).append(symbol)
                continue
            finally:
                last_call[arm.model] = time.monotonic()
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
            )
            repo.add(pred)
            result.stored[arm.name] = result.stored.get(arm.name, 0) + 1
            result.invalid[arm.name] = result.invalid.get(arm.name, 0) + (not pred.valid)
            result.cost_usd += usage.cost_usd
    return result


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
