import io
import json
import logging
from datetime import datetime

from sentinel import log


def _entries(stream):
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_writes_one_json_object_per_line_with_extra_fields():
    out = io.StringIO()
    log.setup("INFO", stream=out)
    logging.getLogger("sentinel.test").info("fetched %d coins", 15, extra={"source": "cmc"})

    [entry] = _entries(out)
    assert entry["level"] == "info"
    assert entry["logger"] == "sentinel.test"
    assert entry["msg"] == "fetched 15 coins"
    assert entry["source"] == "cmc"
    assert entry["ts"].endswith("Z")
    assert datetime.fromisoformat(entry["ts"]).utcoffset().total_seconds() == 0


def test_exception_is_included():
    out = io.StringIO()
    log.setup("INFO", stream=out)
    try:
        raise ValueError("bad payload")
    except ValueError:
        logging.getLogger("sentinel.test").exception("parse failed")

    [entry] = _entries(out)
    assert entry["level"] == "error"
    assert "ValueError: bad payload" in entry["exc"]


def test_level_comes_from_settings(monkeypatch):
    monkeypatch.setenv("SENTINEL_LOG_LEVEL", "error")
    out = io.StringIO()
    log.setup(stream=out)
    logging.getLogger("sentinel.test").warning("hidden")
    assert out.getvalue() == ""


def test_setup_twice_keeps_one_handler():
    out = io.StringIO()
    log.setup("INFO", stream=out)
    log.setup("INFO", stream=out)
    logging.getLogger("sentinel.test").info("once")
    assert len(_entries(out)) == 1


def test_goes_to_stderr_not_stdout(capsys):
    log.setup("INFO")
    logging.getLogger("sentinel.test").info("to stderr")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err)["msg"] == "to stderr"


def test_aws_and_urllib3_debug_logs_stay_off():
    log.setup("DEBUG", stream=io.StringIO())
    for name in ("botocore", "boto3", "urllib3"):
        assert logging.getLogger(name).getEffectiveLevel() == logging.WARNING


def test_stack_info_is_included():
    out = io.StringIO()
    log.setup("INFO", stream=out)
    logging.getLogger("sentinel.test").info("where am I", stack_info=True)
    [entry] = _entries(out)
    assert "test_stack_info_is_included" in entry["stack"]


def test_registered_secret_is_redacted_everywhere():
    out = io.StringIO()
    log.setup("INFO", stream=out)
    log.redact("key-test-value")
    logger = logging.getLogger("sentinel.test")
    logger.info("key is key-test-value", extra={"header": "Bearer key-test-value"})
    try:
        raise RuntimeError("bad key-test-value")
    except RuntimeError:
        logger.exception("failed")

    text = out.getvalue()
    assert "key-test-value" not in text
    first, second = _entries(out)
    assert first["msg"] == "key is [redacted]"
    assert first["header"] == "Bearer [redacted]"
    assert "RuntimeError: bad [redacted]" in second["exc"]
