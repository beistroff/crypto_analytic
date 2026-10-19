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

from sentinel.store.dynamo import BaselineRepo, Position, PositionRepo, TradeRepo, trade_item

ZERO = Decimal(0)
EPSILON = Decimal("1e-9")
SYMBOL = re.compile(r"[A-Z0-9]{1,15}")


class JournalError(RuntimeError):
    """A trade the journal cannot take (bad symbol, selling more than is held)."""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


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
    positions = PositionRepo()
    before = positions.get(symbol)
    moment = _now()
    now = _iso(moment)
    realised = ZERO
    if side == "BUY":
        old_qty = before.qty if before else ZERO
        cost_basis = (before.cost_basis if before else ZERO) + qty * price + fee
        new_qty = old_qty + qty
        avg_price = cost_basis / new_qty
    else:
        if before is None or before.qty < qty - EPSILON:
            held = before.qty if before else ZERO
            raise JournalError(f"cannot sell {qty} {symbol}, holding {held}")
        avg_price = before.avg_price
        realised = (price - avg_price) * qty - fee
        new_qty = before.qty - qty
        cost_basis = avg_price * new_qty
        if new_qty < EPSILON:
            new_qty, cost_basis = ZERO, ZERO
    after = Position(
        symbol=symbol,
        qty=new_qty,
        avg_price=avg_price,
        cost_basis=cost_basis,
        realised_pnl=(before.realised_pnl if before else ZERO) + realised,
        version=(before.version if before else 0) + 1,
        updated_at=now,
    )
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


def set_baseline(usdt: Decimal) -> dict[str, Any]:
    baseline = BaselineRepo().set(usdt, _iso(_now()))
    return {"baseline_usdt": baseline.usdt, "since": baseline.since}


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
