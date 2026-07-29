"""Deterministic paper-account ledger built from immutable broker fills."""

from dataclasses import dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Mapping

from broker.contracts import (
    AccountSnapshot,
    BrokerFillSnapshot,
    PositionSnapshot,
)
from execution.models import OrderSide, require_utc_datetime


@dataclass
class _Position:
    symbol: str
    quantity: float
    average_price: float

    @property
    def side(self) -> OrderSide:
        return OrderSide.BUY if self.quantity > 0 else OrderSide.SELL


class PaperLedger:
    """Track paper balance, positions and PnL from broker fill snapshots."""

    def __init__(
        self,
        account_id: str,
        *,
        starting_balance: float = 1000.0,
        currency: str = "USD",
    ):
        if not isinstance(account_id, str) or not account_id.strip():
            raise ValueError("account_id must be a non-empty string")

        resolved_balance = float(starting_balance)

        if not isfinite(resolved_balance) or resolved_balance < 0:
            raise ValueError(
                "starting_balance must be finite and non-negative"
            )

        if (
            not isinstance(currency, str)
            or len(currency.strip()) != 3
            or not currency.strip().isalpha()
        ):
            raise ValueError("currency must be a three-letter code")

        self.account_id = account_id.strip()
        self.currency = currency.strip().upper()
        self.starting_balance = resolved_balance

        self._realized_pnl = 0.0
        self._commission = 0.0
        self._positions: dict[str, _Position] = {}
        self._marks: dict[str, float] = {}
        self._processed_fills: set[str] = set()
        self._fills: list[BrokerFillSnapshot] = []
        self._as_of = datetime.now(timezone.utc)

    @property
    def realized_pnl(self) -> float:
        return self._realized_pnl

    @property
    def total_commission(self) -> float:
        return self._commission

    @property
    def balance(self) -> float:
        return (
            self.starting_balance
            + self._realized_pnl
            - self._commission
        )

    @property
    def unrealized_pnl(self) -> float:
        return sum(
            self._position_unrealized(position)
            for position in self._positions.values()
        )

    @property
    def equity(self) -> float:
        return self.balance + self.unrealized_pnl

    @property
    def fills(self) -> tuple[BrokerFillSnapshot, ...]:
        return tuple(self._fills)

    def apply_fill(self, fill: BrokerFillSnapshot) -> bool:
        """Apply one fill idempotently."""

        if not isinstance(fill, BrokerFillSnapshot):
            raise TypeError("fill must be a BrokerFillSnapshot")

        if fill.account_id != self.account_id:
            raise ValueError("fill belongs to another account")

        if fill.fill_id in self._processed_fills:
            return False

        self._apply_position_change(fill)
        self._commission += fill.commission
        self._marks[fill.symbol] = fill.price
        self._processed_fills.add(fill.fill_id)
        self._fills.append(fill)
        self._as_of = max(self._as_of, fill.fill_time)

        return True

    def reconcile(
        self,
        fills: tuple[BrokerFillSnapshot, ...],
    ) -> int:
        """Apply unseen fills and return the number applied."""

        applied = 0

        for fill in fills:
            if self.apply_fill(fill):
                applied += 1

        return applied

    def update_marks(
        self,
        prices: Mapping[str, float],
        *,
        as_of: datetime,
    ) -> None:
        """Update mark prices used for unrealized PnL."""

        require_utc_datetime(as_of, "as_of")

        for symbol, price in prices.items():
            if not isinstance(symbol, str) or not symbol.strip():
                raise ValueError(
                    "price symbols must be non-empty strings"
                )

            resolved = float(price)

            if not isfinite(resolved) or resolved <= 0:
                raise ValueError(
                    "mark prices must be finite and greater than zero"
                )

            self._marks[symbol.strip()] = resolved

        self._as_of = max(self._as_of, as_of)

    def positions(self) -> tuple[PositionSnapshot, ...]:
        """Return immutable open-position projections."""

        snapshots = []

        for symbol in sorted(self._positions):
            position = self._positions[symbol]
            mark = self._marks.get(
                symbol,
                position.average_price,
            )

            snapshots.append(
                PositionSnapshot(
                    account_id=self.account_id,
                    symbol=symbol,
                    side=position.side,
                    quantity=abs(position.quantity),
                    average_price=position.average_price,
                    mark_price=mark,
                    unrealized_pnl=self._position_unrealized(
                        position
                    ),
                    as_of=self._as_of,
                )
            )

        return tuple(snapshots)

    def account_snapshot(self) -> AccountSnapshot:
        """Return the current account projection."""

        margin_used = 0.0

        return AccountSnapshot(
            account_id=self.account_id,
            currency=self.currency,
            balance=self.balance,
            equity=self.equity,
            margin_used=margin_used,
            available_funds=self.equity - margin_used,
            as_of=self._as_of,
        )

    def _apply_position_change(
        self,
        fill: BrokerFillSnapshot,
    ) -> None:
        symbol = fill.symbol

        signed_fill = (
            fill.quantity
            if fill.side is OrderSide.BUY
            else -fill.quantity
        )

        current = self._positions.get(symbol)

        if current is None:
            self._positions[symbol] = _Position(
                symbol=symbol,
                quantity=signed_fill,
                average_price=fill.price,
            )
            return

        same_direction = (
            current.quantity > 0 and signed_fill > 0
        ) or (
            current.quantity < 0 and signed_fill < 0
        )

        if same_direction:
            current_size = abs(current.quantity)
            fill_size = abs(signed_fill)
            combined_size = current_size + fill_size

            current.average_price = (
                current.average_price * current_size
                + fill.price * fill_size
            ) / combined_size

            current.quantity += signed_fill
            return

        closing_quantity = min(
            abs(current.quantity),
            abs(signed_fill),
        )

        if current.quantity > 0:
            self._realized_pnl += (
                fill.price - current.average_price
            ) * closing_quantity
        else:
            self._realized_pnl += (
                current.average_price - fill.price
            ) * closing_quantity

        remaining = current.quantity + signed_fill

        if abs(remaining) < 1e-12:
            self._positions.pop(symbol)
            return

        position_flipped = (
            current.quantity > 0 > remaining
            or current.quantity < 0 < remaining
        )

        current.quantity = remaining

        if position_flipped:
            current.average_price = fill.price

    def _position_unrealized(
        self,
        position: _Position,
    ) -> float:
        mark = self._marks.get(
            position.symbol,
            position.average_price,
        )

        if position.quantity > 0:
            return (
                mark - position.average_price
            ) * position.quantity

        return (
            position.average_price - mark
        ) * abs(position.quantity)