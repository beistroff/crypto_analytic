"""Gemini through ``google-genai`` on the free tier (cost 0; the runner keeps each model
under its requests-per-minute limit)."""

from __future__ import annotations

import time

import httpx
import httpx2
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from sentinel import aws
from sentinel.llm import LLMError, Usage

# The SDK sends the timeout to Google as the request's deadline, and free-tier requests can
# wait in a queue: at 2 minutes Gemini 3.8 Flash answered 504 DEADLINE_EXCEEDED every time.
TIMEOUT_MS = 600_000
RETRY_CODES = [429, 500, 503]
# "Overloaded" (503) and the per-minute limit (429) pass within a minute or so; retries
# 2 s apart all hit the same overload and only used up the daily quota.
RETRY_DELAY_S = 60.0


def call[T: BaseModel](
    model: str, system: str, user: str, schema: type[T], attempts: int = 3
) -> tuple[T, Usage]:
    """``attempts`` counts every try against the daily quota (1: no retry)."""
    retry = types.HttpRetryOptions(
        attempts=attempts, initial_delay=RETRY_DELAY_S, http_status_codes=RETRY_CODES
    )
    client = genai.Client(
        api_key=aws.get_secret("gemini_api_key"),
        http_options=types.HttpOptions(timeout=TIMEOUT_MS, retry_options=retry),
    )
    start = time.monotonic()
    try:
        response = client.models.generate_content(
            model=model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=schema.model_json_schema(),
            ),
        )
    except errors.APIError as exc:
        raise LLMError(f"gemini {exc.code} {exc.status}") from exc
    # The SDK retries timeouts and lost connections, then raises its HTTP library's error.
    except (httpx.HTTPError, httpx2.HTTPError) as exc:
        raise LLMError(f"gemini {type(exc).__name__}") from exc
    latency_ms = round((time.monotonic() - start) * 1000)
    try:
        parsed = schema.model_validate_json(response.text or "")
    except ValidationError as exc:
        raise LLMError(f"gemini answer not in the schema: {exc.errors()[0]['msg']}") from exc
    meta = response.usage_metadata or types.GenerateContentResponseUsageMetadata()
    return parsed, Usage(
        model_version=response.model_version or model,
        tokens_in=meta.prompt_token_count or 0,
        tokens_out=(meta.candidates_token_count or 0) + (meta.thoughts_token_count or 0),
        latency_ms=latency_ms,
        cost_usd=0.0,
    )
