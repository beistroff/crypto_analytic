"""Readiness checks: can this instance run the agent?

Each check returns a short detail when it passes and raises when it fails. ``run()``
retries transient failures (network, credentials not there yet, 429/5xx) until a
deadline and stops at once on a fatal one (missing or bad key, missing table), which
waiting would not fix. Details hold status and error codes only, never key values or
AWS error messages (those can name the account and role).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic, sleep
from typing import Any

import requests
from botocore.exceptions import BotoCoreError, ClientError

from sentinel import aws, net
from sentinel.config import get_settings

CMC_KEY_INFO_URL = "https://pro-api.coinmarketcap.com/v1/key/info"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"

# Pause between rounds of retries in run(): 5 s, doubling up to a minute.
FIRST_PAUSE_S = 5.0
MAX_PAUSE_S = 60.0

log = logging.getLogger(__name__)


class CheckFailed(Exception):
    def __init__(self, detail: str, *, transient: bool = False) -> None:
        super().__init__(detail)
        self.detail = detail
        self.transient = transient


@dataclass(frozen=True)
class Result:
    name: str
    ok: bool
    detail: str
    fatal: bool = False


def check_dynamodb() -> str:
    settings = get_settings()
    dynamodb = aws.client("dynamodb")
    for table in (settings.real_table, settings.sim_table):
        status = dynamodb.describe_table(TableName=table)["Table"]["TableStatus"]
        if status != "ACTIVE":
            raise CheckFailed(f"{table} is {status}", transient=True)
    return "tables active"


def check_s3() -> str:
    bucket = get_settings().backup_bucket
    aws.client("s3").head_bucket(Bucket=bucket)
    return f"{bucket} reachable"


def check_cmc() -> str:
    key = aws.get_secret("cmc_api_key")
    response = net.session("cmc").get(CMC_KEY_INFO_URL, headers={"X-CMC_PRO_API_KEY": key})
    _raise_for_status(response)
    # No credit cost. The extra fields are informational: missing or null ones are skipped.
    # CMC's docs disagree on current_month vs current_day.
    data = _obj(_obj(response.json()).get("data"))
    usage = _obj(data.get("usage"))
    left = _obj(usage.get("current_month") or usage.get("current_day")).get("credits_left")
    per_minute = _obj(data.get("plan")).get("rate_limit_minute")
    parts = ["key valid"]
    if per_minute is not None:
        parts.append(f"{per_minute} requests/min")
    if left is not None:
        parts.append(f"{left} credits left")
    return ", ".join(parts)


def check_gemini() -> str:
    key = aws.get_secret("gemini_api_key")
    response = net.session("gemini").get(
        GEMINI_MODELS_URL, params={"pageSize": 1}, headers={"x-goog-api-key": key}
    )
    _raise_for_status(response)
    return "key valid"


CHECKS: dict[str, Callable[[], str]] = {
    "dynamodb": check_dynamodb,
    "s3": check_s3,
    "cmc": check_cmc,
    "gemini": check_gemini,
}


def run(wait_s: float = 0.0) -> list[Result]:
    """Run every check, retrying transient failures for up to ``wait_s`` seconds."""
    deadline = monotonic() + wait_s
    pause = FIRST_PAUSE_S
    results = {name: _run_one(name, check) for name, check in CHECKS.items()}
    while True:
        pending = [r.name for r in results.values() if not r.ok and not r.fatal]
        fatal = any(r.fatal for r in results.values())
        if fatal or not pending or monotonic() + pause > deadline:
            return list(results.values())
        log.info("checks not ready yet", extra={"pending": pending, "retry_in_s": pause})
        sleep(pause)
        pause = min(pause * 2, MAX_PAUSE_S)
        for name in pending:
            results[name] = _run_one(name, CHECKS[name])


def summary(results: list[Result]) -> dict[str, Any]:
    """Compact JSON form for the agent."""
    return {
        "ok": all(r.ok for r in results),
        "checks": {r.name: {"ok": r.ok, "detail": r.detail} for r in results},
    }


def telegram(results: list[Result]) -> str:
    """Five lines or fewer for the user: a verdict, then one line per failed check."""
    passed = sum(r.ok for r in results)
    if passed == len(results):
        return f"Health: OK ({passed}/{len(results)})"
    lines = [f"Health: NOT READY ({passed}/{len(results)} ok)"]
    lines += [f"{r.name}: {r.detail}" for r in results if not r.ok]
    return "\n".join(lines[:5])


def _raise_for_status(response: requests.Response) -> None:
    status = response.status_code
    if status != 200:
        # 429 and 5xx are already retried by sentinel.net; other 4xx mean a bad key.
        raise CheckFailed(f"HTTP {status}", transient=status == 429 or status >= 500)


def _run_one(name: str, check: Callable[[], str]) -> Result:
    try:
        return Result(name, True, check())
    except Exception as exc:
        detail, fatal = _classify(exc)
        log.warning("check failed", extra={"check": name, "detail": detail, "fatal": fatal})
        return Result(name, False, detail, fatal)


def _classify(exc: Exception) -> tuple[str, bool]:
    """(detail, fatal) for a failed check, built from codes and type names only."""
    if isinstance(exc, CheckFailed | aws.SecretError):
        return str(exc), not exc.transient
    if isinstance(exc, ClientError | BotoCoreError):
        return aws.error_code(exc), not aws.is_transient(exc)
    if isinstance(exc, requests.RequestException):
        return type(exc).__name__, False
    return type(exc).__name__, True


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
