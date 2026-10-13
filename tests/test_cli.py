import json

from click.testing import CliRunner

from sentinel import __version__
from sentinel.cli import cli


def test_help_lists_command_groups():
    result = CliRunner().invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "config" in result.output


def test_version():
    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_config_show_prints_compact_json(monkeypatch):
    monkeypatch.setenv("SENTINEL_SIM_TABLE", "sim-test")
    result = CliRunner().invoke(cli, ["config", "show"])
    assert result.exit_code == 0
    assert len(result.stdout.strip().splitlines()) == 1
    settings = json.loads(result.stdout)
    assert settings["sim_table"] == "sim-test"
    assert settings["region"] == "us-east-1"
