import io
import logging

import boto3
import pytest
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    ProfileNotFound,
    ReadTimeoutError,
)
from moto import mock_aws

from sentinel import aws, log


@pytest.fixture
def ssm():
    with mock_aws():
        yield boto3.client("ssm", region_name="us-east-1")


@pytest.fixture
def no_credentials(monkeypatch):
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(var)


def test_reads_securestring(ssm):
    ssm.put_parameter(Name="/sentinel/cmc_api_key", Value="cmc-test-value", Type="SecureString")
    assert aws.get_secret("cmc_api_key") == "cmc-test-value"


def test_value_is_cached_until_cleared(ssm):
    ssm.put_parameter(Name="/sentinel/cmc_api_key", Value="cmc-test-value", Type="SecureString")
    aws.get_secret("cmc_api_key")
    ssm.delete_parameter(Name="/sentinel/cmc_api_key")
    assert aws.get_secret("cmc_api_key") == "cmc-test-value"

    aws.clear_cache()
    with pytest.raises(aws.SecretError):
        aws.get_secret("cmc_api_key")


def test_loaded_key_is_redacted_in_logs(ssm):
    ssm.put_parameter(Name="/sentinel/cmc_api_key", Value="cmc-test-value", Type="SecureString")
    out = io.StringIO()
    log.setup("INFO", stream=out)
    key = aws.get_secret("cmc_api_key")
    logging.getLogger("sentinel.test").info("calling with %s", key)
    assert "cmc-test-value" not in out.getvalue()
    assert "[redacted]" in out.getvalue()


def test_missing_parameter_is_not_transient(ssm):
    with pytest.raises(aws.SecretError, match="/sentinel/gemini_api_key: ParameterNotFound") as exc:
        aws.get_secret("gemini_api_key")
    assert exc.value.transient is False


def test_plain_string_rejected_without_echoing_value(ssm):
    ssm.put_parameter(Name="/sentinel/newsapi_key", Value="plain-test-value", Type="String")
    with pytest.raises(aws.SecretError, match="must be a SecureString") as exc:
        aws.get_secret("newsapi_key")
    assert "plain-test-value" not in str(exc.value)


def test_no_credentials_is_transient(no_credentials):
    with pytest.raises(aws.SecretError, match="NoCredentialsError") as exc:
        aws.get_secret("cmc_api_key")
    assert exc.value.transient is True


def test_client_without_credentials_is_not_cached(no_credentials, monkeypatch):
    with pytest.raises(NoCredentialsError):
        aws.client("ssm")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    assert aws.client("ssm") is aws.client("ssm")


def test_unknown_name_rejected_before_any_aws_call():
    with pytest.raises(ValueError, match="unknown secret 'cmc_key'"):
        aws.get_secret("cmc_key")


def _client_error(code, status):
    response = {"Error": {"Code": code}, "ResponseMetadata": {"HTTPStatusCode": status}}
    return ClientError(response, "DescribeTable")


@pytest.mark.parametrize(
    ("exc", "transient"),
    [
        (_client_error("ThrottlingException", 400), True),
        (_client_error("ProvisionedThroughputExceededException", 400), True),
        (_client_error("InternalServerError", 500), True),
        (_client_error("503", 503), True),
        (_client_error("AccessDeniedException", 400), False),
        (_client_error("ResourceNotFoundException", 400), False),
        (EndpointConnectionError(endpoint_url="https://ssm.us-east-1.amazonaws.com"), True),
        (ReadTimeoutError(endpoint_url="https://ssm.us-east-1.amazonaws.com"), True),
        (NoCredentialsError(), True),
        (ProfileNotFound(profile="missing"), False),
    ],
)
def test_is_transient(exc, transient):
    assert aws.is_transient(exc) is transient


def test_error_code_never_uses_the_message():
    response = {"Error": {"Code": "AccessDeniedException", "Message": "arn:aws:iam::123:role/x"}}
    assert aws.error_code(ClientError(response, "GetParameter")) == "AccessDeniedException"
    assert aws.error_code(ProfileNotFound(profile="missing")) == "ProfileNotFound"
