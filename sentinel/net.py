"""HTTP sessions for external APIs.

Every call to an outside service goes through ``session(source)``, which adds:

- a default timeout (10 s), so no request hangs;
- 3 retries on connection errors, 429 and 5xx (idempotent methods only), waiting 1, 2
  and 4 s but never less than the source's minimum interval; a Retry-After up to 30 s
  is honoured, a longer one returns the response at once;
- a minimum interval between requests to the same source (free-plan rate limits);
- a User-Agent naming the project.

After the last retry the final response is returned; call ``raise_for_status()``.
Send API keys in a header from ``KEY_HEADERS``, never in the URL: urllib3 logs and
error messages include the full URL. Those headers are dropped on a redirect to another
host, as requests does for ``Authorization``.
"""

from __future__ import annotations

import logging
import threading
from time import monotonic, sleep
from typing import Any
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.exceptions import MaxRetryError, ResponseError
from urllib3.util.retry import Retry

from sentinel import __version__
from sentinel.config import HttpSettings, MinIntervals, get_settings

USER_AGENT = f"crypto-sentinel/{__version__}"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
KEY_HEADERS = ("X-CMC_PRO_API_KEY", "x-goog-api-key", "X-Api-Key")

log = logging.getLogger(__name__)

_sessions: dict[str, Session] = {}
_sessions_lock = threading.Lock()


def session(source: str) -> Session:
    """The shared session for ``source`` (e.g. ``"cmc"``), created on first use.

    One session per source and process, so the minimum interval holds for every caller.
    """
    with _sessions_lock:
        if source not in _sessions:
            _sessions[source] = Session(source)
        return _sessions[source]


class Session(requests.Session):
    """``requests.Session`` with a default timeout, retries and a minimum interval."""

    def __init__(self, source: str, cfg: HttpSettings | None = None) -> None:
        if source not in MinIntervals.model_fields:
            raise ValueError(f"unknown source {source!r}: add its limit to config.MinIntervals")
        cfg = cfg or get_settings().http
        super().__init__()
        self.source = source
        self.timeout = cfg.timeout_s
        self.min_interval = getattr(cfg.min_interval_s, source)
        self._next_at = 0.0
        self._throttle_lock = threading.Lock()
        retry = _Retry(
            total=cfg.retries,
            backoff_factor=max(cfg.backoff_s, self.min_interval),
            status_forcelist=RETRY_STATUSES,
            raise_on_status=False,
            max_wait=cfg.retry_after_max_s,
        )
        adapter = HTTPAdapter(max_retries=retry)
        self.mount("https://", adapter)
        self.mount("http://", adapter)
        self.headers["User-Agent"] = USER_AGENT

    def request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = self.timeout
        self._throttle()
        fields = {"source": self.source, "method": method, "url": _without_query(url)}
        started = monotonic()
        try:
            response = super().request(method, url, **kwargs)
        except requests.RequestException as exc:
            log.warning("http request failed", extra={**fields, "error": type(exc).__name__})
            raise
        fields.update(status=response.status_code, ms=round((monotonic() - started) * 1000))
        log.debug("http request", extra=fields)
        return response

    def rebuild_auth(self, prepared_request: requests.PreparedRequest, response: Any) -> None:
        if self.should_strip_auth(response.request.url, prepared_request.url):
            for name in KEY_HEADERS:
                prepared_request.headers.pop(name, None)
        super().rebuild_auth(prepared_request, response)

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        with self._throttle_lock:
            wait = self._next_at - monotonic()
            if wait > 0:
                sleep(wait)
            self._next_at = monotonic() + self.min_interval


class _Retry(Retry):
    """urllib3 Retry that also waits before the first retry and gives up when the
    server's Retry-After is longer than ``max_wait`` instead of sleeping through it.

    (urllib3 2.8+ has its own ``retry_after_max``, which only caps the sleep.)
    """

    def __init__(self, *args: Any, max_wait: float, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.max_wait = max_wait

    def new(self, **kw: Any) -> _Retry:
        kw.setdefault("max_wait", self.max_wait)
        return super().new(**kw)

    def get_backoff_time(self) -> float:
        # urllib3 retries the first time without waiting (then 2x, 4x); wait 1x instead.
        return super().get_backoff_time() or (self.backoff_factor if self.history else 0.0)

    def increment(
        self,
        method: str | None = None,
        url: str | None = None,
        response: Any = None,
        error: Exception | None = None,
        _pool: Any = None,
        _stacktrace: Any = None,
    ) -> _Retry:
        if response is not None:
            wait = self.get_retry_after(response)
            if wait is not None and wait > self.max_wait:
                reason = ResponseError(f"Retry-After {wait:.0f} s is over {self.max_wait:.0f} s")
                raise MaxRetryError(_pool, url, reason)
        return super().increment(method, url, response, error, _pool, _stacktrace)


def _without_query(url: str) -> str:
    parts = urlsplit(url)
    host = parts.netloc.rpartition("@")[2]
    return f"{parts.scheme}://{host}{parts.path}"
