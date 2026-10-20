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
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    CredentialRetrievalError,
    HTTPClientError,
    NoCredentialsError,
)
from botocore.exceptions import ConnectionError as BotoConnectionError

from sentinel import log
from sentinel.config import get_settings

PREFIX = "/sentinel/"

# Every parameter the code reads; a name is added with the first module that uses it.
# (/sentinel/telegram_token is only copied into OpenClaw's config at onboarding.)
NAMES = frozenset(
    {
        "cmc_api_key",
        "newsapi_key",
        "gemini_api_key",
        "openclaw_hook_token",
    }
)

# Standard mode retries throttling, 5xx and connection errors with backoff.
_CONFIG = Config(
    connect_timeout=5, read_timeout=10, retries={"mode": "standard", "max_attempts": 4}
)

# Errors still worth retrying after boto3's own attempts: throttling and server errors
# (by code or HTTP status), lost connections, and credentials not there yet at boot.
# Anything else (access denied, missing resource, bad config) waiting will not fix.
_THROTTLING_CODES = frozenset(
    {
        "Throttling",
        "ThrottlingException",
        "ThrottledException",
        "RequestThrottled",
        "RequestLimitExceeded",
        "ProvisionedThroughputExceededException",
        "TooManyRequestsException",
        "SlowDown",
    }
)
_TRANSIENT_BOTO_ERRORS = (
    BotoConnectionError,
    HTTPClientError,
    NoCredentialsError,
    CredentialRetrievalError,
)

_cache: dict[str, str] = {}


def is_transient(exc: Exception) -> bool:
    """True for AWS errors that may pass on a later try (see ``_THROTTLING_CODES``)."""
    if isinstance(exc, ClientError):
        code = exc.response.get("Error", {}).get("Code", "")
        status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
        return code in _THROTTLING_CODES or status >= 500
    return isinstance(exc, _TRANSIENT_BOTO_ERRORS)


class SecretError(RuntimeError):
    """A key could not be read. The message names the parameter, never a value.

    ``transient`` follows ``is_transient``: True when a later try may pass (throttling,
    no connection, credentials not there yet at boot), False when AWS said no.
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


def error_code(exc: Exception) -> str:
    """AWS error code, or the exception type: never the message (account ids, ARNs)."""
    if isinstance(exc, ClientError):
        return exc.response.get("Error", {}).get("Code") or "ClientError"
    return type(exc).__name__


def clear_cache() -> None:
    """Forget cached keys and clients (tests, or a key rotation in a long-running process)."""
    _cache.clear()
    client.cache_clear()


def _fetch(path: str) -> str:
    # Messages carry error codes only: AWS messages can hold account ids and role ARNs.
    try:
        parameter = client("ssm").get_parameter(Name=path, WithDecryption=True)["Parameter"]
    except (ClientError, BotoCoreError) as exc:
        reason = error_code(exc)
        message = f"cannot read SSM parameter {path}: {reason}"
        raise SecretError(message, transient=is_transient(exc)) from None
    if parameter["Type"] != "SecureString":
        raise SecretError(f"SSM parameter {path} must be a SecureString, not {parameter['Type']}")
    return parameter["Value"]
