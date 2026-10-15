"""Clients for external market and news APIs.

Each client goes through ``sentinel.net`` (timeouts, retries, rate limits), reads its key
with ``sentinel.aws.get_secret`` and sends it in a header, and returns only the fields
the commands use.
"""

from __future__ import annotations


class SourceError(RuntimeError):
    """An API answered with an error. The message holds the status and error code only."""
