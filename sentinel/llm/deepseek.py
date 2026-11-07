"""DeepSeek through its OpenAI-compatible chat API, with thinking off (paid, prepaid balance).

Plain HTTP through ``sentinel.net``, so no extra SDK. JSON
Output mode returns one JSON object but enforces no schema, so the schema goes into the
system prompt and the answer is validated like every other arm's.

Prices are DeepSeek's off-peak list prices (``config.LLM_PRICES``); weekdays from 01:00 to
04:00 and 06:00 to 10:00 UTC are peak and cost double (Chinese public holidays, off-peak
in full, are not tracked, so those runs are counted at the peak price).
"""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime

import requests
from pydantic import BaseModel, ValidationError

from sentinel import aws, net
from sentinel.config import get_settings
from sentinel.llm import LLMError, Usage, reason

URL = "https://api.deepseek.com/chat/completions"
TIMEOUT_S = 120.0
MAX_TOKENS = 2000  # a short JSON answer; thinking is off
RETRY_DELAY_S = 2.0
CACHE_HIT = 0.02  # of the input price
PEAK_HOURS = ((1, 4), (6, 10))  # UTC, Monday to Friday


def call[T: BaseModel](
    model: str, system: str, user: str, schema: type[T], attempts: int = 3
) -> tuple[T, Usage]:
    """``attempts`` tries on 429 and 5xx, 2 s apart doubling (``sentinel.net`` retries GET
    only, as urllib3 does)."""
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": f"{system}\n\n{_schema_note(schema)}"},
            {"role": "user", "content": user},
        ],
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "max_tokens": MAX_TOKENS,
    }
    headers = {"Authorization": f"Bearer {aws.get_secret('deepseek_api_key')}"}
    start = time.monotonic()
    for attempt in range(attempts):
        try:
            response = net.session("deepseek").post(
                URL, json=body, headers=headers, timeout=TIMEOUT_S
            )
        except requests.RequestException as exc:
            raise LLMError(f"deepseek {type(exc).__name__}") from exc
        if response.status_code not in net.RETRY_STATUSES or attempt == attempts - 1:
            break
        time.sleep(RETRY_DELAY_S * 2**attempt)
    latency_ms = round((time.monotonic() - start) * 1000)
    if response.status_code != 200:
        raise LLMError(f"deepseek {response.status_code}: {reason(_error(response))}")
    data = response.json()
    choice = data["choices"][0]
    if choice.get("finish_reason") != "stop":
        raise LLMError(f"deepseek gave no answer ({choice.get('finish_reason')})")
    try:
        parsed = schema.model_validate_json(choice["message"]["content"] or "")
    except ValidationError as exc:
        raise LLMError(f"deepseek answer not in the schema: {exc.errors()[0]['msg']}") from exc
    u = data["usage"]
    hit = u.get("prompt_cache_hit_tokens", 0)
    price_in, price_out = get_settings().llm_prices[model]
    billed_in = u["prompt_tokens"] - hit + hit * CACHE_HIT
    cost = (billed_in * price_in + u["completion_tokens"] * price_out) / 1e6
    return parsed, Usage(
        model_version=data.get("model") or model,
        tokens_in=u["prompt_tokens"],
        tokens_out=u["completion_tokens"],
        latency_ms=latency_ms,
        cost_usd=cost * (2 if _peak(datetime.now(UTC)) else 1),
    )


def _schema_note(schema: type[BaseModel]) -> str:
    return "Answer with one JSON object that follows this JSON schema:\n" + json.dumps(
        schema.model_json_schema()
    )


def _error(response: requests.Response) -> str | None:
    """The API's message from its ``{"error": {"message": ...}}`` body, if any."""
    try:
        return response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return response.text or None


def _peak(now: datetime) -> bool:
    return now.weekday() < 5 and any(start <= now.hour < end for start, end in PEAK_HOURS)
