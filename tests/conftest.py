"""Shared test setup: no network, fake AWS credentials, fresh module state per test."""

import json
import logging
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from sentinel import aws, log, net
from sentinel.config import ENV_VARS, get_settings

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def _no_network(request, monkeypatch):
    """Fail on any connection beyond localhost, unless the test is marked live."""
    if request.node.get_closest_marker("live"):
        return
    connect = socket.socket.connect

    def guarded(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOCAL_HOSTS:
            raise RuntimeError(f"network access in a unit test: {address!r}")
        return connect(sock, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture(autouse=True)
def _isolated_env(request, monkeypatch, tmp_path):
    """Fake AWS credentials, no AWS config files, no overrides from the developer's shell.

    Live tests keep the real environment (run them under aws-vault).
    """
    if request.node.get_closest_marker("live"):
        return
    for var in [*ENV_VARS.values(), "AWS_PROFILE", "AWS_DEFAULT_PROFILE"]:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "aws-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "aws-credentials"))
    monkeypatch.setenv("AWS_EC2_METADATA_DISABLED", "true")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture(autouse=True)
def _fresh_state(monkeypatch):
    get_settings.cache_clear()
    aws.clear_cache()
    monkeypatch.setattr(net, "_sessions", {})
    monkeypatch.setattr(log, "_secrets", set())
    loggers = [logging.getLogger(), *map(logging.getLogger, log._QUIET_LOGGERS)]
    levels = [logger.level for logger in loggers]
    yield
    if log._handler is not None:
        logging.getLogger().removeHandler(log._handler)
        log._handler = None
    for logger, level in zip(loggers, levels, strict=True):
        logger.setLevel(level)


@pytest.fixture
def make_server():
    """Start local HTTP servers that answer scripted replies, then 200 ``{"ok": true}``.

    Append ``(status, headers)`` or ``(status, headers, json_body)`` to ``.replies``;
    ``.seen`` lists each request's path and headers.
    """
    servers = []

    def start():
        replies = []
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append(SimpleNamespace(path=self.path, headers=dict(self.headers)))
                reply = replies.pop(0) if replies else (200, {})
                body = json.dumps(reply[2] if len(reply) > 2 else {"ok": True}).encode()
                self.send_response(reply[0])
                for name, value in reply[1].items():
                    self.send_header(name, value)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        # A short poll interval keeps shutdown() quick in teardown.
        threading.Thread(target=httpd.serve_forever, args=(0.05,), daemon=True).start()
        servers.append(httpd)
        base = f"http://127.0.0.1:{httpd.server_port}"
        return SimpleNamespace(base=base, url=f"{base}/v1/quotes", replies=replies, seen=seen)

    yield start
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def server(make_server):
    return make_server()
