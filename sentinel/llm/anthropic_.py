"""Claude through the ``anthropic`` SDK, with structured outputs (``messages.parse``) and
the system prompt cached: it is the same for every coin in a run, and cached reads cost a
tenth of the input price. Thinking and effort stay at the model's defaults."""

from __future__ import annotations

import time

import anthropic
from pydantic import BaseModel, ValidationError

from sentinel import aws
from sentinel.config import get_settings
from sentinel.llm import LLMError, Usage

MAX_TOKENS = 8000  # room for thinking plus a short JSON answer
TIMEOUT_S = 120.0
CACHE_WRITE, CACHE_READ = 1.25, 0.1  # of the input price


def call[T: BaseModel](
    model: str, system: str, user: str, schema: type[T], attempts: int = 3
) -> tuple[T, Usage]:
    client = anthropic.Anthropic(
        api_key=aws.get_secret("anthropic_api_key"),
        timeout=TIMEOUT_S,
        max_retries=attempts - 1,
    )
    start = time.monotonic()
    try:
        response = client.messages.parse(
            model=model,
            max_tokens=MAX_TOKENS,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            output_format=schema,
        )
    except anthropic.APIStatusError as exc:
        raise LLMError(f"anthropic {exc.status_code}") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMError("anthropic connection error") from exc
    except ValidationError as exc:
        raise LLMError(f"anthropic answer not in the schema: {exc.errors()[0]['msg']}") from exc
    latency_ms = round((time.monotonic() - start) * 1000)
    if response.parsed_output is None:
        raise LLMError(f"anthropic gave no answer ({response.stop_reason})")
    u = response.usage
    written, read = u.cache_creation_input_tokens or 0, u.cache_read_input_tokens or 0
    price_in, price_out = get_settings().llm_prices[model]
    billed_in = u.input_tokens + written * CACHE_WRITE + read * CACHE_READ
    return response.parsed_output, Usage(
        model_version=response.model,
        tokens_in=u.input_tokens + written + read,
        tokens_out=u.output_tokens,
        latency_ms=latency_ms,
        cost_usd=(billed_in * price_in + u.output_tokens * price_out) / 1_000_000,
    )
