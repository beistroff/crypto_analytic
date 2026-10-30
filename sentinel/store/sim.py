"""The sim table (``sentinel-sim``): watches and predictions, both ``PRED`` items, and the
snapshots experiment runs showed the models (``SNAP`` items).

Open items sit in the sparse GSI2 (``WATCH`` while a watch is active, ``OPEN`` until a
prediction is scored), so the checks find them without a Scan.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from botocore.exceptions import ClientError

from sentinel import aws
from sentinel.config import get_settings
from sentinel.signals.schema import Snapshot
from sentinel.store.base import marshal, query, unmarshal

SNAPSHOT_TTL = timedelta(days=180)


def _table() -> str:
    return get_settings().sim_table


def _put_new(item: dict[str, Any]) -> bool:
    """Store a new item; False when an item with the same key exists."""
    try:
        aws.client("dynamodb").put_item(
            TableName=_table(),
            Item=marshal(item),
            ConditionExpression="attribute_not_exists(PK)",
        )
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
            return False
        raise
    return True


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
        return _put_new(watch.item())

    def pending(self) -> list[Watch]:
        """Active watches, oldest first."""
        items = query(
            _table(),
            IndexName="GSI2",
            KeyConditionExpression="GSI2PK = :pk",
            ExpressionAttributeValues=marshal({":pk": "WATCH"}),
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
            "TableName": _table(),
            "Key": marshal(watch.key),
            "UpdateExpression": expression,
            "ExpressionAttributeValues": marshal(values),
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
        return Watch.from_item(unmarshal(response["Attributes"]))


@dataclass(frozen=True)
class Prediction:
    """A call, logged from chat or made by an experiment arm: a ``PRED`` item without a
    ``watch`` map.

    It sits in the sparse GSI2 under ``OPEN`` until the scorer has checked every horizon
    up to its own, keyed by the next ``due_at``. ``snapshot`` is the market the call was
    made in (price, RSI, BTC's regime); ``checks`` holds the scorer's results by horizon
    (``{"h4": {"price", "return_pct", "hit"}}``). Experiment calls also name their run
    ``slot``, the full snapshot they saw (``snapshot_ref``, a ``SNAP`` item's ``as_of``),
    the prompt and what the call cost.
    """

    pred_id: str
    symbol: str
    created_at: str
    model: str
    action: str  # BUY, SELL or HOLD
    direction: str  # UP, DOWN or FLAT
    confidence: Decimal
    horizon_h: int
    entry: Decimal
    target: Decimal | None
    stop: Decimal | None
    btc_context: str
    reasons: list[str]
    risk_note: str | None
    snapshot: dict[str, Any]
    valid: bool
    validator_errors: list[str]
    warnings: list[str]
    due_at: str
    source: str = "chat"  # chat or scheduled
    arm: str = "chat"  # an experiment arm's name for scheduled calls
    slot: str | None = None  # the experiment run: 00, 08 or 16 UTC
    model_version: str | None = None  # the model id the API answered with
    prompt_hash: str | None = None
    snapshot_ref: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    cost_usd: Decimal | None = None
    latency_ms: int | None = None
    # The Naive Bayes gate (gated arms only): NB's P(up), whether it asked for a re-check,
    # the call before it and whether the action changed.
    nb_p_up: Decimal | None = None
    gate_triggered: bool | None = None
    original_action: str | None = None
    revised: bool | None = None
    status: str = "OPEN"  # OPEN or DONE
    checks: dict[str, Any] = field(default_factory=dict)
    target_hit_first: str | None = None  # target, stop or neither (BUY and SELL)
    max_adverse_pct: Decimal | None = None

    @property
    def key(self) -> dict[str, str]:
        return {
            "PK": f"PRED#{self.created_at[:10]}",
            "SK": f"{self.created_at}#{self.symbol}#{self.arm}",
        }

    def item(self) -> dict[str, Any]:
        item = {
            **self.key,
            "GSI1PK": f"SYM#{self.symbol}",
            "GSI1SK": self.created_at,
            "type": "PRED",
            **asdict(self),
        }
        if self.status == "OPEN":  # only open calls sit in the sparse GSI2
            item["GSI2PK"], item["GSI2SK"] = "OPEN", self.due_at
        return {name: value for name, value in item.items() if value is not None}

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> Prediction:
        values = {f.name: item.get(f.name) for f in fields(cls)}
        values["horizon_h"] = int(item["horizon_h"])
        for name in ("tokens_in", "tokens_out", "latency_ms"):  # Decimal from DynamoDB
            if values[name] is not None:
                values[name] = int(values[name])
        values["checks"] = item.get("checks") or {}
        return cls(**values)


class PredictionRepo:
    def add(self, prediction: Prediction) -> bool:
        """Store a call; False when an item with the same key exists."""
        return _put_new(prediction.item())

    def get(self, pred_id: str, date: str) -> Prediction | None:
        """The call ``pred_id`` logged on ``date`` (``YYYY-MM-DD``, from the id)."""
        items = query(
            _table(),
            KeyConditionExpression="PK = :pk",
            FilterExpression="pred_id = :id",
            ExpressionAttributeValues=marshal({":pk": f"PRED#{date}", ":id": pred_id}),
        )
        found = [item for item in items if "watch" not in item]
        return Prediction.from_item(found[0]) if found else None

    def logged(self, dates: list[str]) -> list[Prediction]:
        """The calls logged on ``dates`` (``YYYY-MM-DD``), watches left out, oldest first."""
        items: list[dict[str, Any]] = []
        for date in dates:
            items += query(
                _table(),
                KeyConditionExpression="PK = :pk",
                ExpressionAttributeValues=marshal({":pk": f"PRED#{date}"}),
            )
        return [Prediction.from_item(item) for item in items if "watch" not in item]

    def due(self, now: str) -> list[Prediction]:
        """Open calls with a check due at or before ``now``."""
        items = query(
            _table(),
            IndexName="GSI2",
            KeyConditionExpression="GSI2PK = :pk AND GSI2SK <= :now",
            ExpressionAttributeValues=marshal({":pk": "OPEN", ":now": now}),
        )
        return [Prediction.from_item(item) for item in items]

    def record(
        self,
        pred: Prediction,
        checks: dict[str, Any],
        next_due: str | None,
        target_hit_first: str | None = None,
        max_adverse_pct: Decimal | None = None,
    ) -> bool:
        """Save the checks so far with the next due time, or, with no next one, mark the
        call DONE (it leaves GSI2) with its path results. False when the call is no longer
        OPEN: an overlapping run finished it first, and its result stands."""
        params: dict[str, Any] = {
            "TableName": _table(),
            "Key": marshal(pred.key),
            "ConditionExpression": "#s = :open",
            "ExpressionAttributeNames": {"#s": "status"},  # a reserved word
        }
        if next_due:
            params["UpdateExpression"] = "SET checks = :c, due_at = :due, GSI2SK = :due"
            values = {":c": checks, ":due": next_due}
        else:
            params["UpdateExpression"] = (
                "SET checks = :c, #s = :done, target_hit_first = :first, "
                "max_adverse_pct = :adverse REMOVE GSI2PK, GSI2SK"
            )
            values = {
                ":c": checks,
                ":done": "DONE",
                ":first": target_hit_first,
                ":adverse": max_adverse_pct,
            }
        params["ExpressionAttributeValues"] = marshal({**values, ":open": "OPEN"})
        try:
            aws.client("dynamodb").update_item(**params)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                return False
            raise
        return True


class SnapshotRepo:
    def add(self, snap: Snapshot) -> bool:
        """Store the snapshot an experiment run showed every arm, for 180 days (DynamoDB
        deletes it after ``ttl``); False when one with the same time exists."""
        as_of = datetime.fromisoformat(snap.as_of)
        return _put_new(
            {
                "PK": f"SNAP#{snap.symbol}",
                "SK": snap.as_of,
                "type": "SNAP",
                "created_at": snap.as_of,
                "schema_version": snap.schema_version,
                "payload": snap.model_dump_json(),
                "missing": snap.missing,
                "ttl": int((as_of + SNAPSHOT_TTL).timestamp()),
            }
        )
