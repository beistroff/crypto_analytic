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

TIMEOUT_MS = 120_000
RETRY = types.HttpRetryOptions(attempts=3, initial_delay=2.0, http_status_codes=[429, 500, 503])


def call[T: BaseModel](model: str, system: str, user: str, schema: type[T]) -> tuple[T, Usage]:
    client = genai.Client(
        api_key=aws.get_secret("gemini_api_key"),
        http_options=types.HttpOptions(timeout=TIMEOUT_MS, retry_options=RETRY),
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
