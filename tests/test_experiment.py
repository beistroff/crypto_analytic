import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from sentinel import views
from sentinel.llm import LLMError, Usage, anthropic_, gemini
from sentinel.predict import runner
from sentinel.predict.validator import PredictionOut
from sentinel.store.sim import PredictionRepo

NOW = datetime(2026, 10, 17, 12, 20, tzinfo=UTC)  # the `trending` clock: the 08 slot

CALL = {
    "btc_context": "BTC risk_on, above both averages",
    "action": "BUY",
    "direction": "UP",
    "confidence": 0.6,
    "horizon_h": 24,
    "entry": 100.0,
    "target": 103,
    "stop": 98,
    "reasons": ["uptrend"],
}
EXPERIMENT = """
horizon_h: 24
coins: [XRP, SOL, NOPE]
arms:
  - {name: A, provider: gemini, model: flash-lite, prompt: freeform}
  - {name: B, provider: anthropic, model: claude-haiku-5-5, prompt: structured}
  - {name: C, provider: gemini, model: flash, prompt: structured, sample: 1, attempts: 1}
  - {name: D, provider: gemini, model: pro, prompt: structured, sample: 1}
"""


def test_run_calls_every_arm_once_per_slot(trending, tables, tmp_path, monkeypatch):
    path = tmp_path / "experiment.yaml"
    path.write_text(EXPERIMENT, encoding="utf-8")
    calls, attempts = [], {}

    def fake(model, system, user, schema, tries):
        calls.append((model, user))
        attempts[model] = tries
        if model == "claude-haiku-5-5" and "SOL" in user:
            raise LLMError("anthropic 529")
        entry = 90.0 if model == "claude-haiku-5-5" else 100.0  # B's entry is off: invalid
        return schema(**{**CALL, "entry": entry}), Usage(model, 1000, 200, 900, 0.0002)

    monkeypatch.setattr(runner, "CALLERS", {"gemini": fake, "anthropic": fake})
    monkeypatch.setattr(runner, "_now", lambda: NOW)

    result = runner.run(path=path)
    # NOPE has no candles; C and D share this slot's random coin, SOL; B failed on SOL.
    assert (result.slot, result.stored, result.invalid) == (
        "08",
        {"A": 2, "B": 1, "C": 1, "D": 1},
        {"A": 0, "B": 1, "C": 0, "D": 0},
    )
    assert (result.failed, result.missing) == ({"B": ["SOL"]}, ["NOPE"])
    assert (attempts["flash"], attempts["pro"]) == (1, 3)  # C: no retry, D: the default
    assert "BTC first" in calls[1][1] and "BTC first" not in calls[0][1]  # A freeform, B structured
    assert views.experiment_ran(result).text == (
        "Run 2026-10-17 08: A 2, B 1 (1 invalid), C 1, D 1; $0.0010; B failed: SOL; "
        "no snapshot: NOPE"
    )

    preds = {(p.symbol, p.arm): p for p in PredictionRepo().logged(["2026-10-17"])}
    assert {("SOL", "C"), ("SOL", "D")} <= preds.keys()
    xrp = preds["XRP", "B"]
    assert (xrp.source, xrp.slot, xrp.model_version, xrp.tokens_out) == (
        "scheduled",
        "08",
        "claude-haiku-5-5",
        200,
    )
    assert xrp.snapshot["btc_regime"] == "risk_on" and xrp.snapshot_ref == "2026-10-17T12:20:00Z"
    shown = json.loads(json.dumps(views.prediction(xrp).data))  # what `predict show` prints
    assert (shown["tokens_in"], shown["cost_usd"], shown["latency_ms"]) == (1000, 0.0002, 900)
    snap = tables.get_item(
        TableName="sentinel-sim", Key={"PK": {"S": "SNAP#XRP"}, "SK": {"S": xrp.snapshot_ref}}
    )["Item"]
    payload = json.loads(snap["payload"]["S"])
    assert payload["coin_news"] is None and "news" not in payload["missing"]
    assert trending.news.seen == []  # no NewsAPI request

    calls.clear()
    again = runner.run(path=path)
    assert [model for model, _ in calls] == ["claude-haiku-5-5"]  # only B on SOL again
    assert again.skipped == 5 and again.failed == {"B": ["SOL"]}

    calls.clear()
    path.write_text(EXPERIMENT + "end_date: 2026-10-17\n", encoding="utf-8")
    ended = runner.run(path=path)
    assert calls == [] and views.experiment_ran(ended).text == (
        "Run 2026-10-17 08: experiment ended 2026-10-17"
    )


def test_clients_return_the_answer_with_tokens_and_cost(monkeypatch):
    monkeypatch.setattr(anthropic_.aws, "get_secret", lambda name: "test")
    monkeypatch.setattr(gemini.aws, "get_secret", lambda name: "test")
    claude = SimpleNamespace(
        parsed_output=PredictionOut(**CALL),
        stop_reason="end_turn",
        model="claude-haiku-5-5",
        usage=SimpleNamespace(
            input_tokens=1000,
            output_tokens=200,
            cache_creation_input_tokens=0,
            cache_read_input_tokens=2000,
        ),
    )
    sent = {}

    def parse(**params):
        sent.update(params)
        return claude

    fake_messages = SimpleNamespace(parse=parse)
    monkeypatch.setattr(
        anthropic_.anthropic, "Anthropic", lambda **_: SimpleNamespace(messages=fake_messages)
    )
    out, usage = anthropic_.call("claude-haiku-5-5", "system", "user", PredictionOut)
    assert out.action == "BUY" and sent["system"][0]["cache_control"] == {"type": "ephemeral"}
    # (1000 + 2000 cached at a tenth) x $0.10 + 200 x $0.50, per million tokens
    assert (usage.tokens_in, usage.tokens_out, round(usage.cost_usd, 8)) == (3000, 200, 0.00022)
    claude.parsed_output, claude.stop_reason = None, "refusal"
    with pytest.raises(LLMError, match="refusal"):
        anthropic_.call("claude-haiku-5-5", "system", "user", PredictionOut)

    answer = SimpleNamespace(
        text=json.dumps(CALL),
        model_version="gemini-3.5-flash-lite-001",
        usage_metadata=SimpleNamespace(
            prompt_token_count=900, candidates_token_count=150, thoughts_token_count=50
        ),
    )
    models = SimpleNamespace(generate_content=lambda **_: answer)
    monkeypatch.setattr(gemini.genai, "Client", lambda **_: SimpleNamespace(models=models))
    out, usage = gemini.call("gemini-3.5-flash-lite", "system", "user", PredictionOut)
    assert out.entry == 100.0
    assert usage == Usage("gemini-3.5-flash-lite-001", 900, 200, usage.latency_ms, 0.0)
    answer.text = '{"action": "BUY"}'
    with pytest.raises(LLMError, match="not in the schema"):
        gemini.call("gemini-3.5-flash-lite", "system", "user", PredictionOut)

    def lost(**_):
        raise httpx.ConnectError("connection reset")  # after the SDK's own retries

    models.generate_content = lost
    with pytest.raises(LLMError, match="ConnectError"):
        gemini.call("gemini-3.5-flash-lite", "system", "user", PredictionOut)
