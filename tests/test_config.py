import pytest
from pydantic import ValidationError

from sentinel.config import get_settings, load


def test_defaults_match_terraform():
    settings = load({})
    assert settings.region == "us-east-1"
    assert (settings.real_table, settings.sim_table) == ("sentinel-real", "sentinel-sim")
    assert settings.backup_bucket == "openclaw-files"
    assert (settings.http.timeout_s, settings.http.retries) == (10.0, 3)


def test_environment_overrides():
    settings = load(
        {"AWS_REGION": "eu-west-1", "SENTINEL_SIM_TABLE": "sim-test", "SENTINEL_LOG_LEVEL": "info"}
    )
    assert settings.region == "eu-west-1"
    assert settings.sim_table == "sim-test"
    assert settings.real_table == "sentinel-real"
    assert settings.log_level == "INFO"


def test_empty_variable_keeps_default():
    assert load({"AWS_REGION": ""}).region == "us-east-1"


def test_unknown_log_level_rejected():
    with pytest.raises(ValidationError):
        load({"SENTINEL_LOG_LEVEL": "loud"})


def test_settings_are_frozen():
    with pytest.raises(ValidationError):
        get_settings().region = "eu-west-1"


def test_environment_read_once(monkeypatch):
    monkeypatch.setenv("SENTINEL_REAL_TABLE", "real-test")
    first = get_settings()
    monkeypatch.setenv("SENTINEL_REAL_TABLE", "changed")
    assert get_settings() is first
    assert first.real_table == "real-test"


def test_rate_limits_are_frozen():
    with pytest.raises(ValidationError):
        get_settings().http.min_interval_s.cmc = 0
