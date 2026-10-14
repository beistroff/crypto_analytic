"""AWS access: shared boto3 clients and API keys from SSM Parameter Store.

Clients use short timeouts and boto3's standard retry mode. Keys are SecureString
parameters under ``/sentinel/``; each is read on first use, cached for the life of the
process and registered with ``log.redact``. Never pass a key as a CLI argument or an
environment variable, print it or put it in a URL; send it in a request header
(``sentinel.net.KEY_HEADERS``).
"""

from __future__ import annotations

from functools import cache

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from sentinel import log
from sentinel.config import get_settings

PREFIX = "/sentinel/"

# Every parameter the code may read. The Telegram bot token stays in OpenClaw's config.
NAMES = frozenset(
    {
        "cmc_api_key",
        "newsapi_key",
        "coingecko_api_key",
        "gemini_api_key",
        "anthropic_api_key",
        "openrouter_api_key",
        "openclaw_hook_token",
    }
)

# Standard mode retries throttling, 5xx and connection errors with backoff.
_CONFIG = Config(
    connect_timeout=5, read_timeout=10, retries={"mode": "standard", "max_attempts": 4}
)

_cache: dict[str, str] = {}


class SecretError(RuntimeError):
    """A key could not be read. The message names the parameter, never a value.

    ``transient`` is True when AWS could not be reached or no credentials were found
    (worth retrying, e.g. while the instance boots), False when AWS said no.
    """

    def __init__(self, message: str, *, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


@cache
def client(service: str) -> BaseClient:
    """Shared client for ``service``, created on first use."""
    # Own session per client: creating clients from boto3's default session is not
    # thread-safe.
    session = boto3.session.Session(region_name=get_settings().region)
    if session.get_credentials() is None:
        # Raised before caching: the instance role can lag at boot, and a client
        # without credentials would fail for the rest of the process.
        raise NoCredentialsError()
    return session.client(service, config=_CONFIG)


def get_secret(name: str) -> str:
    """Decrypted value of ``/sentinel/<name>``, e.g. ``get_secret("cmc_api_key")``."""
    if name not in NAMES:
        raise ValueError(f"unknown secret {name!r}, expected one of: {', '.join(sorted(NAMES))}")
    value = _cache.get(name)
    if value is None:
        value = _fetch(PREFIX + name)
        log.redact(value)
        _cache[name] = value
    return value


def clear_cache() -> None:
    """Forget cached keys and clients (tests, or a key rotation in a long-running process)."""
    _cache.clear()
    client.cache_clear()


def _fetch(path: str) -> str:
    # Messages carry error codes only: AWS messages can hold account ids and role ARNs.
    try:
        parameter = client("ssm").get_parameter(Name=path, WithDecryption=True)["Parameter"]
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "Unknown")
        raise SecretError(f"cannot read SSM parameter {path}: {code}") from None
    except BotoCoreError as exc:  # no credentials, endpoint unreachable, ...
        reason = type(exc).__name__
        raise SecretError(f"cannot read SSM parameter {path}: {reason}", transient=True) from None
    if parameter["Type"] != "SecureString":
        raise SecretError(f"SSM parameter {path} must be a SecureString, not {parameter['Type']}")
    return parameter["Value"]
