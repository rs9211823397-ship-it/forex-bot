"""Immutable contracts for broker-style order execution."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Any


class OrderSide(str, Enum):
    """Direction of the opening order."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    """Order types understood by the execution foundation."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderState(str, Enum):
    """Explicit states in the broker order lifecycle."""

    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


TERMINAL_ORDER_STATES = frozenset(
    {
        OrderState.FILLED,
        OrderState.REJECTED,
        OrderState.CANCELLED,
        OrderState.EXPIRED,
    }
)


def _positive_finite(value: float, field_name: str) -> float:
    resolved = float(value)

    if not isfinite(resolved) or resolved <= 0:
        raise ValueError(f"{field_name} must be finite and greater than zero")

    return resolved


def require_utc_datetime(value: datetime, field_name: str) -> datetime:
    """Reject ambiguous or non-UTC timestamps at execution boundaries."""

    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware UTC")

    if value.utcoffset().total_seconds() != 0:
        raise ValueError(f"{field_name} must use UTC")

    return value


@dataclass(frozen=True)
class OrderRequest:
    """A caller-owned, immutable order instruction."""

    client_order_id: str
    symbol: str
    side: OrderSide | str
    quantity: float
    created_time: datetime
    order_type: OrderType | str = OrderType.MARKET
    limit_price: float | None = None
    expire_time: datetime | None = None
    metadata: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    def __post_init__(self):
        if not isinstance(self.client_order_id, str) or not (
            self.client_order_id.strip()
        ):
            raise ValueError("client_order_id must be a non-empty string")

        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("symbol must be a non-empty string")

        object.__setattr__(self, "side", OrderSide(self.side))
        object.__setattr__(self, "order_type", OrderType(self.order_type))
        object.__setattr__(
            self,
            "quantity",
            _positive_finite(self.quantity, "quantity"),
        )

        require_utc_datetime(self.created_time, "created_time")

        if self.order_type is OrderType.LIMIT:
            if self.limit_price is None:
                raise ValueError("LIMIT orders require limit_price")
            _positive_finite(self.limit_price, "limit_price")
        elif self.limit_price is not None:
            _positive_finite(self.limit_price, "limit_price")

        if self.expire_time is not None:
            require_utc_datetime(self.expire_time, "expire_time")

        if (
            self.expire_time is not None
            and self.expire_time < self.created_time
        ):
            raise ValueError("expire_time cannot precede created_time")


@dataclass(frozen=True)
class FillRecord:
    """A single immutable broker fill."""

    fill_id: str
    order_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: float
    reference_price: float
    price: float
    commission: float
    fill_time: datetime

    def __post_init__(self):
        if not self.fill_id or not self.order_id or not self.client_order_id:
            raise ValueError("Fill identifiers must be non-empty")

        if not self.symbol:
            raise ValueError("Fill symbol must be non-empty")

        object.__setattr__(self, "side", OrderSide(self.side))

        for name in ("quantity", "reference_price", "price"):
            _positive_finite(getattr(self, name), name)

        if (
            not isfinite(float(self.commission))
            or float(self.commission) < 0
        ):
            raise ValueError("commission must be finite and non-negative")

        require_utc_datetime(self.fill_time, "fill_time")


@dataclass(frozen=True)
class OrderEvent:
    """Append-only lifecycle event suitable for reconciliation."""

    sequence: int
    order_id: str
    client_order_id: str
    previous_state: OrderState | None
    state: OrderState
    event_time: datetime
    reason: str | None = None
    fill: FillRecord | None = None


@dataclass(frozen=True)
class OrderSnapshot:
    """Current immutable projection of an order."""

    order_id: str
    request: OrderRequest
    state: OrderState
    submitted_time: datetime | None
    updated_time: datetime
    filled_quantity: float = 0.0
    average_fill_price: float | None = None
    commission: float = 0.0
    reason: str | None = None

    @property
    def remaining_quantity(self) -> float:
        return max(self.request.quantity - self.filled_quantity, 0.0)

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_ORDER_STATES
