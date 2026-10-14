"""Settings shared by the CLI, the Lambda handlers and the EC2 services.

Defaults match the Terraform envs. A few values can be overridden through environment
variables (see ``ENV_VARS``). Secrets never live here; they come from ``sentinel.secrets``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from functools import cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]


class MinIntervals(BaseModel):
    """Minimum seconds between two requests to one source, from each free plan's limit.

    Every source that ``sentinel.net`` may call needs a field here.
    """

    model_config = ConfigDict(frozen=True)

    cmc: float = 2.0  # CoinMarketCap Basic: 30 requests per minute
    feargreed: float = 1.0  # alternative.me: 60 requests per minute
    newsapi: float = 1.0  # NewsAPI.org developer plan: 100 requests per day


class HttpSettings(BaseModel):
    model_config = ConfigDict(frozen=True)

    timeout_s: float = 10.0
    retries: int = 3
    # Wait before retries 1, 2 and 3: 1x, 2x and 4x this, at least the source's interval.
    backoff_s: float = 1.0
    # A longer Retry-After (e.g. a used-up daily quota) returns the response at once.
    retry_after_max_s: float = 30.0
    min_interval_s: MinIntervals = Field(default_factory=MinIntervals)


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)

    region: str = "us-east-1"
    real_table: str = "sentinel-real"
    sim_table: str = "sentinel-sim"
    backup_bucket: str = "openclaw-files"
    # WARNING keeps CLI calls quiet; services set INFO.
    log_level: LogLevel = "WARNING"
    http: HttpSettings = Field(default_factory=HttpSettings)

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value


# Environment variable for each overridable field. bootstrap.sh exports AWS_REGION and
# OPENCLAW_S3_BUCKET on the instance; the Lambda runtime sets AWS_REGION.
ENV_VARS = {
    "region": "AWS_REGION",
    "real_table": "SENTINEL_REAL_TABLE",
    "sim_table": "SENTINEL_SIM_TABLE",
    "backup_bucket": "OPENCLAW_S3_BUCKET",
    "log_level": "SENTINEL_LOG_LEVEL",
}


def load(env: Mapping[str, str] | None = None) -> Settings:
    """Defaults plus the overrides set in ``env`` (``os.environ`` when omitted)."""
    env = os.environ if env is None else env
    return Settings(**{field: env[var] for field, var in ENV_VARS.items() if env.get(var)})


@cache
def get_settings() -> Settings:
    """Settings for this process, read from the environment once."""
    return load()
