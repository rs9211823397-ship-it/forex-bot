"""Seeded broker execution simulator isolated from the Phase 1 backtester."""

from dataclasses import dataclass, replace
from math import isfinite
from random import Random

from execution.models import (
    OrderRequest,
    OrderSide,
    OrderSnapshot,
    OrderState,
    OrderType,
    TERMINAL_ORDER_STATES,
)
from execution.order_manager import OrderManager
from risk.instrument import InstrumentSpec


@dataclass(frozen=True)
class BrokerSimulationConfig:
    """Execution assumptions for deterministic research simulations."""

    spread: float | None = None
    slippage: float | None = None
    commission_per_quantity: float | None = None
    random_slippage: float = 0.0
    latency_bars: int = 0
    timeout_bars: int | None = None
    rejection_probability: float = 0.0
    partial_fill_probability: float = 0.0
    partial_fill_ratio: float = 0.5
    seed: int = 0

    def __post_init__(self):
        non_negative = {
            "random_slippage": self.random_slippage,
            "rejection_probability": self.rejection_probability,
            "partial_fill_probability": self.partial_fill_probability,
        }

        for name, value in non_negative.items():
            if not isfinite(float(value)) or float(value) < 0:
                raise ValueError(f"{name} must be finite and non-negative")

        for name in ("rejection_probability", "partial_fill_probability"):
            if float(getattr(self, name)) > 1:
                raise ValueError(f"{name} cannot exceed 1")

        for name in ("spread", "slippage", "commission_per_quantity"):
            value = getattr(self, name)

            if value is not None and (
                not isfinite(float(value)) or float(value) < 0
            ):
                raise ValueError(f"{name} must be finite and non-negative")

        if not isinstance(self.latency_bars, int) or self.latency_bars < 0:
            raise ValueError("latency_bars must be a non-negative integer")

        if self.timeout_bars is not None and (
            not isinstance(self.timeout_bars, int)
            or self.timeout_bars <= 0
        ):
            raise ValueError("timeout_bars must be a positive integer")

        if (
            not isfinite(float(self.partial_fill_ratio))
            or not 0 < float(self.partial_fill_ratio) < 1
        ):
            raise ValueError("partial_fill_ratio must be between 0 and 1")


@dataclass
class _PendingOrder:
    submitted_bar: int
    eligible_bar: int
    partial_applied: bool = False


class BrokerSimulator:
    """
    Simulate broker acknowledgements and market-order fills.

    Orders submitted between bars are eligible on a future call to
    :meth:`process_bar`. A latency of zero means the first processed bar;
    latency N means the (N + 1)th processed bar. This model is separate from
    and does not alter ``BacktestEngine`` execution.
    """

    def __init__(
        self,
        instrument: InstrumentSpec,
        config: BrokerSimulationConfig | None = None,
        order_manager: OrderManager | None = None,
    ):
        if not isinstance(instrument, InstrumentSpec):
            raise TypeError("instrument must be an InstrumentSpec instance")

        self.config = config or BrokerSimulationConfig()
        self.instrument = self._effective_instrument(instrument)
        self.order_manager = order_manager or OrderManager()
        self._random = Random(self.config.seed)
        self._bar_number = 0
        self._pending: dict[str, _PendingOrder] = {}

    def submit(self, request: OrderRequest) -> OrderSnapshot:
        """Submit idempotently and apply deterministic broker acceptance."""

        normalized = self.instrument.normalize_quantity(request.quantity)
        normalized_limit = self._normalize_limit(request)
        effective_request = (
            replace(
                request,
                quantity=normalized,
                limit_price=normalized_limit,
            )
            if normalized > 0
            else request
        )
        existing = self.order_manager.get_by_client_id(
            request.client_order_id
        )

        if existing is not None:
            if existing.request != effective_request:
                return self.order_manager.create(effective_request)

            return existing

        if normalized <= 0:
            created = self.order_manager.create(request)
            submitted = self.order_manager.submit(
                created.order_id,
                request.created_time,
            )
            return self.order_manager.reject(
                submitted.order_id,
                request.created_time,
                "INVALID_NORMALIZED_QUANTITY",
            )

        created = self.order_manager.create(effective_request)
        submitted = self.order_manager.submit(
            created.order_id,
            request.created_time,
        )

        if self._random.random() < self.config.rejection_probability:
            return self.order_manager.reject(
                submitted.order_id,
                request.created_time,
                "SIMULATED_BROKER_REJECTION",
            )

        acknowledged = self.order_manager.acknowledge(
            submitted.order_id,
            request.created_time,
        )
        self._pending[acknowledged.order_id] = _PendingOrder(
            submitted_bar=self._bar_number,
            eligible_bar=(
                self._bar_number + self.config.latency_bars + 1
            ),
        )
        return acknowledged

    def process_bar(
        self,
        reference_price: float,
        event_time,
    ) -> tuple[OrderSnapshot, ...]:
        """Advance one market bar and return orders changed on this bar."""

        reference = float(reference_price)

        if not isfinite(reference) or reference <= 0:
            raise ValueError(
                "reference_price must be finite and greater than zero"
            )

        self._bar_number += 1
        changed: list[OrderSnapshot] = []

        for order_id in tuple(self._pending):
            pending = self._pending[order_id]
            snapshot = self.order_manager.get(order_id)

            if snapshot.state in TERMINAL_ORDER_STATES:
                self._pending.pop(order_id, None)
                continue

            if (
                snapshot.request.expire_time is not None
                and event_time >= snapshot.request.expire_time
            ):
                changed.append(
                    self.order_manager.expire(
                        order_id,
                        event_time,
                        "EXPLICIT_EXPIRY",
                    )
                )
                self._pending.pop(order_id, None)
                continue

            elapsed = self._bar_number - pending.submitted_bar
            latency_is_satisfied = (
                self._bar_number >= pending.eligible_bar
            )
            candidate_fill = (
                self._fill_price(reference, snapshot.request.side)
                if latency_is_satisfied
                else None
            )
            price_is_eligible = (
                candidate_fill is not None
                and self._price_is_eligible(
                    snapshot.request,
                    candidate_fill,
                )
            )

            if (
                self.config.timeout_bars is not None
                and elapsed >= self.config.timeout_bars
                and (
                    not latency_is_satisfied
                    or not price_is_eligible
                )
            ):
                changed.append(
                    self.order_manager.expire(
                        order_id,
                        event_time,
                        "EXECUTION_TIMEOUT",
                    )
                )
                self._pending.pop(order_id, None)
                continue

            if (
                not latency_is_satisfied
                or not price_is_eligible
            ):
                continue

            remaining = snapshot.remaining_quantity

            if (
                not pending.partial_applied
                and self._random.random()
                < self.config.partial_fill_probability
            ):
                proposed = (
                    snapshot.request.quantity
                    * self.config.partial_fill_ratio
                )
                quantity = self.instrument.normalize_quantity(proposed)

                if quantity <= 0 or quantity >= remaining:
                    quantity = remaining
                else:
                    pending.partial_applied = True
            else:
                quantity = remaining

            commission = (
                self.instrument.commission_per_quantity * quantity
            )
            updated = self.order_manager.record_fill(
                order_id,
                quantity=quantity,
                reference_price=reference,
                price=candidate_fill,
                commission=commission,
                fill_time=event_time,
            )
            changed.append(updated)

            if updated.state is OrderState.FILLED:
                self._pending.pop(order_id, None)

        return tuple(changed)

    def _fill_price(self, reference: float, side: OrderSide) -> float:
        half_spread = self.instrument.spread / 2.0
        random_slippage = (
            self._random.random() * self.config.random_slippage
        )
        adverse_cost = (
            half_spread
            + self.instrument.slippage
            + random_slippage
        )

        if side is OrderSide.BUY:
            return self.instrument.normalize_price(
                reference + adverse_cost,
                "BUY",
            )

        return self.instrument.normalize_price(
            reference - adverse_cost,
            "SELL",
        )

    def _normalize_limit(self, request: OrderRequest) -> float | None:
        if request.order_type is not OrderType.LIMIT:
            return request.limit_price

        action = "SELL" if request.side is OrderSide.BUY else "BUY"
        return self.instrument.normalize_price(
            request.limit_price,
            action,
        )

    def _price_is_eligible(
        self,
        request: OrderRequest,
        candidate_fill: float,
    ) -> bool:
        if request.order_type is OrderType.MARKET:
            return True

        if request.side is OrderSide.BUY:
            return candidate_fill <= request.limit_price

        return candidate_fill >= request.limit_price

    def _effective_instrument(
        self,
        instrument: InstrumentSpec,
    ) -> InstrumentSpec:
        changes = {}

        for field_name in (
            "spread",
            "slippage",
            "commission_per_quantity",
        ):
            value = getattr(self.config, field_name)

            if value is not None:
                changes[field_name] = float(value)

        return replace(instrument, **changes) if changes else instrument
