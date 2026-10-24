"""DynamoDB plumbing shared by both tables: item (un)marshalling and a paged Query.

Item layouts are in docs/IMPLEMENTATION_PLAN.md, Appendix A. Reads use ``Query`` (never
``Scan``); numbers are ``Decimal``.
"""

from __future__ import annotations

from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from sentinel import aws

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


def marshal(item: dict[str, Any]) -> dict[str, Any]:
    return {name: _serializer.serialize(value) for name, value in item.items()}


def unmarshal(item: dict[str, Any]) -> dict[str, Any]:
    return {name: _deserializer.deserialize(value) for name, value in item.items()}


def query(table: str, **params: Any) -> list[dict[str, Any]]:
    client = aws.client("dynamodb")
    items: list[dict[str, Any]] = []
    while True:
        page = client.query(TableName=table, **params)
        items += [unmarshal(item) for item in page["Items"]]
        if "LastEvaluatedKey" not in page:
            return items
        params["ExclusiveStartKey"] = page["LastEvaluatedKey"]
