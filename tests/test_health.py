import json
import socket

import boto3
import pytest
from click.testing import CliRunner
from moto import mock_aws

from sentinel import health, net
from sentinel.cli import cli
from sentinel.config import HttpSettings

CMC_KEY = "cmc-test-value"
GEMINI_KEY = "gemini-test-value"
CMC_OK = (200, {}, {"data": {"usage": {"current_month": {"credits_left": 14000}}}})


@pytest.fixture
def aws_ready():
    """Both tables, the backup bucket and both keys, as on a healthy account."""
    with mock_aws():
        ssm = boto3.client("ssm", region_name="us-east-1")
        ssm.put_parameter(Name="/sentinel/cmc_api_key", Value=CMC_KEY, Type="SecureString")
        ssm.put_parameter(Name="/sentinel/gemini_api_key", Value=GEMINI_KEY, Type="SecureString")
        dynamodb = boto3.client("dynamodb", region_name="us-east-1")
        for table in ("sentinel-real", "sentinel-sim"):
            dynamodb.create_table(
                TableName=table,
                KeySchema=[{"AttributeName": "PK", "KeyType": "HASH"}],
                AttributeDefinitions=[{"AttributeName": "PK", "AttributeType": "S"}],
                BillingMode="PAY_PER_REQUEST",
            )
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="openclaw-files")
        yield


@pytest.fixture
def apis(make_server, monkeypatch):
    """Local stand-ins for CMC and Gemini, reached without waits between retries."""
    cmc, gemini = make_server(), make_server()
    monkeypatch.setattr(health, "CMC_KEY_INFO_URL", f"{cmc.base}/v1/key/info")
    monkeypatch.setattr(health, "GEMINI_MODELS_URL", f"{gemini.base}/v1beta/models")
    fast = HttpSettings(backoff_s=0, min_interval_s={"cmc": 0, "gemini": 0})
    monkeypatch.setattr(
        net, "_sessions", {name: net.Session(name, fast) for name in ("cmc", "gemini")}
    )
    return cmc, gemini


@pytest.fixture
def clock(monkeypatch):
    """Fake time for run(): sleeping moves the clock; .slept lists the pauses."""
    state = type("Clock", (), {"now": 0.0, "slept": []})()

    def fake_sleep(seconds):
        state.slept.append(seconds)
        state.now += seconds

    monkeypatch.setattr(health, "monotonic", lambda: state.now)
    monkeypatch.setattr(health, "sleep", fake_sleep)
    return state


def _by_name(results):
    return {r.name: r for r in results}


def test_all_checks_pass(aws_ready, apis):
    cmc, gemini = apis
    cmc.replies.append(CMC_OK)
    results = _by_name(health.run())
    assert all(r.ok for r in results.values())
    assert results["cmc"].detail == "key valid, 14000 credits left"
    assert cmc.seen[0].headers["X-CMC_PRO_API_KEY"] == CMC_KEY
    assert gemini.seen[0].headers["x-goog-api-key"] == GEMINI_KEY
    assert gemini.seen[0].path.endswith("pageSize=1")


def test_missing_table_is_fatal(aws_ready, apis):
    boto3.client("dynamodb", region_name="us-east-1").delete_table(TableName="sentinel-sim")
    result = _by_name(health.run())["dynamodb"]
    assert (result.ok, result.fatal, result.detail) == (False, True, "ResourceNotFoundException")


def test_missing_bucket_is_fatal(aws_ready, apis):
    boto3.client("s3", region_name="us-east-1").delete_bucket(Bucket="openclaw-files")
    result = _by_name(health.run())["s3"]
    assert (result.ok, result.fatal) == (False, True)


def test_missing_key_is_fatal(aws_ready, apis):
    boto3.client("ssm", region_name="us-east-1").delete_parameter(Name="/sentinel/cmc_api_key")
    result = _by_name(health.run())["cmc"]
    assert result.fatal
    assert result.detail == "cannot read SSM parameter /sentinel/cmc_api_key: ParameterNotFound"


@pytest.mark.parametrize(("name", "status"), [("cmc", 401), ("gemini", 400), ("gemini", 403)])
def test_rejected_key_is_fatal(aws_ready, apis, name, status):
    server = dict(zip(("cmc", "gemini"), apis, strict=True))[name]
    server.replies.append((status, {}))
    result = _by_name(health.run())[name]
    assert (result.ok, result.fatal, result.detail) == (False, True, f"HTTP {status}")


def test_server_errors_are_transient(aws_ready, apis):
    cmc, _ = apis
    cmc.replies.extend([(503, {})] * 4)  # first try + 3 retries in sentinel.net
    result = _by_name(health.run())["cmc"]
    assert (result.ok, result.fatal, result.detail) == (False, False, "HTTP 503")


def test_no_credentials_are_transient(apis, monkeypatch):
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(var)
    results = health.run()
    assert all(not r.ok and not r.fatal for r in results)
    assert _by_name(results)["dynamodb"].detail == "NoCredentialsError"


def test_wait_retries_transient_failures_until_they_pass(aws_ready, apis, clock):
    cmc, _ = apis
    cmc.replies.extend([*[(503, {})] * 4, CMC_OK])
    results = health.run(wait_s=60)
    assert all(r.ok for r in results)
    assert clock.slept == [5.0]


def test_wait_stops_at_once_on_a_fatal_failure(aws_ready, apis, clock):
    cmc, gemini = apis
    cmc.replies.extend([(503, {})] * 4)
    gemini.replies.append((403, {}))
    results = _by_name(health.run(wait_s=600))
    assert results["gemini"].fatal
    assert clock.slept == []


def test_wait_gives_up_at_the_deadline(aws_ready, apis, clock):
    cmc, _ = apis
    cmc.replies.extend([(503, {})] * 12)  # three rounds of 4 requests
    result = _by_name(health.run(wait_s=20))["cmc"]
    assert not result.ok
    assert clock.slept == [5.0, 10.0]


def test_cli_json_and_exit_code(aws_ready, apis):
    cmc, _ = apis
    cmc.replies.append(CMC_OK)
    result = CliRunner().invoke(cli, ["health"])
    assert result.exit_code == 0
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert set(report["checks"]) == {"dynamodb", "s3", "cmc", "gemini"}

    cmc.replies.append((401, {}))
    result = CliRunner().invoke(cli, ["health", "--format", "telegram"])
    assert result.exit_code == 1
    lines = result.stdout.strip().splitlines()
    assert lines == ["Health: NOT READY (3/4 ok)", "cmc: HTTP 401"]


def _closed_port_url():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return f"http://127.0.0.1:{sock.getsockname()[1]}/v1/key/info"


@pytest.mark.parametrize("fmt", ["json", "telegram"])
@pytest.mark.parametrize(
    "scenario", ["ok", "cmc_401", "cmc_503", "gemini_403", "cmc_unreachable", "dynamodb_missing"]
)
def test_keys_never_leak(aws_ready, apis, monkeypatch, scenario, fmt):
    cmc, gemini = apis
    if scenario == "ok":
        cmc.replies.append(CMC_OK)
    elif scenario == "cmc_401":
        cmc.replies.append((401, {}, {"status": {"error_message": "bad key"}}))
    elif scenario == "cmc_503":
        cmc.replies.extend([(503, {})] * 4)
    elif scenario == "gemini_403":
        gemini.replies.append((403, {}, {"error": {"message": "key not allowed"}}))
    elif scenario == "cmc_unreachable":
        monkeypatch.setattr(health, "CMC_KEY_INFO_URL", _closed_port_url())
        net._sessions["cmc"] = net.Session("cmc", HttpSettings(retries=0))
    else:
        boto3.client("dynamodb", region_name="us-east-1").delete_table(TableName="sentinel-real")
    monkeypatch.setenv("SENTINEL_LOG_LEVEL", "DEBUG")

    result = CliRunner().invoke(cli, ["health", "--format", fmt])

    everything = result.stdout + result.stderr
    assert result.stdout.strip()
    assert CMC_KEY not in everything
    assert GEMINI_KEY not in everything


@pytest.mark.live
def test_live_instance_is_ready():
    """Real AWS and APIs; run under aws-vault with: pytest -m live."""
    results = health.run()
    assert all(r.ok for r in results), [(r.name, r.detail) for r in results]
