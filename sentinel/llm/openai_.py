"""GPT through the ChatGPT subscription: OpenClaw's one-shot ``infer model run`` (no agent
turn, tools or workspace; the login OpenClaw holds), so it runs on the instance only.

There is no system prompt flag, so the system prompt and the schema go first in the one
prompt. The subscription reports no tokens and bills nothing per call: both stay 0, and
the allowance used shows in OpenClaw's ``/status``.
"""

from __future__ import annotations

import json
import subprocess
import time

from pydantic import BaseModel, ValidationError

from sentinel.llm import LLMError, Usage, reason

OPENCLAW = "/home/ubuntu/.npm-global/bin/openclaw"
TIMEOUT_S = 300


def call[T: BaseModel](
    model: str, system: str, user: str, schema: type[T], attempts: int = 3
) -> tuple[T, Usage]:
    """``attempts`` is unused: OpenClaw retries the provider itself."""
    note = "Answer with one JSON object that follows this JSON schema:\n"
    prompt = f"{system}\n\n{note}{json.dumps(schema.model_json_schema())}\n\n{user}"
    command = [OPENCLAW, "infer", "model", "run", "--model", f"openai/{model}"]
    command += ["--prompt", prompt, "--thinking", "off", "--json"]
    start = time.monotonic()
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT_S)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise LLMError(f"openai {type(exc).__name__}") from exc
    latency_ms = round((time.monotonic() - start) * 1000)
    try:
        # Log lines may come first; the envelope starts at the first line opening with "{".
        out = json.loads(done.stdout[done.stdout.find("\n{") + 1 :])
    except ValueError as exc:
        raise LLMError(f"openai exit {done.returncode}: {reason(done.stderr)}") from exc
    if not out.get("ok"):
        raise LLMError(f"openai: {reason((out.get('error') or {}).get('message'))}")
    try:
        parsed = schema.model_validate_json(out["outputs"][0]["text"])
    except ValidationError as exc:
        raise LLMError(f"openai answer not in the schema: {exc.errors()[0]['msg']}") from exc
    return parsed, Usage(out.get("model") or model, 0, 0, latency_ms, 0.0)
