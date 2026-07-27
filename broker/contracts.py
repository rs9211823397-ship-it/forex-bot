"""Immutable broker-neutral snapshots and adapter protocol."""

from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from typing import Protocol, runtime_checkable

from execution.models import OrderRequest, OrderSide, require_utc_datetime


class ExecutionUnavailableError(RuntimeError):
    """Raised when an unavailable adapter is asked to execute an action."""


def _identifier(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _finite(value: float, field_name: str, *, minimum: float | None = None):
    resolved = float(value)
    if not isfinite(resolved):
        raise ValueError(f"{field_name} must be finite")
    if minimum is not None and resolved < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}")
    return resolved


@dataclass(frozen=True)
class BrokerOrderSnapshot:
    """Point-in-time broker view of one order."""

    order_id: str
    client_order_id: str
    account_id: str
    symbol: str
    side: OrderSide | str
    quantity: float
    filled_quantity: float
    state: str
    updated_time: datetime

    def __post_init__(self):
        for name in (
            "order_id",
            "client_order_id",
            "account_id",
            "symbol",
            "state",
        ):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "side", OrderSide(self.side))
        object.__setattr__(
            self,
            "quantity",
            _finite(self.quantity, "quantity", minimum=0.0),
        )
        if self.quantity == 0:
            raise ValueError("quantity must be greater than zero")
        object.__setattr__(
            self,
            "filled_quantity",
            _finite(
                self.filled_quantity,
                "filled_quantity",
                minimum=0.0,
            ),
        )
        if self.filled_quantity > self.quantity:
            raise ValueError("filled_quantity cannot exceed quantity")
        require_utc_datetime(self.updated_time, "updated_time")


@dataclass(frozen=True)
class BrokerFillSnapshot:
    """Point-in-time broker fill suitable for deterministic reconciliation."""

    fill_id: str
    order_id: str
    account_id: str
    symbol: str
    side: OrderSide | str
    quantity: float
    price: float
    commission: float
    fill_time: datetime

    def __post_init__(self):
        for name in ("fill_id", "order_id", "account_id", "symbol"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "side", OrderSide(self.side))
        object.__setattr__(
            self,
            "quantity",
            _finite(self.quantity, "quantity", minimum=0.0),
        )
        if self.quantity == 0:
            raise ValueError("quantity must be greater than zero")
        object.__setattr__(
            self,
            "price",
            _finite(self.price, "price", minimum=0.0),
        )
        if self.price == 0:
            raise ValueError("price must be greater than zero")
        object.__setattr__(
            self,
            "commission",
            _finite(self.commission, "commission", minimum=0.0),
        )
        require_utc_datetime(self.fill_time, "fill_time")


@dataclass(frozen=True)
class PositionSnapshot:
    """Broker-neutral open-position snapshot."""

    account_id: str
    symbol: str
    side: OrderSide | str
    quantity: float
    average_price: float
    mark_price: float
    unrealized_pnl: float
    as_of: datetime

    def __post_init__(self):
        for name in ("account_id", "symbol"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(self, "side", OrderSide(self.side))
        for name in ("quantity", "average_price", "mark_price"):
            value = _finite(getattr(self, name), name, minimum=0.0)
            if value == 0:
                raise ValueError(f"{name} must be greater than zero")
            object.__setattr__(self, name, value)
        object.__setattr__(
            self,
            "unrealized_pnl",
            _finite(self.unrealized_pnl, "unrealized_pnl"),
        )
        require_utc_datetime(self.as_of, "as_of")

    @property
    def gross_exposure(self) -> float:
        return self.quantity * self.mark_price


@dataclass(frozen=True)
class AccountSnapshot:
    """Broker-neutral account balances at one instant."""

    account_id: str
    currency: str
    balance: float
    equity: float
    margin_used: float
    available_funds: float
    as_of: datetime

    def __post_init__(self):
        for name in ("account_id", "currency"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in (
            "balance",
            "equity",
            "margin_used",
            "available_funds",
        ):
            object.__setattr__(
                self,
                name,
                _finite(getattr(self, name), name),
            )
        if self.margin_used < 0:
            raise ValueError("margin_used cannot be negative")
        require_utc_datetime(self.as_of, "as_of")


@dataclass(frozen=True)
class BrokerHealth:
    """Non-mutating adapter readiness result."""

    adapter: str
    ready: bool
    reason: str

    def __post_init__(self):
        object.__setattr__(self, "adapter", _identifier(self.adapter, "adapter"))
        object.__setattr__(self, "reason", _identifier(self.reason, "reason"))


@runtime_checkable
class BrokerAdapter(Protocol):
    """Small synchronous boundary implemented by future broker connectors."""

    name: str
    is_live: bool

    def health(self) -> BrokerHealth:
        """Return readiness without placing an order."""

    def submit_order(
        self,
        account_id: str,
        request: OrderRequest,
    ) -> BrokerOrderSnapshot:
        """Submit an order or fail without side effects."""

    def cancel_order(
        self,
        account_id: str,
        order_id: str,
    ) -> BrokerOrderSnapshot:
        """Cancel an order or fail without side effects."""

    def orders(self, account_id: str) -> tuple[BrokerOrderSnapshot, ...]:
        """Return the broker's current order projection."""

    def fills(self, account_id: str) -> tuple[BrokerFillSnapshot, ...]:
        """Return fills visible to the account."""

    def positions(self, account_id: str) -> tuple[PositionSnapshot, ...]:
        """Return current positions visible to the account."""

    def account_snapshot(self, account_id: str) -> AccountSnapshot:
        """Return the latest account balance snapshot."""
