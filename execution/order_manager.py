"""Deterministic order lifecycle management and event reconciliation."""

from dataclasses import replace
from datetime import datetime
from math import isclose, isfinite

from execution.models import (
    FillRecord,
    OrderEvent,
    OrderRequest,
    OrderSnapshot,
    OrderState,
    require_utc_datetime,
)


class OrderLifecycleError(ValueError):
    """Raised when an order transition violates the lifecycle contract."""


class OrderManager:
    """Own order state while exposing immutable snapshots and events."""

    _TRANSITIONS = {
        OrderState.CREATED: {
            OrderState.SUBMITTED,
            OrderState.CANCELLED,
        },
        OrderState.SUBMITTED: {
            OrderState.ACKNOWLEDGED,
            OrderState.REJECTED,
            OrderState.CANCELLED,
            OrderState.EXPIRED,
        },
        OrderState.ACKNOWLEDGED: {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.REJECTED,
            OrderState.CANCELLED,
            OrderState.EXPIRED,
        },
        OrderState.PARTIALLY_FILLED: {
            OrderState.PARTIALLY_FILLED,
            OrderState.FILLED,
            OrderState.CANCELLED,
            OrderState.EXPIRED,
        },
    }

    def __init__(self):
        self._orders: dict[str, OrderSnapshot] = {}
        self._client_ids: dict[str, str] = {}
        self._events: list[OrderEvent] = []
        self._fills: list[FillRecord] = []

    @property
    def events(self) -> tuple[OrderEvent, ...]:
        return tuple(self._events)

    @property
    def fills(self) -> tuple[FillRecord, ...]:
        return tuple(self._fills)

    @property
    def orders(self) -> tuple[OrderSnapshot, ...]:
        """Return all orders as immutable snapshots in creation order."""

        return tuple(self._orders.values())

    def create(self, request: OrderRequest) -> OrderSnapshot:
        """Create once; duplicate client IDs return the original order."""

        existing_id = self._client_ids.get(request.client_order_id)

        if existing_id is not None:
            existing = self._orders[existing_id]

            if existing.request != request:
                raise OrderLifecycleError(
                    "client_order_id is already associated with "
                    "a different request"
                )

            return existing

        order_id = f"ORD-{len(self._orders) + 1:08d}"
        snapshot = OrderSnapshot(
            order_id=order_id,
            request=request,
            state=OrderState.CREATED,
            submitted_time=None,
            updated_time=request.created_time,
        )
        self._orders[order_id] = snapshot
        self._client_ids[request.client_order_id] = order_id
        self._append_event(
            snapshot,
            previous_state=None,
            event_time=request.created_time,
        )
        return snapshot

    def get(self, order_id: str) -> OrderSnapshot:
        try:
            return self._orders[order_id]
        except KeyError as exc:
            raise KeyError(f"Unknown order_id: {order_id}") from exc

    def get_by_client_id(self, client_order_id: str) -> OrderSnapshot | None:
        order_id = self._client_ids.get(client_order_id)
        return self._orders.get(order_id) if order_id is not None else None

    def history(self, order_id: str) -> tuple[OrderEvent, ...]:
        self.get(order_id)
        return tuple(
            event for event in self._events if event.order_id == order_id
        )

    def submit(
        self,
        order_id: str,
        event_time: datetime,
    ) -> OrderSnapshot:
        return self._transition(
            order_id,
            OrderState.SUBMITTED,
            event_time,
            submitted_time=event_time,
        )

    def acknowledge(
        self,
        order_id: str,
        event_time: datetime,
    ) -> OrderSnapshot:
        return self._transition(
            order_id,
            OrderState.ACKNOWLEDGED,
            event_time,
        )

    def reject(
        self,
        order_id: str,
        event_time: datetime,
        reason: str,
    ) -> OrderSnapshot:
        return self._transition(
            order_id,
            OrderState.REJECTED,
            event_time,
            reason=reason,
        )

    def cancel(
        self,
        order_id: str,
        event_time: datetime,
        reason: str = "CANCELLED_BY_CALLER",
    ) -> OrderSnapshot:
        return self._transition(
            order_id,
            OrderState.CANCELLED,
            event_time,
            reason=reason,
        )

    def expire(
        self,
        order_id: str,
        event_time: datetime,
        reason: str = "ORDER_TIMEOUT",
    ) -> OrderSnapshot:
        return self._transition(
            order_id,
            OrderState.EXPIRED,
            event_time,
            reason=reason,
        )

    def record_fill(
        self,
        order_id: str,
        *,
        quantity: float,
        reference_price: float,
        price: float,
        commission: float,
        fill_time: datetime,
    ) -> OrderSnapshot:
        current = self.get(order_id)
        values = (quantity, reference_price, price, commission)

        if not all(isfinite(float(value)) for value in values):
            raise ValueError("Fill values must be finite")

        if quantity <= 0 or reference_price <= 0 or price <= 0:
            raise ValueError(
                "Fill quantity and prices must be greater than zero"
            )

        if commission < 0:
            raise ValueError("Fill commission cannot be negative")

        remaining = current.remaining_quantity

        if quantity > remaining and not isclose(
            quantity,
            remaining,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise OrderLifecycleError(
                "Fill quantity exceeds remaining order quantity"
            )

        fill_quantity = min(float(quantity), remaining)
        total_quantity = current.filled_quantity + fill_quantity
        previous_notional = (
            (current.average_fill_price or 0.0)
            * current.filled_quantity
        )
        average_fill_price = (
            previous_notional + float(price) * fill_quantity
        ) / total_quantity
        target_state = (
            OrderState.FILLED
            if isclose(
                total_quantity,
                current.request.quantity,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            else OrderState.PARTIALLY_FILLED
        )
        fill = FillRecord(
            fill_id=f"FILL-{len(self._fills) + 1:08d}",
            order_id=order_id,
            client_order_id=current.request.client_order_id,
            symbol=current.request.symbol,
            side=current.request.side,
            quantity=fill_quantity,
            reference_price=float(reference_price),
            price=float(price),
            commission=float(commission),
            fill_time=fill_time,
        )
        updated = self._transition(
            order_id,
            target_state,
            fill_time,
            filled_quantity=total_quantity,
            average_fill_price=average_fill_price,
            commission=current.commission + float(commission),
            fill=fill,
        )
        self._fills.append(fill)
        return updated

    def _transition(
        self,
        order_id: str,
        target_state: OrderState,
        event_time: datetime,
        *,
        reason: str | None = None,
        fill: FillRecord | None = None,
        **changes,
    ) -> OrderSnapshot:
        current = self.get(order_id)
        require_utc_datetime(event_time, "event_time")
        allowed = self._TRANSITIONS.get(current.state, set())

        if target_state not in allowed:
            raise OrderLifecycleError(
                f"Invalid order transition: "
                f"{current.state.value} -> {target_state.value}"
            )

        if event_time < current.updated_time:
            raise OrderLifecycleError(
                "Order event time cannot move backwards"
            )

        updated = replace(
            current,
            state=target_state,
            updated_time=event_time,
            reason=reason,
            **changes,
        )
        self._orders[order_id] = updated
        self._append_event(
            updated,
            previous_state=current.state,
            event_time=event_time,
            reason=reason,
            fill=fill,
        )
        return updated

    def _append_event(
        self,
        snapshot: OrderSnapshot,
        *,
        previous_state: OrderState | None,
        event_time: datetime,
        reason: str | None = None,
        fill: FillRecord | None = None,
    ):
        self._events.append(
            OrderEvent(
                sequence=len(self._events) + 1,
                order_id=snapshot.order_id,
                client_order_id=snapshot.request.client_order_id,
                previous_state=previous_state,
                state=snapshot.state,
                event_time=event_time,
                reason=reason,
                fill=fill,
            )
        )
