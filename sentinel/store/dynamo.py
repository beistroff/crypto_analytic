"""DynamoDB access: trades, positions and the starting balance in the real table, watches
in the sim table.

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


def _sim_table() -> str:
    return get_settings().sim_table


def _marshal(item: dict[str, Any]) -> dict[str, Any]:
    return {name: _serializer.serialize(value) for name, value in item.items()}


def _unmarshal(item: dict[str, Any]) -> dict[str, Any]:
    return {name: _deserializer.deserialize(value) for name, value in item.items()}


def _query(table: str, **params: Any) -> list[dict[str, Any]]:
    client = aws.client("dynamodb")
    items: list[dict[str, Any]] = []
    while True:
        page = client.query(TableName=table, **params)
        items += [_unmarshal(item) for item in page["Items"]]
        if "LastEvaluatedKey" not in page:
            return items
        params["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def export_real() -> list[dict[str, Any]]:
    """Every item of the real table, for the nightly backup.

    The instance role has no ``Scan``, so this is a ``Query`` per partition it knows: the
    baseline, the positions, and the trades of each position's symbol (a closed position
    stays in the table, so every symbol ever traded is listed). A new item type in
    ``sentinel-real`` has to be added here.
    """
    items = _partition(_table(), "META") + _partition(_table(), "POS")
    symbols = [item["SK"] for item in items if item["PK"] == "POS"]
    for symbol in symbols:
        items += _partition(_table(), f"TRADE#{symbol}")
    return items


def _partition(table: str, pk: str) -> list[dict[str, Any]]:
    return _query(
        table,
        KeyConditionExpression="PK = :pk",
        ExpressionAttributeValues=_marshal({":pk": pk}),
        ConsistentRead=True,
    )


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
        return [Position.from_item(item) for item in _partition(_table(), "POS")]


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


@dataclass(frozen=True)
class Watch:
    """A level the user wants to hear about: a ``PRED`` item from chat with a ``watch`` map.

    While it is active it sits in the sparse GSI2 under ``WATCH``, so ``watch check`` finds
    it without a Scan.
    """

    pred_id: str
    symbol: str
    created_at: str
    trigger: str  # touch_below, close_below or close_above
    level: Decimal  # stored as the prediction's entry
    timeframe: str | None = None  # close triggers only: 1d or 4h
    stop: Decimal | None = None
    target: Decimal | None = None
    note: str | None = None
    status: str = "active"  # active, hit or removed
    hit_at: str | None = None
    hit_price: Decimal | None = None

    @property
    def key(self) -> dict[str, str]:
        return {"PK": f"PRED#{self.created_at[:10]}", "SK": f"{self.created_at}#{self.symbol}#chat"}

    def item(self) -> dict[str, Any]:
        watch: dict[str, Any] = {"trigger": self.trigger, "status": self.status}
        if self.timeframe:
            watch["timeframe"] = self.timeframe
        item: dict[str, Any] = {
            **self.key,
            "GSI1PK": f"SYM#{self.symbol}",
            "GSI1SK": self.created_at,
            "GSI2PK": "WATCH",
            "GSI2SK": self.created_at,
            "type": "PRED",
            "created_at": self.created_at,
            "pred_id": self.pred_id,
            "symbol": self.symbol,
            "arm": "chat",
            "source": "chat",
            "entry": self.level,
            "watch": watch,
        }
        # Optional fields are left out when not given.
        for name in ("stop", "target", "note"):
            if getattr(self, name) is not None:
                item[name] = getattr(self, name)
        return item

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> Watch:
        watch = item["watch"]
        return cls(
            pred_id=item["pred_id"],
            symbol=item["symbol"],
            created_at=item["created_at"],
            trigger=watch["trigger"],
            level=item["entry"],
            timeframe=watch.get("timeframe"),
            stop=item.get("stop"),
            target=item.get("target"),
            note=item.get("note"),
            status=watch["status"],
            hit_at=watch.get("hit_at"),
            hit_price=watch.get("hit_price"),
        )


class WatchRepo:
    def add(self, watch: Watch) -> bool:
        """Store a watch; False when an item with the same key exists."""
        try:
            aws.client("dynamodb").put_item(
                TableName=_sim_table(),
                Item=_marshal(watch.item()),
                ConditionExpression="attribute_not_exists(PK)",
            )
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def pending(self) -> list[Watch]:
        """Active watches, oldest first."""
        items = _query(
            _sim_table(),
            IndexName="GSI2",
            KeyConditionExpression="GSI2PK = :pk",
            ExpressionAttributeValues=_marshal({":pk": "WATCH"}),
        )
        return [Watch.from_item(item) for item in items]

    def mark_hit(self, watch: Watch, hit_at: str, hit_price: Decimal) -> Watch | None:
        """Mark an active watch as hit (it leaves GSI2); None when it was removed meanwhile."""
        return self._update(
            watch,
            "SET #w.#s = :hit, #w.hit_at = :at, #w.hit_price = :price REMOVE GSI2PK, GSI2SK",
            {":hit": "hit", ":at": hit_at, ":price": hit_price, ":active": "active"},
            condition="#w.#s = :active",
        )

    def remove(self, watch: Watch, removed_at: str) -> bool:
        """Stop an active watch; False when it was hit or removed in the meantime."""
        updated = self._update(
            watch,
            "SET #w.#s = :removed, #w.removed_at = :at REMOVE GSI2PK, GSI2SK",
            {":removed": "removed", ":at": removed_at, ":active": "active"},
            condition="#w.#s = :active",
        )
        return updated is not None

    def _update(
        self,
        watch: Watch,
        expression: str,
        values: dict[str, Any],
        condition: str | None = None,
    ) -> Watch | None:
        params: dict[str, Any] = {
            "TableName": _sim_table(),
            "Key": _marshal(watch.key),
            "UpdateExpression": expression,
            "ExpressionAttributeValues": _marshal(values),
            "ReturnValues": "ALL_NEW",
        }
        # "status" is a reserved word.
        params["ExpressionAttributeNames"] = {"#w": "watch", "#s": "status"}
        if condition:
            params["ConditionExpression"] = condition
        try:
            response = aws.client("dynamodb").update_item(**params)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return None
            raise
        return Watch.from_item(_unmarshal(response["Attributes"]))
