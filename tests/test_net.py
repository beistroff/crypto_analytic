import logging
import socket
import time

import pytest
import requests
from requests.adapters import HTTPAdapter

from sentinel import net
from sentinel.config import HttpSettings

KEY = {"X-CMC_PRO_API_KEY": "cmc-test-value"}


def _session(**changes):
    """A "cmc" session without waits unless a test asks for them."""
    cfg = {"backoff_s": 0, "min_interval_s": {"cmc": 0}, **changes}
    return net.Session("cmc", HttpSettings(**cfg))


@pytest.fixture
def waits(monkeypatch):
    """Seconds urllib3 slept between retries (it calls time.sleep)."""
    slept = []
    monkeypatch.setattr(time, "sleep", slept.append)
    return slept


def test_retries_5xx_then_succeeds(server):
    server.replies.extend([(503, {}), (502, {})])
    response = _session().get(server.url)
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert len(server.seen) == 3


def test_gives_up_after_three_retries(server):
    server.replies.extend([(500, {})] * 5)
    response = _session().get(server.url)
    assert response.status_code == 500
    assert len(server.seen) == 4
    with pytest.raises(requests.HTTPError):
        response.raise_for_status()


def test_client_errors_are_not_retried(server):
    server.replies.append((404, {}))
    assert _session().get(server.url).status_code == 404
    assert len(server.seen) == 1


def test_backoff_waits_before_every_retry(server, waits):
    server.replies.extend([(503, {})] * 3)
    assert _session(backoff_s=1).get(server.url).status_code == 200
    assert waits == [1, 2, 4]


def test_backoff_is_at_least_the_min_interval(server, waits):
    server.replies.append((503, {}))
    _session(backoff_s=1, min_interval_s={"cmc": 2}).get(server.url)
    assert waits == [2]


def test_short_retry_after_is_honoured(server, waits):
    server.replies.append((429, {"Retry-After": "3"}))
    assert _session().get(server.url).status_code == 200
    assert waits == [3]


def test_long_retry_after_returns_at_once(server, waits):
    server.replies.append((429, {"Retry-After": "3600"}))
    response = _session(retry_after_max_s=30).get(server.url)
    assert response.status_code == 429
    assert len(server.seen) == 1
    assert waits == []


def test_default_timeout_and_user_agent(server, monkeypatch):
    timeouts = []
    send = HTTPAdapter.send

    def spy(self, request, **kwargs):
        timeouts.append(kwargs["timeout"])
        return send(self, request, **kwargs)

    monkeypatch.setattr(HTTPAdapter, "send", spy)
    session = _session(timeout_s=7)
    session.get(server.url)
    session.get(server.url, timeout=3)
    assert timeouts == [7, 3]
    assert server.seen[0].headers["User-Agent"] == net.USER_AGENT


def test_min_interval_spaces_requests(server, monkeypatch):
    clock = [100.0]
    slept = []

    def fake_sleep(seconds):
        slept.append(seconds)
        clock[0] += seconds

    monkeypatch.setattr(net, "monotonic", lambda: clock[0])
    monkeypatch.setattr(net, "sleep", fake_sleep)
    session = _session(min_interval_s={"cmc": 2.0})
    session.get(server.url)
    clock[0] += 0.5
    session.get(server.url)
    session.get(server.url)
    assert slept == [1.5, 2.0]


def test_one_session_per_source_with_configured_limits():
    cmc = net.session("cmc")
    assert net.session("cmc") is cmc
    assert (cmc.timeout, cmc.min_interval) == (10.0, 2.0)


def test_unknown_source_is_rejected():
    with pytest.raises(ValueError, match="unknown source 'coinmarketcap'"):
        net.session("coinmarketcap")


def test_key_header_dropped_on_redirect_to_another_host(make_server):
    first, other = make_server(), make_server()
    first.replies.append((302, {"Location": other.url}))
    assert _session().get(first.url, headers=KEY).status_code == 200
    assert first.seen[0].headers["X-CMC_PRO_API_KEY"] == "cmc-test-value"
    assert "X-CMC_PRO_API_KEY" not in other.seen[0].headers


def test_key_header_kept_on_redirect_to_the_same_host(server):
    server.replies.append((302, {"Location": f"{server.base}/v1/moved"}))
    _session().get(server.url, headers=KEY)
    assert [seen.headers["X-CMC_PRO_API_KEY"] for seen in server.seen] == ["cmc-test-value"] * 2


def test_log_records_hold_no_query_string_or_key(server, caplog):
    caplog.set_level(logging.DEBUG, logger="sentinel.net")
    _session().get(server.url, params={"q": "query-test-value"}, headers=KEY)
    [record] = [r for r in caplog.records if r.name == "sentinel.net"]
    assert record.url == server.url
    assert record.status == 200
    assert "query-test-value" not in str(vars(record))
    assert "cmc-test-value" not in str(vars(record))


def test_connection_error_is_logged_and_raised(caplog):
    with socket.socket() as sock:  # grab a free port, then leave it closed
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    caplog.set_level(logging.WARNING, logger="sentinel.net")
    with pytest.raises(requests.ConnectionError):
        _session(retries=0).get(f"http://127.0.0.1:{port}/v1/quotes", headers=KEY)
    [record] = [r for r in caplog.records if r.name == "sentinel.net"]
    assert record.error == "ConnectionError"
    assert "cmc-test-value" not in str(vars(record))
