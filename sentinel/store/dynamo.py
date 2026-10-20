"""DynamoDB access to the real table: trades, positions and the starting balance.

Item layouts are in docs/IMPLEMENTATION_PLAN.md, Appendix A. Reads use ``Query`` (never
``Scan``); numbers are ``Decimal``. A trade and the position it changes are written in
one transaction that checks the position's ``version`` (optimistic locking).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer
from botocore.exceptions import ClientError

from sentinel import aws
from sentinel.config import get_settings

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


class VersionConflict(RuntimeError):
    """The position changed between reading and writing it, or the trade id exists."""


@dataclass(frozen=True)
class Position:
    symbol: str
    qty: Decimal
    avg_price: Decimal
    cost_basis: Decimal
    realised_pnl: Decimal
    version: int
    created_at: str  # when the position was first opened
    updated_at: str

    def item(self) -> dict[str, Any]:
        return {
            "PK": "POS",
            "SK": self.symbol,
            "GSI1PK": f"SYM#{self.symbol}",
            "GSI1SK": "POS",
            "type": "POSITION",
            "created_at": self.created_at,
            "qty": self.qty,
            "avg_price": self.avg_price,
            "cost_basis": self.cost_basis,
            "realised_pnl": self.realised_pnl,
            "version": self.version,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> Position:
        return cls(
            symbol=item["SK"],
            qty=item["qty"],
            avg_price=item["avg_price"],
            cost_basis=item["cost_basis"],
            realised_pnl=item["realised_pnl"],
            version=int(item["version"]),
            created_at=item["created_at"],
            updated_at=item["updated_at"],
        )


def trade_item(
    trade_id: str,
    ts: str,
    symbol: str,
    side: str,
    qty: Decimal,
    price: Decimal,
    fee: Decimal,
    venue: str | None,
    note: str | None,
    source: str,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "PK": f"TRADE#{symbol}",
        "SK": f"{ts}#{trade_id}",
        "GSI1PK": f"SYM#{symbol}",
        "GSI1SK": ts,
        "type": "TRADE",
        "created_at": ts,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": price,
        "quote_amount": qty * price,
        "fee": fee,
        "fee_asset": "USDT",
        "source": source,
    }
    # Optional text is left out when not given.
    if venue:
        item["venue"] = venue
    if note:
        item["note"] = note
    return item


def _table() -> str:
    return get_settings().real_table


def _marshal(item: dict[str, Any]) -> dict[str, Any]:
    return {name: _serializer.serialize(value) for name, value in item.items()}


def _unmarshal(item: dict[str, Any]) -> dict[str, Any]:
    return {name: _deserializer.deserialize(value) for name, value in item.items()}


def _query(**params: Any) -> list[dict[str, Any]]:
    client = aws.client("dynamodb")
    items: list[dict[str, Any]] = []
    while True:
        page = client.query(TableName=_table(), **params)
        items += [_unmarshal(item) for item in page["Items"]]
        if "LastEvaluatedKey" not in page:
            return items
        params["ExclusiveStartKey"] = page["LastEvaluatedKey"]


class PositionRepo:
    def get(self, symbol: str) -> Position | None:
        response = aws.client("dynamodb").get_item(
            TableName=_table(),
            Key=_marshal({"PK": "POS", "SK": symbol}),
            ConsistentRead=True,
        )
        item = response.get("Item")
        return Position.from_item(_unmarshal(item)) if item else None

    def list(self) -> list[Position]:
        """Every position ever held, closed ones (qty 0) included, by symbol."""
        items = _query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues=_marshal({":pk": "POS"}),
            ConsistentRead=True,
        )
        return [Position.from_item(item) for item in items]


class TradeRepo:
    def add(self, trade: dict[str, Any], position: Position, expected_version: int | None) -> None:
        """Write the trade and the new position, or neither.

        ``expected_version`` is the version read before the trade (None for a first
        buy); ``position.version`` must be the next one.
        """
        if expected_version is None:
            guard = {"ConditionExpression": "attribute_not_exists(PK)"}
        else:
            guard = {
                "ConditionExpression": "#v = :expected",
                "ExpressionAttributeNames": {"#v": "version"},
                "ExpressionAttributeValues": _marshal({":expected": expected_version}),
            }
        table = _table()
        try:
            aws.client("dynamodb").transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": table,
                            "Item": _marshal(trade),
                            "ConditionExpression": "attribute_not_exists(PK)",
                        }
                    },
                    {"Put": {"TableName": table, "Item": _marshal(position.item()), **guard}},
                ]
            )
        except ClientError as exc:
            # Only a failed condition is a conflict; a throttled or clashing transaction is
            # re-raised so the caller sees its real error code.
            reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
            if "ConditionalCheckFailed" in reasons:
                raise VersionConflict(f"{position.symbol} changed, run the trade again") from None
            raise


@dataclass(frozen=True)
class Baseline:
    usdt: Decimal
    since: str


class BaselineRepo:
    def get(self) -> Baseline | None:
        response = aws.client("dynamodb").get_item(
            TableName=_table(),
            Key=_marshal({"PK": "META", "SK": "BASELINE"}),
            ConsistentRead=True,
        )
        item = response.get("Item")
        if not item:
            return None
        item = _unmarshal(item)
        return Baseline(item["baseline_usdt"], item["since"])

    def set(self, usdt: Decimal, since: str) -> Baseline:
        item = {
            "PK": "META",
            "SK": "BASELINE",
            "type": "META",
            "created_at": since,
            "baseline_usdt": usdt,
            "since": since,
        }
        aws.client("dynamodb").put_item(TableName=_table(), Item=_marshal(item))
        return Baseline(usdt, since)
