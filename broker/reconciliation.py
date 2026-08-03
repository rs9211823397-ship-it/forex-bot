"""Deterministic comparison of internal and broker order projections."""

from dataclasses import dataclass
from datetime import datetime
from math import isclose
from typing import Iterable

from broker.contracts import BrokerOrderSnapshot
from execution.models import require_utc_datetime


@dataclass(frozen=True, order=True)
class ReconciliationIssue:
    """One stable, sortable mismatch."""

    category: str
    order_id: str
    field: str
    internal_value: str
    broker_value: str


@dataclass(frozen=True)
class ReconciliationReport:
    """Immutable reconciliation result for one explicit as-of instant."""

    as_of: datetime
    matched_orders: int
    internal_order_count: int
    broker_order_count: int
    issues: tuple[ReconciliationIssue, ...]

    @property
    def is_reconciled(self) -> bool:
        return not self.issues


def _index(
    orders: Iterable[BrokerOrderSnapshot],
    source: str,
) -> dict[str, BrokerOrderSnapshot]:
    result: dict[str, BrokerOrderSnapshot] = {}
    for order in orders:
        if order.order_id in result:
            raise ValueError(f"Duplicate {source} order_id: {order.order_id}")
        result[order.order_id] = order
    return result


def reconcile_orders(
    internal_orders: Iterable[BrokerOrderSnapshot],
    broker_orders: Iterable[BrokerOrderSnapshot],
    *,
    as_of: datetime,
) -> ReconciliationReport:
    """Compare order state without consulting a wall clock or network."""

    require_utc_datetime(as_of, "as_of")
    internal = _index(internal_orders, "internal")
    external = _index(broker_orders, "broker")
    issues: list[ReconciliationIssue] = []
    matched = 0

    for order_id in sorted(set(internal) | set(external)):
        internal_order = internal.get(order_id)
        broker_order = external.get(order_id)

        if internal_order is None:
            issues.append(
                ReconciliationIssue(
                    "MISSING_INTERNAL",
                    order_id,
                    "order",
                    "<missing>",
                    "present",
                )
            )
            continue
        if broker_order is None:
            issues.append(
                ReconciliationIssue(
                    "MISSING_BROKER",
                    order_id,
                    "order",
                    "present",
                    "<missing>",
                )
            )
            continue

        order_issues = []
        for field in (
            "client_order_id",
            "account_id",
            "symbol",
            "side",
            "quantity",
            "state",
        ):
            internal_value = getattr(internal_order, field)
            broker_value = getattr(broker_order, field)
            if internal_value != broker_value:
                order_issues.append(
                    ReconciliationIssue(
                        "VALUE_MISMATCH",
                        order_id,
                        field,
                        str(internal_value),
                        str(broker_value),
                    )
                )

        if not isclose(
            internal_order.filled_quantity,
            broker_order.filled_quantity,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            order_issues.append(
                ReconciliationIssue(
                    "VALUE_MISMATCH",
                    order_id,
                    "filled_quantity",
                    str(internal_order.filled_quantity),
                    str(broker_order.filled_quantity),
                )
            )

        if order_issues:
            issues.extend(order_issues)
        else:
            matched += 1

    return ReconciliationReport(
        as_of=as_of,
        matched_orders=matched,
        internal_order_count=len(internal),
        broker_order_count=len(external),
        issues=tuple(sorted(issues)),
    )
