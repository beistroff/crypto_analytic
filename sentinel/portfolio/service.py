"""Trade journal logic: buy, sell, average cost, realised P&L and the cash balance.

Average cost method. A buy adds its cost (quantity times price, plus the fee) to the
position's cost basis and re-averages. A sell keeps the average price and adds
``(price - avg_price) * qty - fee`` to the realised P&L. The position closes when the
quantity drops below ``EPSILON``. Fees are in USDT, the quote currency.

Cash is derived, not stored: the starting balance, minus the cost basis still deployed,
plus everything realised so far.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from ulid import ULID

from sentinel.store.real import BaselineRepo, Position, PositionRepo, TradeRepo, trade_item

ZERO = Decimal(0)
EPSILON = Decimal("1e-9")
PLACES = Decimal("1e-10")  # inputs and results are rounded to 10 decimals
SYMBOL = re.compile(r"[A-Z0-9]{1,15}")


class JournalError(RuntimeError):
    """A trade the journal cannot take (bad symbol, selling more than is held)."""


def _round(value: Decimal) -> Decimal:
    """Keep ``PLACES`` decimals: enough for $1 of BTC, short enough for DynamoDB."""
    return value.quantize(PLACES)


def plain(value: Decimal) -> str:
    """A number as people write it: ``3``, ``0.0001388``, never ``3.0000000000`` or ``1E+2``."""
    return format(value.normalize(), "f")


def _now() -> str:
    """UTC time as ISO 8601 text: DynamoDB has no date type, and this text sorts by time."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def record_trade(
    side: str,
    symbol: str,
    qty: Decimal,
    price: Decimal,
    fee: Decimal = ZERO,
    *,
    venue: str | None = None,
    note: str | None = None,
    source: str = "telegram",
) -> dict[str, Any]:
    """Journal a buy or sell and update the position; returns what the agent should report."""
    symbol = symbol.upper()
    side = side.upper()
    if not SYMBOL.fullmatch(symbol):
        raise JournalError(f"bad symbol {symbol!r}")
    if side not in ("BUY", "SELL"):
        raise JournalError(f"bad side {side!r}, expected BUY or SELL")
    qty, price, fee = _round(qty), _round(price), _round(fee)
    if qty <= 0 or price <= 0 or fee < 0:
        raise JournalError("qty and price must be positive and fee not negative")
    before = PositionRepo().get(symbol)
    now = _now()
    realised = ZERO
    if side == "BUY":
        old_qty = before.qty if before else ZERO
        cost_basis = (before.cost_basis if before else ZERO) + qty * price + fee
        new_qty = old_qty + qty
        avg_price = cost_basis / new_qty
    else:
        if before is None or before.qty < qty - EPSILON:
            held = plain(before.qty) if before else "0"
            raise JournalError(f"cannot sell {plain(qty)} {symbol}, holding {held}")
        avg_price = before.avg_price
        # Profit locked in by this sale: what each coin sold for minus what it cost on
        # average (buy fees included), less this sale's fee.
        realised = (price - avg_price) * qty - fee
        new_qty = before.qty - qty
        cost_basis = avg_price * new_qty
        if new_qty < EPSILON:
            new_qty, cost_basis = ZERO, ZERO
    after = Position(
        symbol=symbol,
        qty=_round(new_qty),
        avg_price=_round(avg_price),
        cost_basis=_round(cost_basis),
        realised_pnl=_round((before.realised_pnl if before else ZERO) + realised),
        version=(before.version if before else 0) + 1,
        created_at=before.created_at if before else now,
        updated_at=now,
    )
    realised = _round(realised)
    trade_id = str(ULID())
    trade = trade_item(trade_id, now, symbol, side, qty, price, fee, venue, note, source)
    TradeRepo().add(trade, after, before.version if before else None)
    return {
        "trade_id": trade_id,
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "price": price,
        "fee": fee,
        "realised_pnl": realised if side == "SELL" else None,
        "position": after,
    }


def set_baseline(usdt: Decimal, *, replace: bool = False) -> dict[str, Any]:
    """Set the starting cash, once. ``replace`` overwrites it and reports the old value."""
    if usdt < 0:
        raise JournalError("starting cash must not be negative")
    repo = BaselineRepo()
    old = repo.get()
    if old and not replace:
        raise JournalError(
            f"starting cash is already {plain(old.usdt)} USDT since {old.since}; "
            "pass --replace to change it"
        )
    baseline = repo.set(_round(usdt), _now())
    result: dict[str, Any] = {"baseline_usdt": baseline.usdt, "since": baseline.since}
    if old:
        result["replaced"] = {"baseline_usdt": old.usdt, "since": old.since}
    return result


@dataclass(frozen=True)
class Summary:
    baseline_usdt: Decimal | None
    since: str | None
    cash_usdt: Decimal | None  # None until a baseline is set
    invested_usdt: Decimal
    realised_pnl: Decimal
    open_positions: list[Position]  # largest cost basis first


def summary() -> Summary:
    positions = PositionRepo().list()
    baseline = BaselineRepo().get()
    invested = sum((p.cost_basis for p in positions), ZERO)
    realised = sum((p.realised_pnl for p in positions), ZERO)
    held = sorted((p for p in positions if p.qty > 0), key=lambda p: -p.cost_basis)
    return Summary(
        baseline_usdt=baseline.usdt if baseline else None,
        since=baseline.since if baseline else None,
        cash_usdt=baseline.usdt - invested + realised if baseline else None,
        invested_usdt=invested,
        realised_pnl=realised,
        open_positions=held,
    )
