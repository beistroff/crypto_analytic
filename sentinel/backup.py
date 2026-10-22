"""Nightly JSON backup of the real DynamoDB table to S3.

It lands next to the file backups of ``ops/s3_backup.sh``:
``s3://<bucket>/backups/<UTC stamp>/dynamodb/<table>.json``. Numbers are written as
strings so no digit is lost; the file is a plain list of the table's items.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sentinel import aws
from sentinel.config import get_settings
from sentinel.store import dynamo

STAMP_FORMAT = "%Y-%m-%d_%H-%M_UTC"  # the folder name ops/s3_backup.sh uses
STAMP = re.compile(r"[0-9A-Za-z_-]{1,40}")


class BackupError(RuntimeError):
    """A backup request the command cannot take (a stamp that is not a folder name)."""


def export_real(stamp: str | None = None, *, dry_run: bool = False) -> dict[str, Any]:
    """Write every item of the real table to S3; ``dry_run`` reads the table and writes nothing.

    ``stamp`` names the backup folder; ``ops/s3_backup.sh`` passes its own so the files of
    one night sit together.
    """
    now = datetime.now(UTC)
    stamp = stamp or now.strftime(STAMP_FORMAT)
    if not STAMP.fullmatch(stamp):
        raise BackupError(f"bad stamp {stamp!r}, expected a folder name like {STAMP_FORMAT}")
    settings = get_settings()
    items = dynamo.export_real()
    key = f"backups/{stamp}/dynamodb/{settings.real_table}.json"
    if not dry_run:
        document = {
            "table": settings.real_table,
            "exported_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "items": items,
        }
        aws.client("s3").put_object(
            Bucket=settings.backup_bucket,
            Key=key,
            # Decimal is not JSON: str() keeps it exact.
            Body=json.dumps(document, default=str, sort_keys=True).encode(),
            ContentType="application/json",
        )
    return {
        "dry_run": dry_run,
        "bucket": settings.backup_bucket,
        "key": key,
        "items": len(items),
        "types": dict(Counter(item["type"] for item in items)),
    }
