"""Model clients for the experiment runner (plan 3.1).

Each provider module has one function, ``call(model, system, user, schema)``: the same
prompt in, an answer validated against ``schema`` (the API's JSON output mode) and its
``Usage`` out. Keys come from SSM through ``sentinel.aws.get_secret``; the SDKs send them
in headers and retry 429 and 5xx answers with backoff.
"""

from __future__ import annotations

from dataclasses import dataclass


class LLMError(RuntimeError):
    """A call that failed or gave no answer in the schema (status codes only, no keys)."""


@dataclass(frozen=True)
class Usage:
    model_version: str  # the model id the API answered with
    tokens_in: int
    tokens_out: int  # thinking included: it is billed as output
    latency_ms: int
    cost_usd: float
