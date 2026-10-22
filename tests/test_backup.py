import json
from decimal import Decimal

import boto3
from click.testing import CliRunner

from sentinel.cli import cli
from sentinel.portfolio import service

D = Decimal


def test_export_writes_the_real_table_next_to_the_file_backup(tables):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="openclaw-files")
    service.set_baseline(D(1000))
    service.record_trade("buy", "SOL", D(2), D("100.5"), D(1))
    service.record_trade("buy", "ETH", D(1), D(50))
    service.record_trade("sell", "ETH", D(1), D(60))  # a closed position is still backed up
    run = CliRunner()

    dry = run.invoke(cli, ["backup", "export", "--stamp", "2026-10-22_03-00_UTC", "--dry-run"])
    assert json.loads(dry.output)["items"] == 6
    assert s3.list_objects_v2(Bucket="openclaw-files")["KeyCount"] == 0

    done = run.invoke(cli, ["backup", "export", "--stamp", "2026-10-22_03-00_UTC"])
    assert json.loads(done.output)["types"] == {"META": 1, "POSITION": 2, "TRADE": 3}
    key = "backups/2026-10-22_03-00_UTC/dynamodb/sentinel-real.json"
    document = json.loads(s3.get_object(Bucket="openclaw-files", Key=key)["Body"].read())
    assert document["table"] == "sentinel-real"
    sol = next(i for i in document["items"] if i["PK"] == "POS" and i["SK"] == "SOL")
    assert isinstance(sol["cost_basis"], str)  # text, so no digit passes through a float
    assert D(sol["cost_basis"]) == D("202")

    bad = run.invoke(cli, ["backup", "export", "--stamp", "../x"])
    assert bad.exit_code == 1
    assert "bad stamp" in json.loads(bad.output)["error"]
