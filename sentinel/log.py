"""JSON-lines logging.

One JSON object per line on stderr. journald collects stderr as well as stdout, and
stdout stays free for CLI output, which the agent reads. Only EC2 entry points (the
CLI, the poller) call ``setup()``; Lambda uses the runtime's own JSON log format, which
already has a handler on the root logger. Modules use ``logging.getLogger(__name__)``
and pass structured fields through ``extra``.

Every key loaded by ``sentinel.aws`` is registered with ``redact()`` and replaced by
``[redacted]`` in each line, whichever library logged it.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import TextIO

from sentinel.config import get_settings

# Attributes every LogRecord has; anything else on a record came from ``extra``.
_RECORD_ATTRS = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}

# At DEBUG these libraries log request URLs and response bodies, which can hold keys.
_QUIET_LOGGERS = ("botocore", "boto3", "urllib3")

_handler: logging.Handler | None = None
_secrets: set[str] = set()


def redact(value: str) -> None:
    """Replace ``value`` with ``[redacted]`` in every log line from now on."""
    if value:
        _secrets.add(value)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in vars(record).items():
            if key not in _RECORD_ATTRS:
                entry.setdefault(key, value)
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            entry["stack"] = self.formatStack(record.stack_info)
        line = json.dumps(entry, default=str, separators=(",", ":"))
        for secret in tuple(_secrets):
            line = line.replace(json.dumps(secret)[1:-1], "[redacted]")
        return line


def setup(level: str | None = None, stream: TextIO | None = None) -> None:
    """Send all log records as JSON lines to ``stream`` (stderr by default).

    ``level`` defaults to the ``log_level`` setting. Safe to call more than once.
    """
    global _handler
    root = logging.getLogger()
    if _handler is not None:
        root.removeHandler(_handler)
    _handler = logging.StreamHandler(stream or sys.stderr)
    _handler.setFormatter(JsonFormatter())
    root.addHandler(_handler)
    root.setLevel((level or get_settings().log_level).upper())
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
